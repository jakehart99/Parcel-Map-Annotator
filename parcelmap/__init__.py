"""Parcel Map Annotator — turn a property address into an annotated satellite image.

Fully free, no API keys. Uses OpenStreetMap (Nominatim/Photon, Overpass),
Esri World Imagery (with USGS NAIP fallback), and DuckDuckGo favicons for logos.
"""
from .pipeline import generate_map_image  # re-export for convenience

__all__ = ["generate_map_image"]
__version__ = "1.0.0"
