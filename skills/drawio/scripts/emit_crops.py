#!/usr/bin/env python3
"""Cut LOOK crops from a render using validate.py regions (stage: LOOK).

Usage: emit_crops.py FILE PNG REPORT_JSON [--outdir DIR]

Consumes the frozen validate.py --json report, maps each flagged region from
drawio units to PNG pixels, and writes one crop per region (gate hits first,
then near-misses, then the legend, then the four quadrants) up to MAX_CROPS.
Each crop gets a nonce; the printed DONE-CHECK skeleton is pre-filled with crop
ids, gate results, and nonces so the LOOK step's only remaining work is reading
each crop and quoting what it sees.

Without PIL the crops cannot be cut: it writes crops.txt with the pixel
rectangles and says so, and the LOOK falls back to the full PNG.
"""
import argparse
import json
import os
import secrets
import sys
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from constants import MAX_CROPS, LEGEND_ID_TOKEN, CROP_MARGIN_PX
from validate import decompress_body, reject_dangerous_xml

# Region kinds that mark a defect worth a dedicated crop, in priority order.
HIT_KINDS = ("label-collision", "edge-through-node", "overflow")


def png_size(path):
    """Read width/height from the PNG IHDR chunk; no PIL dependency for mapping."""
    with open(path, "rb") as f:
        head = f.read(24)
    if head[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    return int.from_bytes(head[16:20], "big"), int.from_bytes(head[20:24], "big")


def _iter_models(src_path):
    """Yield each page's mxGraphModel, decompressing compressed diagram bodies.

    Uses the validator's loader helpers so the LOOK stage sees the same cells the
    validator did: drawio-desktop's default save is compressed, and its raw text
    carries no mxCell elements at all.
    """
    with open(src_path, encoding="utf-8") as f:
        data = f.read()
    reject_dangerous_xml(data)
    root = ET.fromstring(data)
    if root.tag.rsplit("}", 1)[-1] == "mxGraphModel":
        yield root
        return
    for dia in root.findall("diagram"):
        model = dia.find("mxGraphModel")
        if model is None:
            body = (dia.text or "").strip()
            if body:
                body_xml = decompress_body(body)
                reject_dangerous_xml(body_xml)
                model = ET.fromstring(body_xml)
        if model is not None:
            yield model


def parse_vertices(src_path):
    """Return [(id, style, ax, ay, w, h)] with absolute coords (container children
    resolved). Handles compressed bodies and object/UserObject-wrapped cells."""
    cells = {}
    for model in _iter_models(src_path):
        scope = model.find("root")
        if scope is None:
            scope = model
        for c in scope.findall("mxCell"):
            cid = c.get("id")
            if cid is not None:
                cells[cid] = c
        # object/UserObject wraps a cell: the id is on the wrapper, geometry on the
        # inner mxCell. Stamp the id onto the inner cell so it resolves like any other.
        for obj in scope.findall("object") + scope.findall("UserObject"):
            inner = obj.find("mxCell")
            oid = obj.get("id")
            if inner is not None and oid is not None:
                inner.set("id", oid)
                cells[oid] = inner

    def geom(c):
        g = c.find("mxGeometry")
        if g is None:
            return None
        try:
            return (float(g.get("x", 0)), float(g.get("y", 0)),
                    float(g.get("width", 0)), float(g.get("height", 0)))
        except (TypeError, ValueError):
            return None

    def abs_origin(c, seen):
        p = c.get("parent")
        if p in (None, "0", "1") or p not in cells or p in seen:
            return (0.0, 0.0)
        pc = cells[p]
        g = geom(pc)
        base = abs_origin(pc, seen | {p})
        if g is None or pc.get("vertex") != "1":
            return base
        return (base[0] + g[0], base[1] + g[1])

    out = []
    for cid, c in cells.items():
        if c.get("vertex") != "1":
            continue
        g = geom(c)
        if g is None or g[2] <= 0 or g[3] <= 0:
            continue
        ox, oy = abs_origin(c, {cid})
        out.append((cid, c.get("style", "") or "", ox + g[0], oy + g[1], g[2], g[3]))
    return out


def content_bbox(verts):
    xs0 = min(v[2] for v in verts)
    ys0 = min(v[3] for v in verts)
    xs1 = max(v[2] + v[4] for v in verts)
    ys1 = max(v[3] + v[5] for v in verts)
    return xs0, ys0, xs1 - xs0, ys1 - ys0


def is_content(cid):
    return LEGEND_ID_TOKEN not in (cid or "").lower()


def geometry_summary(verts):
    """aspect, area utilization, and quadrant node counts, computed from the source."""
    content = [v for v in verts if is_content(v[0])]
    if not content:
        content = verts
    x0, y0, w, h = content_bbox(content)
    aspect = w / h if h else 0.0
    node_area = sum(v[4] * v[5] for v in content)
    util = node_area / (w * h) if w and h else 0.0
    mx, my = x0 + w / 2, y0 + h / 2
    quad = [0, 0, 0, 0]  # TL, TR, BL, BR
    for v in content:
        cx, cy = v[2] + v[4] / 2, v[3] + v[5] / 2
        i = (0 if cx < mx else 1) + (0 if cy < my else 2)
        quad[i] += 1
    return aspect, util, quad


def failed_gate_set(report):
    out = set()
    for g in report.get("gates_failed", []):
        try:
            out.add(int(g))
        except (TypeError, ValueError):
            if isinstance(g, dict):
                for k in ("check", "id", "number"):
                    if k in g:
                        try:
                            out.add(int(g[k]))
                        except (TypeError, ValueError):
                            pass
    return out


def select_regions(regions):
    buckets = {k: [] for k in ("hit", "near", "legend", "quadrant", "other")}
    for r in regions:
        k = r.get("kind")
        if k in HIT_KINDS:
            buckets["hit"].append(r)
        elif k == "near-miss":
            buckets["near"].append(r)
        elif k == "legend":
            buckets["legend"].append(r)
        elif k == "quadrant":
            buckets["quadrant"].append(r)
        else:
            buckets["other"].append(r)
    ordered = (buckets["hit"] + buckets["other"] + buckets["near"]
               + buckets["legend"] + buckets["quadrant"])
    return ordered[:MAX_CROPS]


def main():
    ap = argparse.ArgumentParser(
        description="stage LOOK: cut crops from a render using validate.py regions"
    )
    ap.add_argument("file")
    ap.add_argument("png")
    ap.add_argument("report_json")
    ap.add_argument("--outdir")
    args = ap.parse_args()

    for p in (args.file, args.png, args.report_json):
        if not os.path.exists(p):
            print(f"emit_crops: missing input: {p}", file=sys.stderr)
            return 2

    with open(args.report_json, encoding="utf-8") as f:
        report = json.load(f)

    verts = parse_vertices(args.file)
    if not verts:
        print("emit_crops: source has no sized vertices; nothing to map", file=sys.stderr)
        return 2
    cx0, cy0, cw, ch = content_bbox(verts)
    pw, ph = png_size(args.png)
    scale = pw / cw if cw else 1.0  # drawio PNG crops to content; width fixes the scale

    outdir = args.outdir or os.path.join(os.path.dirname(os.path.abspath(args.png)), "crops")
    os.makedirs(outdir, exist_ok=True)

    def to_box(bbox):
        bx, by, bw, bh = bbox
        px, py = (bx - cx0) * scale, (by - cy0) * scale
        left = max(0, int(px - CROP_MARGIN_PX))
        top = max(0, int(py - CROP_MARGIN_PX))
        right = min(pw, int(px + bw * scale + CROP_MARGIN_PX))
        bottom = min(ph, int(py + bh * scale + CROP_MARGIN_PX))
        if right <= left:
            right = min(pw, left + 1)
        if bottom <= top:
            bottom = min(ph, top + 1)
        return left, top, right, bottom

    selected = select_regions(report.get("regions", []))
    crops = []
    n = 0
    for r in selected:
        kind = r.get("kind", "region")
        bbox = r.get("bbox") or [cx0, cy0, cw, ch]
        if kind == "legend" and not any(c["id"] == "crop-legend" for c in crops):
            cid = "crop-legend"
        else:
            n += 1
            cid = f"crop-{n}"
        crops.append({
            "id": cid, "nonce": secrets.token_hex(4), "kind": kind,
            "note": (r.get("note") or "").strip(), "box": to_box(bbox),
        })

    try:
        from PIL import Image
        have_pil = True
    except ImportError:
        have_pil = False

    degraded = ""
    if have_pil:
        img = Image.open(args.png).convert("RGB")
        for c in crops:
            img.crop(c["box"]).save(os.path.join(outdir, f"{c['id']}.png"))
    else:
        lines = ["PIL absent: crops were not cut. LOOK the full PNG at the pixel rectangles below.",
                 f"full PNG: {os.path.abspath(args.png)} ({pw}x{ph})"]
        for c in crops:
            l, t, rgt, b = c["box"]
            lines.append(f"{c['id']} {c['kind']} px[left={l} top={t} right={rgt} bottom={b}] {c['note']}")
        with open(os.path.join(outdir, "crops.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        degraded = " (DEGRADED: PIL absent, see crops.txt, LOOK the full PNG)"

    with open(os.path.join(outdir, "looked.manifest"), "w", encoding="utf-8") as f:
        for c in crops:
            f.write(f"{c['id']} {c['nonce']} {c['kind']} {c['note']}\n")

    _print_skeleton(report, crops, verts, degraded)
    return 0


def _crops_of(crops, kinds):
    return [c for c in crops if c["kind"] in kinds]


def _ref(cs, action):
    if not cs:
        return None
    return "; ".join(f"[{c['id']} nonce={c['nonce']}: {action}]" for c in cs[:2])


def _print_skeleton(report, crops, verts, degraded):
    stage = report.get("stage", "hand")
    counts = report.get("counts", {})
    n_pin, m_un = counts.get("pinned", 0), counts.get("unpinned", 0)
    failed = failed_gate_set(report)
    green = report.get("verdict") == "structure-ok-not-verified" and not failed
    aspect, util, quad = geometry_summary(verts)

    if green:
        gates_line = (f"validate.py --stage {stage}: all gates green "
                      f"(counts: {n_pin} pinned exact, {m_un} unpinned approximate)")
    else:
        gates_line = f"validate.py --stage {stage}: GATES FAILED {sorted(failed) or report.get('gates_failed')}"

    label_ref = _ref(_crops_of(crops, ("label-collision", "overflow")),
                     "READ AND QUOTE THE LABEL TEXT HERE") \
        or "[no label region flagged; LOOK the full PNG and QUOTE the longest edge label]"
    etn = _crops_of(crops, ("edge-through-node",))
    etn_status = "gate 11 green for pinned" if 11 not in failed else "gate 11 FAILED"
    etn_ref = _ref(etn, "confirm the at-risk region is clean") \
        or "no flagged region; LOOK the full PNG"
    fan_ref = _ref(_crops_of(crops, ("near-miss",)), "confirm the trunk/lane is clean") \
        or "gates 13/14 not flagged; LOOK the highest-degree node in the full PNG"
    legend_status = "gates 20/21 green" if not ({20, 21} & failed) else f"gates {sorted({20,21} & failed)} FAILED"
    legend_ref = _ref(_crops_of(crops, ("legend",)), "confirm swatches match content") \
        or "no legend crop; confirm from the full PNG if a legend is required"

    print(f"DONE-CHECK (tier: RENDER+LOOK){degraded}")
    print("  render tier ran:      docker")
    print(f"  structural gates:     {gates_line}")
    print(f"  edge-labels legible:  {label_ref}")
    print(f"  no edge-through-node: {etn_status}; {etn_ref}")
    print(f"  fan-out disciplined:  {fan_ref}")
    print(f"  legend complete:      {legend_status}; {legend_ref}")
    print(f"  aspect / dead-zone:   aspect={aspect:.2f} util={util*100:.0f}% quadrants={quad}")
    resid = "none" if green else f"gates failed: {sorted(failed) or report.get('gates_failed')}"
    print(f"  residual defects:     {resid}")


if __name__ == "__main__":
    sys.exit(main())
