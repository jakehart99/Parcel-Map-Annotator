# Parcel Map Annotator

Turn a property address into a marketing-ready **satellite map**: the lot is
outlined in red, and nearby businesses are labeled with their logo (or a clean
text label). Built for commercial real estate. **No Google, no API keys** — the
entire data stack is free and key-less.

---

## What it does

Given an address, it:

1. **Geocodes** the address to lat/lng (OpenStreetMap Nominatim → Photon).
2. **Fetches a satellite image** of the address + surroundings (Esri World
   Imagery; USGS NAIP public-domain fallback for US addresses).
3. **Outlines the real lot/building polygon** in translucent red (from
   OpenStreetMap building & address data), with a pin at the exact address.
   A lot size, if given, helps pick the right polygon among neighbors.
4. **Finds nearby businesses** (OpenStreetMap via the Overpass API) and places a
   **logo marker** (DuckDuckGo favicon, resolved via the business's website or a
   built-in brand→domain table) — falling back to a **text label** when no logo
   resolves.
5. Adds a **title, legend, scale bar, north arrow, and attribution**.

---

## Data sources (all free, no keys)

| Concern | Source |
|---|---|
| Geocoding | OpenStreetMap **Nominatim** (fallback **Photon**) |
| Satellite imagery | **Esri World Imagery** (fallback **USGS NAIP**, US public domain) |
| Lot/building outline | OpenStreetMap building & address data (**Overpass**) |
| Nearby businesses | OpenStreetMap via **Overpass API** |
| Business logos | **DuckDuckGo** favicons (key-free) + brand→domain table |

> **Attribution (required by license):** the output image includes
> `© OpenStreetMap contributors · Imagery: Esri, Maxar, Earthstar Geographics`.

---

## Setup

```bash
cd "/Volumes/SSK SSD/MacbookStorage/Software/ParcelMapAnnotator/Parcel-Map-Annotator"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

(Python 3.10+ recommended. Tested on 3.12.)

---

## Usage

### Command line

```bash
python -m parcelmap "123 Main St, Springfield, IL"
python -m parcelmap "123 Main St, Springfield, IL" --acres 2.5 --extent 600 -o out.png
python -m parcelmap "1 Apple Park Way, Cupertino, CA" --search-radius 1000 -v
```

Options:

| Flag | Default | Description |
|---|---|---|
| `--acres` | none | Lot size in acres (helps pick the best-matching parcel polygon) |
| `--extent` | 500 | Ground half-width (m) the satellite image spans |
| `--search-radius` | 800 | Radius (m) for the nearby-business search |
| `--size` | 1280 | Square output size in pixels |
| `--no-businesses` | off | Skip the business lookup |
| `-o` | `output/<slug>.png` | Output PNG path |
| `-v` | off | Verbose logging |

**Batch** many addresses:

```bash
while read addr; do
  python -m parcelmap "$addr" --acres 3 -o "output/$(echo "$addr" | tr ' /' '__').png"
done < addresses.txt
```

### Web UI

```bash
python -m parcelmap.app
```

Open <http://127.0.0.1:5050>, paste an address, click **Generate map**, then view
or download the PNG. This is the friendliest option for non-technical staff.

> **One-click launcher (macOS):** double-click **`Start Parcel Map.command`** in
> the project root. It starts the server and opens the browser automatically.
> (Uses port 5050 — not 5000, which macOS AirPlay Receiver occupies.)

---

## How the geometry works

The satellite image spans a true ground distance of `2 × extent_m`. Because Web
Mercator stretches ground distance by `sec(latitude)` in both axes, and we apply
that same factor when building the image's bounding box, the overlay math
collapses to a latitude-independent rule:

> **pixels per ground meter = size_px ÷ (2 × extent_m)**

So the parcel outline and scale bar are always true-to-ground. See
`parcelmap/geo.py`.

---

## Project layout

```
parcelmap/
  config.py     defaults & free providers (no secrets)
  geo.py        Web Mercator + pixel mapping
  geocode.py    address -> lat/lng
  imagery.py    satellite image fetch (Esri + USGS)
  places.py     nearby businesses (Overpass)
  parcel.py     real lot/building polygon (Overpass)
  brands.py     brand -> domain table for logo resolution
  logos.py      DuckDuckGo favicon -> marker logo
  compose.py    assemble the final annotated image
  pipeline.py   one entry point: address -> image
  cli.py        command-line interface
  app.py        Flask web UI
templates/ static/   web assets
tests/         geo + composition unit tests
```

---

## Extending it

- **True tax-parcel lot lines:** the current outline uses the OSM building /
  address footprint (accurate shape, good US coverage). For authoritative lot
  lines you could add a county-GIS / Regrid source — `compose()` already draws
  any lat/lng polygon, so only `parcel.py` would change.
- **More brand logos:** extend `BRAND_DOMAIN` in `parcelmap/brands.py`.
- **Different imagery:** swap the URL in `config.ESRI_IMAGERY_URL`.

---

## Troubleshooting

- **"Could not geocode address"** — check the spelling / add city and state.
  Nominatim and Photon are both tried; both must fail for this error.
- **No businesses shown** — Overpass may be slow or the area sparsely mapped.
  Try a larger `--search-radius`, or run with `-v` to see which endpoints failed.
  The image still generates without businesses.
- **Logos missing for some businesses** — expected for non-chains / businesses
  without a mapped website; these fall back to text labels.
- **Imagery fails** — both Esri and USGS are tried; check connectivity. For
  heavy/commercial volume, Esri may require a license (use USGS NAIP for a
  public-domain US alternative).

---

## Licensing notes

- Code: yours to use.
- Map data: **© OpenStreetMap contributors** (ODbL) — attribution is baked in.
- Esri World Imagery: free with attribution for reasonable use; heavy commercial
  use may require an Esri license.
- USGS NAIP (the configured fallback): **U.S. public domain**, no attribution or
  licensing risk for US properties.
