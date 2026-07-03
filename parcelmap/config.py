"""Default configuration for parcelmap. No secrets, no API keys.

All values can be overridden at the call site (pipeline.generate_map_image kwargs)
or via environment variables for the user agent.
"""
from __future__ import annotations

import os

# --- Imagery / framing -------------------------------------------------------
DEFAULT_SIZE_PX = 1280          # square output image
DEFAULT_EXTENT_M = 500          # ground half-width the satellite image spans (surroundings)
DEFAULT_SEARCH_RADIUS_M = 800   # radius used to find nearby businesses
DEFAULT_PARCEL_SEARCH_M = 70    # radius (m) to search OSM for the lot/building polygon
ACRES_TO_M2 = 4046.8564224

# --- Styling -----------------------------------------------------------------
AOI_COLOR = (220, 30, 30)        # red used for the area-of-interest circle
AOI_FILL_ALPHA = 42              # 0-255 transparency of the parcel/site fill
AOI_STROKE_WIDTH = 6
MARKER_LOGO_PX = 58              # rendered logo marker size
MARKER_MAX_BUSINESSES = 18       # cap on number of businesses returned / legended
MAP_MAX_MARKERS = 10            # max labeled markers drawn on the map (rest stay in the legend)

# --- Network -----------------------------------------------------------------
USER_AGENT = os.environ.get(
    "PARCELMAP_USER_AGENT",
    "ParcelMapAnnotator/1.0 (commercial-real-estate location map tool)",
)
REQUEST_TIMEOUT = 30

# Free, key-less data providers (primary first, fallback after).
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
PHOTON_URL = "https://photon.komoot.io/api/"
ESRI_IMAGERY_URL = "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export"
USGS_IMAGERY_URL = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
FAVICON_URL = "https://icons.duckduckgo.com/ip3/{domain}.ico"
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

# Legally required attribution (OSM + Esri terms).
ATTRIBUTION = "© OpenStreetMap contributors · Imagery: Esri, Maxar, Earthstar Geographics"
