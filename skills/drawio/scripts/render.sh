#!/usr/bin/env bash
# stage RENDER: export PNG (scale 1.5) + SVG via the pinned headless drawio image,
# then blank-guard the result. Usage: render.sh FILE [OUTBASE]
#
# The renderer's exit code is unreliable (#2248: prints "Export Failed" on
# success, renders blank for bad input without erroring), so success is decided
# by output-exists + size + blankguard, never by docker's return code.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() {
  echo "usage: render.sh FILE [OUTBASE]   (stage: RENDER; exits 0 rendered, 2 no-docker, 3 blank/failed)"
}
case "${1:-}" in
  -h|--help) usage; exit 0 ;;
  "") usage; exit 2 ;;
esac

FILE="$1"
if [ ! -f "$FILE" ]; then
  echo "render.sh: no such file: $FILE" >&2
  exit 2
fi
FILE="$(realpath "$FILE")"
IN_DIR="$(dirname "$FILE")"
IN_BASE="$(basename "$FILE")"

# Output paths: OUTBASE.png/.svg if given, else alongside the input.
if [ "${2:-}" != "" ]; then
  OUT_PNG="$(realpath -m "$2").png"
  OUT_SVG="$(realpath -m "$2").svg"
else
  OUT_PNG="${IN_DIR}/${IN_BASE%.*}.png"
  OUT_SVG="${IN_DIR}/${IN_BASE%.*}.svg"
fi
PNG_BASE="$(basename "$OUT_PNG")"
SVG_BASE="$(basename "$OUT_SVG")"

# Pull the pinned values; never hardcode a second copy of the numbers.
read -r IMAGE SHM TIMEOUT_S < <(python3 -c "import sys,os; sys.path.insert(0,'$SCRIPT_DIR'); import constants as c; print(c.DOCKER_IMAGE, c.DOCKER_SHM, c.RENDER_TIMEOUT_S)")

if ! command -v docker >/dev/null 2>&1; then
  echo "STRUCTURE-ONLY DEGRADATION: docker not found."
  echo "No PNG/SVG was produced, so the render+LOOK verification tier did not run."
  echo "validate.py structural gates are the ONLY signal; overlaps, clipped labels,"
  echo "and edge-through-node defects that need a rendered LOOK stay UNVERIFIED."
  echo "Install docker (image: ${IMAGE}) to render, or accept structure-only."
  if command -v npx >/dev/null 2>&1 && npx --no-install playwright --version >/dev/null 2>&1; then
    echo "note: a Playwright fallback renderer is NOT implemented in v1 (no fake fallback)."
  fi
  exit 2
fi

# One export per format; docker writes into the mounted input dir (/data).
run_export() {
  local fmt="$1" outbase="$2"
  shift 2
  # The CLI exit code is untrustworthy; the file check below is authoritative.
  timeout "$TIMEOUT_S" docker run --rm --shm-size="$SHM" -w /data -v "$IN_DIR":/data \
    "$IMAGE" -x -f "$fmt" "$@" -o "$outbase" "$IN_BASE" >/dev/null 2>&1 || true
  return 0
}

run_export png "$PNG_BASE" -s 1.5
run_export svg "$SVG_BASE"

# docker wrote into IN_DIR; move to the requested location if it differs.
if [ "${IN_DIR}/${PNG_BASE}" != "$OUT_PNG" ]; then mv -f "${IN_DIR}/${PNG_BASE}" "$OUT_PNG" 2>/dev/null || true; fi
if [ "${IN_DIR}/${SVG_BASE}" != "$OUT_SVG" ]; then mv -f "${IN_DIR}/${SVG_BASE}" "$OUT_SVG" 2>/dev/null || true; fi

if [ ! -s "$OUT_SVG" ] || [ ! -s "$OUT_PNG" ]; then
  echo "RENDER PRODUCED A BLANK OR DEGENERATE IMAGE"
  echo "  (missing or zero-byte output: PNG=$OUT_PNG SVG=$OUT_SVG; renderer hung or failed)"
  exit 3
fi

if ! python3 "$SCRIPT_DIR/blankguard.py" "$OUT_SVG" "$OUT_PNG" --source "$FILE"; then
  echo "RENDER PRODUCED A BLANK OR DEGENERATE IMAGE"
  exit 3
fi

echo "RENDERED - NOT YET LOOKED AT. Run: python3 scripts/emit_crops.py $FILE $OUT_PNG <report.json>"
exit 0
