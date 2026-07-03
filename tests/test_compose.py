"""Tests for image composition on a synthetic base (no network)."""
from PIL import Image

from parcelmap import compose, geo
from parcelmap.places import Business

_SQUARE_POLYGON = [
    (40.001, -89.001),
    (40.001, -88.999),
    (40.0, -88.999),
    (40.0, -89.001),
]


def _fake_base(size=1280):
    return Image.new("RGB", (size, size), (90, 130, 90))


def _bounds():
    return geo.ImageBounds.around(lat=40.0, lng=-89.0, extent_m=500, size_px=1280)


def test_compose_returns_rgb_of_requested_size():
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, _SQUARE_POLYGON,
        businesses=[], title="Test Address",
    )
    assert out.mode == "RGB"
    assert out.size == (1280, 1280)


def test_compose_with_text_markers():
    businesses = [
        Business(name="Example Cafe", lat=40.001, lng=-89.001, category="cafe"),
        Business(name="ACME Bank", lat=39.999, lng=-88.999, category="bank"),
    ]
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, _SQUARE_POLYGON,
        businesses=businesses, title="Test Address",
    )
    assert out.size == (1280, 1280)


def test_marker_outside_frame_is_skipped():
    # A business far outside the frame must not raise.
    businesses = [Business(name="Far Away", lat=41.0, lng=-88.0, category="shop")]
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, _SQUARE_POLYGON,
        businesses=businesses, title="Edge case",
    )
    assert out.size == (1280, 1280)


def test_logo_marker_path():
    logo = Image.new("RGBA", (64, 64), (255, 255, 255, 255))
    businesses = [Business(name="Branded", lat=40.001, lng=-89.001, category="fast_food", logo=logo)]
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, _SQUARE_POLYGON,
        businesses=businesses, title="Logo test",
    )
    assert out.size == (1280, 1280)


def test_compose_without_polygon_draws_pin():
    # When no parcel polygon is available, the address pin still renders.
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, None,
        businesses=[], title="No parcel",
    )
    assert out.size == (1280, 1280)


def test_many_overlapping_markers_do_not_crash():
    # Many tightly clustered businesses with long names stress de-collision + wrap.
    businesses = [
        Business(
            name=f"A Reasonably Long Business Name {i} LLC",
            lat=40.0 + (i % 5) * 0.0002,
            lng=-89.0 + (i // 5) * 0.0002,
            category="restaurant",
            distance_mi=0.1 * i,
        )
        for i in range(30)
    ]
    out = compose.compose(
        _fake_base(), _bounds(), 40.0, -89.0, _SQUARE_POLYGON,
        businesses=businesses, title="Stress test",
    )
    assert out.size == (1280, 1280)
