#!/usr/bin/env python3
"""explain: turn a .drawio suite into one interactive, self-contained HTML page.

The page shows the REAL drawio SVG export with a transparent hotspot over every
box. Clicking a box opens a panel that says what it is, why it exists, and one
concrete fact. Built for standing in front of a team and answering questions.

Three commands:

    explain.py init  SUITE_DIR --content DIR   scaffold one JSON per diagram,
                                               pre-seeded with every element id
    explain.py build SUITE_DIR --content DIR   render, calibrate, assemble
    explain.py check HTML_FILE                 static self-checks on the output

The prose is yours; this script never invents text. `init` gives you the exact
element list so nothing gets silently skipped, `build` refuses to ship a page
whose boxes lost their text, and `check` re-reads the built page.

Two traps this exists to handle, both of which produced wrong output before:

1. The drawio->SVG shift is a pure translation, but it differs PER DIAGRAM: each
   export is centred on its own content bounds, and a canvas with negative
   coordinates gets a positive offset. It is derived here from dimension matches
   and the build aborts when the majority is not clear. Never hardcode it.

2. Element ids are unique only WITHIN a diagram. drawio reuses `title`, `legend`,
   `legend-tx-1`... across every file of a suite with different meanings, so text
   is keyed "<diagram>::<id>". A flat merge silently loses most of it.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from collections import Counter

HERE = os.path.dirname(os.path.abspath(__file__))
ASSETS = os.path.normpath(os.path.join(HERE, "..", "assets"))
RENDER_IMAGE = "rlespinasse/drawio-desktop-headless"

# A hotspot smaller than this is a legend colour chip, not a component.
MIN_CHIP_W, MIN_CHIP_H = 70, 26
# Refuse a calibration that is not clearly the majority.
MIN_OFFSET_VOTES = 8
OFFSET_MARGIN = 1.5
# Refuse a build whose coverage collapsed (a stale content path once produced 33
# of 240 entries and still "built fine").
MIN_COVERAGE = 0.90

UI = {
    "en": {
        "overview": "Overview", "complete": "Complete", "components": "Components",
        "reference": "Reference", "search_box": "Find a box ...",
        "search_ref": "Search the reference ...", "mark": "Mark clickable",
        "smaller": "Smaller", "bigger": "Bigger", "fit": "Fit", "actual": "100%",
        "what": "What is it", "why": "Why we do it", "fact": "Worth knowing",
        "also": "Also appears in", "detail": "Detail diagram", "close": "Close",
        "hits": "hits", "clickable": "boxes are clickable",
        "hint": "Click any element in the diagram. This panel then says what it is, "
                "why we do it that way, and one fact about it.",
        "keys": "Drag to pan. Ctrl + wheel to zoom. <kbd>Esc</kbd> closes, "
                "<kbd>n</kbd>/<kbd>p</kbd> walk through the boxes.",
        "copy": "Copy link", "copied": "Link copied", "walk": "Walk",
        "nothing": "Nothing found. Shorten the term or clear the field.",
        "theme": "Light / dark",
    },
    "de": {
        "overview": "Überblick", "complete": "Vollständig", "components": "Komponenten",
        "reference": "Nachschlagen", "search_box": "Kasten suchen ...",
        "search_ref": "Im Nachschlagewerk suchen ...", "mark": "Klickbare markieren",
        "smaller": "Kleiner", "bigger": "Größer", "fit": "Einpassen", "actual": "100%",
        "what": "Was ist das", "why": "Warum machen wir das", "fact": "Gut zu wissen",
        "also": "Kommt auch vor in", "detail": "Detail-Diagramm", "close": "Schließen",
        "hits": "Treffer", "clickable": "Kästen sind anklickbar",
        "hint": "Klick auf ein Element im Diagramm. Dann steht hier, was es ist, "
                "warum wir es so machen und ein Fakt dazu.",
        "keys": "Ziehen zum Verschieben. Strg + Mausrad zum Zoomen. <kbd>Esc</kbd> "
                "schließt, <kbd>n</kbd>/<kbd>p</kbd> laufen durch die Kästen.",
        "copy": "Link kopieren", "copied": "Link kopiert", "walk": "Durchgehen",
        "nothing": "Nichts gefunden. Suchbegriff kürzen oder Feld leeren.",
        "theme": "Hell / dunkel",
    },
}

# Accept either language's field names so content files stay readable in the
# language they were written in.
FIELD_ALIASES = {
    "title": ("title", "titel"), "what": ("what", "was"),
    "why": ("why", "warum"), "fact": ("fact", "fakt"),
    "detail": ("detail",),
    # the diagram's own text, written by `init`. Kept so `check` can tell a real
    # cross-diagram leak from two boxes that legitimately carry the same label.
    "_label": ("_label",),
}


def die(msg: str) -> "None":
    print(f"explain: {msg}", file=sys.stderr)
    raise SystemExit(2)


def norm_entry(raw: dict) -> dict:
    out = {}
    for key, aliases in FIELD_ALIASES.items():
        for a in aliases:
            if raw.get(a):
                out[key] = str(raw[a]).strip()
                break
    return out


# --------------------------------------------------------------------------
# 1. parse
# --------------------------------------------------------------------------
def _unescape(s: str) -> str:
    if not s:
        return ""
    t = html.unescape(html.unescape(s))
    t = re.sub(r"<br\s*/?>", " | ", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\s+", " ", t).strip()


def _style(s: str) -> dict:
    d = {}
    for part in (s or "").split(";"):
        if not part:
            continue
        k, _, v = part.partition("=")
        d[k.strip()] = v.strip() if v else True
    return d


def parse_drawio(path: str) -> dict:
    """Flatten a .drawio into nodes with ABSOLUTE coordinates.

    drawio stores a child's geometry relative to its parent group, so the parent
    chain has to be walked or every grouped element lands in the wrong place.
    """
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as e:
        die(f"{path}: not parseable XML ({e}). Is it compressed? Author uncompressed.")
    # `a or b` is wrong on Elements: an Element with no children is falsy, so a
    # valid-but-empty <root> would silently fall through to the next lookup.
    model = root.find(".//mxGraphModel/root")
    if model is None:
        model = root.find(".//root")
    if model is None:
        die(f"{path}: no <mxGraphModel><root> found")

    cells = {}
    order = []
    for c in model:
        cid = c.get("id")
        if cid is None:
            continue
        geo = c.find("mxGeometry")
        g = {}
        if geo is not None:
            for k in ("x", "y", "width", "height"):
                v = geo.get(k)
                g[k] = float(v) if v is not None else 0.0
        cells[cid] = {
            "id": cid, "label": _unescape(c.get("value")), "style": c.get("style") or "",
            "parent": c.get("parent"), "vertex": c.get("vertex") == "1",
            "edge": c.get("edge") == "1", "geo": g,
        }
        order.append(cid)

    def abs_xy(cid, depth=0):
        c = cells.get(cid)
        if c is None or depth > 25:
            return 0.0, 0.0
        px = py = 0.0
        p = c.get("parent")
        if p in cells and cells[p]["vertex"]:
            px, py = abs_xy(p, depth + 1)
        return px + c["geo"].get("x", 0.0), py + c["geo"].get("y", 0.0)

    nodes = []
    for cid in order:
        c = cells[cid]
        if c["edge"] or not c["vertex"]:
            continue
        w, h = c["geo"].get("width", 0.0), c["geo"].get("height", 0.0)
        if w <= 0 or h <= 0:
            continue
        st = _style(c["style"])
        x, y = abs_xy(cid)
        fill, stroke = st.get("fillColor"), st.get("strokeColor")
        nodes.append({
            "id": cid, "label": c["label"],
            "x": round(x, 1), "y": round(y, 1), "w": round(w, 1), "h": round(h, 1),
            # A cell with neither fill nor stroke draws no shape: it is a bare
            # text label, and asserting shape alignment on it is meaningless.
            "drawn": not (fill in (None, "none") and stroke in (None, "none")),
        })
    return {"nodes": nodes}


def explainable(nodes: list) -> list:
    return [n for n in nodes
            if n["label"] and not (n["w"] < MIN_CHIP_W and n["h"] < MIN_CHIP_H)]


# --------------------------------------------------------------------------
# 2. render + calibrate
# --------------------------------------------------------------------------
def render_svg(src: str, out_svg: str, quiet: bool = False) -> None:
    if os.path.exists(out_svg) and os.path.getmtime(out_svg) > os.path.getmtime(src):
        return
    if not shutil.which("docker"):
        die("docker not found. It renders the SVG; see references/verify.md for fallbacks.")
    os.makedirs(os.path.dirname(out_svg) or ".", exist_ok=True)
    cmd = [
        "docker", "run", "--rm",
        "-v", f"{os.path.abspath(os.path.dirname(src))}:/data",
        "-v", f"{os.path.abspath(os.path.dirname(out_svg))}:/out",
        "--user", f"{os.getuid()}:{os.getgid()}", "-e", "HOME=/tmp",
        "--shm-size=1g", RENDER_IMAGE, "-x", "-f", "svg", "--border", "12",
        "-o", f"/out/{os.path.basename(out_svg)}", f"/data/{os.path.basename(src)}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(out_svg):
        die(f"render failed for {src}: {(r.stderr or r.stdout)[-400:]}")
    if not quiet:
        print(f"    rendered {os.path.basename(src)}")


def strip_raster(svg_text: str) -> str:
    """drawio ships every label twice: a <foreignObject> that browsers use and a
    base64 PNG fallback. Dropping the fallback cuts about 96% of the bytes."""
    return re.sub(r'<image[^>]*xlink:href="data:image/[^"]*"[^>]*/?>(</image>)?',
                  "", svg_text)


def calibrate(svg_text: str, nodes: list, name: str) -> tuple:
    """Derive the drawio->SVG translation from node/rect dimension matches."""
    rects = [tuple(map(float, r)) for r in re.findall(
        r'<rect x="(-?[\d.]+)" y="(-?[\d.]+)" width="([\d.]+)" height="([\d.]+)"',
        svg_text)]
    votes = Counter()
    for n in nodes:
        for rx, ry, rw, rh in rects:
            if abs(rw - n["w"]) <= 1 and abs(rh - n["h"]) <= 1:
                votes[(round(rx - n["x"]), round(ry - n["y"]))] += 1
    if not votes:
        die(f"{name}: could not calibrate (no rect matched any node size)")
    (dx, dy), top = votes.most_common(1)[0]
    runner = votes.most_common(2)[1][1] if len(votes) > 1 else 0
    if top < MIN_OFFSET_VOTES or top <= runner * OFFSET_MARGIN:
        die(f"{name}: offset ({dx},{dy}) is not a clear majority "
            f"(votes={top}, runner-up={runner}). Re-render before building.")
    return dx, dy, top


def canvas_of(svg_text: str) -> tuple:
    m = re.search(r'<svg[^>]*width="([\d.]+)px"[^>]*height="([\d.]+)px"', svg_text)
    return (float(m.group(1)), float(m.group(2))) if m else (1000.0, 1000.0)


# --------------------------------------------------------------------------
# 3. suite discovery
# --------------------------------------------------------------------------
def discover(suite_dir: str, components_sub: str | None) -> list:
    """Return [(key, relpath, kind)] with overview/complete first."""
    top = sorted(f for f in os.listdir(suite_dir) if f.endswith(".drawio"))
    if not top:
        die(f"{suite_dir}: no .drawio files")
    out = []
    for f in top:
        low = f.lower()
        kind = "main"
        if "overview" in low or "high-level" in low:
            kind = "overview"
        elif "complete" in low or "enterprise" in low:
            kind = "complete"
        out.append((os.path.splitext(f)[0], f, kind))
    out.sort(key=lambda t: {"overview": 0, "complete": 1, "main": 2}[t[2]])

    if components_sub:
        cdir = os.path.join(suite_dir, components_sub)
        if not os.path.isdir(cdir):
            die(f"--components {components_sub}: not a directory under {suite_dir}")
        for f in sorted(x for x in os.listdir(cdir) if x.endswith(".drawio")):
            out.append((os.path.splitext(f)[0],
                        os.path.join(components_sub, f), "component"))
    return out


def pretty(name: str) -> str:
    s = re.sub(r"^\d+[-_]?", "", name).replace("-", " ").replace("_", " ")
    return s.strip().capitalize() or name


def load_labels(content_dir: str) -> dict:
    """Optional content/labels.json: {"<diagram>": "Tab label"}.

    Filenames make poor tab labels, and an English filename reads badly on a
    German page. This lets the suite name its own tabs without renaming files.
    """
    path = os.path.join(content_dir, "labels.json")
    if not os.path.exists(path):
        return {}
    try:
        raw = json.load(open(path, encoding="utf-8"))
    except json.JSONDecodeError as e:
        die(f"{path}: invalid JSON ({e})")
    return {k: str(v) for k, v in raw.items() if isinstance(v, (str, int))}


# --------------------------------------------------------------------------
# commands
# --------------------------------------------------------------------------
def cmd_init(a) -> int:
    diagrams = discover(a.suite, a.components)
    os.makedirs(a.content, exist_ok=True)
    total = seeded = 0
    for key, rel, _kind in diagrams:
        nodes = explainable(parse_drawio(os.path.join(a.suite, rel))["nodes"])
        path = os.path.join(a.content, f"text.{key}.json")
        existing = {}
        if os.path.exists(path):
            existing = json.load(open(path, encoding="utf-8"))
        doc = {}
        for n in nodes:
            total += 1
            prev = existing.get(n["id"], {})
            if prev.get("what") or prev.get("was"):
                doc[n["id"]] = prev
                seeded += 1
            else:
                doc[n["id"]] = {"_label": n["label"], "title": "", "what": "",
                                "why": "", "fact": ""}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(doc, f, ensure_ascii=False, indent=1)
        print(f"  {key}: {len(nodes)} elements -> {os.path.basename(path)}")
    print(f"\n{total} elements across {len(diagrams)} diagrams; {seeded} already written.")
    print(f"Fill title/what/why/fact in {a.content}/text.*.json, then run: explain.py build")
    return 0


def load_content(content_dir: str, keys: list) -> dict:
    """Read text.<diagram>.json into "<diagram>::<id>" keys.

    Also accepts one flat file for a single-diagram suite, but never merges two
    diagrams into one namespace: ids repeat across a suite with other meanings.
    """
    texts = {}
    if not os.path.isdir(content_dir):
        die(f"{content_dir}: no such directory. Run `explain.py init` first.")
    for key in keys:
        path = os.path.join(content_dir, f"text.{key}.json")
        if not os.path.exists(path):
            continue
        try:
            raw = json.load(open(path, encoding="utf-8"))
        except json.JSONDecodeError as e:
            die(f"{path}: invalid JSON ({e})")
        for eid, entry in raw.items():
            if not isinstance(entry, dict):
                continue
            e = norm_entry(entry)
            if e.get("what") or e.get("why") or e.get("fact"):
                texts[f"{key}::{eid}"] = e
    return texts


def cmd_build(a) -> int:
    lang = a.lang
    t = UI[lang]
    diagrams = discover(a.suite, a.components)
    keys = [k for k, _r, _kind in diagrams]
    texts = load_content(a.content, keys)
    labels = load_labels(a.content)
    work = a.work or os.path.join(a.content, ".work")
    os.makedirs(work, exist_ok=True)

    print(f"==> {len(diagrams)} diagrams, lang={lang}")
    built, all_nodes, offsets = [], {}, {}
    for key, rel, kind in diagrams:
        src = os.path.join(a.suite, rel)
        svg_path = os.path.join(work, f"{key}.svg")
        if not a.no_render:
            render_svg(src, svg_path, quiet=a.quiet)
        if not os.path.exists(svg_path):
            die(f"{svg_path} missing. Drop --no-render, or render first.")
        svg = strip_raster(open(svg_path, encoding="utf-8").read())
        svg = re.sub(r"<\?xml[^>]*\?>|<!DOCTYPE[^>]*>", "", svg).strip()
        nodes = parse_drawio(src)["nodes"]
        dx, dy, votes = calibrate(svg, nodes, key)
        offsets[key] = (dx, dy)
        all_nodes[key] = nodes
        built.append({"key": key, "kind": kind, "rel": rel, "svg": svg,
                      "canvas": canvas_of(svg), "nodes": nodes})
        if not a.quiet:
            print(f"    {key}: offset=({dx},{dy}) votes={votes}")

    # ---- coverage gate ----
    expected = sum(len(explainable(b["nodes"])) for b in built)
    have = 0
    for b in built:
        have += sum(1 for n in explainable(b["nodes"])
                    if f'{b["key"]}::{n["id"]}' in texts)
    print(f"==> coverage {have}/{expected} elements documented")
    if expected and have < expected * MIN_COVERAGE:
        missing = []
        for b in built:
            for n in explainable(b["nodes"]):
                if f'{b["key"]}::{n["id"]}' not in texts:
                    missing.append(f'{b["key"]}::{n["id"]} ({n["label"][:40]})')
        die(f"only {have} of {expected} elements have text. Missing e.g.: "
            + "; ".join(missing[:5])
            + f"\n  Fill them in {a.content}/text.*.json, or pass --min-coverage.")

    # ---- element appears in more than one diagram: offer a jump ----
    where = {}
    for b in built:
        for n in explainable(b["nodes"]):
            gid = f'{b["key"]}::{n["id"]}'
            if gid in texts:
                where.setdefault(n["label"].strip().lower(), []).append(
                    [b["key"], n["id"]])
    also = {}
    for b in built:
        for n in explainable(b["nodes"]):
            gid = f'{b["key"]}::{n["id"]}'
            if gid not in texts:
                continue
            peers = [p for p in where.get(n["label"].strip().lower(), [])
                     if p[0] != b["key"]]
            if peers:
                also[gid] = peers

    page = render_page(built, texts, offsets, also, lang, t, a, labels)
    out = a.out or os.path.join(a.suite, "explain.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"==> wrote {out} ({len(page)//1024} KB, {len(texts)} popups)")
    return 0


def esc(s) -> str:
    return html.escape(str(s or ""), quote=True)


def render_page(built, texts, offsets, also, lang, t, a, labels=None) -> str:
    labels = labels or {}

    def tab_label(key, fallback):
        return labels.get(key) or fallback
    css = open(os.path.join(ASSETS, "explain.css"), encoding="utf-8").read()
    js = open(os.path.join(ASSETS, "explain.js"), encoding="utf-8").read()

    comps = [b for b in built if b["kind"] == "component"]
    mains = [b for b in built if b["kind"] != "component"]

    def body(b):
        key = b["key"]
        ox, oy = offsets[key]
        nodes = [n for n in explainable(b["nodes"]) if f'{key}::{n["id"]}' in texts]
        nodes.sort(key=lambda n: -(n["w"] * n["h"]))

        def holds(p, q):
            return (p is not q and p["x"] <= q["x"] + 1 and p["y"] <= q["y"] + 1
                    and p["x"] + p["w"] >= q["x"] + q["w"] - 1
                    and p["y"] + p["h"] >= q["y"] + q["h"] - 1
                    and p["w"] * p["h"] > q["w"] * q["h"])

        hots = []
        for n in nodes:
            gid = f'{key}::{n["id"]}'
            cont = any(holds(n, m) for m in nodes)
            hots.append(
                f'<button class="hot{" zone" if cont else ""}" data-id="{esc(gid)}"'
                f' data-dg="{esc(key)}" data-leaf="{0 if cont else 1}"'
                f' data-shape="{1 if n["drawn"] else 0}"'
                f' style="left:{n["x"]+ox:.1f}px;top:{n["y"]+oy:.1f}px;'
                f'width:{n["w"]:.1f}px;height:{n["h"]:.1f}px"'
                f' title="{esc(texts[gid].get("title") or n["label"])}"></button>')
        w, h = b["canvas"]
        return f'''
  <div class="dgbar">
    <span class="dgtitle">{esc(tab_label(key, pretty(key)))}</span>
    <span class="dgfile">{esc(b["rel"])}</span>
    <div class="dgspace"></div>
    <input class="dgsearch" type="search" data-dg="{esc(key)}"
           placeholder="{esc(t["search_box"])}" autocomplete="off">
    <label class="dgtoggle"><input type="checkbox" class="dgmark"
      data-dg="{esc(key)}" checked> {esc(t["mark"])}</label>
    <div class="zoomer">
      <button class="zb" data-act="out" data-dg="{esc(key)}" title="{esc(t["smaller"])}">&minus;</button>
      <span class="zlvl" data-dg="{esc(key)}">100%</span>
      <button class="zb" data-act="in" data-dg="{esc(key)}" title="{esc(t["bigger"])}">+</button>
      <button class="zb wide" data-act="fit" data-dg="{esc(key)}">{esc(t["fit"])}</button>
      <button class="zb wide" data-act="reset" data-dg="{esc(key)}">{esc(t["actual"])}</button>
      <button class="zb wide walk" data-act="walk" data-dg="{esc(key)}">{esc(t["walk"])} &rsaquo;</button>
    </div>
  </div>
  <div class="dgbody">
    <div class="dgwrap" data-dg="{esc(key)}" tabindex="0">
      <div class="dgcanvas" data-dg="{esc(key)}" style="width:{w:.0f}px;height:{h:.0f}px">
        {b["svg"]}
        <div class="hots">{"".join(hots)}</div>
      </div>
    </div>
    <aside class="detail" data-dg="{esc(key)}">
      <div class="dhint">
        <div class="dhint-i">?</div>
        <p><b>{len(hots)} {esc(t["clickable"])}.</b></p>
        <p>{esc(t["hint"])}</p>
        <p class="dhint-k">{t["keys"]}</p>
      </div>
      <div class="dcard" hidden>
        <button class="dclose" title="{esc(t["close"])}">&times;</button>
        <h3 class="dtitel"></h3>
        <div class="dsec dwhat"><b>{esc(t["what"])}</b><p></p></div>
        <div class="dsec dwhy"><b>{esc(t["why"])}</b><p></p></div>
        <div class="dsec dfact"><b>{esc(t["fact"])}</b><p></p></div>
        <div class="dalso" hidden><b>{esc(t["also"])}</b><span></span></div>
        <div class="ddetail" hidden>{esc(t["detail"])}: <code></code></div>
        <button class="dcopy">{esc(t["copy"])}</button>
      </div>
    </aside>
  </div>'''

    tabs, panels = [], []
    for b in mains:
        label = tab_label(b["key"], t["overview"] if b["kind"] == "overview" else (
            t["complete"] if b["kind"] == "complete" else pretty(b["key"])))
        tabs.append(f'<button class="tab" role="tab" data-tab="{esc(b["key"])}">{esc(label)}</button>')
        panels.append(f'<div class="tabpanel" id="panel-{esc(b["key"])}" role="tabpanel" hidden>{body(b)}</div>')
    if comps:
        tabs.append(f'<button class="tab" role="tab" data-tab="__comp">{esc(t["components"])}</button>')
        pills = "".join(
            f'<button class="pill{" on" if i == 0 else ""}" data-comp="{esc(c["key"])}">'
            f'{esc(tab_label(c["key"], pretty(c["key"])))}</button>' for i, c in enumerate(comps))
        bodies = "".join(
            f'<div class="comp" data-comp="{esc(c["key"])}"{"" if i == 0 else " hidden"}>{body(c)}</div>'
            for i, c in enumerate(comps))
        panels.append(f'<div class="tabpanel" id="panel-__comp" role="tabpanel" hidden>'
                      f'<div class="pills">{pills}</div>{bodies}</div>')
    ref = ""
    if a.reference and os.path.exists(a.reference):
        ref = open(a.reference, encoding="utf-8").read()
        tabs.append(f'<button class="tab" role="tab" data-tab="__ref">{esc(t["reference"])}</button>')
        panels.append(f'<div class="tabpanel" id="panel-__ref" role="tabpanel" hidden>'
                      f'<main>{ref}</main></div>')

    order = [b["key"] for b in mains] + (["__comp"] if comps else []) + (["__ref"] if ref else [])
    cfg = {"lang": lang, "tabs": order,
           "comps": [c["key"] for c in comps],
           "dgs": [b["key"] for b in built],
           "ui": {k: t[k] for k in ("copied", "hits", "nothing")}}
    title = a.title or pretty(os.path.basename(os.path.abspath(a.suite)))
    return f'''<!doctype html>
<html lang="{lang}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<style>{css}</style>
</head>
<body>
<div class="top">
  <h1>{esc(title)}</h1>
  <div class="tabs" role="tablist">{"".join(tabs)}</div>
  <div class="searchwrap">
    <input id="q" type="search" placeholder="{esc(t["search_ref"])}" autocomplete="off" hidden>
    <span id="hits"></span>
    <button class="tbtn" id="theme" title="{esc(t["theme"])}">◐</button>
  </div>
</div>
{"".join(panels)}
<div class="empty hide" id="noresult">{esc(t["nothing"])}</div>
<script>
const TEXTS = {json.dumps(texts, ensure_ascii=False)};
const ALSO  = {json.dumps(also, ensure_ascii=False)};
const CFG   = {json.dumps(cfg, ensure_ascii=False)};
</script>
<script>{js}</script>
</body>
</html>
'''


def _related(a: str, b: str, floor: float = 0.2) -> bool:
    """Do two labels describe the same thing? Word overlap, plural-tolerant."""
    def toks(s):
        return list({w for w in re.findall(r"[a-z0-9\u00e4\u00f6\u00fc\u00df]{3,}", s.lower())})
    A, B = toks(a), toks(b)
    if not A or not B:
        return a.strip().lower() == b.strip().lower()
    same = lambda x, y: x == y or (len(x) >= 4 and (x.startswith(y) or y.startswith(x)))  # noqa: E731
    inter = sum(1 for x in A if any(same(x, y) for y in B))
    return inter / max(1, len(set(A) | set(B))) >= floor


def cmd_check(a) -> int:
    """Static checks on a built page: the failures that shipped silently before."""
    text = open(a.html, encoding="utf-8").read()
    m = re.search(r"const TEXTS = (\{.*?\});\nconst ALSO", text, re.S)
    if not m:
        die(f"{a.html}: no TEXTS block; is this an explain page?")
    texts = json.loads(m.group(1))
    problems = []

    n_hot = len(re.findall(r'<button class="hot', text))
    if n_hot != len(texts):
        problems.append(f"{n_hot} hotspots but {len(texts)} texts")

    for k, v in texts.items():
        for f in ("title", "what", "why"):
            if not v.get(f) or len(str(v[f]).strip()) < 3:
                problems.append(f"{k}: empty '{f}'")
    # ids repeat across diagrams; identical prose on unrelated labels is a leak
    by_id = {}
    for k, v in texts.items():
        dg, _, eid = k.partition("::")
        by_id.setdefault(eid, []).append((dg, v))
    for eid, rows in by_id.items():
        for i in range(len(rows)):
            for j in range(i + 1, len(rows)):
                a, b = rows[i][1], rows[j][1]
                if not a.get("what") or a.get("what") != b.get("what"):
                    continue
                la, lb = (a.get("_label") or "").strip(), (b.get("_label") or "").strip()
                # The same concept legitimately appears on the overview and the full
                # canvas with different wording ("Faithfulness gate: five abstain axes"
                # vs "Faithfulness gate: 5 axes"), so shared prose there is correct.
                # A real flat-merge leak has UNRELATED labels ("Pipeline stage" vs
                # "Export step"), so compare word overlap, not string equality.
                if la and lb and _related(la, lb):
                    continue
                problems.append(
                    f"{eid}: identical text in {rows[i][0]} ({la or '?'}) and "
                    f"{rows[j][0]} ({lb or '?'}); ids repeat across a suite, "
                    f"so check this is really the same thing")
    if problems:
        print(f"explain check: {len(problems)} problem(s)")
        for p in problems[:20]:
            print(f"  - {p}")
        return 1
    print(f"explain check OK: {len(texts)} popups, {n_hot} hotspots, no empty fields.")
    print("STRUCTURE OK - NOT YET VERIFIED: open the page and click boxes before handing it over.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(prog="explain.py", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("init", help="scaffold content files listing every element")
    pi.add_argument("suite")
    pi.add_argument("--content", required=True, help="directory for text.*.json")
    pi.add_argument("--components", help="subdirectory of component diagrams")
    pi.set_defaults(fn=cmd_init)

    pb = sub.add_parser("build", help="render, calibrate, and assemble the page")
    pb.add_argument("suite")
    pb.add_argument("--content", required=True)
    pb.add_argument("--components")
    pb.add_argument("--out")
    pb.add_argument("--title")
    pb.add_argument("--reference", help="HTML fragment for a reference tab")
    pb.add_argument("--lang", choices=sorted(UI), default="en")
    pb.add_argument("--work", help="scratch dir for SVGs (default <content>/.work)")
    pb.add_argument("--no-render", action="store_true", help="reuse SVGs in --work")
    pb.add_argument("--quiet", action="store_true")
    pb.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    pb.set_defaults(fn=cmd_build)

    pc = sub.add_parser("check", help="static checks on a built page")
    pc.add_argument("html")
    pc.set_defaults(fn=cmd_check)

    a = p.parse_args()
    if getattr(a, "min_coverage", None) is not None:
        globals()["MIN_COVERAGE"] = a.min_coverage
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
