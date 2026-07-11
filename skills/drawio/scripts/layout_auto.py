#!/usr/bin/env python3
"""MODE-AUTO layout driver (stage: PRE-LAYOUT -> POST-LAYOUT).

Usage: layout_auto.py FILE [--direction DOWN|RIGHT]

Feeds a topology .drawio (naive stacked geometry is fine) to the pinned image's
ELK pass and re-reads the engine-assigned coordinates, then hands the result to
validate.py --stage post-layout. On a geometry gate failure it climbs a fix
ladder (bump spacing, then an alternate preset) up to ENGINE_MAX_INVOCATIONS
engine calls before printing the C4-split terminal instruction.

Verified round-trip (2026-07-10, image v1.62.0): `-x -f xml --layout '<elk-json>'
-o out.drawio in.drawio` re-emits an uncompressed mxfile whose vertex geometry is
the engine's, not the input's. `-f drawio` writes a compressed binary body that
validate.py cannot read, so `-f xml` is the only usable export here. `--layout
libavoid` hangs indefinitely on this image (timeout 124, no output), so that
ladder rung probes once with a short bound and skips when it does not answer.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from constants import (
    DOCKER_IMAGE, DOCKER_SHM, RENDER_TIMEOUT_S,
    ELK_NODE_NODE, ELK_EDGE_NODE, ELK_LAYER_SPACING,
    ELK_BUMP_NODE_NODE, ELK_BUMP_EDGE_NODE, ELK_BUMP_LAYER,
    ENGINE_MAX_INVOCATIONS, MODE_HAND_MAX_NODES,
)

LIBAVOID_PROBE_S = 25  # libavoid hangs on this image; bound the one-time probe short


def elk_json(direction, node_node, layer, edge_node):
    return json.dumps([{
        "layout": "elkLayered",
        "config": {
            "elk.direction": direction,
            "elk.spacing.nodeNode": node_node,
            "elk.layered.spacing.nodeNodeBetweenLayers": layer,
            "elk.spacing.edgeNode": edge_node,
        },
    }])


def engine_run(in_dir, in_base, out_base, layout_arg, timeout_s):
    """Run one ELK pass; return True iff a non-empty output file landed.

    docker's exit code is unreliable, so the output-file check is authoritative.
    """
    out_path = os.path.join(in_dir, out_base)
    if os.path.exists(out_path):
        os.remove(out_path)
    subprocess.run(
        ["timeout", str(timeout_s), "docker", "run", "--rm",
         f"--shm-size={DOCKER_SHM}", "-w", "/data", "-v", f"{in_dir}:/data",
         DOCKER_IMAGE, "-x", "-f", "xml", "--layout", layout_arg,
         "-o", out_base, in_base],
        capture_output=True,
    )
    return os.path.exists(out_path) and os.path.getsize(out_path) > 0


def validate_post_layout(out_path, report_path):
    """Return (available, failed_gates). available is False when validate.py is absent."""
    validator = os.path.join(SCRIPT_DIR, "validate.py")
    if not os.path.exists(validator):
        return False, set()
    subprocess.run(
        ["python3", validator, out_path, "--stage", "post-layout", "--json", report_path],
        capture_output=True, text=True,
    )
    failed = set()
    try:
        with open(report_path, encoding="utf-8") as f:
            failed = {int(g) for g in json.load(f).get("gates_failed", [])}
    except (OSError, ValueError):
        pass
    return True, failed


# Only node-overlap is fixable by respacing. Structural gates are authoring
# errors; density needs a split; legend gates belong to the post-legend pass
# (the legend is built after placement, from engine coordinates).
LADDER_GATES = {8}
STRUCTURAL_GATES = {1, 2, 3, 4, 5, 15}
DENSITY_GATES = {16}
LEGEND_GATES = {20, 21, 25}


def c4_split_block(n_nodes):
    print()
    print("C4-SPLIT REQUIRED (terminal rung: engine could not place this cleanly)")
    print(f"  This topology ({n_nodes} content nodes) resists automatic placement within")
    print(f"  {ENGINE_MAX_INVOCATIONS} engine passes. Split it by C4 level, one diagram per page,")
    print(f"  each page under {MODE_HAND_MAX_NODES} nodes (MODE-HAND territory):")
    print("    1. Context: the system as one box plus its external actors and systems.")
    print("    2. Containers: apps, services, datastores inside the system boundary.")
    print("    3. Components: the internals of the one container that needs zoom.")
    print("  Draw each level as its own diagram, link them by a shared node name, and")
    print("  hand-place per the MODE-HAND grid. Re-run layout_auto on any page still")
    print(f"  above {MODE_HAND_MAX_NODES} nodes after the split.")


def count_content_nodes(path):
    import xml.etree.ElementTree as ET
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError:
        return 0
    return sum(1 for c in root.iter("mxCell") if c.get("vertex") == "1")


def main():
    ap = argparse.ArgumentParser(
        description="stage POST-LAYOUT: ELK-place a topology, gate it, climb the fix ladder"
    )
    ap.add_argument("file")
    ap.add_argument("--direction", choices=["DOWN", "RIGHT"], default="DOWN")
    args = ap.parse_args()

    if not os.path.isfile(args.file):
        print(f"layout_auto: no such file: {args.file}", file=sys.stderr)
        return 2
    if not shutil.which("docker"):
        print("layout_auto: docker not found; the ELK layout pass needs the pinned image")
        return 2

    in_path = os.path.abspath(args.file)
    in_dir = os.path.dirname(in_path)
    in_base = os.path.basename(in_path)
    stem = os.path.splitext(in_base)[0]
    out_base = f"{stem}.auto.drawio"
    out_path = os.path.join(in_dir, out_base)
    report_path = os.path.join(in_dir, f"{stem}.auto.report.json")
    n_nodes = count_content_nodes(in_path)

    # Ladder rungs in order. libavoid sits between bump and alt-preset but is
    # probe-gated: it only counts as a rung if it actually returns a layout.
    d = args.direction
    alt = "verticalTree" if d == "RIGHT" else "horizontalFlow"
    rungs = [
        ("elkLayered", elk_json(d, ELK_NODE_NODE, ELK_LAYER_SPACING, ELK_EDGE_NODE), RENDER_TIMEOUT_S),
        ("bump-spacing", elk_json(d, ELK_BUMP_NODE_NODE, ELK_BUMP_LAYER, ELK_BUMP_EDGE_NODE), RENDER_TIMEOUT_S),
        ("libavoid", "libavoid", LIBAVOID_PROBE_S),
        ("alt-preset", alt, RENDER_TIMEOUT_S),
    ]

    invocations = 0
    for name, layout_arg, timeout_s in rungs:
        if invocations >= ENGINE_MAX_INVOCATIONS:
            break
        produced = engine_run(in_dir, in_base, out_base, layout_arg, timeout_s)
        if name == "libavoid" and not produced:
            # Known to hang on this image; not counted, drop to the next rung.
            print("layout_auto: libavoid did not answer within the probe bound, skipping rung")
            continue
        invocations += 1
        if not produced:
            print(f"layout_auto: rung '{name}' produced no output (engine hung or failed)")
            continue

        available, failed = validate_post_layout(out_path, report_path)
        if not available:
            print(f"layout_auto: laid out via '{name}' -> {out_path}")
            print("layout_auto: validate.py absent, post-layout geometry gates NOT run (structure UNVERIFIED)")
            return 0
        structural = failed & STRUCTURAL_GATES
        if structural:
            print(f"layout_auto: structural gates {sorted(structural)} failed; these are authoring "
                  f"errors respacing cannot fix (see {report_path})")
            return 1
        if failed & DENSITY_GATES:
            c4_split_block(n_nodes)
            return 4
        if not failed & LADDER_GATES:
            print(f"layout_auto: laid out via '{name}' -> {out_path}")
            deferred = failed & LEGEND_GATES
            if deferred:
                print(f"layout_auto: legend gates {sorted(deferred)} deferred: add the title and legend "
                      f"now (references/legend-color.md), placed from the engine coordinates, then "
                      f"re-run validate.py --stage post-layout on the finished file")
            print(f"LAID OUT - NOT YET VERIFIED. Render + LOOK required. Run: scripts/render.sh {out_path}")
            return 0
        print(f"layout_auto: rung '{name}' left geometry gates failing (see {report_path}), climbing")

    c4_split_block(n_nodes)
    return 4


if __name__ == "__main__":
    sys.exit(main())
