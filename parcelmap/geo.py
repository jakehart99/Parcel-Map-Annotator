"""Web Mercator (EPSG:3857) projection and pixel mapping. Pure, no dependencies.

Web Mercator stretches true ground distance by sec(latitude) in both axes.
We account for that when building the image bounding box, which makes the
overlay math simplify to: pixels-per-ground-meter = size_px / (2 * extent_m).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EARTH_RADIUS = 6378137.0  # EPSG:3857 sphere radius, in meters


def wgs84_to_webmercator(lat: float, lng: float) -> tuple[float, float]:
    """WGS84 lat/lng (degrees) -> Web Mercator x/y (meters)."""
    x = EARTH_RADIUS * math.radians(lng)
    y = EARTH_RADIUS * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))
    return x, y


def webmercator_to_wgs84(x: float, y: float) -> tuple[float, float]:
    """Web Mercator x/y (meters) -> WGS84 lat/lng (degrees)."""
    lng = math.degrees(x / EARTH_RADIUS)
    lat = math.degrees(2 * math.atan(math.exp(y / EARTH_RADIUS)) - math.pi / 2)
    return lat, lng


@dataclass
class ImageBounds:
    """Projection metadata for a fetched satellite image.

    ``extent_m`` is the TRUE ground half-width the image spans (not projected
    meters), so callers can reason about distances in plain meters.
    """

    lat0: float
    lng0: float
    extent_m: float
    xmin: float
    ymin: float
    xmax: float
    ymax: float
    size_px: int

    @classmethod
    def around(cls, lat: float, lng: float, extent_m: float, size_px: int) -> "ImageBounds":
        cx, cy = wgs84_to_webmercator(lat, lng)
        # Convert ground meters -> projected meters (Mercator stretches by sec(lat)).
        half = extent_m / math.cos(math.radians(lat))
        return cls(
            lat0=lat,
            lng0=lng,
            extent_m=extent_m,
            xmin=cx - half,
            ymin=cy - half,
            xmax=cx + half,
            ymax=cy + half,
            size_px=size_px,
        )

    def px_per_ground_meter(self) -> float:
        """Pixels per true ground meter (independent of latitude by design)."""
        return self.size_px / (2.0 * self.extent_m)

    def ground_m_to_px(self, meters: float) -> float:
        return meters * self.px_per_ground_meter()

    def to_pixel(self, lat: float, lng: float) -> tuple[float, float]:
        """Project a lat/lng to pixel coordinates on this image (y flipped)."""
        x, y = wgs84_to_webmercator(lat, lng)
        px = (x - self.xmin) / (self.xmax - self.xmin) * self.size_px
        py = (self.ymax - y) / (self.ymax - self.ymin) * self.size_px
        return px, py

    def contains(self, lat: float, lng: float) -> bool:
        x, y = wgs84_to_webmercator(lat, lng)
        return self.xmin <= x <= self.xmax and self.ymin <= y <= self.ymax


def haversine_mi(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance between two lat/lng points, in miles."""
    radius_mi = 3958.7613
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * radius_mi * math.atan2(math.sqrt(a), math.sqrt(1 - a))
