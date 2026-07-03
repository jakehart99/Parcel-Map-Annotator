"""Address -> geocode result using free OSM providers. No API key.

Tries Nominatim first, then Photon (Komoot). Nominatim's usage policy requires a
descriptive User-Agent and <= 1 request/second. We also request address details
so the parcel resolver can match the house number to the right building.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import lru_cache

import requests

from . import config

log = logging.getLogger(__name__)
_GEOCODE_TIMEOUT = min(config.REQUEST_TIMEOUT, 12)


@dataclass
class GeoResult:
    lat: float
    lng: float
    display: str
    house_number: str = ""
    street: str = ""


class GeocodeError(Exception):
    """Raised when no provider can resolve the address."""


def _nominatim(address: str):
    r = requests.get(
        config.NOMINATIM_URL,
        params={"q": address, "format": "json", "limit": 1, "addressdetails": 1},
        headers={"User-Agent": config.USER_AGENT},
        timeout=_GEOCODE_TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    if not data:
        return None
    d = data[0]
    addr = d.get("address") or {}
    return GeoResult(
        lat=float(d["lat"]),
        lng=float(d["lon"]),
        display=d.get("display_name") or address,
        house_number=str(addr.get("house_number", "") or ""),
        street=str(addr.get("road", "") or addr.get("street", "") or ""),
    )


def _photon(address: str):
    r = requests.get(
        config.PHOTON_URL,
        params={"q": address, "limit": 1},
        headers={"User-Agent": config.USER_AGENT},
        timeout=_GEOCODE_TIMEOUT,
    )
    r.raise_for_status()
    feats = r.json().get("features")
    if not feats:
        return None
    f = feats[0]
    lon, lat = f["geometry"]["coordinates"][:2]
    p = f.get("properties") or {}
    return GeoResult(
        lat=float(lat),
        lng=float(lon),
        display=p.get("name") or p.get("label") or address,
        house_number=str(p.get("housenumber", "") or ""),
        street=str(p.get("street", "") or ""),
    )


@lru_cache(maxsize=128)
def geocode(address: str) -> GeoResult:
    """Resolve an address to a GeoResult (lat, lng, display, house_number, street)."""
    for fn in (_nominatim, _photon):
        try:
            res = fn(address)
            if res:
                return res
        except Exception as e:
            log.warning("Geocoder %s failed: %s", fn.__name__, e)
    raise GeocodeError(f"Could not geocode address: {address!r}")
