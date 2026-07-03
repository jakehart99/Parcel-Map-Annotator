"""Orchestration: a property address -> an annotated satellite PIL image.

Single entry point for the CLI and web UI. Each stage degrades gracefully:
imagery has a fallback provider; the parcel polygon, businesses, and logos are
optional; only geocoding failure is fatal.
"""
from __future__ import annotations

import logging

from . import config, parcel
from .brands import normalize
from .compose import compose
from .geocode import GeocodeError, geocode
from .imagery import fetch_satellite
from .logos import get_logo
from .places import nearby_businesses

log = logging.getLogger(__name__)


def _without_subject_business(businesses, display_name: str):
    subject = normalize((display_name or "").split(",")[0])
    if not subject:
        return businesses
    return [
        b for b in businesses
        if not (
            b.distance_mi is not None
            and b.distance_mi <= 0.02
            and normalize(b.name) == subject
        )
    ]


def generate_map_image(
    address: str,
    lot_size_acres: float | None = None,
    extent_m: float | None = None,
    search_radius_m: float | None = None,
    size: int | None = None,
    fetch_businesses: bool = True,
):
    """Generate the annotated map image for ``address``.

    Parameters
    ----------
    address : str
        Free-text property address.
    lot_size_acres : float, optional
        If given, used to pick the parcel polygon whose area best matches.
    extent_m : float, optional
        Ground half-width (meters) the satellite image spans (the surroundings).
    search_radius_m : float, optional
        Radius (meters) for the nearby-business search.
    size : int, optional
        Square output size in pixels.
    fetch_businesses : bool
        If False, skip the Overpass business lookup.
    """
    extent_m = config.DEFAULT_EXTENT_M if extent_m is None else extent_m
    search_radius_m = config.DEFAULT_SEARCH_RADIUS_M if search_radius_m is None else search_radius_m
    size = config.DEFAULT_SIZE_PX if size is None else size

    log.info("Geocoding %r", address)
    geo = geocode(address)
    lat, lng = geo.lat, geo.lng
    log.info("Resolved -> %s (%.5f, %.5f)", geo.display, lat, lng)

    log.info("Fetching satellite imagery (extent %sm)", extent_m)
    base, bounds = fetch_satellite(lat, lng, extent_m, size)

    target_area = (lot_size_acres * config.ACRES_TO_M2) if lot_size_acres else None
    polygon = parcel.get_parcel_polygon(
        lat, lng, house_number=geo.house_number, target_area_m2=target_area
    )
    log.info("Parcel polygon: %s", "found" if polygon else "NOT FOUND (marking address point)")

    businesses = []
    if fetch_businesses:
        log.info("Finding nearby businesses (radius %sm)", search_radius_m)
        businesses = nearby_businesses(lat, lng, search_radius_m)
        businesses = _without_subject_business(businesses, geo.display or address)
        for b in businesses:
            b.logo = get_logo(b)
        log.info("Found %d businesses (%d with logos)",
                 len(businesses), sum(1 for b in businesses if b.logo))

    return compose(base, bounds, lat, lng, polygon, businesses, geo.display or address)
