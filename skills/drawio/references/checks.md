# Check registry

The `report.json` from `validate.py` carries `gates_failed` and `warnings` as
arrays of these check numbers (plus `gate_details`/`warning_details` with the
message text). This table decodes them. Severity: **G** hard gate (blocks),
**W** warning (routes to LOOK), **M** meta (informational). "Geo" means the
check runs only in a geometry stage (`hand` / `post-layout`), not `pre-layout`.

| # | severity | stage | what it checks |
|---|---|---|---|
| 1 | G | all | well-formed XML with an `mxfile`/`mxGraphModel` root (also fires on unreadable/oversize/DTD input) |
| 2 | G | all | mandatory root cells `0`/`1` present; cell ids unique (duplicates detected at parse time) |
| 3 | G | all | every cell's `parent` resolves |
| 4 | G | all | every edge has `source` and `target` wired to real cell ids |
| 5 | G | all | vertex/edge exclusivity, numeric geometry with `as="geometry"`, non-rect shapes carry a perimeter |
| 6 | W | geo | coordinates on the 10px grid |
| 7 | W | geo | no negative coordinates; content within the page bounds |
| 8 | G | geo | sibling boxes do not overlap |
| 9 | G (hand) / W (post-layout) | geo | labels do not collide with boxes or sit on pinned edges |
| 10 | W | geo | a label does not overflow its own box (wrap and non-wrap use one width model) |
| 11 | G (pinned, hand) / W (approx or engine-routed) | geo | an edge does not pass through a box it does not connect |
| 12 | W | geo | edge crossings under the count threshold |
| 13 | W | geo | a node fanning 5+ edges over >180deg needs a shared trunk |
| 14 | W | geo | no more than the allowed edges pinned to one box side |
| 15 | G | geo | no zero-length edges, stacked-identical boxes, or cells orphaned from id=0 |
| 16 | G (>25) / W (>20) | geo | content-node density under the split threshold |
| 17 | W | geo | content aspect ratio within `[0.4, 3.0]` |
| 18 | W | geo | area utilization above the dead-zone floor |
| 19 | W | geo | no empty quadrant next to a crowded one |
| 20 | G | all | legend swatches / line samples match the content fills and edge styles (both directions) |
| 21 | G | all | a legend is present when more than one semantic channel is in play |
| 22 | W | geo | text/fill luminance contrast (drawio default colors assumed when unset) |
| 24 | W | geo | no disconnected (degree-0) content node |
| 25 | G | all | every content edge style has a matching legend line sample (phantom samples gate too) |

Note: number 23 is reserved for META lines (e.g. unpinned labeled edges, the
same-side-pin disclosure) rather than a gate or warning. Numbers 9 and 11 change
severity by stage/pinnedness, which is why `report.json` also carries the
message text in `gate_details`/`warning_details`.
