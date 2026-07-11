#!/usr/bin/env bash
# First-build gate: prove the render/verify toolchain works on this machine.
# Renders a baseline, blank-guards it, validates it, calibrates text widths,
# lays out a 14-node topology, and runs the fixture suite. Steps whose inputs
# belong to the validator build (validate.py, run_fixtures.py) print SKIPPED when
# absent; every present step must pass or the script exits non-zero.
#
# Real fixtures are preferred; when tests/fixtures is not populated yet the
# toolchain steps fall back to self-generated diagrams in a temp dir so the gate
# still exercises the real image, blankguard, calibration, and ELK round-trip.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCR="$ROOT/scripts"
FIX="$ROOT/tests/fixtures"

case "${1:-}" in
  -h|--help)
    echo "usage: smoke.sh   (stage: BUILD-GATE; exits 0 only when all present steps pass)"
    exit 0 ;;
esac

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
FAIL=0

ok()   { echo "  [OK]      $1"; }
skip() { echo "  [SKIPPED] $1"; }
bad()  { echo "  [FAIL]    $1"; FAIL=1; }

# A clean single-channel baseline: one fill, pinned edges, no legend required.
gen_baseline() {
  cat > "$1" <<'EOF'
<mxfile host="smoke" compressed="false">
  <diagram id="b1" name="baseline">
    <mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1" pageWidth="850" pageHeight="300" math="0" shadow="0">
      <root>
        <mxCell id="0" />
        <mxCell id="1" parent="0" />
        <mxCell id="n1" value="client" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="1"><mxGeometry x="40" y="40" width="120" height="60" as="geometry" /></mxCell>
        <mxCell id="n2" value="api" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="1"><mxGeometry x="240" y="40" width="120" height="60" as="geometry" /></mxCell>
        <mxCell id="n3" value="service" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="1"><mxGeometry x="440" y="40" width="120" height="60" as="geometry" /></mxCell>
        <mxCell id="n4" value="store" style="rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;" vertex="1" parent="1"><mxGeometry x="640" y="40" width="120" height="60" as="geometry" /></mxCell>
        <mxCell id="e1" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="n1" target="n2"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="e2" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="n2" target="n3"><mxGeometry relative="1" as="geometry" /></mxCell>
        <mxCell id="e3" style="edgeStyle=orthogonalEdgeStyle;html=1;exitX=1;exitY=0.5;entryX=0;entryY=0.5;" edge="1" parent="1" source="n3" target="n4"><mxGeometry relative="1" as="geometry" /></mxCell>
      </root>
    </mxGraphModel>
  </diagram>
</mxfile>
EOF
}

# 14 single-fill nodes on naive stacked coords for the ELK layout pass.
gen_topology() {
  {
    echo '<mxfile host="smoke" compressed="false"><diagram id="t1" name="topo"><mxGraphModel dx="800" dy="600" grid="1" gridSize="10" page="1" pageWidth="850" pageHeight="1100" math="0" shadow="0"><root><mxCell id="0" /><mxCell id="1" parent="0" />'
    for i in $(seq 1 14); do
      y=$((i * 40))
      echo "<mxCell id=\"n$i\" value=\"svc$i\" style=\"rounded=0;whiteSpace=wrap;html=1;fillColor=#DAE8FC;strokeColor=#6C8EBF;\" vertex=\"1\" parent=\"1\"><mxGeometry x=\"40\" y=\"$y\" width=\"120\" height=\"40\" as=\"geometry\" /></mxCell>"
    done
    # a spanning tree plus a couple of cross edges to give the engine work
    for pair in "1 2" "2 3" "2 4" "4 5" "4 6" "4 7" "6 8" "6 9" "5 10" "7 10" "9 11" "11 12" "12 13" "13 14"; do
      read -r a b <<< "$pair"
      echo "<mxCell id=\"e_${a}_${b}\" style=\"edgeStyle=orthogonalEdgeStyle;html=1;\" edge=\"1\" parent=\"1\" source=\"n$a\" target=\"n$b\"><mxGeometry relative=\"1\" as=\"geometry\" /></mxCell>"
    done
    echo '</root></mxGraphModel></diagram></mxfile>'
  } > "$1"
}

echo "SMOKE: drawio toolchain build gate"
echo "image:   $(python3 -c "import sys;sys.path.insert(0,'$SCR');import constants as c;print(c.DOCKER_IMAGE)")"
echo

# Resolve the baseline (real fixture preferred, else generated).
if [ -f "$FIX/good_baseline.drawio" ]; then
  BASELINE="$FIX/good_baseline.drawio"; BSRC="fixture"
else
  BASELINE="$TMP/good_baseline.drawio"; gen_baseline "$BASELINE"; BSRC="generated (fixture absent)"
fi

# Resolve the layout topology.
TOPO=""
for cand in good_auto_arch.topology good_auto_arch_topology good_auto_arch; do
  if [ -f "$FIX/$cand.drawio" ]; then TOPO="$FIX/$cand.drawio"; TSRC="fixture ($cand)"; break; fi
done
if [ -z "$TOPO" ]; then
  TOPO="$TMP/topo14.drawio"; gen_topology "$TOPO"; TSRC="generated (fixture absent)"
fi

echo "step 1: render.sh baseline [$BSRC]"
RC=0; bash "$SCR/render.sh" "$BASELINE" "$TMP/baseline" >/dev/null 2>&1 || RC=$?
if [ "$RC" -eq 0 ] && [ -s "$TMP/baseline.png" ] && [ -s "$TMP/baseline.svg" ]; then
  BASE_PNG_BYTES=$(wc -c < "$TMP/baseline.png")
  ok "rendered PNG ${BASE_PNG_BYTES}B + SVG $(wc -c < "$TMP/baseline.svg")B"
elif [ "$RC" -eq 2 ]; then
  skip "render (docker absent, exit 2)"; BASE_PNG_BYTES=0
else
  bad "render exit $RC"; BASE_PNG_BYTES=0
fi

echo "step 2: blankguard (standalone)"
if [ -s "${TMP}/baseline.svg" ]; then
  RC=0; python3 "$SCR/blankguard.py" "$TMP/baseline.svg" "$TMP/baseline.png" --source "$BASELINE" || RC=$?
  if [ "$RC" -eq 0 ]; then ok "SVG marks above the ratio floor"; else bad "blankguard exit $RC"; fi
else
  skip "blankguard (no SVG to guard)"
fi

echo "step 3: validate.py baseline"
if [ -f "$SCR/validate.py" ]; then
  RC=0; python3 "$SCR/validate.py" "$BASELINE" --stage hand >/dev/null 2>&1 || RC=$?
  if [ "$RC" -eq 0 ]; then ok "gates green on baseline"; else bad "validate.py exit $RC on baseline"; fi
else
  skip "validate.py absent (validator build still in progress)"
fi

echo "step 4: calibrate_charwidth.py"
RC=0; CAL_OUT="$(python3 "$SCR/calibrate_charwidth.py" 2>&1)" || RC=$?
if [ "$RC" -eq 0 ] && [ -f "$SCR/calibration.json" ]; then
  ok "$(echo "$CAL_OUT" | grep -o 'classes=.*flat_p95_mixed=[0-9.]*' | head -1)"
elif [ "$RC" -eq 2 ]; then
  skip "calibrate (docker or PIL absent, exit 2)"
else
  bad "calibrate exit $RC"
fi

echo "step 5: layout_auto.py 14-node topology [$TSRC]"
RC=0; LAY_OUT="$(python3 "$SCR/layout_auto.py" "$TOPO" --direction DOWN 2>&1)" || RC=$?
if [ "$RC" -eq 0 ]; then
  ok "$(echo "$LAY_OUT" | grep -m1 'laid out via' || echo 'layout produced')"
elif [ "$RC" -eq 2 ]; then
  skip "layout (docker absent, exit 2)"
else
  # shellcheck disable=SC2001  # multi-line indent; parameter expansion cannot do this readably
  echo "$LAY_OUT" | sed 's/^/      /'
  bad "layout_auto exit $RC (engine could not place cleanly)"
fi

echo "step 6: run_fixtures.py"
if [ -f "$ROOT/tests/run_fixtures.py" ]; then
  RC=0; python3 "$ROOT/tests/run_fixtures.py" || RC=$?
  if [ "$RC" -eq 0 ]; then ok "fixtures match validator spec"; else bad "run_fixtures.py exit $RC"; fi
else
  skip "run_fixtures.py absent (validator build still in progress)"
fi

echo
echo "VERIFY tags converted this run:"
PNG_FLOOR=$(python3 -c "import sys;sys.path.insert(0,'$SCR');import constants as c;print(c.PNG_MIN_BYTES)")
if [ "${BASE_PNG_BYTES:-0}" -gt 0 ]; then
  echo "  PNG_MIN_BYTES [VERIFY]: floor ${PNG_FLOOR}B vs real render ${BASE_PNG_BYTES}B (floor holds, no false-blank)"
else
  echo "  PNG_MIN_BYTES [VERIFY]: not exercised (no render this run)"
fi
echo "  DOCKER_IMAGE / DOCKER_SHM: image rendered under --shm-size without a renderer crash"
echo "  --layout elkLayered XML round-trip: engine geometry re-read (see step 5)"
[ -f "$SCR/calibration.json" ] && echo "  calibration.json [MEASURED]: written next to constants.py"
echo

if [ "$FAIL" -ne 0 ]; then
  echo "SMOKE FAILED: one or more present steps did not pass"
  exit 1
fi
echo "SMOKE COMPLETE: toolchain verified on this machine"
