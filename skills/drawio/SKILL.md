---
name: drawio
description: Use when creating or editing draw.io / .drawio / diagrams.net files, when the user asks for an architecture, flowchart, ER, or network diagram as a file deliverable, or when an existing diagram renders with overlaps, stray arrows, unreadable labels, or a missing legend.
---

# drawio: diagrams that survive being looked at

Hand-written .drawio XML fails in ways the author cannot see: valid XML, overlapping boxes, edges through nodes, labels on lines, no legend. Structure checks do not catch visual defects. This skill's spine is therefore a render-and-look loop; the doctrines exist so the first render is nearly right.

**The one unbreakable rule: never hand over a diagram you have not rendered and looked at.** A parse check is not verification. The validator here refuses to say "done" by design.

## Workflow

1. **Plan.** One diagram, one message. Count the content nodes (title and legend do not count):
   - 12 or fewer: MODE-HAND. Place boxes by the grid formula in [references/layout.md](references/layout.md).
   - 13 to 25: MODE-AUTO. Author the topology only (nodes with styles, edges, labels, no legend yet), run `scripts/layout_auto.py`, then add the title and legend positioned from the engine's coordinates. Do not hand-place, do not hand-fix engine coordinates. Pick `--direction RIGHT` when the dependency chain is deeper than about 6 ranks, so the result is not a tower.
   - more than 25: split by abstraction level into linked pages first.
2. **Author uncompressed XML** per [references/xml.md](references/xml.md) (skeleton, killer table). Doctrines:
   - Layout: grid pitch 200x160, boxes 160x60/80, uniform per type, snap 10, margins 40 ([references/layout.md](references/layout.md)).
   - Edges: id endpoints always; pin exit/entry on any labeled edge and any node with 2+ connections; orthogonal default; labels offset 12px off the line with white background; fan-out of 5+ gets a trunk lane or an annotation instead of edge spray ([references/edges.md](references/edges.md)).
   - Color and legend: drawio-native palette, max 6 semantic fills, same type same color; legend required when more than one color/line-style/shape meaning is in play, built exactly to the pattern the validator checks ([references/legend-color.md](references/legend-color.md)).
   - Order in file: containers, vertices, edges, then title and legend last (z-order is document order).
3. **Validate:** `python3 scripts/validate.py FILE --stage hand --json report.json` (stage `post-layout` after layout_auto). Fix gates, re-run, max 3 rounds. Green output says `STRUCTURE OK - NOT YET VERIFIED`: believe it, you are not done.
4. **Render:** `scripts/render.sh FILE`. Docker, pinned image, blank guard included. Exit 2 means no docker: fallback rules in [references/verify.md](references/verify.md).
5. **Look:** `python3 scripts/emit_crops.py FILE FILE.png report.json`, then actually read every crop image and the full PNG. Fix what you see, re-render, max 2 rounds.
6. **Hand over with the completed DONE-CHECK block** (skeleton comes pre-filled from emit_crops with gate results and per-crop nonces; you add only what you read in each crop). Format and rules: [references/verify.md](references/verify.md).

## Quick reference

| task | where |
|---|---|
| XML skeleton, style strings, killer mistakes | references/xml.md |
| grid formula, mode fork, direction, containers | references/layout.md |
| pinning, routing, edge labels, arrow semantics, fan-out | references/edges.md |
| palette, contrast, legend construction and placement | references/legend-color.md |
| loop state machine, DONE-CHECK, STOP table, fallbacks | references/verify.md |
| worked example that passes every gate | tests/fixtures/good_hand_flow.drawio |
| all numbers | scripts/constants.py |

## Red flags: stop and re-read references/verify.md

- You are about to reply "diagram created" without a render having happened.
- You are writing coordinates that are not multiples of 10 or that came from intuition instead of the formula.
- You are adding a seventh fill color, a second meaning for dashed lines, or a legend entry for a style that appears nowhere.
- You are about to fill a DONE-CHECK line without opening its crop.
- The diagram has more than 12 nodes and you are placing boxes by hand anyway.

## Scope

v1 covers architecture, flowchart, ER (plain stacked-vertex entities, crow's-foot edges), and network diagrams on light backgrounds, native shapes only. Out of scope: sequence diagrams, dark mode, `mxgraph.*` stencil libraries, mermaid conversion. When a request needs those, say so instead of improvising half of one.
