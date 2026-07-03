"""Local web UI (Flask). Run: python -m parcelmap.app -> http://127.0.0.1:5000

Paste an address, optionally set lot size / framing, and view/download the
annotated map image. No API keys, fully on-device.
"""
from __future__ import annotations

import base64
import io
import logging
import os

from flask import Flask, abort, render_template, request

from . import config, pipeline

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

_ROOT = os.path.dirname(__file__)
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


def _initial_values():
    return {
        "address": "",
        "acres": "",
        "extent": str(config.DEFAULT_EXTENT_M),
        "search_radius": str(config.DEFAULT_SEARCH_RADIUS_M),
        "size": str(config.DEFAULT_SIZE_PX),
    }


def _submitted_values(address: str):
    values = _initial_values()
    values.update({
        "address": address,
        "acres": (request.form.get("acres") or "").strip(),
        "extent": (request.form.get("extent") or "").strip() or values["extent"],
        "search_radius": (request.form.get("search_radius") or "").strip() or values["search_radius"],
        "size": (request.form.get("size") or "").strip() or values["size"],
    })
    return values


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", values=_initial_values())


@app.route("/generate", methods=["POST"])
def generate():
    address = (request.form.get("address") or "").strip()
    if not address:
        abort(400, "Address is required")
    values = _submitted_values(address)

    try:
        img = pipeline.generate_map_image(
            address=address,
            lot_size_acres=_num(request.form.get("acres")),
            extent_m=_num(request.form.get("extent")),
            search_radius_m=_num(request.form.get("search_radius")),
            size=_num(request.form.get("size"), cast=int),
        )
    except Exception as e:
        return render_template("index.html", error=str(e), address=address, values=values), 500

    buf = io.BytesIO()
    img.save(buf, "PNG")
    image_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return render_template(
        "index.html",
        image=image_b64,
        address=address,
        values=values,
    )


if __name__ == "__main__":
    # Port 5050 (not 5000) — macOS AirPlay Receiver claims 5000 on Monterey+.
    app.run(host="127.0.0.1", port=5050, debug=True)
