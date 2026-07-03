"""Assemble the final annotated satellite image.

Layers, bottom to top:
  base satellite  ->  red parcel outline + address pin  ->  business markers
                  ->  title bar / word-wrapped legend / scale bar / north arrow / attribution

Markers are de-collided (decluttered): each label is nudged to a free position
around its point with a leader line back to the location. If no collision-free
spot exists (very dense areas), the business degrades to just a pin — its name
and distance remain in the legend. Labels are also kept off the chrome
(title / legend / scale / north).
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFont

from . import config
from .geo import ImageBounds

# Category -> marker/legend color (RGB).
CATEGORY_COLORS = {
    "fast_food": (210, 70, 40),
    "restaurant": (200, 90, 50),
    "cafe": (150, 90, 60),
    "bar": (120, 70, 130),
    "pub": (120, 70, 130),
    "ice_cream": (180, 90, 150),
    "bank": (40, 90, 160),
    "financial": (40, 90, 160),
    "pharmacy": (40, 150, 90),
    "fuel": (60, 130, 60),
    "car_wash": (60, 130, 130),
    "supermarket": (180, 60, 120),
    "convenience": (180, 90, 60),
    "car_repair": (90, 90, 90),
    "car": (90, 90, 90),
    "clothes": (150, 70, 150),
    "hardware": (120, 90, 50),
    "mobile_phone": (50, 120, 120),
    "doctors": (40, 150, 150),
    "dentist": (40, 150, 150),
    "veterinary": (40, 150, 150),
    "gym": (90, 130, 60),
    "school": (60, 100, 160),
    "kindergarten": (60, 100, 160),
    "hotel": (120, 60, 90),
    "office": (70, 70, 110),
}
DEFAULT_COLOR = (40, 120, 200)

_PLACEMENT_MARGIN = 8   # min pixel gap between two label boxes
_PLACEMENT_STEPS = 12   # how far to push a label out before degrading to a pin
_TITLE_BAR_H = 76
_LEGEND_MAX_ENTRIES = 12


def _color(category: str) -> tuple[int, int, int]:
    return CATEGORY_COLORS.get(category, DEFAULT_COLOR)


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold
        else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Supplemental/Tahoma.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _text_size(draw, text: str, font) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _word_wrap(draw, text: str, font, max_w: int) -> list[str]:
    """Wrap text to max_w pixels, breaking overly long single words too."""
    lines: list[str] = []
    cur = ""
    for raw in text.split():
        chunks = []
        word = raw
        while draw.textlength(word, font=font) > max_w and len(word) > 1:
            cut = 1
            while cut + 1 < len(word) and draw.textlength(word[: cut + 1], font=font) <= max_w:
                cut += 1
            chunks.append(word[:cut])
            word = word[cut:]
        chunks.append(word)
        for ch in chunks:
            test = ch if not cur else cur + " " + ch
            if draw.textlength(test, font=font) <= max_w:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = ch
    if cur:
        lines.append(cur)
    return lines or [""]


def _truncate_to_width(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    ell = "..."
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if draw.textlength(text[:mid].rstrip() + ell, font=font) <= max_w:
            lo = mid
        else:
            hi = mid - 1
    return text[:lo].rstrip() + ell


def _compact_title(title: str) -> str:
    parts = [p.strip() for p in title.split(",") if p.strip()]
    if not parts:
        return title

    useful = []
    for p in parts:
        if p.lower() == "united states" or p.lower().endswith("county"):
            continue
        useful.append("TX" if p == "Texas" else p)

    if len(useful) >= 3 and useful[1].isdigit():
        useful = [useful[0], f"{useful[1]} {useful[2]}", *useful[3:]]

    if "TX" in useful:
        useful = useful[: useful.index("TX") + 1]
    else:
        useful = useful[:4]
    return ", ".join(useful)


def _nice_scale_length(bounds: ImageBounds) -> float:
    target_px = 120.0
    meters = target_px / bounds.px_per_ground_meter()
    nice = []
    for mag in (1, 10, 100, 1000, 10000):
        nice.extend([mag, 2 * mag, 5 * mag])
    nice.sort()
    for cand in nice:
        if cand >= meters:
            return float(cand)
    return meters


# --- geometry helpers -------------------------------------------------------

def _rects_overlap(a, b, margin: int = _PLACEMENT_MARGIN) -> bool:
    return not (a[2] + margin <= b[0] or b[2] + margin <= a[0]
                or a[3] + margin <= b[1] or b[3] + margin <= a[1])


def _offscreen_amount(box, size) -> float:
    x0, y0, x1, y1 = box
    return (max(0, 4 - x0) + max(0, 4 - y0)
            + max(0, x1 - (size[0] - 4)) + max(0, y1 - (size[1] - 4)))


def _nearest_rect_point(px, py, box):
    return min(max(px, box[0]), box[2]), min(max(py, box[1]), box[3])


def _place_label(px, py, w, h, placed, size) -> tuple[int, int, bool]:
    """Find a free top-left (x0,y0) for a w×h box near (px,py).

    Returns (x0, y0, collided). Tries 8 directions at increasing radii; the first
    collision-free, on-screen position wins. If none is found, returns the
    least-bad position with collided=True so the caller can skip the label.
    """
    hw, hh = w / 2.0, h / 2.0
    angles = [0, 180, 270, 90, 45, 135, 225, 315]  # 0=right, 90=down (image coords)
    best = None
    for step in range(_PLACEMENT_STEPS):
        extra = step * 24
        for deg in angles:
            rad = math.radians(deg)
            reach = max(hw * abs(math.cos(rad)) + hh * abs(math.sin(rad)), 12.0)
            r = 14 + extra + reach
            cx = px + r * math.cos(rad)
            cy = py + r * math.sin(rad)
            box = (int(cx - hw), int(cy - hh), int(cx + hw), int(cy + hh))
            collide = any(_rects_overlap(box, p) for p in placed)
            off = _offscreen_amount(box, size)
            if not collide and off == 0:
                return box[0], box[1], False
            score = (collide, off, r)
            if best is None or score < best[0]:
                best = (score, box)
    return best[1][0], best[1][1], True


# --- parcel + markers -------------------------------------------------------

def _draw_parcel(overlay, bounds, polygon, center_lat, center_lng) -> None:
    d = ImageDraw.Draw(overlay)
    if polygon and len(polygon) >= 3:
        xy = [bounds.to_pixel(lat, lng) for (lat, lng) in polygon]
        d.polygon(xy, fill=config.AOI_COLOR + (config.AOI_FILL_ALPHA,))
        d.line(xy + [xy[0]], fill=(255, 255, 255, 230),
               width=config.AOI_STROKE_WIDTH + 5, joint="curve")
        d.line(xy + [xy[0]], fill=config.AOI_COLOR,
               width=config.AOI_STROKE_WIDTH, joint="curve")
    cx, cy = bounds.to_pixel(center_lat, center_lng)
    d.ellipse([cx - 9, cy - 9, cx + 9, cy + 9], fill=(255, 255, 255, 255),
              outline=config.AOI_COLOR + (255,), width=4)
    d.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill=config.AOI_COLOR + (255,))


def _sub_line(business) -> str:
    parts = []
    if business.category:
        parts.append(business.category.replace("_", " ").title())
    if business.distance_mi is not None:
        dist = "<0.01 mi" if business.distance_mi < 0.01 else f"{business.distance_mi:.2f} mi"
        parts.append(dist)
    return "  ·  ".join(parts)


def _text_box_size(draw, business) -> tuple[int, int]:
    name = business.name
    sub = _sub_line(business)
    nfont = _font(19, bold=True)
    sfont = _font(13)
    nw, nh = _text_size(draw, name, nfont)
    sw = sh = 0
    if sub:
        sw, sh = _text_size(draw, sub, sfont)
    pad_x, pad_y = 11, 7
    w = max(nw, sw) + pad_x * 2
    h = nh + (sh + 3 if sub else 0) + pad_y * 2
    return w, h


def _draw_text_box(layer, x0, y0, w, h, px, py, business) -> None:
    d = ImageDraw.Draw(layer)
    color = _color(business.category)
    lx, ly = _nearest_rect_point(px, py, (x0, y0, x0 + w, y0 + h))
    d.line([px, py, lx, ly], fill=color + (180,), width=2)
    d.rounded_rectangle([x0 + 3, y0 + 4, x0 + w + 3, y0 + h + 4], radius=9,
                        fill=(0, 0, 0, 70))
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=9,
                        fill=(255, 255, 255, 238), outline=color + (255,), width=2)
    nfont = _font(19, bold=True)
    sfont = _font(13)
    name = business.name
    sub = _sub_line(business)
    _, nh = _text_size(d, name, nfont)
    pad_x, pad_y = 11, 7
    d.text((x0 + pad_x, y0 + pad_y), name, font=nfont, fill=(28, 28, 28, 255))
    if sub:
        d.text((x0 + pad_x, y0 + pad_y + nh + 2), sub, font=sfont, fill=(110, 110, 110, 255))


def _draw_logo_box(layer, x0, y0, px, py, business) -> None:
    d = ImageDraw.Draw(layer)
    w, h = business.logo.size
    lx, ly = _nearest_rect_point(px, py, (x0, y0, x0 + w, y0 + h))
    d.line([px, py, lx, ly], fill=_color(business.category) + (180,), width=2)
    shadow = Image.new("RGBA", (w + 6, h + 6), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle([3, 3, w + 2, h + 2],
                                             radius=max(7, w // 8), fill=(0, 0, 0, 85))
    layer.alpha_composite(shadow, (x0 - 3, y0 - 2))
    layer.alpha_composite(business.logo, (x0, y0))


def _draw_pin(layer, px, py, color) -> None:
    ImageDraw.Draw(layer).ellipse(
        [px - 6, py - 6, px + 6, py + 6],
        fill=color + (255,), outline=(255, 255, 255, 255), width=2,
    )


def _subject_box_size(draw) -> tuple[int, int]:
    font = _font(15, bold=True)
    sub_font = _font(12)
    w1, h1 = _text_size(draw, "SUBJECT SITE", font)
    w2, h2 = _text_size(draw, "Outlined parcel", sub_font)
    return max(w1, w2) + 26, h1 + h2 + 20


def _draw_subject_callout(layer, x0, y0, w, h, px, py, has_polygon: bool) -> None:
    d = ImageDraw.Draw(layer)
    lx, ly = _nearest_rect_point(px, py, (x0, y0, x0 + w, y0 + h))
    d.line([px, py, lx, ly], fill=config.AOI_COLOR + (230,), width=3)
    d.rounded_rectangle([x0 + 4, y0 + 5, x0 + w + 4, y0 + h + 5], radius=8,
                        fill=(0, 0, 0, 95))
    d.rounded_rectangle([x0, y0, x0 + w, y0 + h], radius=8,
                        fill=(170, 26, 26, 242), outline=(255, 255, 255, 255), width=2)
    title_font = _font(15, bold=True)
    sub_font = _font(12)
    d.text((x0 + 13, y0 + 9), "SUBJECT SITE", font=title_font, fill=(255, 255, 255, 255))
    sub = "Outlined parcel" if has_polygon else "Address point"
    d.text((x0 + 13, y0 + 28), sub, font=sub_font, fill=(255, 225, 225, 255))
    d.ellipse([px - 12, py - 12, px + 12, py + 12], fill=(255, 255, 255, 255),
              outline=config.AOI_COLOR + (255,), width=4)
    d.ellipse([px - 4, py - 4, px + 4, py + 4], fill=config.AOI_COLOR + (255,))


# --- chrome (title / legend / scale / north / attribution) ------------------

def _draw_title(canvas, title):
    d = ImageDraw.Draw(canvas)
    W, _ = canvas.size
    label_font = _font(12, bold=True)
    title_font = _font(24, bold=True)
    pad = 16
    bar = Image.new("RGBA", (W, _TITLE_BAR_H), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    bd.rectangle([0, 0, W, _TITLE_BAR_H], fill=(17, 22, 29, 184))
    bd.line([0, _TITLE_BAR_H - 1, W, _TITLE_BAR_H - 1], fill=(255, 255, 255, 55), width=1)
    canvas.alpha_composite(bar, (0, 0))
    d.text((pad, 10), "SUBJECT PROPERTY", font=label_font, fill=(255, 196, 196, 255))
    display_title = _truncate_to_width(
        d, _compact_title(title), title_font, W - pad * 2 - 104
    )
    d.text((pad, 29), display_title, font=title_font, fill=(255, 255, 255, 255))


def _legend_geometry(draw, size, businesses):
    W, H = size
    title_font = _font(17, bold=True)
    name_font = _font(14, bold=True)
    sub_font = _font(12)
    pad = 12
    box_w = 286
    content_w = box_w - 2 * pad
    dot = 10
    name_line_h = 19
    sub_line_h = 16
    item_gap = 8
    title_h = 24
    footer_h = 0
    shown_businesses = businesses[:_LEGEND_MAX_ENTRIES]
    omitted = max(0, len(businesses) - len(shown_businesses))
    if omitted:
        footer_h = 22
    avail_h = H - _TITLE_BAR_H - 24

    entries = []
    for b in shown_businesses:
        sub = _sub_line(b)
        wrapped = _word_wrap(draw, b.name, name_font, content_w - dot - 10)
        nh = len(wrapped) * name_line_h
        sh = sub_line_h if sub else 0
        entries.append((b, wrapped, sub, nh + sh + item_gap))

    while entries and (title_h + sum(e[3] for e in entries) + footer_h + pad) > avail_h:
        entries.pop()
        omitted += 1
    if not entries:
        return None

    if omitted:
        footer_h = 22
    box_h = title_h + sum(e[3] for e in entries) + footer_h + pad
    x0 = 16
    y0 = H - box_h - 16
    return {
        "box": (x0, y0, x0 + box_w, y0 + box_h),
        "entries": entries,
        "omitted": omitted,
        "fonts": (title_font, name_font, sub_font),
        "pad": pad, "dot": dot,
        "name_line_h": name_line_h, "sub_line_h": sub_line_h,
        "item_gap": item_gap, "title_h": title_h,
    }


def _draw_legend(canvas, g):
    d = ImageDraw.Draw(canvas)
    x0, y0, x1, y1 = g["box"]
    title_font, name_font, sub_font = g["fonts"]
    pad, dot = g["pad"], g["dot"]
    d.rounded_rectangle([x0 + 4, y0 + 5, x1 + 4, y1 + 5], radius=10, fill=(0, 0, 0, 75))
    d.rounded_rectangle([x0, y0, x1, y1], radius=10,
                        fill=(255, 255, 255, 242), outline=(174, 179, 187, 255), width=1)
    d.text((x0 + pad, y0 + pad), "Nearby businesses", font=title_font, fill=(30, 30, 30, 255))
    yy = y0 + pad + g["title_h"]
    for b, wrapped, sub, _ in g["entries"]:
        color = _color(b.category)
        d.ellipse([x0 + pad, yy + 4, x0 + pad + dot, yy + 4 + dot], fill=color + (255,))
        tx = x0 + pad + dot + 10
        for i, line in enumerate(wrapped):
            d.text((tx, yy + i * g["name_line_h"]), line, font=name_font, fill=(40, 40, 40, 255))
        name_h = len(wrapped) * g["name_line_h"]
        if sub:
            d.text((tx, yy + name_h + 1), sub, font=sub_font, fill=(105, 105, 105, 255))
        yy += name_h + (g["sub_line_h"] if sub else 0) + g["item_gap"]
    if g.get("omitted"):
        d.line([x0 + pad, yy - 1, x1 - pad, yy - 1], fill=(215, 218, 224, 255), width=1)
        d.text((x0 + pad, yy + 5), f"+ {g['omitted']} more nearby", font=sub_font,
               fill=(75, 82, 92, 255))


def _draw_scale(canvas, bounds):
    d = ImageDraw.Draw(canvas)
    length_m = _nice_scale_length(bounds)
    length_px = bounds.ground_m_to_px(length_m)
    x0 = canvas.size[0] - length_px - 40
    y0 = canvas.size[1] - 40
    d.line([x0, y0, x0 + length_px, y0], fill=(255, 255, 255, 255), width=4)
    d.line([x0, y0 - 6, x0, y0 + 6], fill=(255, 255, 255, 255), width=3)
    d.line([x0 + length_px, y0 - 6, x0 + length_px, y0 + 6], fill=(255, 255, 255, 255), width=3)
    font = _font(14, bold=True)
    label = f"{int(length_m)} m" if length_m < 1000 else f"{length_m / 1000:g} km"
    tw, th = _text_size(d, label, font)
    d.rounded_rectangle(
        [x0 + length_px / 2 - tw / 2 - 7, y0 - th - 19,
         x0 + length_px / 2 + tw / 2 + 7, y0 - th - 1],
        radius=5, fill=(0, 0, 0, 150),
    )
    d.text((x0 + length_px / 2 - tw / 2, y0 - th - 16), label, font=font, fill=(255, 255, 255, 255))


def _draw_north(canvas):
    d = ImageDraw.Draw(canvas)
    cx = canvas.size[0] - 44
    cy = 86
    d.polygon([(cx, cy - 20), (cx - 11, cy + 9), (cx, cy + 2), (cx + 11, cy + 9)],
              fill=(255, 255, 255, 235), outline=(40, 40, 40, 255))
    font = _font(16, bold=True)
    tw, _ = _text_size(d, "N", font)
    d.text((cx - tw / 2, cy - 38), "N", font=font, fill=(255, 255, 255, 255))


def _draw_attribution(canvas):
    d = ImageDraw.Draw(canvas)
    font = _font(12)
    text = config.ATTRIBUTION
    tw, th = _text_size(d, text, font)
    x = (canvas.size[0] - tw) // 2
    y = canvas.size[1] - th - 8
    d.rounded_rectangle([x - 8, y - 3, x + tw + 8, y + th + 3], radius=4, fill=(255, 255, 255, 180))
    d.text((x, y), text, font=font, fill=(60, 60, 60, 255))


def _reserve_regions(size, legend_box):
    W, H = size
    regions = [
        (0, 0, W, _TITLE_BAR_H),    # title strip
        (W - 96, 0, W, 132),        # north badge
        (W - 320, H - 72, W, H),    # scale bar
        (W // 2 - 260, H - 44, W // 2 + 260, H),  # attribution
    ]
    if legend_box:
        regions.append(legend_box)
    return regions


def compose(
    base: Image.Image,
    bounds: ImageBounds,
    center_lat: float,
    center_lng: float,
    parcel_polygon,
    businesses,
    title: str,
) -> Image.Image:
    """Compose the final annotated RGB image."""
    canvas = base.convert("RGBA")
    W, H = canvas.size

    # Red lot/building outline + address pin on its own layer.
    aoi = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _draw_parcel(aoi, bounds, parcel_polygon, center_lat, center_lng)
    canvas.alpha_composite(aoi)

    # Figure out where the chrome will sit so markers avoid it.
    measure = ImageDraw.Draw(canvas)
    legend_geom = _legend_geometry(measure, canvas.size, businesses)
    placed = _reserve_regions(canvas.size, legend_geom["box"] if legend_geom else None)
    sx, sy = bounds.to_pixel(center_lat, center_lng)
    sw, sh = _subject_box_size(measure)
    subject_x, subject_y, _ = _place_label(sx, sy, sw, sh, placed, canvas.size)
    placed.append((subject_x, subject_y, subject_x + sw, subject_y + sh))

    # Business markers, nearest first, decluttered. A label is only drawn when it
    # lands collision-free; otherwise the business degrades to a pin (name +
    # distance stay in the legend).
    markers = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    for b in businesses[: config.MAP_MAX_MARKERS]:
        px, py = bounds.to_pixel(b.lat, b.lng)
        if not (0 <= px < W and 0 <= py < H):
            continue
        if b.logo is not None:
            w, h = b.logo.size
        else:
            w, h = _text_box_size(measure, b)
        x0, y0, collided = _place_label(px, py, w, h, placed, canvas.size)
        pin_color = _color(b.category)
        if not collided:
            placed.append((x0, y0, x0 + w, y0 + h))
            if b.logo is not None:
                _draw_logo_box(markers, x0, y0, px, py, b)
            else:
                _draw_text_box(markers, x0, y0, w, h, px, py, b)
        _draw_pin(markers, px, py, pin_color)
    canvas.alpha_composite(markers)

    subject = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    _draw_subject_callout(
        subject, subject_x, subject_y, sw, sh, sx, sy, parcel_polygon is not None
    )
    canvas.alpha_composite(subject)

    _draw_title(canvas, title)
    if legend_geom:
        _draw_legend(canvas, legend_geom)
    _draw_scale(canvas, bounds)
    _draw_north(canvas)
    _draw_attribution(canvas)

    return canvas.convert("RGB")
