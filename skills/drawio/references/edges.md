# Edges: endpoints, routing, labels, semantics

`scripts/constants.py` is authoritative for numbers.

## Endpoint policy

- Every edge references `source` and `target` by cell id. No floating endpoints, ever.
- **Pin connection points** (`exitX/exitY` on the source, `entryX/entryY` on the target, range 0..1 where 0 is left/top and 1 is right/bottom) whenever either holds:
  - the node has 2 or more connections, or
  - the edge carries a label.
  Pinning is not cosmetic: the validator's edge-through-node and label-collision gates are exact only for pinned edges. An unpinned labeled edge downgrades its own checks to warnings and pushes the burden onto the visual pass.
- Distribute multiple edges on one side at 0.25 / 0.5 / 0.75. Two edges into the same side of the same node never share an entry point.
- For a top-to-bottom flow, the default is exit bottom (`exitX=0.5;exitY=1`), enter top (`entryX=0.5;entryY=0`).

## Routing

- Default style: `edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;`.
- Straight edges only when source and target centers share an axis (same row or column), and for ER relationship lines.
- Waypoints (`<Array as="points">`) only when the router would otherwise pass through a node or when routing a marked back-edge around the content. When you add a waypoint that feeds a pinned entry, the waypoint coordinate must equal the entry point's absolute coordinate on that axis, computed, not eyeballed: a mismatch renders a dead dogleg.
- Leave a straight stub of at least 20px before the arrowhead lands.
- If an edge must cross half the diagram, the problem is node placement, not routing. Move the node.
- An edge may never pass through a box it does not connect. Clearance to unrelated boxes: 20px.

## Labels

- Place on the edge cell's `value`, positioned by geometry: `x` in [-1, 1] along the edge (0 = midpoint), `y` = perpendicular offset in px. Default: `x=0`, `y=12` so the label sits beside the line, never on it.
- `labelBackgroundColor=#ffffff` on every labeled edge. It keeps crossings from striking through the text (this package targets light backgrounds; see legend-color.md).
- Font 11. One to three words, verb phrases ("publishes to", "reads from", "scrapes"). Every relationship edge in an architecture diagram gets one; an unlabeled arrow is the first thing a reviewer flags.
- Drop a label that merely repeats what the target box already says.
- Flowchart decisions: exactly two labeled exits per diamond, yes leaves the bottom, no leaves the right, on every diamond in the diagram.

## Semantic vocabulary

Pick from this table, use each meaning consistently, and give every style in use a legend row:

| meaning | line | arrowhead | style fragment |
|---|---|---|---|
| synchronous call / data flow | solid | filled | `endArrow=block;endFill=1;` |
| async / event / message | dashed | open | `dashed=1;endArrow=open;` |
| dependency ("uses") | dashed | open | `dashed=1;endArrow=open;` |
| monitoring / telemetry | dotted | open, thin | `dashed=1;dashPattern=1 3;endArrow=open;strokeWidth=1;` |
| inheritance (UML) | solid | hollow triangle | `endArrow=block;endFill=0;` |
| composition (UML) | solid | filled diamond at source | `startArrow=diamondThin;startFill=1;` |
| bidirectional | solid | filled both ends | `startArrow=block;endArrow=block;endFill=1;startFill=1;` |

Rule of thumb: solid = runtime data path, dashed = async or dependency, filled = concrete, hollow = abstract.

## Fan-out and cross-cutting concerns

- A node with 5 or more edges gets a dedicated channel: reserve a column (or row) for it at the edge of the layout and run its edges as a trunk with short taps, or introduce an explicit aggregator.
- Monitoring-scrapes-everything (Prometheus, log shippers, audit) never fans individual diagonals across the canvas. Two sanctioned patterns:
  1. **Trunk:** the monitor sits in its own bottom or side lane; one orthogonal trunk line runs along the lane, with short taps to each scraped node.
  2. **Annotation:** when monitoring coverage is total, drop the edges entirely and mark scraped nodes (a small badge or a legend note "all services export metrics to Prometheus"). Total coverage drawn edge-by-edge is noise, not information.
- Bidirectional pairs: one line with two arrowheads, not two parallel lines. When direction-per-flow genuinely matters, two parallel edges 20px apart.
- ER in v1 uses plain edges with crow's-foot arrowheads (`endArrow=ERmany;startArrow=ERone;` and variants) between entity boxes built as stacked plain vertices. The `tableRow` construct is banned pending render verification.
