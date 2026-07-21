# Verification: the loop is the product

A .drawio file that parses is not a diagram. Every defect in the failure catalog below shipped inside valid XML, self-reported as correct by its author. The render-and-LOOK loop is the authority; the validator only makes the first render nearly right.

## Countermeasure table

Every known failure mode maps to a named countermeasure. G = validator hard gate, W = validator warning, LOOK = visual checklist item, C = compliance machinery. Fixture ids live in tests/fixtures/.

| # | failure | prevented by | caught by | fixture |
|---|---|---|---|---|
| 1 | boxes/legend overlapping content | grid formula, legend placement rule | G8 sibling overlap, G9 label collision | bad_overlap_legend |
| 2 | label clipped by own box | sizing table, arcSize rule | W10 overflow + LOOK | bad_clipped_label |
| 3 | edge through a node | rank routing, pinning | G11 (pinned, MODE-HAND), W + LOOK unpinned or engine-routed | bad_edge_through_node |
| 4 | ambiguous edge label | label offset rule | G9 when colliding, LOOK crop otherwise | bad_edge_label_ambiguity_* |
| 5 | snake/tower canvas | direction policy, aspect target | W17 aspect | bad_aspect_snake |
| 6 | density overload | mode fork, split policy | G16 >25, W >20 | bad_density |
| 7 | shipped unrendered | verify loop below | C: tier label in DONE-CHECK | (process) |
| 8 | edge label on a box | label offset + pinning | G9 | bad_label_box_collision |
| 9 | label on the line, arrowhead through text | perpendicular offset, labelBackground | G9 vs pinned polylines | bad_label_on_line |
| 10 | fan-out spaghetti | trunk/annotation policy | W13 fan-out, W12 crossings | bad_fanout_spaghetti |
| 11 | broken edge stubs | endpoint policy | G15 degenerate cells | bad_broken_stubs |
| 12 | far-floating label | offset bounds | G9 / LOOK crop | bad_far_label_* |
| 13 | dead-zone imbalance | size-to-content rule | W18 utilization, W19 quadrants | bad_deadzone |
| 14 | legend missing/incomplete | legend doctrine | G20 correspondence, G21 presence | bad_legend_incomplete, bad_legend_missing |
| 15 | self-reported success without looking | verify loop | C: DONE-CHECK with nonces | (process) |

## The loop

```
author XML
  -> [MODE-AUTO only] scripts/layout_auto.py     (engine places; fix ladder on gate failure)
  -> python3 scripts/validate.py FILE --stage hand|post-layout --json report.json
       gates failed -> fix XML, re-run (max 3 rounds; still failing = design problem, rethink layout)
       gates green  -> prints STRUCTURE OK - NOT YET VERIFIED (this is not done)
  -> scripts/render.sh FILE                      (PNG + SVG, blank guard; exit 2 = no docker, see ladder below)
  -> python3 scripts/emit_crops.py FILE PNG report.json
  -> LOOK: read every crop image, then the full PNG   (max 2 rounds of look-fix-rerender)
  -> emit the completed DONE-CHECK block
```

Round caps are hard: 3 validator rounds, 2 look rounds, 5 user-feedback rounds. Hitting a cap means stop and report honestly, not loop forever and not hand over silently.

## LOOK discipline

A full-image glance cannot detect sub-40px defects; a thumbnail-only check equals not checking. `emit_crops.py` computes the highest-risk regions from the validator report (every flagged or near-miss label, the legend, the four quadrants) and writes numbered crop images plus `looked.manifest` with a nonce per crop. Read each crop and answer its line in the skeleton. For each crop you must be able to quote label text you actually read there; if you cannot read it in the crop, that is a defect, fix it.

## DONE-CHECK (the only artifact allowed to say the work is complete)

`emit_crops.py` prints the skeleton pre-filled with gate results, counts, and nonces. You fill only the bracketed observations. Every line cites a gate or a crop id with its nonce; a line without a citation is malformed and means the check was not done. Reproduce the nonces exactly: they prove the crops existed when you reported.

```
DONE-CHECK (tier: RENDER+LOOK)
  render tier ran:      docker
  structural gates:     validate.py --stage hand: all gates green (7 pinned exact, 0 unpinned)
  edge-labels legible:  crop-1 nonce=9f3a12cd: reads "publishes to", clear of boxes
  no edge-through-node: gate 11 green; crop-2 nonce=55e0b1aa: gap between orders and kafka clean
  fan-out disciplined:  crop-3 nonce=c2418890: prometheus trunk in bottom lane, taps only
  legend complete:      gates 20/21 green; crop-legend nonce=7d99e0f4: 5 swatches match fills
  aspect / dead-zone:   aspect=1.52 util=31% quadrants=[4,5,3,4]
  residual defects:     none
```

`tier: STRUCTURE-ONLY` is a permitted terminal state only when docker is genuinely absent AND the diagram is MODE-HAND (12 nodes or fewer). It must say so out loud: the user learns no eye saw the pixels. A STRUCTURE-ONLY handover of a MODE-AUTO diagram is forbidden; split instead.

## Fallback ladder

1. Docker present, render clean: full loop, tier RENDER+LOOK.
2. Render hangs (timeout) or blank guard fails: the render is broken, not optional. Fix the XML or the invocation; a hung render never counts as passed.
3. Docker absent: try it before claiming absence (`docker run --rm <image> --version`). Genuinely absent: MODE-HAND only, tier STRUCTURE-ONLY, degradation stated in the DONE-CHECK.

## STOP table

When one of these sentences forms, stop and do the thing on the right.

| about to think | reality |
|---|---|
| "The XML is valid, so the diagram is correct." | Valid XML shipped every defect in the catalog. Render it. |
| "There is no renderer here, I'll just validate." | Prove it: run the docker probe first. The one baseline that skipped this had docker available the whole time. |
| "The thumbnail looks fine." | Sub-40px defects are invisible at thumbnail scale. Read the crops. |
| "The validator passed, that's the gate." | The validator's own success line says NOT YET VERIFIED. It means it. |
| "This diagram is too simple to need the loop." | The 4-node calibration fixture took two render rounds to get right. Simple is not immune. |
| "I'll fill the DONE-CHECK from memory." | Lines without nonces are malformed. The nonces exist so this shortcut visibly fails. |
| "The user is waiting, skip the crops this once." | The user is waiting for a diagram that is right. One crop round costs a minute; a shipped overlap costs the redo plus trust. |

## Degraded modes and editing an existing diagram

The loop stays honest when something is missing; it never fakes a step.

- **Compressed input (drawio-desktop's default save).** `validate.py`, `render.sh`,
  and `emit_crops.py` all read compressed `.drawio` bodies, so the full loop works
  on a file saved from the desktop app. (Older builds exited 2 at the LOOK stage on
  these; that is fixed.)
- **Multi-page files.** A diagram with more than 25 nodes is split across linked
  pages. Render and validate one page at a time.
- **PIL absent.** `emit_crops.py` cannot cut crop images without Pillow; it writes
  `crops.txt` with the pixel rectangles instead and says so. LOOK the full PNG at
  those rectangles.
- **Docker exit codes.** `render.sh` exits `2` when docker (or python3) is absent
  (structure-only, degradation stated) and `3` when the render is blank or
  degenerate (a real failure to fix, never "passed"). See the fallback ladder above.
- **Hostile or corrupt input.** A malformed file, a rejected DTD, or a decompression
  bomb exits `1` (a bad file), not `2` (a broken tool).
