"""Frozen constants for the drawio skill. Every value carries a provenance tag:

[HELD]       quoted from primary research (drawio docs, engine defaults, measured toolchain facts)
[DERIVED]    computed from held facts; the derivation is commented and load-bearing, do not "clean up"
[MEASURED]   calibrated on this machine by rendering a fixture and measuring pixels
[VERIFY]     assumption that smoke.sh must confirm before it may be trusted as exact
"""

# ---- MODE fork ----
MODE_HAND_MAX_NODES = 12       # [DERIVED] one 7+/-2 row plus slack; above this, delegate placement to the engine

# ---- MODE-HAND geometry (nodes <= 12) ----
NODE_W = 160                   # [DERIVED] ~20 chars at font 12 with 2*12 side padding
NODE_H_1LINE = 60              # [DERIVED]
NODE_H_2LINE = 80              # [DERIVED]
NODE_MIN_W, NODE_MIN_H = 80, 40
COL_PITCH = 200                # [DERIVED] NODE_W 160 + 2*EDGE_NODE_CLEARANCE so a vertical edge passes between columns
ROW_PITCH_BASE = 160           # [DERIVED] NODE_H_2LINE 80 + 80 gap
ROW_PITCH_LABELED = 180        # [DERIVED] +20 slack when a crossing edge carries a 2-line label
SIBLING_GAP = 40
EDGE_NODE_CLEARANCE = 20       # [DERIVED] hard-gate threshold for edge-through-node
EDGE_EDGE_SEP = 20             # parallel edge stride
CANVAS_MARGIN = 40
GRID_SNAP = 10                 # [HELD] drawio default gridSize
LABEL_PERP_OFFSET = 12         # [DERIVED] label sits off the line, inside the band
STUB_BEFORE_ARROW = 20         # [HELD] Agents365/wuxudongxd field rule
LABEL_BAND_H = 44              # [DERIVED] 2 lines * 11 * 1.25 + 16 pad

# ---- Text metrics ----
FONT_TITLE, FONT_CONTAINER, FONT_NODE = 18, 13, 12
FONT_SUB, FONT_EDGE, FONT_LEGEND = 10, 11, 11
LINE_HEIGHT = 1.25             # [HELD] drawio default lineHeight, exact, safe to gate on
TEXT_PAD_X, TEXT_PAD_Y = 12, 8

# Character width model. Flat constants are the uncalibrated fallback; the class
# table is the calibrated model measured on this box (see calibration in tests/).
CHAR_W_WARN = 0.60             # [HELD] own-box overflow warning, uncalibrated fallback
CHAR_W_GATE = 0.70             # [DERIVED] collision gate inflation: above uppercase mean advance, fails toward whitespace
CHAR_W_SLACK_CHARS = 1         # extra char added before the gate compare
# [MEASURED] rendered on rlespinasse/drawio-desktop-headless 2026-07-10, scale confirmed 1.00 px/unit:
# mixed labels 0.436..0.477 * fontSize, M-run 0.815, i-run 0.208, bold = regular * 1.065.
CHAR_CLASS_WIDE = 0.72         # [MEASURED->DERIVED] A-Z 0-9 @ # % _ and similar
CHAR_CLASS_XWIDE = 0.85        # [MEASURED] m w M W
CHAR_CLASS_NARROW = 0.28       # [MEASURED] i l j t f r . , : ; ' " | ( ) [ ] space
CHAR_CLASS_BODY = 0.46         # [MEASURED] remaining lowercase
BOLD_FACTOR = 1.065            # [MEASURED]

# ---- ELK spacing for MODE-AUTO (mirrors the hand gaps) ----
ELK_NODE_NODE = 40
ELK_EDGE_NODE = 20
ELK_LAYER_SPACING = 90
# fix-ladder bump values when post-layout gates fail:
ELK_BUMP_NODE_NODE = 60
ELK_BUMP_EDGE_NODE = 30
ELK_BUMP_LAYER = 120
ENGINE_MAX_INVOCATIONS = 3     # then the C4-split terminal rung fires

# ---- Thresholds ----
DENSITY_GATE = 25              # hard: split the diagram
DENSITY_WARN = 20
ASPECT_WARN_HI, ASPECT_WARN_LO = 3.0, 0.4
UTIL_WARN_LO = 0.10            # area utilization below this = dead-zone warning
FANOUT_LANE_AT = 5             # >=5 edges on one node: dedicated lane/trunk required
EDGES_PER_SIDE_WARN = 3
LUMINANCE_DARK_TEXT = 150      # Y > 150 -> dark text, else white  (Y = (299R+587G+114B)/1000)
MAX_SEMANTIC_FILLS = 6

def crossing_warn_threshold(edge_count: int) -> int:
    return max(2, edge_count // 4)

# ---- Legend ----
LEGEND_ID_TOKEN = "legend"     # any cell whose id contains this is legend furniture
LEGEND_W = 220
LEGEND_TITLE_H = 28
LEGEND_ROW_H = 24
LEGEND_SWATCH_W, LEGEND_SWATCH_H = 30, 16
LEGEND_CLEARANCE = 40
# Reserved NEUTRAL container tints. A container filled with any of these is furniture,
# not a semantic color, and is excluded from legend correspondence. A container using
# a palette fill is semantic and demands a legend row. (Red-team SB4 ruling.)
CONTAINER_TINT_FILLS = {"none", "#ffffff", "#f5f5f5", "#fafafa", "#fbf7ee"}

# ---- Palette: drawio-native pairs (fill, stroke), contrast-safe by construction [HELD] ----
PALETTE = {
    "blue":   ("#DAE8FC", "#6C8EBF"),
    "green":  ("#D5E8D4", "#82B366"),
    "yellow": ("#FFF2CC", "#D6B656"),
    "orange": ("#FFE6CC", "#D79B00"),
    "red":    ("#F8CECC", "#B85450"),
    "purple": ("#E1D5E7", "#9673A6"),
    "gray":   ("#F5F5F5", "#666666"),
}

# ---- Loop caps ----
VALIDATOR_FIX_ROUNDS = 3
VISION_ROUNDS = 2
USER_LOOP_ROUNDS = 5
MAX_CROPS = 12

# ---- Render / blank guard ----
DOCKER_IMAGE = "rlespinasse/drawio-desktop-headless:v1.62.0"  # [HELD] pin the version, arg parsing regresses across releases (registry tags carry the 'v' prefix; bare '1.62.0' is manifest-unknown)
DOCKER_SHM = "1g"              # [MEASURED] renderer crashes on this box without it
RENDER_TIMEOUT_S = 120         # [HELD] CLI export hangs are a real bug; kill and report
PNG_MIN_BYTES = 2048           # [VERIFY]
PIXEL_STDEV_MIN = 5
DISTINCT_COLORS_MIN = 3
SVG_ELEM_RATIO = 0.8           # rendered drawables >= (edges + vertices * 0.8)  [DERIVED]
