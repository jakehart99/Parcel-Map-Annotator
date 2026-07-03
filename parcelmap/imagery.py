"""Fetch a satellite image for a location. No API key.

Primary: Esri World Imagery (ArcGIS REST ``export`` returns a sized JPEG for a
Web-Mercator bounding box in a single request — no tile stitching). Fallback:
USGS NAIP via The National Map (US public domain, zero licensing risk).
"""
from __future__ import annotations

import io
import logging

from PIL import Image
import requests

from . import config
from .geo import ImageBounds

log = logging.getLogger(__name__)


def _export(url: str, bounds: ImageBounds, size: int) -> Image.Image:
    bbox = f"{bounds.xmin},{bounds.ymin},{bounds.xmax},{bounds.ymax}"
    params = {
        "bbox": bbox,
        "bboxSR": "3857",
        "imageSR": "3857",
        "size": f"{size},{size}",
        "format": "jpeg",
        "f": "image",
        "transparent": "false",
    }
    r = requests.get(
        url,
        params=params,
        headers={"User-Agent": config.USER_AGENT},
        timeout=config.REQUEST_TIMEOUT,
    )
    r.raise_for_status()
    img = Image.open(io.BytesIO(r.content))
    return img.convert("RGB")


def fetch_satellite(
    lat: float,
    lng: float,
    extent_m: float | None = None,
    size: int | None = None,
) -> tuple[Image.Image, ImageBounds]:
    """Return (satellite_image, bounds). Tries providers in order."""
    extent_m = config.DEFAULT_EXTENT_M if extent_m is None else extent_m
    size = config.DEFAULT_SIZE_PX if size is None else size
    bounds = ImageBounds.around(lat, lng, extent_m, size)

    last_err = None
    for url in (config.ESRI_IMAGERY_URL, config.USGS_IMAGERY_URL):
        try:
            return _export(url, bounds, size), bounds
        except Exception as e:
            last_err = e
            log.warning("Imagery provider failed (%s): %s", url, e)
    raise RuntimeError(f"All imagery providers failed: {last_err}")
