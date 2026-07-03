"""Command-line interface.

Examples
--------
  python -m parcelmap "123 Main St, Springfield, IL"
  python -m parcelmap "123 Main St, Springfield, IL" --acres 2.5 --extent 600 -o out.png
"""
from __future__ import annotations

import argparse
import logging
import os
import sys

from . import pipeline


def _slug(text: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in text.lower())[:60].strip("-") or "map"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="parcelmap",
        description="Generate an annotated satellite map for a property address (no API keys).",
    )
    p.add_argument("address", help="Property address, e.g. '123 Main St, Springfield, IL'")
    p.add_argument("--acres", type=float, default=None,
                   help="Lot size in acres (sizes the red area-of-interest circle)")
    p.add_argument("--extent", type=int, default=None,
                   help="Ground half-width (meters) the satellite image spans")
    p.add_argument("--search-radius", type=int, default=None,
                   help="Radius (meters) to search for nearby businesses")
    p.add_argument("--size", type=int, default=None, help="Output image size in pixels (square)")
    p.add_argument("--no-businesses", action="store_true", help="Skip nearby-business lookup")
    p.add_argument("-o", "--output", default=None,
                   help="Output PNG path (default: output/<slug>.png)")
    p.add_argument("-v", "--verbose", action="store_true", help="Verbose logging")
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    out = args.output
    if not out:
        os.makedirs("output", exist_ok=True)
        out = os.path.join("output", _slug(args.address) + ".png")

    try:
        img = pipeline.generate_map_image(
            address=args.address,
            lot_size_acres=args.acres,
            extent_m=args.extent,
            search_radius_m=args.search_radius,
            size=args.size,
            fetch_businesses=not args.no_businesses,
        )
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    img.save(out, "PNG")
    print(f"Saved: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
