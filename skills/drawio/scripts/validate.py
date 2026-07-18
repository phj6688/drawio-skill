#!/usr/bin/env python3
"""Structural validator for .drawio files (stage: STRUCTURE).

Usage: validate.py FILE [--stage hand|pre-layout|post-layout] [--json REPORT] [--fixture-mode]

Runs a 25-check registry over the diagram geometry. Hard gates fire only on
exact geometry (pinned edges, resolved absolute coordinates, the mandated legend
pattern); anything approximated is a warning. There is no success token: a clean
run prints the verdict-inversion line telling you to render and LOOK.

--fixture-mode ignores calibration.json and uses the constants fallback so the
test corpus behaves identically on any box.
"""
import argparse
import base64
import json
import math
import os
import re
import sys
import urllib.parse
import zlib
import xml.etree.ElementTree as ET

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from constants import (
    GRID_SNAP, SIBLING_GAP, EDGE_NODE_CLEARANCE,
    CHAR_W_WARN, CHAR_W_GATE, CHAR_W_SLACK_CHARS,
    CHAR_CLASS_WIDE, CHAR_CLASS_XWIDE, CHAR_CLASS_NARROW, CHAR_CLASS_BODY,
    BOLD_FACTOR, LINE_HEIGHT, TEXT_PAD_X, TEXT_PAD_Y,
    FONT_NODE, FONT_EDGE,
    DENSITY_GATE, DENSITY_WARN, ASPECT_WARN_HI, ASPECT_WARN_LO, UTIL_WARN_LO,
    FANOUT_LANE_AT, EDGES_PER_SIDE_WARN, LUMINANCE_DARK_TEXT,
    crossing_warn_threshold, LEGEND_ID_TOKEN, CONTAINER_TINT_FILLS,
    MAX_DECOMPRESSED_BYTES,
)

NEAR_MISS_FACTOR = 2  # a clearance-band multiple counts as a near-miss region


# ---- calibration ----------------------------------------------------------
def load_char_model(fixture_mode):
    """Return per-class ratios. calibration.json wins unless fixture-mode pins constants."""
    model = {
        "wide": CHAR_CLASS_WIDE, "xwide": CHAR_CLASS_XWIDE,
        "narrow": CHAR_CLASS_NARROW, "body": CHAR_CLASS_BODY,
        "bold": BOLD_FACTOR, "flat": CHAR_W_WARN,
    }
    if fixture_mode:
        return model
    path = os.path.join(SCRIPT_DIR, "calibration.json")
    if not os.path.exists(path):
        return model
    try:
        with open(path, encoding="utf-8") as f:
            cal = json.load(f)
        cls = cal.get("classes", {})
        for k in ("wide", "xwide", "narrow", "body"):
            if k in cls:
                model[k] = float(cls[k])
        if "bold_factor" in cal:
            model["bold"] = float(cal["bold_factor"])
        if "flat_p95_mixed" in cal:
            model["flat"] = float(cal["flat_p95_mixed"])
    except (ValueError, OSError):
        pass
    return model


XWIDE_CHARS = set("mwMW")
WIDE_CHARS = set("ABCDEFGHIJKLNOPQRSTUVXYZ0123456789@#%_&$")  # M,W handled as xwide
NARROW_CHARS = set("iljtfr.,:;'\"|()[]{} ")


def char_ratio(ch, model):
    if ch in XWIDE_CHARS:
        return model["xwide"]
    if ch in WIDE_CHARS:
        return model["wide"]
    if ch in NARROW_CHARS:
        return model["narrow"]
    return model["body"]


# ---- label text -----------------------------------------------------------
_TAG_RE = re.compile(r"<[^>]+>")
_BR_RE = re.compile(r"<br\s*/?>|&#xa;|&#10;|\n", re.IGNORECASE)


def label_lines(value):
    """Split a cell value into visible text lines, stripping HTML tags/entities."""
    if not value:
        return []
    parts = _BR_RE.split(value)
    out = []
    for p in parts:
        txt = _TAG_RE.sub("", p)
        txt = (txt.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
               .replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " "))
        out.append(txt)
    while out and out[-1].strip() == "" and len(out) > 1:
        out.pop()
    return out


def class_line_width(line, font_size, bold, model):
    w = sum(char_ratio(c, model) * font_size for c in line)
    return w * model["bold"] if bold else w


def gate_line_width(line, font_size, bold, model):
    """Inflated width for the outside-label collision gate (constants-driven)."""
    n = len(line) + CHAR_W_SLACK_CHARS
    w = CHAR_W_GATE * font_size * n
    if bold:
        w *= model["bold"]
    return max(w, class_line_width(line, font_size, bold, model))


def label_box(lines, font_size, bold, model, mode):
    """(width, height) for a text block. mode 'gate' inflates, else class model."""
    if not lines:
        return 0.0, 0.0
    if mode == "gate":
        w = max(gate_line_width(ln, font_size, bold, model) for ln in lines)
    else:
        w = max(class_line_width(ln, font_size, bold, model) for ln in lines)
    h = len(lines) * font_size * LINE_HEIGHT + 2 * TEXT_PAD_Y
    return w, h


# ---- style / color --------------------------------------------------------
def parse_style(style):
    d, tokens = {}, []
    for part in (style or "").split(";"):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            d[k.strip()] = v.strip()
        else:
            tokens.append(part)
    return d, tokens


def norm_hex(c):
    if not c:
        return None
    c = c.strip().lower()
    if c in ("none", "default"):
        return c
    if c.startswith("#"):
        h = c[1:]
        if len(h) == 3:
            h = "".join(ch * 2 for ch in h)
        if len(h) == 6:
            return "#" + h
    return c


def luminance(hexc):
    h = norm_hex(hexc)
    if not h or not h.startswith("#") or len(h) != 7:
        return None
    r, g, b = int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)
    return (299 * r + 587 * g + 114 * b) / 1000


# ---- geometry -------------------------------------------------------------
def rects_overlap(a, b, margin=0.0):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return (ax < bx + bw + margin and bx < ax + aw + margin
            and ay < by + bh + margin and by < ay + ah + margin)


def rect_gap(a, b):
    """Shortest gap between two AABBs; 0 if they touch or overlap."""
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    dx = max(bx - (ax + aw), ax - (bx + bw), 0.0)
    dy = max(by - (ay + ah), ay - (by + bh), 0.0)
    return math.hypot(dx, dy)


def seg_intersect(p1, p2, p3, p4):
    def ccw(a, b, c):
        return (c[1] - a[1]) * (b[0] - a[0]) - (b[1] - a[1]) * (c[0] - a[0])
    d1 = ccw(p3, p4, p1)
    d2 = ccw(p3, p4, p2)
    d3 = ccw(p1, p2, p3)
    d4 = ccw(p1, p2, p4)
    if ((d1 > 0) != (d2 > 0)) and ((d3 > 0) != (d4 > 0)):
        return True
    return False


def seg_rect_hit(p1, p2, rect):
    x, y, w, h = rect
    if _pt_in_rect(p1, rect) or _pt_in_rect(p2, rect):
        return True
    corners = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    edges = [(corners[i], corners[(i + 1) % 4]) for i in range(4)]
    return any(seg_intersect(p1, p2, e[0], e[1]) for e in edges)


def _pt_in_rect(p, rect):
    x, y, w, h = rect
    return x <= p[0] <= x + w and y <= p[1] <= y + h


def inflate(rect, m):
    x, y, w, h = rect
    return (x - m, y - m, w + 2 * m, h + 2 * m)


def polyline_len(pts):
    return sum(math.dist(pts[i], pts[i + 1]) for i in range(len(pts) - 1))


def point_at_frac(pts, frac):
    total = polyline_len(pts)
    if total == 0:
        return pts[0], (1.0, 0.0)
    target = frac * total
    acc = 0.0
    for i in range(len(pts) - 1):
        seg = math.dist(pts[i], pts[i + 1])
        if acc + seg >= target or i == len(pts) - 2:
            t = (target - acc) / seg if seg else 0.0
            t = max(0.0, min(1.0, t))
            x = pts[i][0] + t * (pts[i + 1][0] - pts[i][0])
            y = pts[i][1] + t * (pts[i + 1][1] - pts[i][1])
            dx, dy = pts[i + 1][0] - pts[i][0], pts[i + 1][1] - pts[i][1]
            n = math.hypot(dx, dy) or 1.0
            return (x, y), (dx / n, dy / n)
        acc += seg
    return pts[-1], (1.0, 0.0)


# ---- model ----------------------------------------------------------------
class Cell:
    __slots__ = ("id", "el", "parent", "is_vertex", "is_edge", "style",
                 "sd", "tokens", "value", "source", "target",
                 "gx", "gy", "gw", "gh", "rel", "as_geom", "ax", "ay",
                 "waypoints", "connectable")

    def __init__(self, el):
        self.el = el
        self.id = el.get("id")
        self.parent = el.get("parent")
        self.is_vertex = el.get("vertex") == "1"
        self.is_edge = el.get("edge") == "1"
        self.style = el.get("style", "") or ""
        self.sd, self.tokens = parse_style(self.style)
        self.value = el.get("value", "")
        self.source = el.get("source")
        self.target = el.get("target")
        self.connectable = el.get("connectable")
        g = el.find("mxGeometry")
        self.rel = g is not None and g.get("relative") == "1"
        self.as_geom = g is not None and g.get("as") == "geometry"
        self.gx = _num(g, "x")
        self.gy = _num(g, "y")
        self.gw = _num(g, "width")
        self.gh = _num(g, "height")
        self.ax = self.ay = None  # absolute origin, filled later
        self.waypoints = []
        if g is not None:
            arr = g.find("Array")
            if arr is not None and arr.get("as") == "points":
                for pt in arr.findall("mxPoint"):
                    self.waypoints.append((float(pt.get("x", 0)), float(pt.get("y", 0))))

    def bbox(self):
        return (self.ax, self.ay, self.gw or 0.0, self.gh or 0.0)


def _num(g, k):
    if g is None:
        return None
    v = g.get(k)
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _geom_offset(el, key):
    g = el.find("mxGeometry")
    if g is None:
        return None
    pt = g.find("mxPoint")
    for p in g.findall("mxPoint"):
        if p.get("as") == key:
            return float(p.get("x", 0)), float(p.get("y", 0))
    return None


# ---- file loading ---------------------------------------------------------
_DTD_RE = re.compile(r"<!(?:DOCTYPE|ENTITY)\b", re.IGNORECASE)


def reject_dangerous_xml(text):
    """Reject DTD/entity declarations before parsing (billion-laughs defense).

    Legitimate .drawio files never carry a DOCTYPE or ENTITY; guarding here does
    not depend on the host libexpat version. Raises ValueError -> gate 1.
    """
    if _DTD_RE.search(text):
        raise ValueError("xml doctype/entity declarations are not allowed "
                         "(possible entity-expansion attack)")


def _bounded_inflate(raw, wbits):
    """zlib-inflate raw with a hard output ceiling; a bomb raises ValueError."""
    d = zlib.decompressobj(wbits)
    out = d.decompress(raw, MAX_DECOMPRESSED_BYTES + 1)
    if len(out) > MAX_DECOMPRESSED_BYTES or d.unconsumed_tail:
        raise ValueError(
            f"decompressed diagram body exceeds {MAX_DECOMPRESSED_BYTES} bytes "
            "(possible decompression bomb)")
    out += d.flush()
    if len(out) > MAX_DECOMPRESSED_BYTES:
        raise ValueError(
            f"decompressed diagram body exceeds {MAX_DECOMPRESSED_BYTES} bytes "
            "(possible decompression bomb)")
    return out.decode("utf-8")


def decompress_body(text):
    raw = base64.b64decode(text)
    try:
        xml = _bounded_inflate(raw, -15)
    except zlib.error:
        xml = _bounded_inflate(raw, 15)  # oversize ValueError propagates, not retried
    return urllib.parse.unquote(xml)


def load_pages(path):
    """Return [(page_name, mxGraphModel_element)] handling mxfile, bare model, compressed bodies."""
    with open(path, encoding="utf-8") as f:
        data = f.read()
    reject_dangerous_xml(data)  # parse point 1: the raw file text
    root = ET.fromstring(data)
    tag = root.tag.split("}")[-1]
    if tag == "mxGraphModel":
        return [("Page-1", root)]
    if tag != "mxfile":
        raise ValueError(f"root element is <{tag}>, expected mxfile or mxGraphModel")
    pages = []
    for i, dia in enumerate(root.findall("diagram")):
        name = dia.get("name") or dia.get("id") or f"Page-{i+1}"
        model = dia.find("mxGraphModel")
        if model is None:
            body = (dia.text or "").strip()
            if body:
                body_xml = decompress_body(body)
                reject_dangerous_xml(body_xml)  # parse point 2: the decompressed body
                model = ET.fromstring(body_xml)
        if model is None:
            raise ValueError(f"diagram '{name}' has no mxGraphModel body")
        pages.append((name, model))
    if not pages:
        raise ValueError("mxfile has no <diagram> pages")
    return pages


# ---- per-page analysis ----------------------------------------------------
class Report:
    def __init__(self, stage):
        self.stage = stage
        self.gates = {}      # number -> list[str]
        self.warnings = {}   # number -> list[str]
        self.meta = []       # list[str]
        self.regions = []    # list[dict]
        self.pinned = 0
        self.unpinned = 0

    def gate(self, n, msg):
        self.gates.setdefault(n, []).append(msg)

    def warn(self, n, msg):
        self.warnings.setdefault(n, []).append(msg)

    def region(self, kind, bbox, note):
        self.regions.append({"kind": kind, "bbox": [round(v, 1) for v in bbox], "note": note})


def resolve_abs(cells):
    """Fill absolute origin for every vertex by walking parent chains (parents are vertices)."""
    def parent_origin(cid, seen):
        """Absolute origin of cid's parent container, or (0,0) at the layer root."""
        c = cells.get(cid)
        if c is None:
            return (0.0, 0.0)
        p = c.parent
        pc = cells.get(p)
        if p in (None, "0", "1") or pc is None or p in seen or not pc.is_vertex \
                or pc.gx is None:
            return (0.0, 0.0)
        base = parent_origin(p, seen | {cid})
        return (base[0] + pc.gx, base[1] + pc.gy)
    for cid, c in cells.items():
        if c.is_vertex and c.gx is not None:
            ox, oy = parent_origin(cid, {cid})
            c.ax, c.ay = ox + c.gx, oy + c.gy


def is_legend(cid):
    return LEGEND_ID_TOKEN in (cid or "").lower()


def is_text_only(c):
    if "text" in c.tokens:
        return True
    return (c.sd.get("fillColor", "").lower() == "none"
            and c.sd.get("strokeColor", "").lower() == "none")


def is_container(c):
    return c.sd.get("container") == "1" or "swimlane" in c.tokens or "group" in c.tokens


def ancestor_of(cells, a, b):
    """True if a is an ancestor of b."""
    cur = cells.get(b)
    seen = set()
    while cur is not None and cur.id not in seen:
        seen.add(cur.id)
        if cur.parent == a:
            return True
        cur = cells.get(cur.parent)
    return False


def font_of(c, default):
    try:
        return float(c.sd.get("fontSize", default))
    except ValueError:
        return default


def is_bold(c):
    try:
        return bool(int(c.sd.get("fontStyle", "0")) & 1)
    except ValueError:
        return False


def conn_point(c, fx, fy):
    return (c.ax + fx * (c.gw or 0), c.ay + fy * (c.gh or 0))


def center(c):
    return (c.ax + (c.gw or 0) / 2, c.ay + (c.gh or 0) / 2)


def edge_pinned(c):
    return bool(c.waypoints) or all(k in c.sd for k in ("exitX", "exitY", "entryX", "entryY"))


def edge_polyline(c, cells):
    """(points, exact) for an edge. exact True when waypointed or fully pinned."""
    src = cells.get(c.source)
    tgt = cells.get(c.target)
    if src is None or tgt is None or src.ax is None or tgt.ax is None:
        return None, False
    if c.waypoints:
        p0 = conn_point(src, float(c.sd.get("exitX", 0.5)), float(c.sd.get("exitY", 0.5))) \
            if "exitX" in c.sd else center(src)
        p1 = conn_point(tgt, float(c.sd.get("entryX", 0.5)), float(c.sd.get("entryY", 0.5))) \
            if "entryX" in c.sd else center(tgt)
        return [p0] + c.waypoints + [p1], True
    if all(k in c.sd for k in ("exitX", "exitY", "entryX", "entryY")):
        ex, ey = float(c.sd["exitX"]), float(c.sd["exitY"])
        p0 = conn_point(src, ex, ey)
        p1 = conn_point(tgt, float(c.sd["entryX"]), float(c.sd["entryY"]))
        if ex in (0.0, 1.0):
            corner = (p1[0], p0[1])
        elif ey in (0.0, 1.0):
            corner = (p0[0], p1[1])
        else:
            corner = (p1[0], p0[1])
        return [p0, corner, p1], True
    return [center(src), center(tgt)], False


def poly_segments(pts):
    return [(pts[i], pts[i + 1]) for i in range(len(pts) - 1)]


def content_vertices(cells):
    """Semantic content nodes: real vertices, not legend/title/text furniture or edge labels."""
    out = []
    for c in cells.values():
        if not c.is_vertex or c.gx is None or (c.gw or 0) <= 0 or (c.gh or 0) <= 0:
            continue
        if is_legend(c.id) or c.connectable == "0":
            continue
        parent = cells.get(c.parent)
        if parent is not None and parent.is_edge:
            continue
        if is_text_only(c) and not c.value.strip():
            continue
        if is_text_only(c):
            continue
        out.append(c)
    return out


def shape_kind(c):
    for t in ("ellipse", "rhombus", "hexagon", "triangle", "parallelogram",
              "cylinder", "cloud", "actor", "note", "process", "step"):
        if t in c.style:
            return t
    return "rect"


def content_bbox(verts):
    xs0 = min(c.ax for c in verts)
    ys0 = min(c.ay for c in verts)
    xs1 = max(c.ax + (c.gw or 0) for c in verts)
    ys1 = max(c.ay + (c.gh or 0) for c in verts)
    return xs0, ys0, xs1 - xs0, ys1 - ys0


# ---- edge labels ----------------------------------------------------------
def edge_labels(c, cells, pts):
    """Yield (anchor_center, lines, font_size, bold) for an edge's own value and child labels."""
    out = []
    if c.value and c.value.strip():
        lines = label_lines(c.value)
        gx = c.gx if c.gx is not None else 0.0
        gy = c.gy if c.gy is not None else 0.0
        frac = (gx + 1) / 2 if -1 <= gx <= 1 else 0.5
        base, dirv = point_at_frac(pts, frac)
        perp = (-dirv[1], dirv[0])
        cx = base[0] + perp[0] * gy
        cy = base[1] + perp[1] * gy
        off = _geom_offset(c.el, "offset")
        if off:
            cx += off[0]
            cy += off[1]
        out.append(((cx, cy), lines, font_of(c, FONT_EDGE), is_bold(c)))
    for child in cells.values():
        if child.parent != c.id or not child.is_vertex:
            continue
        if "edgeLabel" not in child.style and child.connectable != "0":
            continue
        lines = label_lines(child.value)
        if not lines:
            continue
        gx = child.gx if child.gx is not None else 0.0
        gy = child.gy if child.gy is not None else 0.0
        frac = (gx + 1) / 2 if -1 <= gx <= 1 else 0.5
        base, dirv = point_at_frac(pts, frac)
        perp = (-dirv[1], dirv[0])
        cx = base[0] + perp[0] * gy
        cy = base[1] + perp[1] * gy
        off = _geom_offset(child.el, "offset")
        if off:
            cx += off[0]
            cy += off[1]
        out.append(((cx, cy), lines, font_of(child, FONT_EDGE), is_bold(child)))
    return out


def external_node_label(c, model):
    """(bbox, lines) when a node label is placed outside its own box, else None."""
    lp = c.sd.get("labelPosition")
    vlp = c.sd.get("verticalLabelPosition")
    if lp not in ("left", "right") and vlp not in ("top", "bottom"):
        return None
    lines = label_lines(c.value)
    if not lines:
        return None
    w, h = label_box(lines, font_of(c, FONT_NODE), is_bold(c), model, "gate")
    bx, by = c.ax, c.ay
    if lp == "right":
        x = c.ax + (c.gw or 0)
        y = c.ay + (c.gh or 0) / 2 - h / 2
    elif lp == "left":
        x = c.ax - w
        y = c.ay + (c.gh or 0) / 2 - h / 2
    elif vlp == "bottom":
        x = c.ax + (c.gw or 0) / 2 - w / 2
        y = c.ay + (c.gh or 0)
    else:  # top
        x = c.ax + (c.gw or 0) / 2 - w / 2
        y = c.ay - h
    return (x, y, w, h), lines


# ---- checks ---------------------------------------------------------------
def run_checks(name, model, cells, page_attrs, stage, rep):
    geo_stage = stage in ("hand", "post-layout")

    # 2 root cells + unique ids
    ids = [c.id for c in cells.values()]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        rep.gate(2, f"[{name}] duplicate cell ids: {sorted(dupes)}")
    for req in ("0", "1"):
        if req not in cells:
            rep.gate(2, f"[{name}] missing mandatory root cell id={req}")

    # 3 parent refs
    for c in cells.values():
        if c.id == "0":
            continue
        if c.parent is None:
            rep.gate(3, f"[{name}] cell {c.id} has no parent")
        elif c.parent not in cells:
            rep.gate(3, f"[{name}] cell {c.id} parent '{c.parent}' does not resolve")

    # 4 edge endpoints
    for c in cells.values():
        if not c.is_edge:
            continue
        if not c.source or not c.target:
            rep.gate(4, f"[{name}] edge {c.id} has a floating endpoint; wire source+target to cell ids")
            continue
        if c.source not in cells or c.target not in cells:
            rep.gate(4, f"[{name}] edge {c.id} source/target does not resolve "
                        f"(source={c.source}, target={c.target})")

    # 5 exclusivity + geometry sanity + perimeter
    perim_needs = {"rhombus": "rhombusPerimeter", "triangle": "trianglePerimeter",
                   "hexagon": "hexagonPerimeter", "parallelogram": "parallelogramPerimeter"}
    for c in cells.values():
        if c.is_vertex and c.is_edge:
            rep.gate(5, f"[{name}] cell {c.id} declares both vertex and edge")
        parent = cells.get(c.parent)
        is_edgelabel = (parent is not None and parent.is_edge) or "edgeLabel" in c.style
        if c.is_vertex and not is_edgelabel:
            if c.gx is None or c.gw is None or c.gh is None or not c.as_geom:
                rep.gate(5, f"[{name}] vertex {c.id} needs numeric geometry with as=\"geometry\"")
            elif (c.gw <= 0 or c.gh <= 0):
                rep.gate(5, f"[{name}] vertex {c.id} has non-positive width/height")
            if c.rel:
                rep.gate(5, f"[{name}] vertex {c.id} has relative=\"1\" (collapses to a corner)")
            for shp, per in perim_needs.items():
                if (shp in c.tokens or f"shape={shp}" in c.style) and "perimeter=" not in c.style:
                    rep.gate(5, f"[{name}] {shp} vertex {c.id} needs perimeter={per}")
        if c.is_edge:
            if not c.rel:
                rep.gate(5, f"[{name}] edge {c.id} geometry needs relative=\"1\"")
            if not c.as_geom:
                rep.gate(5, f"[{name}] edge {c.id} geometry needs as=\"geometry\"")

    # geometry checks need real sized boxes; edge-label children carry no width/height
    verts_all = [c for c in cells.values() if c.is_vertex and c.gx is not None
                 and c.gy is not None and c.gw and c.gh and c.gw > 0 and c.gh > 0]
    content = content_vertices(cells)
    content_ids = {c.id for c in content}

    # 15 zero-length edges, stacked vertices, orphans (full stage only)
    if geo_stage:
        for c in cells.values():
            if c.is_edge and c.source and c.source == c.target and not c.waypoints:
                rep.gate(15, f"[{name}] edge {c.id} is zero-length (source==target, no waypoints)")
        seen_boxes = {}
        for c in verts_all:
            if c.connectable == "0":
                continue
            key = (round(c.ax, 1), round(c.ay, 1), round(c.gw, 1), round(c.gh, 1))
            if key in seen_boxes:
                rep.gate(15, f"[{name}] vertices {seen_boxes[key]} and {c.id} share an identical bbox {key}")
            else:
                seen_boxes[key] = c.id
        for c in cells.values():
            if c.id == "0":
                continue
            cur, steps, ok = c, 0, False
            seen = set()
            while cur is not None and steps < 200 and cur.id not in seen:
                seen.add(cur.id)
                if cur.parent == "0":
                    ok = True
                    break
                cur = cells.get(cur.parent)
                steps += 1
            if not ok:
                rep.gate(15, f"[{name}] cell {c.id} has no parent chain reaching id=0 (orphan)")

    # 6 off-grid
    if geo_stage:
        for c in verts_all:
            for label, v in (("x", c.gx), ("y", c.gy), ("w", c.gw), ("h", c.gh)):
                if v is not None and abs(v) % GRID_SNAP != 0:
                    rep.warn(6, f"[{name}] {c.id} {label}={v} is off the {GRID_SNAP}px grid")
                    break

    # 7 out of bounds
    pw = page_attrs.get("pageWidth")
    ph = page_attrs.get("pageHeight")
    if geo_stage:
        for c in verts_all:
            if c.ax < 0 or c.ay < 0:
                rep.warn(7, f"[{name}] {c.id} has negative coordinates ({c.ax},{c.ay})")
            elif pw and ph and (c.ax + c.gw > pw or c.ay + c.gh > ph):
                rep.warn(7, f"[{name}] {c.id} extends beyond the page ({pw}x{ph})")

    # build edge polylines once
    edges = [c for c in cells.values() if c.is_edge and c.source and c.target]
    polys = {}
    for e in edges:
        pts, exact = edge_polyline(e, cells)
        if pts is not None:
            polys[e.id] = (pts, exact)
            if exact:
                rep.pinned += 1
            else:
                rep.unpinned += 1

    if geo_stage:
        _geo_checks(name, model, cells, content, content_ids, verts_all, edges, polys, rep, stage)

    # 16 density (full stage only)
    if geo_stage:
        n = len(content)
        if n > DENSITY_GATE:
            rep.gate(16, f"[{name}] {n} content nodes exceed the density gate ({DENSITY_GATE}); split the diagram")
        elif n > DENSITY_WARN:
            rep.warn(16, f"[{name}] {n} content nodes exceed the density warning ({DENSITY_WARN})")

    # 20/21/25 legend (topology + color; runs pre-layout and full)
    _legend_checks(name, cells, content, edges, rep)

    if not geo_stage:
        return

    # 22 luminance
    for c in content:
        fill = c.sd.get("fillColor")
        fc = c.sd.get("fontColor")
        if not fill or not fc:
            continue
        yf = luminance(fill)
        yt = luminance(fc)
        if yf is None or yt is None:
            continue
        if yf > LUMINANCE_DARK_TEXT and yt > LUMINANCE_DARK_TEXT:
            rep.warn(22, f"[{name}] {c.id} light text on light fill (fill Y={yf:.0f}, text Y={yt:.0f})")
        elif yf <= LUMINANCE_DARK_TEXT and yt <= LUMINANCE_DARK_TEXT:
            rep.warn(22, f"[{name}] {c.id} dark text on dark fill (fill Y={yf:.0f}, text Y={yt:.0f})")

    # 23 META, 24 degree-0
    deg = {c.id: 0 for c in content}
    for e in edges:
        for end in (e.source, e.target):
            if end in deg:
                deg[end] += 1
    for e in edges:
        if e.id in polys and not polys[e.id][1] and (e.value or "").strip():
            rep.meta.append(f"[{name}] edge {e.id} is labeled but not pinned (doctrine wants pinned edges)")
    for c in content:
        if e_pinned_degree(c.id, edges, polys) >= 2 and any(
                e.id in polys and not polys[e.id][1]
                for e in edges if c.id in (e.source, e.target)):
            rep.meta.append(f"[{name}] node {c.id} has degree>=2 with unpinned edges")
    # 24 degree-0
    for c in content:
        if deg.get(c.id, 0) == 0:
            rep.warn(24, f"[{name}] content node {c.id} is disconnected (degree 0)")


def e_pinned_degree(cid, edges, polys):
    return sum(1 for e in edges if cid in (e.source, e.target))


def _geo_checks(name, model, cells, content, content_ids, verts_all, edges, polys, rep, stage):
    # 8 sibling AABB overlap (legend furniture participates)
    by_parent = {}
    for c in verts_all:
        if c.connectable == "0":
            continue
        pc = cells.get(c.parent)
        if pc is not None and pc.is_edge:
            continue
        by_parent.setdefault(c.parent, []).append(c)
    for group in by_parent.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if ancestor_of(cells, a.id, b.id) or ancestor_of(cells, b.id, a.id):
                    continue
                ra, rb = a.bbox(), b.bbox()
                if rects_overlap(ra, rb, margin=0.0):
                    ox = min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0])
                    oy = min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1])
                    if ox > 0 and oy > 0:
                        rep.gate(8, f"[{name}] siblings {a.id} and {b.id} overlap by {ox:.0f}x{oy:.0f}px")
                        rep.region("label-collision",
                                   (max(ra[0], rb[0]), max(ra[1], rb[1]), ox, oy),
                                   f"sibling overlap {a.id}/{b.id}")
                elif rect_gap(ra, rb) < SIBLING_GAP:
                    rep.region("near-miss", ra, f"siblings {a.id}/{b.id} closer than {SIBLING_GAP}px")

    # collect label bboxes for check 9
    labels = []  # (bbox, lines, owner_cell_id, incident_ids, owner_edge_id)
    for c in content:
        ext = external_node_label(c, model)
        if ext:
            bbox, lines = ext
            inc = {c.id} | {e.source for e in edges if e.target == c.id} \
                | {e.target for e in edges if e.source == c.id}
            labels.append((bbox, lines, c.id, inc, None))
    for c in cells.values():
        if is_text_only(c) and c.is_vertex and c.value.strip() and c.gx is not None \
                and c.ax is not None and (c.gw or 0) > 0:
            labels.append((c.bbox(), label_lines(c.value), c.id, {c.id}, None))
    for e in edges:
        if e.id not in polys:
            continue
        pts = polys[e.id][0]
        for (cx, cy), lines, fs, bold in edge_labels(e, cells, pts):
            w, h = label_box(lines, fs, bold, model, "gate")
            bbox = (cx - w / 2, cy - h / 2, w, h)
            inc = {e.source, e.target}
            labels.append((bbox, lines, e.id, inc, e.id))

    # 9 label collision (gate) + near-miss regions
    # Post-layout, edge polylines come from the engine and the renderer's actual
    # routing diverges from our waypoint interpretation (proven by render), so
    # polyline-derived positions may not gate: they warn and feed LOOK crops.
    engine_geom = stage == "post-layout"
    band = EDGE_NODE_CLEARANCE * NEAR_MISS_FACTOR
    for bbox, lines, owner, inc, owner_edge in labels:
        text = " ".join(lines)[:24]
        polyline_based = owner_edge is not None
        for v in verts_all:
            if v.id == owner or v.id in inc or v.connectable == "0":
                continue
            if ancestor_of(cells, v.id, owner) or ancestor_of(cells, owner, v.id):
                continue
            if is_legend(owner) and is_legend(v.id):
                continue
            if rects_overlap(bbox, v.bbox(), margin=0.0):
                if engine_geom and polyline_based:
                    rep.warn(9, f"[{name}] label '{text}' may overlap node {v.id} (engine-routed, LOOK)")
                else:
                    rep.gate(9, f"[{name}] label '{text}' (owner {owner}) collides with node {v.id}")
                rep.region("label-collision", bbox, f"label '{text}' over node {v.id}")
                break
            elif rect_gap(bbox, v.bbox()) < band:
                rep.region("near-miss", bbox, f"label '{text}' near node {v.id}")
        for e in edges:
            if owner_edge == e.id or e.id not in polys or not polys[e.id][1]:
                continue
            if e.source == owner or e.target == owner:
                continue
            hit = any(seg_rect_hit(s[0], s[1], bbox) for s in poly_segments(polys[e.id][0]))
            if hit:
                if engine_geom:
                    rep.warn(9, f"[{name}] label '{text}' may sit on edge {e.id} (engine-routed, LOOK)")
                else:
                    rep.gate(9, f"[{name}] label '{text}' (owner {owner}) sits on pinned edge {e.id}")
                rep.region("label-collision", bbox, f"label '{text}' on edge {e.id}")
                break

    # 10 own-box overflow (warn)
    for c in content:
        if not c.value.strip():
            continue
        lines = label_lines(c.value)
        fs = font_of(c, FONT_NODE)
        usable = (c.gw or 0) - 2 * TEXT_PAD_X
        wrap = "whiteSpace=wrap" in c.style or c.sd.get("whiteSpace") == "wrap"
        wline = max((class_line_width(ln, fs, is_bold(c), model) for ln in lines), default=0.0)
        if not wrap:
            if wline > usable:
                rep.warn(10, f"[{name}] {c.id} label '{' '.join(lines)[:24]}' overflows its box "
                             f"(est {wline:.0f}px > {usable:.0f}px usable)")
                rep.region("overflow", c.bbox(), f"label overflow {c.id}")
        else:
            per_line = max(1, int(usable // (0.55 * fs))) if fs else 1
            nlines = sum(max(1, math.ceil(len(ln) / per_line)) for ln in lines) if per_line else len(lines)
            need = nlines * fs * LINE_HEIGHT + 2 * TEXT_PAD_Y
            if need > (c.gh or 0):
                rep.warn(10, f"[{name}] {c.id} wrapped label needs {need:.0f}px height > {c.gh:.0f}px")
                rep.region("overflow", c.bbox(), f"wrapped overflow {c.id}")

    # 11 edge-through-node
    exact_hits = 0
    approx_hits = 0
    for e in edges:
        if e.id not in polys:
            continue
        pts, exact = polys[e.id]
        for v in verts_all:
            if v.id in (e.source, e.target) or v.connectable == "0":
                continue
            if ancestor_of(cells, v.id, e.id):
                continue
            # legend line samples sit beside their own text rows by construction
            if is_legend(e.id) and is_legend(v.id):
                continue
            rect = inflate(v.bbox(), EDGE_NODE_CLEARANCE)
            if any(seg_rect_hit(s[0], s[1], rect) for s in poly_segments(pts)):
                if exact and not engine_geom:
                    rep.gate(11, f"[{name}] pinned edge {e.id} passes through node {v.id}")
                    rep.region("edge-through-node", v.bbox(), f"edge {e.id} through {v.id}")
                    exact_hits += 1
                else:
                    why = "engine-routed" if engine_geom else "approx"
                    rep.warn(11, f"[{name}] {why} edge {e.id} may pass through node {v.id} (LOOK)")
                    rep.region("edge-through-node", v.bbox(), f"{why} edge {e.id} near {v.id}")
                    approx_hits += 1
    mode_note = "engine geometry: edge-path checks warn and defer to LOOK" if engine_geom else \
                f"exact for {rep.pinned} pinned edges, approximate for {rep.unpinned} un-pinned (LOOK required)"
    rep.meta.append(f"[{name}] edge-through-node: {mode_note}")

    # 12 crossings
    exlist = [(e, polys[e.id][0]) for e in edges if e.id in polys]
    crossings = 0
    for i in range(len(exlist)):
        for j in range(i + 1, len(exlist)):
            e1, p1 = exlist[i]
            e2, p2 = exlist[j]
            if {e1.source, e1.target} & {e2.source, e2.target}:
                continue
            if any(seg_intersect(a[0], a[1], b[0], b[1])
                   for a in poly_segments(p1) for b in poly_segments(p2)):
                crossings += 1
    thr = crossing_warn_threshold(len(edges))
    if crossings > thr:
        rep.warn(12, f"[{name}] {crossings} edge crossings exceed threshold {thr}")

    # 13 fan-out
    inc_edges = {c.id: [] for c in content}
    for e in edges:
        for end, other in ((e.source, e.target), (e.target, e.source)):
            if end in inc_edges:
                inc_edges[end].append((e, other))
    for cid, lst in inc_edges.items():
        if len(lst) < FANOUT_LANE_AT:
            continue
        cc = center(cells[cid])
        angles = []
        for e, other in lst:
            oc = cells.get(other)
            if oc is None or oc.ax is None:
                continue
            angles.append(math.degrees(math.atan2(center(oc)[1] - cc[1], center(oc)[0] - cc[0])))
        if _angular_spread(angles) > 180:
            rep.warn(13, f"[{name}] node {cid} fans {len(lst)} edges over >180deg without a shared trunk")

    # 14 edges per side
    for c in content:
        sides = {"top": 0, "bottom": 0, "left": 0, "right": 0}
        for e in edges:
            key = None
            if e.source == c.id and "exitX" in e.sd:
                key = _side(float(e.sd["exitX"]), float(e.sd.get("exitY", 0.5)))
            elif e.target == c.id and "entryX" in e.sd:
                key = _side(float(e.sd["entryX"]), float(e.sd.get("entryY", 0.5)))
            if key:
                sides[key] += 1
        for side, cnt in sides.items():
            if cnt > EDGES_PER_SIDE_WARN:
                rep.warn(14, f"[{name}] node {c.id} has {cnt} edges on its {side} side (>{EDGES_PER_SIDE_WARN})")

    if not content:
        return
    # 17 aspect, 18 utilization, 19 quadrant
    x0, y0, w, h = content_bbox(content)
    aspect = w / h if h else 0.0
    if aspect > ASPECT_WARN_HI or (aspect and aspect < ASPECT_WARN_LO):
        rep.warn(17, f"[{name}] content aspect ratio {aspect:.2f} outside "
                     f"[{ASPECT_WARN_LO}, {ASPECT_WARN_HI}]")
    node_area = sum((c.gw or 0) * (c.gh or 0) for c in content)
    util = node_area / (w * h) if w and h else 0.0
    if util < UTIL_WARN_LO:
        rep.warn(18, f"[{name}] area utilization {util*100:.0f}% below {UTIL_WARN_LO*100:.0f}% (dead-zone)")
    mx, my = x0 + w / 2, y0 + h / 2
    quad = [0, 0, 0, 0]
    for c in content:
        cx, cy = center(c)
        idx = (0 if cx < mx else 1) + (0 if cy < my else 2)
        quad[idx] += 1
    if min(quad) == 0 and max(quad) >= 2:
        rep.warn(19, f"[{name}] quadrant imbalance {quad} (an empty quadrant with a crowded one)")
    for qi, (qx, qy) in enumerate([(x0, y0), (mx, y0), (x0, my), (mx, my)]):
        rep.region("quadrant", (qx, qy, w / 2, h / 2), f"quadrant {qi} count={quad[qi]}")


def _side(fx, fy):
    if fx == 0.0:
        return "left"
    if fx == 1.0:
        return "right"
    if fy == 0.0:
        return "top"
    if fy == 1.0:
        return "bottom"
    return "right" if fx >= 0.5 else "left"


def _angular_spread(angles):
    if len(angles) < 2:
        return 0.0
    a = sorted(angles)
    gaps = [a[i + 1] - a[i] for i in range(len(a) - 1)]
    gaps.append(360 - (a[-1] - a[0]))
    return 360 - max(gaps)


def _legend_checks(name, cells, content, edges, rep):
    fills = set()
    for c in content:
        fill = c.sd.get("fillColor")
        stroke = c.sd.get("strokeColor")
        if is_container(c) and norm_hex(fill) in {norm_hex(x) for x in CONTAINER_TINT_FILLS}:
            continue
        if fill:
            fills.add((norm_hex(fill), norm_hex(stroke)))
    edge_tuples = set()
    for e in edges:
        edge_tuples.add((e.sd.get("dashed", "0"), norm_hex(e.sd.get("strokeColor")),
                         e.sd.get("endArrow", "classic")))
    shapes = {shape_kind(c) for c in content}

    channels = (len(fills) > 1) or (len(edge_tuples) > 1) or (len(shapes) > 1)
    if not channels:
        return

    legend_cells = [c for c in cells.values() if is_legend(c.id)]
    conforming = any(is_legend(c.id) for c in legend_cells)
    if not legend_cells or not conforming:
        rep.gate(21, f"[{name}] legend required ({len(fills)} fills, {len(edge_tuples)} edge styles, "
                     f"{len(shapes)} shapes) but none present; add cells with '{LEGEND_ID_TOKEN}' in the id")
        return

    swatch_fills = set()
    for c in legend_cells:
        if not c.is_vertex or c.connectable == "0":
            continue
        fill = c.sd.get("fillColor")
        if not fill or is_text_only(c):
            continue
        if norm_hex(fill) in {norm_hex(x) for x in CONTAINER_TINT_FILLS} and is_container(c):
            continue
        swatch_fills.add((norm_hex(fill), norm_hex(c.sd.get("strokeColor"))))
    legend_edge_tuples = set()
    for c in legend_cells:
        if c.is_edge:
            legend_edge_tuples.add((c.sd.get("dashed", "0"), norm_hex(c.sd.get("strokeColor")),
                                    c.sd.get("endArrow", "classic")))

    if len(fills) > 1 or swatch_fills:
        if fills != swatch_fills:
            missing = fills - swatch_fills
            extra = swatch_fills - fills
            rep.gate(20, f"[{name}] legend swatches do not match content fills "
                         f"(missing {sorted(map(str, missing))}, extra {sorted(map(str, extra))})")
            rep.region("legend", _legend_bbox(legend_cells), "swatch/content fill mismatch")
    if len(edge_tuples) > 1 or legend_edge_tuples:
        if not edge_tuples.issubset(legend_edge_tuples):
            rep.gate(25, f"[{name}] content edge styles {sorted(map(str, edge_tuples))} missing from "
                         f"legend line samples {sorted(map(str, legend_edge_tuples))}")
        if edge_tuples != legend_edge_tuples and (len(edge_tuples) > 1):
            rep.gate(20, f"[{name}] legend line samples do not match content edge styles")


def _legend_bbox(legend_cells):
    verts = [c for c in legend_cells if c.is_vertex and c.ax is not None]
    if not verts:
        return (0, 0, 1, 1)
    x0 = min(c.ax for c in verts)
    y0 = min(c.ay for c in verts)
    x1 = max(c.ax + (c.gw or 0) for c in verts)
    y1 = max(c.ay + (c.gh or 0) for c in verts)
    return (x0, y0, x1 - x0, y1 - y0)


# ---- driver ---------------------------------------------------------------
def validate(path, stage, fixture_mode):
    model = load_char_model(fixture_mode)
    rep = Report(stage)
    pages = load_pages(path)
    for name, page in pages:
        root = page.find("root")
        if root is None:
            rep.gate(1, f"[{name}] mxGraphModel has no <root>")
            continue
        cells = {}
        order = []
        for el in root.findall("mxCell"):
            c = Cell(el)
            if c.id is None:
                rep.gate(2, f"[{name}] a cell is missing its id")
                continue
            cells[c.id] = c
            order.append(c)
        for obj in root.findall("object") + root.findall("UserObject"):
            inner = obj.find("mxCell")
            if inner is not None:
                c = Cell(inner)
                c.id = obj.get("id")
                c.value = obj.get("label", c.value)
                if c.id:
                    cells[c.id] = c
        resolve_abs(cells)
        page_attrs = {}
        for k in ("pageWidth", "pageHeight"):
            v = page.get(k)
            if v:
                try:
                    page_attrs[k] = float(v)
                except ValueError:
                    pass
        run_checks(name, model, cells, page_attrs, stage, rep)
    return rep


def print_report(rep, stage):
    out = []
    out.append(f"drawio structural report (stage: {stage})")
    out.append(f"pinned edges (exact geometry): {rep.pinned}   unpinned (approximate): {rep.unpinned}")
    out.append("")
    if rep.gates:
        out.append("GATES (blocking):")
        for n in sorted(rep.gates):
            for msg in rep.gates[n]:
                out.append(f"  [{n:2d}] {msg}")
    else:
        out.append("GATES (blocking): none fired")
    out.append("")
    if rep.warnings:
        out.append("WARNINGS (LOOK required):")
        for n in sorted(rep.warnings):
            for msg in rep.warnings[n]:
                out.append(f"  [{n:2d}] {msg}")
    else:
        out.append("WARNINGS (LOOK required): none fired")
    if rep.meta:
        out.append("")
        out.append("META (informational):")
        for m in rep.meta:
            out.append(f"  {m}")
    out.append("")
    if rep.gates:
        total = sum(len(v) for v in rep.gates.values())
        out.append(f"GATES FAILED: {total}")
    else:
        out.append("STRUCTURE OK - NOT YET VERIFIED. Render + LOOK required. "
                   "Run: scripts/render.sh <file>")
    print("\n".join(out))


def build_json(rep):
    return {
        "stage": rep.stage,
        "gates_failed": sorted(rep.gates),
        "warnings": sorted(rep.warnings),
        "regions": rep.regions,
        "counts": {"pinned": rep.pinned, "unpinned": rep.unpinned},
        "verdict": "gates-failed" if rep.gates else "structure-ok-not-verified",
    }


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="stage STRUCTURE: 25-check structural gate for .drawio files")
    ap.add_argument("file")
    ap.add_argument("--stage", choices=["hand", "pre-layout", "post-layout"], default="hand")
    ap.add_argument("--json", dest="json_path")
    ap.add_argument("--fixture-mode", action="store_true",
                    help="ignore calibration.json, use constants (deterministic tests)")
    args = ap.parse_args(argv)

    if not os.path.exists(args.file):
        print(f"validate: file not found: {args.file}", file=sys.stderr)
        return 2
    try:
        rep = validate(args.file, args.stage, args.fixture_mode)
    except (ET.ParseError, ValueError) as e:
        # check 1: malformed XML or a non-mxfile/mxGraphModel root is a well-formedness gate
        print("drawio structural report")
        print("\nGATES (blocking):")
        print(f"  [ 1] well-formed XML / valid root failed: {e}")
        print("\nGATES FAILED: 1")
        if args.json_path:
            with open(args.json_path, "w", encoding="utf-8") as f:
                json.dump({"stage": args.stage, "gates_failed": [1], "warnings": [],
                           "regions": [], "counts": {"pinned": 0, "unpinned": 0},
                           "verdict": "gates-failed"}, f, indent=2)
        return 1
    except Exception as e:  # unexpected internal fault, distinct from a diagram defect
        print(f"validate: internal error analyzing file: {e}", file=sys.stderr)
        return 2

    print_report(rep, args.stage)
    if args.json_path:
        with open(args.json_path, "w", encoding="utf-8") as f:
            json.dump(build_json(rep), f, indent=2)
    return 1 if rep.gates else 0


if __name__ == "__main__":
    sys.exit(main())
