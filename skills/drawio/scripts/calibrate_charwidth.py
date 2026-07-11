#!/usr/bin/env python3
"""Measure rendered text widths on this box and write calibration.json (stage: CALIBRATE).

Usage: calibrate_charwidth.py [--keep] [--outdir DIR]

Renders a fixture of known strings next to a reference rect through the pinned
headless image, measures dark-pixel extents with PIL, and writes per-class width
ratios plus a conservative flat p95 next to constants.py. validate.py prefers
calibration.json when present and falls back to the constants otherwise.

Skips cleanly (exit 2) when docker or PIL is absent: calibration is machine-local
and must never be faked from the constants it is meant to replace.
"""
import argparse
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from constants import DOCKER_IMAGE, DOCKER_SHM, RENDER_TIMEOUT_S

REF_X, REF_Y, REF_W, REF_H = 40, 40, 400, 20
ROW_X, ROW_Y0, ROW_DY, ROW_H = 40, 100, 60, 30

# (text, fontSize, bold, class). class in wide/xwide/narrow/body feeds that class
# average; "mixed" feeds the flat p95; None is a sanity row. Caps-heavy real
# labels are the point: all-caps advances are wider than typical mixed case and
# an overflow estimate must not under-count them.
ROWS = [
    ("ABCDEFGHJKLNOPQRSTUVYZ0123456789@#%_", 12, 0, "wide"),
    ("MWMWMWMWMWMWmwmwmwmwmwmw", 12, 0, "xwide"),
    ("iltfjr.,:;'()[]iltfjr.,:;'()[]", 12, 0, "narrow"),
    ("aeosnucdgkbpqvxyzaeosnucdgkbpqvxyz", 12, 0, "body"),
    ("M" * 16, 12, 0, None),
    ("i" * 16, 12, 0, None),
    ("REST / HTTP", 12, 0, "mixed"),
    ("PromQL query", 12, 0, "mixed"),
    ("SQL", 12, 0, "mixed"),
    ("HTTPS", 12, 0, "mixed"),
    ("auth-service (FastAPI) v2.1", 12, 0, "mixed"),
    ("Orchestrate Linear Backlog Payments", 12, 0, "mixed"),
    ("REST / HTTP", 11, 0, "mixed"),
    ("PromQL query", 14, 0, "mixed"),
    ("Orchestrate Linear Backlog", 12, 0, "boldpair"),
    ("Orchestrate Linear Backlog", 12, 1, "boldpair"),
]


def gen_xml():
    cells = [
        f'<mxCell id="ref" value="" style="rounded=0;fillColor=#000000;strokeColor=none;" '
        f'vertex="1" parent="1"><mxGeometry x="{REF_X}" y="{REF_Y}" width="{REF_W}" '
        f'height="{REF_H}" as="geometry" /></mxCell>'
    ]
    for i, (text, size, bold, _cls) in enumerate(ROWS):
        y = ROW_Y0 + i * ROW_DY
        style = (
            "text;html=1;align=left;verticalAlign=middle;"
            f"fontSize={size};fontStyle={bold};fontColor=#000000;fillColor=none;strokeColor=none;"
        )
        esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
        cells.append(
            f'<mxCell id="t{i}" value="{esc}" style="{style}" vertex="1" parent="1">'
            f'<mxGeometry x="{ROW_X}" y="{y}" width="700" height="{ROW_H}" as="geometry" /></mxCell>'
        )
    body = "\n        ".join(cells)
    return f"""<mxfile host="calib" compressed="false">
  <diagram id="c1" name="calib">
    <mxGraphModel dx="800" dy="600" grid="0" gridSize="10" page="1" pageWidth="850" pageHeight="1400" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        {body}
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>"""


def render(drawio_path, png_path):
    work = os.path.dirname(drawio_path)
    subprocess.run(
        ["timeout", str(RENDER_TIMEOUT_S), "docker", "run", "--rm",
         f"--shm-size={DOCKER_SHM}", "-w", "/data", "-v", f"{work}:/data",
         DOCKER_IMAGE, "-x", "-f", "png", "-s", "1",
         "-o", os.path.basename(png_path), os.path.basename(drawio_path)],
        capture_output=True,  # docker exit code is unreliable; the file check decides
    )
    return os.path.exists(png_path) and os.path.getsize(png_path) > 0


def measure(png_path):
    from PIL import Image

    img = Image.open(png_path).convert("L")
    w, h = img.size
    px = img.load()

    def dark_cols(y_lo, y_hi):
        cols = []
        for x in range(w):
            for y in range(max(0, y_lo), min(h, y_hi)):
                if px[x, y] < 128:
                    cols.append(x)
                    break
        return cols

    ref_cols = dark_cols(0, int(REF_Y + REF_H + 10))
    if not ref_cols:
        raise RuntimeError("reference rect not found in render")
    scale = (max(ref_cols) - min(ref_cols) + 1) / REF_W

    rows = []
    for i, (text, size, bold, cls) in enumerate(ROWS):
        y_unit = ROW_Y0 + i * ROW_DY
        y_lo = int((y_unit - REF_Y) * scale)
        y_hi = int((y_unit + ROW_H - REF_Y) * scale)
        cols = dark_cols(y_lo, y_hi)
        if not cols:
            continue
        width_u = (max(cols) - min(cols) + 1) / scale
        char_w = width_u / len(text)
        rows.append({
            "text": text, "fontSize": size, "bold": bool(bold), "class": cls,
            "len": len(text), "width_u": round(width_u, 2),
            "char_w_u": round(char_w, 3), "ratio": round(char_w / size, 4),
        })
    return scale, rows


def p95(values):
    if not values:
        return None
    s = sorted(values)
    idx = min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)
    return s[idx]


def summarize(rows):
    def mean_ratio(cls):
        rs = [r["ratio"] for r in rows if r["class"] == cls]
        return round(sum(rs) / len(rs), 4) if rs else None

    classes = {
        "wide": mean_ratio("wide"),
        "xwide": mean_ratio("xwide"),
        "narrow": mean_ratio("narrow"),
        "body": mean_ratio("body"),
    }
    mixed = [r["ratio"] for r in rows if r["class"] == "mixed"]
    flat = round(p95(mixed), 4) if mixed else None

    bp = {r["bold"]: r["ratio"] for r in rows if r["class"] == "boldpair"}
    bold_factor = round(bp[True] / bp[False], 4) if bp.get(True) and bp.get(False) else None

    return classes, bold_factor, flat


def main():
    ap = argparse.ArgumentParser(
        description="stage CALIBRATE: measure text widths, write calibration.json next to constants.py"
    )
    ap.add_argument("--keep", action="store_true", help="keep the rendered fixture for inspection")
    ap.add_argument("--outdir", help="directory for intermediate files (default: temp)")
    args = ap.parse_args()

    if not shutil.which("docker"):
        print("calibrate: docker not found; cannot measure (calibration must be real, not faked)")
        return 2
    try:
        import PIL  # noqa: F401
    except ImportError:
        print("calibrate: PIL not found; cannot measure the render")
        return 2

    work = args.outdir or tempfile.mkdtemp(prefix="drawio-calib-")
    os.makedirs(work, exist_ok=True)
    drawio_path = os.path.join(work, "calib.drawio")
    png_path = os.path.join(work, "calib.png")
    with open(drawio_path, "w", encoding="utf-8") as f:
        f.write(gen_xml())

    if not render(drawio_path, png_path):
        print("calibrate: render produced no PNG (docker hung or failed)")
        return 2

    scale, rows = measure(png_path)
    classes, bold_factor, flat = summarize(rows)

    out = {
        "classes": classes,
        "bold_factor": bold_factor,
        "flat_p95_mixed": flat,
        "measured_rows": rows,
        "scale_px_per_unit": round(scale, 4),
        "image": DOCKER_IMAGE,
    }
    out_path = os.path.join(SCRIPT_DIR, "calibration.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2)
        f.write("\n")

    if not args.keep and not args.outdir:
        shutil.rmtree(work, ignore_errors=True)

    print(f"calibrate: wrote {out_path}")
    print(f"  classes={classes} bold_factor={bold_factor} flat_p95_mixed={flat} scale={scale:.4f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
