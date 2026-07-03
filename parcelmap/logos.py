"""Resolve a business logo via key-free DuckDuckGo favicons. Returns PIL image or None.

Resolution order for the domain:
  1. the OSM ``website`` / ``brand:website`` / ``contact:website`` tag, or
  2. the built-in brand->domain table (parcelmap.brands).
Then we fetch ``https://icons.duckduckgo.com/ip3/{domain}.ico`` (no key) and
mount it on a clean white rounded background suitable for overlay.
"""
from __future__ import annotations

import io
import logging
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

from PIL import Image, ImageDraw
import requests

from . import config
from .brands import BRAND_DOMAIN, normalize

log = logging.getLogger(__name__)
_LOGO_TIMEOUT = min(config.REQUEST_TIMEOUT, 10)
_CACHE: dict[tuple[str, int], Image.Image | None] = {}

try:
    _RESAMPLE = Image.Resampling.LANCZOS  # Pillow >= 9.1
except AttributeError:  # pragma: no cover
    _RESAMPLE = Image.LANCZOS  # type: ignore[attr-defined]


def _domain_from_url(url: str) -> str:
    if not url:
        return ""
    try:
        net = urlparse(url if "://" in url else "http://" + url).netloc.lower()
    except Exception:
        return ""
    if net.startswith("www."):
        net = net[4:]
    return net.split(":")[0]


def _root_domain(domain: str) -> str:
    parts = [p for p in domain.split(".") if p]
    if len(parts) <= 2:
        return domain
    return ".".join(parts[-2:])


def _add_candidate(candidates: list[str], domain: str) -> None:
    domain = (domain or "").strip().lower()
    if not domain:
        return
    if domain.startswith("www."):
        domain = domain[4:]
    if domain not in candidates:
        candidates.append(domain)


def _domain_candidates(business) -> list[str]:
    key = normalize(business.brand) or normalize(business.name)
    candidates: list[str] = []
    _add_candidate(candidates, BRAND_DOMAIN.get(key, ""))

    website_domain = _domain_from_url(business.website)
    _add_candidate(candidates, website_domain)
    root = _root_domain(website_domain)
    if root != website_domain:
        _add_candidate(candidates, root)

    return candidates


def _read_image_url(url: str) -> Image.Image | None:
    r = requests.get(url, headers={"User-Agent": config.USER_AGENT}, timeout=_LOGO_TIMEOUT)
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content)).convert("RGBA")
    if img.width < 8 or img.height < 8:
        return None
    if not _looks_usable_logo(img):
        return None
    return img


def _looks_usable_logo(img: Image.Image) -> bool:
    bbox = img.getbbox()
    if bbox is None:
        return False
    cropped = img.crop(bbox)
    if cropped.width < 8 or cropped.height < 8:
        return False
    colors = cropped.convert("RGB").getcolors(maxcolors=256)
    if colors is not None and len(colors) <= 2:
        return False
    return True


def _direct_favicon_urls(domain: str):
    yield f"https://{domain}/favicon.ico"
    if not domain.startswith("www."):
        yield f"https://www.{domain}/favicon.ico"


class _IconLinkParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.hrefs: list[tuple[int, str]] = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() != "link":
            return
        data = {k.lower(): (v or "") for k, v in attrs}
        rel = data.get("rel", "").lower()
        if "icon" in rel and data.get("href"):
            size_score = 0
            for part in data.get("sizes", "").split():
                if "x" in part:
                    try:
                        size_score = max(size_score, int(part.split("x", 1)[0]))
                    except ValueError:
                        pass
            rel_score = 1000 if "apple-touch-icon" in rel else 500
            self.hrefs.append((rel_score + size_score, data["href"]))


def _page_icon_urls(domain: str):
    for base in (f"https://{domain}/", f"https://www.{domain}/"):
        try:
            r = requests.get(
                base,
                headers={"User-Agent": config.USER_AGENT},
                timeout=_LOGO_TIMEOUT,
            )
            r.raise_for_status()
            parser = _IconLinkParser()
            parser.feed(r.text[:300000])
            for _, href in sorted(parser.hrefs, reverse=True)[:4]:
                yield urljoin(r.url, href)
        except Exception as e:
            log.debug("Icon page discovery failed for %s: %s", domain, e)


def _favicon(domain: str):
    seen: set[str] = set()
    for url in _page_icon_urls(domain):
        if url in seen:
            continue
        seen.add(url)
        try:
            img = _read_image_url(url)
            if img is not None:
                return img
        except Exception as e:
            log.debug("Logo source failed for %s (%s): %s", domain, url, e)
    for url in (
        config.FAVICON_URL.format(domain=domain),
        *_direct_favicon_urls(domain),
    ):
        if url in seen:
            continue
        seen.add(url)
        try:
            img = _read_image_url(url)
            if img is not None:
                return img
        except Exception as e:
            log.debug("Logo source failed for %s (%s): %s", domain, url, e)
    return None


def _mount_on_background(logo: Image.Image, target_px: int) -> Image.Image:
    pad = max(4, target_px // 10)
    box = target_px + pad * 2
    bg = Image.new("RGBA", (box, box), (0, 0, 0, 0))
    draw = ImageDraw.Draw(bg)
    draw.rounded_rectangle(
        [0, 0, box - 1, box - 1],
        radius=max(7, box // 8),
        fill=(255, 255, 255, 248),
        outline=(58, 62, 70, 255),
        width=2,
    )
    scale = min(target_px / logo.width, target_px / logo.height)
    nw = max(1, int(logo.width * scale))
    nh = max(1, int(logo.height * scale))
    resized = logo.resize((nw, nh), _RESAMPLE)
    bg.alpha_composite(resized, ((box - nw) // 2, (box - nh) // 2))
    return bg


def get_logo(business, target_px: int | None = None) -> Image.Image | None:
    """Return a marker-ready RGBA logo image, or None if unresolvable."""
    target_px = config.MARKER_LOGO_PX if target_px is None else target_px
    for domain in _domain_candidates(business):
        cache_key = (domain, target_px)
        if cache_key in _CACHE:
            cached = _CACHE[cache_key]
            if cached is not None:
                return cached.copy()
            continue
        logo = _favicon(domain)
        mounted = _mount_on_background(logo, target_px) if logo is not None else None
        _CACHE[cache_key] = mounted
        if mounted is not None:
            return mounted.copy()
    log.debug("No logo for %r", business.name)
    return None
