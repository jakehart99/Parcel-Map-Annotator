"""Nearby businesses via the Overpass API (OpenStreetMap). No API key.

Queries amenity/shop/office nodes and ways within a radius around the point,
dedupes by name, prioritizes brand-tagged chains, and caps the count.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import requests

from . import config
from .geo import haversine_mi

log = logging.getLogger(__name__)


@dataclass
class Business:
    name: str
    lat: float
    lng: float
    category: str = ""
    brand: str = ""
    website: str = ""
    distance_mi: float | None = None  # miles from the subject property
    # logo PIL.Image (RGBA) attached after creation by logos.get_logo
    logo: Any = field(default=None, repr=False)


_COMMERCIAL_AMENITIES = (
    "restaurant|fast_food|cafe|bar|pub|bank|pharmacy|fuel|cinema|theatre|"
    "clinic|dentist|doctors|gym|school|college"
)

_OVERPASS_Q = """
[out:json][timeout:12];
(
  node["name"]["amenity"~"{amenities}"](around:{r},{lat},{lng});
  node["name"]["shop"](around:{r},{lat},{lng});
  node["name"]["office"](around:{r},{lat},{lng});
  way["name"]["amenity"~"{amenities}"](around:{r},{lat},{lng});
  way["name"]["shop"](around:{r},{lat},{lng});
  way["name"]["office"](around:{r},{lat},{lng});
);
out center tags qt {out_limit};
"""

# Categories whose contribution is usually noise for a location map.
_EXCLUDED = {"parking", "bench", "fountain", "waste_basket", "toilets",
             "drinking_water", "post_box", "telephone", "atm",
             "vending_machine", "hunting_stand"}


def _category(tags: dict) -> str:
    if "amenity" in tags:
        return tags["amenity"]
    if "shop" in tags:
        return tags["shop"]
    if "office" in tags:
        return tags["office"]
    return "business"


@lru_cache(maxsize=128)
def _fetch_overpass(query: str):
    last_err = None
    for url in config.OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                url,
                data={"data": query},
                headers={"User-Agent": config.USER_AGENT},
                timeout=min(config.REQUEST_TIMEOUT, 15),
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            log.warning("Overpass endpoint failed (%s): %s", url, e)
    raise RuntimeError(f"All Overpass endpoints failed: {last_err}")


def nearby_businesses(
    lat: float,
    lng: float,
    radius: float | None = None,
    limit: int | None = None,
) -> list[Business]:
    radius = config.DEFAULT_SEARCH_RADIUS_M if radius is None else radius
    limit = config.MARKER_MAX_BUSINESSES if limit is None else limit
    query = _OVERPASS_Q.format(
        r=radius,
        lat=lat,
        lng=lng,
        amenities=_COMMERCIAL_AMENITIES,
        out_limit=max(50, limit * 5),
    )

    try:
        data = _fetch_overpass(query)
    except RuntimeError as e:
        log.error("%s", e)
        return []

    seen: set[str] = set()
    out: list[Business] = []
    for el in data.get("elements", []):
        tags = el.get("tags") or {}
        name = tags.get("name")
        if not name:
            continue
        category = _category(tags)
        if category in _EXCLUDED:
            continue
        if el.get("type") == "node":
            lat_, lng_ = el.get("lat"), el.get("lon")
        else:
            c = el.get("center") or {}
            lat_, lng_ = c.get("lat"), c.get("lon")
        if lat_ is None or lng_ is None:
            continue

        key = name.strip().lower()
        if key in seen:
            continue
        seen.add(key)

        blat, blng = float(lat_), float(lng_)
        out.append(
            Business(
                name=name.strip(),
                lat=blat,
                lng=blng,
                category=category,
                brand=tags.get("brand", ""),
                website=(
                    tags.get("website")
                    or tags.get("brand:website")
                    or tags.get("contact:website")
                    or ""
                ),
                distance_mi=haversine_mi(lat, lng, blat, blng),
            )
        )

    # Nearest first (most relevant for a "nearby businesses" map); logos still
    # resolve regardless of order.
    out.sort(key=lambda b: b.distance_mi if b.distance_mi is not None else 0.0)
    return out[:limit]
