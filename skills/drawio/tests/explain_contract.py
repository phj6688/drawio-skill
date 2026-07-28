#!/usr/bin/env python3
"""Contract tests for explain.py. Docker-free, browser-free, stdlib only.

Covers the failure modes that actually shipped broken output during development:
per-diagram calibration, id collisions across a suite, and coverage collapse.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.normpath(os.path.join(HERE, "..", "scripts", "explain.py"))

spec = importlib.util.spec_from_file_location("explain", SCRIPT)
explain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(explain)

FAILS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(("PASS  " if ok else "FAIL  ") + name + (f"  [{detail}]" if detail else ""))
    if not ok:
        FAILS.append(name)


def drawio(cells: str, ) -> str:
    return ('<mxfile><diagram><mxGraphModel><root>'
            '<mxCell id="0"/><mxCell id="1" parent="0"/>'
            f'{cells}</root></mxGraphModel></diagram></mxfile>')


def box(cid, x, y, w, h, label="B", parent="1", style="rounded=0;fillColor=#dae8fc;strokeColor=#6c8ebf;"):
    return (f'<mxCell id="{cid}" value="{label}" style="{style}" vertex="1" parent="{parent}">'
            f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry"/></mxCell>')


def svg_with(rects, w=800, h=600) -> str:
    body = "".join(f'<rect x="{x}" y="{y}" width="{rw}" height="{rh}"/>' for x, y, rw, rh in rects)
    return f'<svg width="{w}px" height="{h}px" viewBox="0 0 {w} {h}">{body}</svg>'


def main() -> int:
    # ---- parse: absolute coordinates through a parent group ----
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "a.drawio")
        open(p, "w").write(drawio(
            box("grp", 100, 200, 400, 300, "Group") +
            box("kid", 20, 30, 80, 40, "Kid", parent="grp")))
        nodes = {n["id"]: n for n in explain.parse_drawio(p)["nodes"]}
        check("child coordinates are resolved to absolute",
              (nodes["kid"]["x"], nodes["kid"]["y"]) == (120.0, 230.0),
              f'{nodes["kid"]["x"]},{nodes["kid"]["y"]}')

    # ---- parse: a cell with no fill and no stroke draws no shape ----
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "b.drawio")
        open(p, "w").write(drawio(
            box("solid", 0, 0, 100, 40, "S") +
            box("bare", 0, 60, 100, 40, "T", style="text;fillColor=none;strokeColor=none;")))
        nodes = {n["id"]: n for n in explain.parse_drawio(p)["nodes"]}
        check("drawn flag distinguishes shapes from bare labels",
              nodes["solid"]["drawn"] is True and nodes["bare"]["drawn"] is False,
              f'solid={nodes["solid"]["drawn"]} bare={nodes["bare"]["drawn"]}')

    # ---- calibrate: recovers a known translation, including a negative origin ----
    for ox, oy, label in ((-5, -8, "negative"), (-3, 92, "positive y (negative-origin canvas)")):
        # sizes must differ by more than the +/-1 match tolerance, or every node
        # also matches its neighbours' rects and the vote splits
        nodes = [{"id": f"n{i}", "x": i * 130.0, "y": i * 70.0,
                  "w": 100.0 + i * 13, "h": 40.0 + i * 7, "label": "x", "drawn": True}
                 for i in range(12)]
        svg = svg_with([(n["x"] + ox, n["y"] + oy, n["w"], n["h"]) for n in nodes])
        dx, dy, votes = explain.calibrate(svg, nodes, "t")
        check(f"calibrate recovers offset ({label})", (dx, dy) == (ox, oy), f"got ({dx},{dy}) votes={votes}")

    # ---- calibrate: refuses when the evidence is thin ----
    try:
        explain.calibrate(svg_with([(0, 0, 100, 40)]),
                          [{"id": "a", "x": 5.0, "y": 8.0, "w": 100.0, "h": 40.0,
                            "label": "x", "drawn": True}], "thin")
        check("calibrate refuses a thin majority", False, "accepted 1 vote")
    except SystemExit:
        check("calibrate refuses a thin majority", True)

    # ---- strip_raster removes the PNG duplicates, keeps the text ----
    s = ('<svg><foreignObject><div>Hello</div></foreignObject>'
         '<image x="1" y="2" width="3" height="4" xlink:href="data:image/png;base64,AAAA"/></svg>')
    out = explain.strip_raster(s)
    check("strip_raster drops raster fallbacks, keeps labels",
          "base64" not in out and "Hello" in out)

    # ---- field aliases: German and English content files both load ----
    de = explain.norm_entry({"titel": "T", "was": "W", "warum": "Y", "fakt": "F"})
    en = explain.norm_entry({"title": "T", "what": "W", "why": "Y", "fact": "F"})
    check("content accepts either language's field names", de == en, f"{de} vs {en}")

    # ---- ids collide across a suite: namespacing must keep them apart ----
    with tempfile.TemporaryDirectory() as d:
        suite = os.path.join(d, "suite")
        content = os.path.join(d, "content")
        os.makedirs(suite)
        # drawio reuses ids like "title"/"legend" in every file of a suite
        for name, lab in (("01-overview", "Pipeline stage"), ("02-detail", "Export step")):
            open(os.path.join(suite, f"{name}.drawio"), "w").write(
                drawio(box("legend-tx-1", 40, 40, 160, 30, lab) +
                       box("other", 40, 100, 160, 30, "Other")))
        r = subprocess.run([sys.executable, SCRIPT, "init", suite, "--content", content],
                           capture_output=True, text=True)
        check("init scaffolds one file per diagram", r.returncode == 0 and
              os.path.exists(os.path.join(content, "text.01-overview.json")) and
              os.path.exists(os.path.join(content, "text.02-detail.json")),
              r.stderr[-160:])
        seeded = json.load(open(os.path.join(content, "text.01-overview.json"), encoding="utf-8"))
        check("init seeds every element with its label",
              seeded["legend-tx-1"]["_label"] == "Pipeline stage", str(list(seeded)))

        # fill both, then confirm the two same-id entries stay distinct
        for name, txt in (("01-overview", "the first"), ("02-detail", "the second")):
            path = os.path.join(content, f"text.{name}.json")
            doc = json.load(open(path, encoding="utf-8"))
            for eid in doc:
                doc[eid].update({"title": f"{eid} {txt}", "what": f"what {txt}",
                                 "why": f"why {txt}", "fact": f"fact {txt}"})
            json.dump(doc, open(path, "w", encoding="utf-8"), ensure_ascii=False)
        texts = explain.load_content(content, ["01-overview", "02-detail"])
        check("same id in two diagrams stays two entries",
              texts.get("01-overview::legend-tx-1", {}).get("what") == "what the first" and
              texts.get("02-detail::legend-tx-1", {}).get("what") == "what the second",
              f"{len(texts)} entries")

    # ---- coverage gate: an empty content dir must not produce a page ----
    with tempfile.TemporaryDirectory() as d:
        suite = os.path.join(d, "suite")
        content = os.path.join(d, "content")
        os.makedirs(suite)
        os.makedirs(content)
        open(os.path.join(suite, "x.drawio"), "w").write(box("a", 40, 40, 120, 40, "A"))
        open(os.path.join(suite, "x.drawio"), "w").write(drawio(box("a", 40, 40, 120, 40, "A")))
        out = os.path.join(d, "out.html")
        r = subprocess.run([sys.executable, SCRIPT, "build", suite, "--content", content,
                            "--out", out, "--no-render"], capture_output=True, text=True)
        check("build refuses when nothing is documented",
              r.returncode != 0 and not os.path.exists(out),
              f"rc={r.returncode}")

    # ---- discover orders overview first, then complete, then the rest ----
    with tempfile.TemporaryDirectory() as d:
        for f in ("03-enterprise-architecture-complete.drawio", "01-high-level-overview.drawio",
                  "05-other.drawio"):
            open(os.path.join(d, f), "w").write(drawio(box("a", 0, 0, 10, 10)))
        kinds = [k for _n, _r, k in explain.discover(d, None)]
        check("discover puts overview first and complete second",
              kinds == ["overview", "complete", "main"], str(kinds))

    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): " + ", ".join(FAILS))
        return 1
    print("explain contract: all checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
