# explain: turning a diagram suite into a page people can interrogate

A rendered diagram answers "what is the shape of this system". It does not answer
"what is that box and why is it there", which is the question every person in the
room actually asks. `scripts/explain.py` builds one self-contained HTML page from a
`.drawio` suite: the real SVG export, a transparent hotspot over every box, and a
panel that explains the box you clicked.

Use it when the deliverable is a walkthrough, an onboarding page, or a design
review someone will run in front of a team. Do not use it as a substitute for
getting the diagram right: it renders what is there, so a bad diagram becomes a
bad explainer.

## The loop

```bash
# 1. scaffold: one JSON per diagram, pre-seeded with every element id and its label
python3 scripts/explain.py init  docs/architecture --content docs/architecture/content \
        --components 02-components

# 2. write the prose into content/text.*.json  (this is the actual work)

# 3. build: render, calibrate, assemble
python3 scripts/explain.py build docs/architecture --content docs/architecture/content \
        --components 02-components --lang en --out docs/architecture/explain.html

# 4. check, then LOOK
python3 scripts/explain.py check docs/architecture/explain.html
node     scripts/explain_verify.js  docs/architecture/explain.html   # needs playwright
```

`init` is re-runnable: entries you already wrote are preserved, new diagram
elements appear as empty slots. Run it again after every diagram edit.

## Flags

| flag | effect |
|---|---|
| `--content DIR` | where `text.<diagram>.json` lives. Required. |
| `--components SUBDIR` | folder of component diagrams; adds a Components tab with a picker |
| `--lang en\|de` | language of the UI chrome. Content language is whatever you wrote |
| `--out FILE` | output path (default `<suite>/explain.html`) |
| `--title` | page title (default: the suite folder name) |
| `--reference FILE` | HTML fragment appended as a Reference tab (glossary, tables, FAQ) |
| `--work DIR` | scratch dir for rendered SVGs (default `<content>/.work`) |
| `--no-render` | reuse SVGs already in `--work`; fails if they are missing |
| `--min-coverage` | fraction of elements that must have text (default 0.90) |

An optional `content/labels.json` names the tabs, because a filename makes a poor
tab label and an English filename reads badly on a German page:

```json
{ "01-high-level-overview": "Überblick",
  "02-orchestration-layer-conductor": "Konduktor-Pipeline" }
```

## Writing the content

Each entry has four fields. Keep them short: this is read standing up, mid-sentence.

```json
"cx_o4": {
  "_label": "4 Triage + Router (LiteLLM)",
  "title": "Triage + Router",
  "what":  "Reads intent and sensitivity, then sets model tier, system prompt, tool allowlist.",
  "why":   "One pipeline has to be strict in different ways for three surfaces. A switch beats three systems.",
  "fact":  "Sensitive routes to the local model fail-closed: no GPU means 503, never a cloud fallback."
}
```

- `_label` is written by `init` and is the diagram's own text. Leave it alone; it
  tells you (and the next author) what the box actually says.
- German field names (`titel`, `was`, `warum`, `fakt`) are accepted too, so a
  German content file reads like German.
- `detail` is optional: a path to the component diagram that expands this box.
- Legend entries deserve text as much as components do. "What does the amber
  dashed line mean" is a question, and an unexplained legend makes the whole
  palette guesswork.

## Two traps that produce confidently wrong output

**The SVG offset differs per diagram.** drawio centres each export on its own
content bounds, so the drawio-to-SVG translation is not one constant for a repo.
A suite of twelve diagrams needed three different offsets, one of them positive
because that canvas had negative coordinates. `explain.py` derives it per file by
matching node dimensions against drawn rects, and aborts when the winning offset
is not a clear majority. If you ever find yourself hardcoding it, the hotspots
will silently sit next to their boxes instead of on them.

**Element ids are unique only within a diagram.** drawio hands out `title`,
`legend`, `legend-tx-1`... in every file, and they mean different things:
`legend-tx-1` was "Pipeline stage" on one sheet and "Export step" on another in
the same suite. Text is therefore keyed `<diagram>::<id>`. A flat merge across a
12-diagram suite silently collapsed 240 elements into 97 keys.

## Verifying it

A hotspot layer that is off by a constant still looks plausible in a screenshot,
and both traps above produce exactly that. So the check is measured, not eyeballed:
`explain_verify.js` asserts every hotspot sits within 6 px of the shape it covers.

The distinction that makes the check honest: a cell that draws a shape must match
a **shape**. Cells styled `fillColor=none;strokeColor=none` (legend labels, titles)
draw nothing and are matched against their rendered label instead. Collapsing those
two cases into one lenient rule is how a systematic offset once reported "100%
aligned" while every box was 23 px out.

`explain.py check` runs the static half (no browser): empty fields, hotspot count
against text count, and identical prose on ids that repeat across diagrams.

## What the page gives the person presenting

- Click any box for what / why / one fact.
- `n` and `p`, or the Walk button, step through the boxes in reading order. This
  is the demo path: no hunting for the next thing to say.
- `/` focuses search; matches highlight in place and the rest dims.
- Deep links: the URL carries `#diagram/element`, so "look at this box" is a link.
- Boxes that appear in more than one diagram offer a jump to the other one.
- Clickable boxes carry a faint ring by default, because nobody clicks a diagram
  they have no reason to believe is clickable.
- Light and dark, keyboard navigable, works from `file://` with no network.

## Scope

One suite, one page. Diagrams must be uncompressed `.drawio` (as this skill
requires anyway). Rendering needs the same docker image as `render.sh`; without
docker, render elsewhere and pass `--no-render`. The page has no build step and no
external requests: it is one HTML file you can mail to someone.
