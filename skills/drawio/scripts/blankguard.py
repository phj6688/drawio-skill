#!/usr/bin/env python3
"""Detect a blank or degenerate render (stage: RENDER).

Usage: blankguard.py SVG [PNG] [--source FILE]

The renderer's exit code lies (it prints "Export Failed" on success and can
emit a blank canvas for malformed input without erroring), so a render is only
trusted after counting drawable marks in the SVG. Exit 0 quiet on ok, exit 1
with a reason on fail. render.sh owns all success messaging.
"""
import argparse
import math
import os
import sys
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from constants import (
    SVG_ELEM_RATIO,
    PNG_MIN_BYTES,
    PIXEL_STDEV_MIN,
    DISTINCT_COLORS_MIN,
    ABS_FLOOR,
)
from validate import reject_dangerous_xml

# SVG marks that carry visible geometry. div/foreignObject/switch are html-label
# scaffolding, not marks; <image> is drawio's label fallback and counts as content.
DRAWABLE_TAGS = {"path", "rect", "ellipse", "circle", "polygon", "image", "text"}


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def _float(v):
    try:
        return float(str(v).replace("px", "").strip())
    except (TypeError, ValueError):
        return None


def count_drawables(svg_path):
    root = ET.parse(svg_path).getroot()
    canvas_w = _float(root.get("width"))
    canvas_h = _float(root.get("height"))
    n = 0
    for el in root.iter():
        tag = _local(el.tag)
        if tag not in DRAWABLE_TAGS:
            continue
        # Drop a full-canvas rect: it is the background, not a mark.
        if tag == "rect" and canvas_w and canvas_h:
            rw, rh = _float(el.get("width")), _float(el.get("height"))
            if rw and rh and rw >= 0.98 * canvas_w and rh >= 0.98 * canvas_h:
                continue
        n += 1
    return n


def source_cell_counts(src_path):
    """Vertices + edges in the source .drawio, ignoring the id 0/1 roots.

    Reads uncompressed XML only; the author writes uncompressed and the layout
    driver re-emits -f xml uncompressed, so a compressed body here means the
    wrong file was passed.
    """
    with open(src_path, encoding="utf-8") as f:
        raw = f.read()
    reject_dangerous_xml(raw)
    root = ET.fromstring(raw)
    verts = edges = 0
    for c in root.iter("mxCell"):
        if c.get("vertex") == "1":
            verts += 1
        elif c.get("edge") == "1":
            edges += 1
    return verts, edges


def pil_degenerate(png_path):
    """Return a failure reason if PIL is present and the PNG looks blank, else None.

    Absent PIL yields None (skip): the SVG mark count is the primary gate.
    """
    try:
        from PIL import Image
    except ImportError:
        return None
    if os.path.getsize(png_path) < PNG_MIN_BYTES:
        return f"PNG {os.path.getsize(png_path)}B < {PNG_MIN_BYTES}B floor"
    img = Image.open(png_path).convert("RGB").resize((64, 64))
    raw = img.tobytes()  # 64*64*3 bytes; avoids the deprecated getdata path
    px = [raw[i : i + 3] for i in range(0, len(raw), 3)]
    lum = [(299 * p[0] + 587 * p[1] + 114 * p[2]) / 1000 for p in px]
    mean = sum(lum) / len(lum)
    stdev = math.sqrt(sum((v - mean) ** 2 for v in lum) / len(lum))
    if stdev <= PIXEL_STDEV_MIN:
        return f"pixel luminance stdev {stdev:.2f} <= {PIXEL_STDEV_MIN} (flat image)"
    distinct = len(set(px))
    if distinct <= DISTINCT_COLORS_MIN:
        return f"only {distinct} distinct colors <= {DISTINCT_COLORS_MIN}"
    return None


def main():
    ap = argparse.ArgumentParser(
        description="stage RENDER: fail if the SVG/PNG is a blank or degenerate render"
    )
    ap.add_argument("svg")
    ap.add_argument("png", nargs="?")
    ap.add_argument("--source", help="source .drawio for the drawable-ratio gate")
    args = ap.parse_args()

    try:
        drawables = count_drawables(args.svg)
    except (ET.ParseError, FileNotFoundError, OSError) as e:
        print(f"blankguard: SVG unreadable ({e})")
        return 1

    if args.source:
        verts, edges = source_cell_counts(args.source)
        need = max(ABS_FLOOR, SVG_ELEM_RATIO * (verts + edges))
        if drawables < need:
            print(
                f"blankguard: {drawables} SVG marks < {need:.1f} "
                f"(ratio {SVG_ELEM_RATIO} * {verts} vertices + {edges} edges)"
            )
            return 1
    elif drawables < ABS_FLOOR:
        print(f"blankguard: {drawables} SVG marks < {ABS_FLOOR} floor")
        return 1

    if args.png and os.path.exists(args.png):
        reason = pil_degenerate(args.png)
        if reason:
            print(f"blankguard: {reason}")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
