# Layout: one grid, two modes

`scripts/constants.py` is authoritative for all numbers. Count content nodes first (boxes that carry meaning; title and legend do not count). The count picks the mode.

## Mode fork

- **12 nodes or fewer: MODE-HAND.** You place every box with the grid formula below. All geometry gates apply to your file directly.
- **More than 12 nodes: MODE-AUTO.** Do not hand-place. Emit topology (nodes in a simple stacked column, edges by id, styles and labels final, no legend or title yet) and run `scripts/layout_auto.py`, which delegates placement to the drawio layout engine and re-validates the result. Legend and title come after the engine pass, placed from the engine's coordinates; the script defers legend gates to that step and tells you so. Never hand-edit engine-produced coordinates; if geometry gates fail, the script walks its fix ladder and its terminal rung tells you to split the diagram. Direction: `--direction DOWN` by default, `RIGHT` when the dependency chain runs deeper than about 6 ranks (a deep chain laid DOWN becomes a tower).
- **More than 25 nodes: split before authoring.** One diagram, one message. Split by abstraction level (system overview page linking to per-subsystem pages), not by cutting arbitrary boxes.
- No docker available means MODE-AUTO does not exist: reduce or split to 12 nodes or fewer per page. Hand-placing 20 boxes without the render loop is how bad diagrams get shipped.

## MODE-HAND recipe

1. **Assign ranks.** Sources (nothing points at them) get rank 0. Every other node: 1 + the maximum rank of its predecessors. For a top-to-bottom flow, rank = row.
2. **Break cycles.** If an edge points back up, keep it but mark it: it will be the exception to flow direction and needs a visible route around the content (side channel), not through it.
3. **Order within each rank** to minimize crossings: place each node roughly under the average position of the nodes it connects to in the row above. Two same-rank nodes that both feed the same target sit adjacent.
4. **Coordinates by formula, never by feel:**

```
x = 40 + column * 200        (column 0, 1, 2, ... within the rank, centered rows: offset by half-pitches)
y = 40 + rank * 160          (use 180 for a gap that carries a two-line edge label)
```

Standard box: 160x60 (one line of text), 160x80 (two lines). Same node type = same size, always; size the group by its longest label (about 20 characters per line at font 12), then apply that size to every node of the type. Never below 80x40.

5. **Snap everything to 10.** Off-grid coordinates are the visible signature of a careless diagram.
6. **Center parents over children:** parent x = the mean of child x values, rounded to 20.
7. **Reserve the gaps.** The 80px between rows exists for edge labels and clearances. Nothing else goes there: no floating notes, no legend.

## Direction policy

- Flowcharts and pipelines: top to bottom.
- Architecture: top to bottom (clients and external actors in the top row, services in the middle bands, data stores in the bottom row). Left to right only when the flow has many shallow stages and TB would produce a tower.
- Network: top to bottom by tier (internet, edge, core, access).
- ER: no global direction; cluster related entities, minimize crossings.
- At least 90 percent of edges follow the primary direction. The exceptions are the marked back-edges from step 2.
- External systems sit at the canvas edge with a dashed border (dashed border means external or planned; it is a different signal from a dashed edge, which means async).

## Containers

- Use a container only when the boundary itself means something (trust zone, deployment unit, subsystem). Informal grouping is done with whitespace.
- Inner padding 20px on all sides between the container border and its children. Title bar 30px (`swimlane;startSize=30`). Maximum nesting depth 3.
- Container fills come from the reserved neutral tints (see references/legend-color.md). A container painted with a semantic palette color owes the legend a row.

## Canvas discipline

- 40px margin around the content bounding box. Size the page to the content; never park content in a corner of a huge canvas.
- Aspect ratio of the content box should land between 1.3 and 1.8 (relative to whichever side is longer). A 1400x3000 tower or a 5000x400 snake means the direction choice or the rank packing is wrong: rebalance columns or switch direction.
- Title: 18px bold, top-left, stating type and scope ("Container diagram: payments platform"). The title states the conclusion when the diagram argues one.

## MODE-AUTO notes

`layout_auto.py` passes the same spacing regime to the engine (node gap 40, edge clearance 20, layer gap 90), so engine output lands in the same visual register as hand output. What you lose in MODE-AUTO: the reserved label bands, and hard gating on edge paths. The engine re-routes edges and the renderer's final routing is not reproducible from the written waypoints, so edge-path defects (through-node, label-on-line) surface as warnings plus LOOK crops after layout instead of blocking gates before it. Node overlap, density, and legend checks still gate on engine output, since node geometry is exact. That trade is stated, not hidden: in MODE-AUTO the crops are not optional reading.
