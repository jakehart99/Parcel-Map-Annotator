"""Local web UI (Flask). Run: python -m parcelmap.app -> http://127.0.0.1:5050

Paste an address, optionally set lot size / framing, and view/download the
annotated map image. No API keys, fully on-device.
"""
from __future__ import annotations

import io
import logging
import os

from flask import Flask, abort, redirect, render_template, request, send_file, url_for
from PIL import Image

from . import config, pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_ROOT = os.path.dirname(__file__)
_MIN_WEB_SIZE_PX = 640
_MAX_WEB_SIZE_PX = 1280
_MIN_EXTENT_M = 100
_MAX_EXTENT_M = 5000
_MIN_SEARCH_RADIUS_M = 100
_MAX_SEARCH_RADIUS_M = 5000
_MAX_RESPONSE_BYTES = int(os.environ.get("PARCELMAP_MAX_RESPONSE_BYTES", "4300000"))

try:
    _RESAMPLE = Image.Resampling.LANCZOS
except AttributeError:  # pragma: no cover
    _RESAMPLE = Image.LANCZOS  # type: ignore[attr-defined]

app = Flask(
    __name__,
    template_folder=os.path.join(_ROOT, "..", "templates"),
    static_folder=os.path.join(_ROOT, "..", "static"),
)


def _num(form_value, cast=float, default=None):
    raw = (form_value or "").strip()
    if raw == "":
        return default
    try:
        return cast(raw)
    except (TypeError, ValueError):
        return default


def _clamp(value, minimum, maximum):
    if value is None:
        return None
    return max(minimum, min(maximum, value))


def _initial_values():
    return {
        "address": "",
        "acres": "",
        "extent": str(config.DEFAULT_EXTENT_M),
        "search_radius": str(config.DEFAULT_SEARCH_RADIUS_M),
        "size": str(config.DEFAULT_SIZE_PX),
    }


def _values_from_mapping(mapping, address: str):
    values = _initial_values()
    values.update({
        "address": address,
        "acres": (mapping.get("acres") or "").strip(),
        "extent": (mapping.get("extent") or "").strip() or values["extent"],
        "search_radius": (mapping.get("search_radius") or "").strip() or values["search_radius"],
        "size": (mapping.get("size") or "").strip() or values["size"],
    })
    return values


def _submitted_values(address: str):
    return _values_from_mapping(request.form, address)


def _map_options(mapping):
    extent_m = _num(mapping.get("extent"), default=config.DEFAULT_EXTENT_M)
    search_radius_m = _num(mapping.get("search_radius"), default=config.DEFAULT_SEARCH_RADIUS_M)
    size = _num(mapping.get("size"), cast=int, default=config.DEFAULT_SIZE_PX)
    return {
        "lot_size_acres": _num(mapping.get("acres")),
        "extent_m": _clamp(extent_m, _MIN_EXTENT_M, _MAX_EXTENT_M),
        "search_radius_m": _clamp(search_radius_m, _MIN_SEARCH_RADIUS_M, _MAX_SEARCH_RADIUS_M),
        "size": _clamp(size, _MIN_WEB_SIZE_PX, _MAX_WEB_SIZE_PX),
    }


def _png_buffer(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True, compress_level=9)
    return buf


def _send_png(img, download: bool = False):
    working = img
    buf = _png_buffer(working)

    while buf.getbuffer().nbytes > _MAX_RESPONSE_BYTES and min(working.size) > _MIN_WEB_SIZE_PX:
        next_size = max(_MIN_WEB_SIZE_PX, int(min(working.size) * 0.85))
        working = working.resize((next_size, next_size), _RESAMPLE)
        buf = _png_buffer(working)

    buf.seek(0)
    kwargs = {
        "mimetype": "image/png",
        "as_attachment": download,
        "max_age": 300,
    }
    if download:
        kwargs["download_name"] = "parcel-map.png"
    return send_file(buf, **kwargs)


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", values=_initial_values())


@app.route("/generate", methods=["POST"])
def generate():
    address = (request.form.get("address") or "").strip()
    if not address:
        abort(400, "Address is required")
    values = _submitted_values(address)
    return redirect(url_for("result", **values), code=303)


@app.route("/result", methods=["GET"])
def result():
    address = (request.args.get("address") or "").strip()
    if not address:
        return redirect(url_for("index"), code=303)
    values = _values_from_mapping(request.args, address)
    image_url = url_for("map_png", **values)
    download_url = url_for("map_png", **values, download="1")
    return render_template(
        "index.html",
        image_url=image_url,
        download_url=download_url,
        address=address,
        values=values,
    )


@app.route("/map.png", methods=["GET"])
def map_png():
    address = (request.args.get("address") or "").strip()
    if not address:
        abort(400, "Address is required")

    try:
        img = pipeline.generate_map_image(
            address=address,
            **_map_options(request.args),
        )
    except Exception as e:
        abort(500, str(e))

    return _send_png(img, download=request.args.get("download") == "1")


if __name__ == "__main__":
    # Port 5050 (not 5000) — macOS AirPlay Receiver claims 5000 on Monterey+.
    app.run(host="127.0.0.1", port=5050, debug=True)
