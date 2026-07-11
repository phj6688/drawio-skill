# drawio XML: the format rules that break files when ignored

Authoritative sources: drawio.com diagram-generation reference, jgraph/drawio-mcp shared references, mxGraph docs. `scripts/constants.py` is authoritative for every number.

## Skeleton (always write uncompressed)

```xml
<mxfile host="app.diagrams.net" type="device" compressed="false">
  <diagram id="page-1" name="Page-1">
    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1"
                  pageWidth="850" pageHeight="1100" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <!-- content cells go here, parent="1" -->
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
```

Both root cells are mandatory: `id="0"` has no parent, `id="1"` is the default layer with `parent="0"`. Every content cell's parent chain must end at 0. Multi-page files repeat the `diagram` element, each page with its own root pair. Never hand-write the compressed form (base64 deflate); one wrong byte makes the file unopenable.

## Vertex

```xml
<mxCell id="auth-service" value="auth-service&#xa;(FastAPI)"
        style="rounded=1;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;"
        vertex="1" parent="1">
  <mxGeometry x="240" y="200" width="160" height="60" as="geometry" />
</mxCell>
```

- Geometry needs numeric `x y width height` and `as="geometry"`. Coordinates are absolute pixels, origin top-left, y grows downward.
- Never put `relative="1"` on a vertex: coordinates get reinterpreted as 0..1 fractions and the shape collapses into a corner.
- Use descriptive ids (`auth-service`, not `cell-47`). Ids must be unique. `join` is reserved, do not use it as an id.

## Edge

```xml
<mxCell id="e-gw-auth" value="REST" style="edgeStyle=orthogonalEdgeStyle;rounded=1;html=1;endArrow=block;endFill=1;exitX=0.5;exitY=1;entryX=0.5;entryY=0;labelBackgroundColor=#ffffff;"
        edge="1" parent="1" source="api-gateway" target="auth-service">
  <mxGeometry x="0" y="12" relative="1" as="geometry">
    <mxPoint as="offset" />
  </mxGeometry>
</mxCell>
```

- `source` and `target` are cell ids of existing vertices, always. Floating `mxPoint` endpoints detach when anything moves and fail validation.
- Edge geometry is `<mxGeometry relative="1" as="geometry"/>`, no width/height.
- Edge label position: geometry `x` runs along the edge in [-1, 1] (0 = midpoint), `y` is the perpendicular offset in pixels. See references/edges.md for the placement rule.
- Waypoints when needed: `<Array as="points"><mxPoint x="480" y="300"/></Array>` inside the geometry, absolute coordinates.

## Style strings

`key=value;` pairs. A bare token first selects the base shape (`ellipse;`, `rhombus;`, `text;`, `swimlane;`, `group;`). Unknown keys are silently ignored, so a typo like `filColor` produces no error and no color: copy keys from here or from the templates, never from memory.

Non-rectangular shapes must carry their perimeter or edges attach to the bounding box instead of the outline:

| shape | style |
|---|---|
| decision | `rhombus;whiteSpace=wrap;html=1;perimeter=rhombusPerimeter;` |
| database | `shape=cylinder3;whiteSpace=wrap;html=1;boundedLbl=1;backgroundOutline=1;` |
| hexagon | `shape=hexagon;whiteSpace=wrap;html=1;perimeter=hexagonPerimeter2;` |
| parallelogram (I/O) | `shape=parallelogram;whiteSpace=wrap;html=1;perimeter=parallelogramPerimeter;` |
| actor | `shape=actor;whiteSpace=wrap;html=1;` |
| cloud | `ellipse;shape=cloud;whiteSpace=wrap;html=1;` |
| plain text | `text;html=1;strokeColor=none;fillColor=none;align=left;` |
| titled container | `swimlane;startSize=30;html=1;` |

Stick to these primitives. `shape=mxgraph.*` stencil names silently render as blank boxes when guessed wrong; they are out of scope for v1.

## Labels

- Escape XML entities in `value`: `&amp; &lt; &gt; &quot;`. A raw `&` makes the whole file unparseable.
- Line breaks: `&#xa;`, or `&lt;br&gt;` with `html=1`. Never a literal `\n`.
- Do not combine `whiteSpace=wrap` with `&#xa;` in the same label; the text collapses to one line. Pick one: manual breaks or wrapping.
- `arcSize` is a percentage of the smaller box dimension, not pixels. For uniform corner radii use `absoluteArcSize=1;arcSize=8;`.

## Containers and layers

- Children of a container use coordinates relative to the container's top-left corner, not the canvas. A child with canvas-absolute coordinates renders far outside its parent. When `parent` is anything other than `"1"`, coordinates are small and parent-relative.
- Leave `startSize` clearance below a swimlane title bar before placing children.
- Cross-container edges use `parent="1"`.
- Never emit `collapsed="1"`; children become invisible and the diagram looks empty.
- Z-order is document order: later cells paint on top. Emit containers first, then vertices, then edges, then the title and legend last.

## The killer table

| mistake | effect |
|---|---|
| unescaped `& < >` in value | file will not open |
| duplicate id | cell silently dropped, edges mis-wire |
| dangling parent/source/target | orphaned or vanishing cells |
| missing id 0 or 1 cell | broken page |
| missing `as="geometry"` | geometry ignored, shape lands at 0,0 |
| `relative="1"` on a vertex | shape collapses to a corner |
| edge geometry without `relative="1"` | label and route misplaced |
| container child with absolute coords | child renders outside the container |
| literal `\n` in a label | printed as text |
| style key typo | silently ignored |
| missing perimeter on non-rect shape | edges hit the bounding box |
| XML comments | some importers reject the file; emit none |

A file can pass every rule here and still be a bad diagram. Structure is checked by `scripts/validate.py`; quality is proven only by rendering and looking (references/verify.md).
