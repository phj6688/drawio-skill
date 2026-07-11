# Legend and color

`scripts/constants.py` is authoritative for numbers and hex values.

## Palette (light background only in v1)

Use the drawio-native pairs. They look native in the editor and every fill/stroke pair already clears the contrast floor:

| role convention | fill | stroke |
|---|---|---|
| primary tier / compute | #DAE8FC | #6C8EBF |
| success / worker / green tier | #D5E8D4 | #82B366 |
| queue / decision / attention | #FFF2CC | #D6B656 |
| gateway / ingress | #FFE6CC | #D79B00 |
| data stores / danger | #F8CECC | #B85450 |
| async / special | #E1D5E7 | #9673A6 |
| neutral / external | #F5F5F5 | #666666 |

Rules:
- At most 6 semantic fills plus neutral gray per diagram. Same type = same color, everywhere. A color that does not carry meaning does not appear.
- Every fill keeps its paired stroke. No borderless boxes.
- Font color by fill brightness: Y = (299R + 587G + 114B) / 1000; Y above 150 takes near-black text, otherwise white. Every fill in the table above takes near-black.
- Container backgrounds come only from the reserved neutral tints (`none`, `#FFFFFF`, `#F5F5F5`, `#FAFAFA`). A container filled with a semantic color counts as a semantic use and owes the legend a row.
- Dashed borders mean external or planned, nothing else.
- Dark mode is out of scope in v1: do not set `background` on `mxGraphModel`, keep `labelBackgroundColor=#ffffff` on labeled edges, and do not use `light-dark()` values. A dark variant is a different deliverable, not a flag.

## Legend doctrine

Required whenever the diagram uses more than one semantic channel: more than one fill, more than one line style, more than one arrowhead meaning, or more than one shape meaning. A single-color single-line-style diagram carries no legend.

The legend is validator-enforced both ways when required: every content fill and every edge style tuple in use must have a matching legend row, and every legend row must correspond to something actually used. Phantom entries fail the gate just like missing ones.

## Construction pattern (the validator expects this shape)

- One container cell whose id contains `legend`, 220 wide, `swimlane;startSize=28;html=1;fontSize=12;fontStyle=1` titled `Legend`, neutral tint fill.
- Height = 28 + 24 per row.
- Each color row: a 30x16 swatch rectangle child carrying the exact `fillColor`/`strokeColor` it describes, at x=10, plus a `text;html=1;align=left;fontSize=11` label child at x=50, width 160.
- Each line-style row: a 40px horizontal edge sample (two invisible 1x1 anchor vertices inside the legend, or a styled edge between two points) carrying the exact `dashed/dashPattern/strokeColor/endArrow` it describes, plus the text label.
- Row pitch 24. Children use container-relative coordinates.

```xml
<mxCell id="legend" value="Legend" style="swimlane;startSize=28;html=1;fontSize=12;fontStyle=1;fillColor=#FAFAFA;strokeColor=#666666;" vertex="1" parent="1">
  <mxGeometry x="1000" y="640" width="220" height="124" as="geometry" />
</mxCell>
<mxCell id="legend-sw-1" value="" style="rounded=0;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="legend">
  <mxGeometry x="10" y="36" width="30" height="16" as="geometry" />
</mxCell>
<mxCell id="legend-tx-1" value="Edge tier (sync HTTP)" style="text;html=1;align=left;fontSize=11;" vertex="1" parent="legend">
  <mxGeometry x="50" y="34" width="160" height="20" as="geometry" />
</mxCell>
```

## Placement

Bottom-right corner of the content area by default (bottom-left when content crowds the right edge), 40px clear of all content. The legend participates in the overlap gates like any other box: a legend on top of a subtitle is the most common real-world collision, so place it after the layout is final and check the gap arithmetic, not the vibe.

## Title

18px bold text cell at top-left of the content area, full width available, placed last, checked for overlap like everything else. Subtitle (optional) 11px, below the title, width capped so it never runs under a corner legend.
