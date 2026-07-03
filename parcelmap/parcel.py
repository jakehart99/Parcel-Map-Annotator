"""Resolve the real lot/building polygon for a location via OpenStreetMap.

No API key. OSM does not store authoritative tax-parcel lot lines everywhere,
but it does store **building footprints** and **address-tagged polygons** (in the
US, largely the imported Microsoft building footprints), which is the real shape
to outline on a location map.

Selection, best to worst:
  1. a polygon whose ``addr:housenumber`` matches the geocoded house number,
  2. a polygon that contains the address point,
  3. (if a lot size is given) the polygon whose area is closest to it,
  4. the nearest footprint.

Returns the polygon as a list of (lat, lng) vertices, or ``None`` if nothing
confident is found (the caller then just marks the address point).
"""
from __future__ import annotations

import logging
import math

import requests

from . import config

log = logging.getLogger(__name__)

_M_PER_DEG_LAT = 111320.0  # meters per degree of latitude (approx)

_QUERY = """
[out:json][timeout:12];
(
  way["building"](around:{r},{lat},{lng});
  way["addr:housenumber"](around:{r},{lat},{lng});
  way["landuse"](around:{r},{lat},{lng});
);
out geom qt 40;
"""


def _query(lat: float, lng: float, radius: float):
    q = _QUERY.format(r=radius, lat=lat, lng=lng)
    last = None
    for url in config.OVERPASS_ENDPOINTS:
        try:
            r = requests.post(
                url,
                data={"data": q},
                headers={"User-Agent": config.USER_AGENT},
                timeout=min(config.REQUEST_TIMEOUT, 15),
            )
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last = e
            log.warning("Overpass (parcel) failed (%s): %s", url, e)
    log.error("All Overpass endpoints failed for parcel lookup: %s", last)
    return None


def _geometry(element) -> list[tuple[float, float]] | None:
    geom = element.get("geometry")
    if not geom or len(geom) < 3:
        return None
    return [(float(g["lat"]), float(g["lon"])) for g in geom]


def _point_in_poly(lat: float, lng: float, poly) -> bool:
    """Ray-casting point-in-polygon; poly is a list of (lat, lng)."""
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        lat_i, lng_i = poly[i]
        lat_j, lng_j = poly[j]
        if (lat_i > lat) != (lat_j > lat):
            x_int = (lng_j - lng_i) * (lat - lat_i) / (lat_j - lat_i) + lng_i
            if lng < x_int:
                inside = not inside
        j = i
    return inside


def _to_local_meters(lat: float, lng: float, lat0: float, lng0: float) -> tuple[float, float]:
    """Project (lat,lng) to meters east/north of (lat0,lng0) on a flat earth."""
    x = (lng - lng0) * _M_PER_DEG_LAT * math.cos(math.radians(lat0))
    y = (lat - lat0) * _M_PER_DEG_LAT
    return x, y


def _area_m2(poly) -> float:
    ref_lat = sum(p[0] for p in poly) / len(poly)
    ref_lng = sum(p[1] for p in poly) / len(poly)
    pts = [_to_local_meters(lat, lng, ref_lat, ref_lng) for lat, lng in poly]
    s = 0.0
    n = len(pts)
    for i in range(n):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % n]
        s += x1 * y2 - x2 * y1
    return abs(s) / 2.0


def _point_to_poly_m(lat0: float, lng0: float, poly) -> float:
    """Min distance (meters) from (lat0,lng0) to any edge of poly."""
    pts = [_to_local_meters(lat, lng, lat0, lng0) for lat, lng in poly]
    px = py = 0.0

    def seg_dist(ax, ay, bx, by):
        dx, dy = bx - ax, by - ay
        if dx == 0 and dy == 0:
            return math.hypot(px - ax, py - ay)
        t = ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)
        t = max(0.0, min(1.0, t))
        cx, cy = ax + t * dx, ay + t * dy
        return math.hypot(px - cx, py - cy)

    best = float("inf")
    n = len(pts)
    for i in range(n):
        ax, ay = pts[i]
        bx, by = pts[(i + 1) % n]
        best = min(best, seg_dist(ax, ay, bx, by))
    return best


def get_parcel_polygon(
    lat: float,
    lng: float,
    house_number: str | None = None,
    target_area_m2: float | None = None,
    radius: float | None = None,
) -> list[tuple[float, float]] | None:
    """Return the best lot/building polygon [(lat,lng),...] for the point, or None."""
    radius = config.DEFAULT_PARCEL_SEARCH_M if radius is None else radius
    data = _query(lat, lng, radius)
    if not data:
        return None

    hn = (house_number or "").strip()
    candidates = []
    for el in data.get("elements", []):
        poly = _geometry(el)
        if not poly:
            continue
        tags = el.get("tags") or {}
        candidates.append({
            "poly": poly,
            "tags": tags,
            "addr_match": bool(hn) and (tags.get("addr:housenumber", "").strip() == hn),
            "contains": _point_in_poly(lat, lng, poly),
            "area": _area_m2(poly),
            "dist": _point_to_poly_m(lat, lng, poly),
            "is_building": "building" in tags,
        })
    if not candidates:
        return None

    def keyf(c):
        area_err = 0.0
        if target_area_m2 and c["area"] > 0:
            area_err = abs(c["area"] - target_area_m2) / target_area_m2
        # addr_match > contains > area closeness > building tag > distance
        return (not c["addr_match"], not c["contains"], area_err, not c["is_building"], c["dist"])

    candidates.sort(key=keyf)
    best = candidates[0]
    if best["addr_match"] or best["contains"] or best["dist"] <= 30.0:
        log.info("Parcel selected: addr_match=%s contains=%s area=%.0f m² dist=%.1f m",
                 best["addr_match"], best["contains"], best["area"], best["dist"])
        return best["poly"]
    log.info("No confident parcel polygon (nearest dist=%.1f m)", best["dist"])
    return None
