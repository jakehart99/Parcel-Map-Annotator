"""Tests for projection and pixel-mapping math (no network)."""
import math

from parcelmap import geo


def test_webmercator_roundtrip():
    for lat, lng in [(0, 0), (40, -89), (-33, 151), (60, 30)]:
        x, y = geo.wgs84_to_webmercator(lat, lng)
        lat2, lng2 = geo.webmercator_to_wgs84(x, y)
        assert math.isclose(lat, lat2, abs_tol=1e-9)
        assert math.isclose(lng, lng2, abs_tol=1e-9)


def test_origin_maps_to_known_xy():
    x, y = geo.wgs84_to_webmercator(0, 0)
    assert math.isclose(x, 0.0, abs_tol=1e-6)
    assert math.isclose(y, 0.0, abs_tol=1e-6)  # tan(pi/4) isn't exactly 1 in float


def test_center_pixel_is_image_center():
    bounds = geo.ImageBounds.around(lat=40.0, lng=-89.0, extent_m=500, size_px=1280)
    px, py = bounds.to_pixel(40.0, -89.0)
    assert math.isclose(px, 640.0, abs_tol=1e-6)
    assert math.isclose(py, 640.0, abs_tol=1e-6)


def test_ground_to_pixel_relation():
    # px-per-ground-meter == size / (2*extent), independent of latitude.
    for lat in (0.0, 35.0, 55.0):
        bounds = geo.ImageBounds.around(lat=lat, lng=0.0, extent_m=500, size_px=1000)
        assert math.isclose(bounds.px_per_ground_meter(), 1.0)  # 1000/(2*500)
        assert math.isclose(bounds.ground_m_to_px(250), 250.0)


def test_lat_increases_upward():
    bounds = geo.ImageBounds.around(lat=40.0, lng=-89.0, extent_m=500, size_px=1000)
    _, south = bounds.to_pixel(39.9, -89.0)
    _, north = bounds.to_pixel(40.1, -89.0)
    assert north < south  # higher latitude -> smaller pixel y (toward top)


def test_contains():
    bounds = geo.ImageBounds.around(lat=40.0, lng=-89.0, extent_m=500, size_px=1000)
    assert bounds.contains(40.0, -89.0)
    assert not bounds.contains(40.2, -89.0)  # ~22 km away, far outside 500 m
