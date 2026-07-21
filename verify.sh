#!/usr/bin/env bash
# Repo verify gate. Default tier is hermetic (no docker); --full adds the docker
# smoke tier. Exits non-zero on the first failure, naming the step. Mirrors CI.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FULL=0
[ "${1:-}" = "--full" ] && FULL=1
fail() { echo "verify: FAILED at: $1" >&2; exit 1; }

echo "[1] py_compile"
python3 -m py_compile "$ROOT"/skills/drawio/scripts/*.py \
  "$ROOT"/skills/drawio/tests/run_fixtures.py || fail "py_compile"

echo "[2] fixture suite"
python3 "$ROOT/skills/drawio/tests/run_fixtures.py" >/dev/null || fail "run_fixtures"

echo "[3] JSON manifests"
python3 - "$ROOT" <<'PY' || fail "manifests"
import json, os, subprocess, sys
root = sys.argv[1]
files = subprocess.run(["git", "-C", root, "ls-files", "*.json"],
                       capture_output=True, text=True).stdout.split()
for f in files:
    try:
        json.load(open(os.path.join(root, f), encoding="utf-8"))
    except Exception as e:
        print(f"invalid JSON {f}: {e}", file=sys.stderr); sys.exit(1)
manifest = os.path.join(root, ".claude-plugin/plugin.json")
data = json.load(open(manifest, encoding="utf-8"))
for k in ("name", "version", "skills"):
    if not data.get(k):
        print(f"manifest missing '{k}'", file=sys.stderr); sys.exit(1)
PY

echo "[4] ruff"
if command -v ruff >/dev/null 2>&1; then
  (cd "$ROOT" && ruff check .) || fail "ruff"
else
  echo "  ruff absent, skipped"
fi

echo "[5] shellcheck"
if command -v shellcheck >/dev/null 2>&1; then
  mapfile -t sh < <(git -C "$ROOT" ls-files '*.sh')
  if [ ${#sh[@]} -gt 0 ]; then (cd "$ROOT" && shellcheck "${sh[@]}") || fail "shellcheck"; fi
else
  echo "  shellcheck absent, skipped"
fi

if [ "$FULL" = "1" ]; then
  echo "[full] smoke.sh (docker tier)"
  bash "$ROOT/skills/drawio/smoke.sh" || fail "smoke.sh"
  echo "[full] working tree after smoke (expect at most calibration.json):"
  git -C "$ROOT" status --porcelain
fi

echo "verify: OK"
