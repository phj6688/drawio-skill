#!/usr/bin/env python3
"""Fixture harness for validate.py: every reproduction must fire exactly its spec.

Runs validate.py over each fixture in --fixture-mode and diffs the JSON report
against tests/expected/<name>.json. Semantics:
  bad_*  gates fire as an EXACT set (listed fire, nothing else); listed warnings
         must fire (extras allowed); regions_min counts defect regions (quadrants
         excluded) that must be present.
  good_* zero gates and zero warnings, strict.
Verdict-inversion invariant is asserted on every run: no report may contain a
done-state token, and good fixtures must carry the NOT YET VERIFIED line.

stdlib only, no pytest. Exit 1 on any mismatch.
"""
import json
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
FIX_DIR = os.path.join(HERE, "fixtures")
EXP_DIR = os.path.join(HERE, "expected")
VALIDATE = os.path.join(HERE, "..", "scripts", "validate.py")
FORBIDDEN = re.compile(r"PASS|VALID|✓|0 errors")


def run_one(name):
    fixture = os.path.join(FIX_DIR, f"{name}.drawio")
    if not os.path.exists(fixture):
        return [f"fixture file missing: {fixture}"], "", 2
    fd, tmp = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        proc = subprocess.run(
            [sys.executable, VALIDATE, fixture, "--stage", "hand",
             "--fixture-mode", "--json", tmp],
            capture_output=True, text=True)
        with open(tmp, encoding="utf-8") as f:
            report = json.load(f)
    finally:
        os.remove(tmp)
    return report, proc.stdout, proc.returncode


def defect_regions(report):
    return [r for r in report.get("regions", []) if r.get("kind") != "quadrant"]


def check(name, expected):
    report, stdout, rc = run_one(name)
    if isinstance(report, list):  # missing fixture
        return report
    problems = []
    is_good = name.startswith("good_")
    got_gates = set(report.get("gates_failed", []))
    got_warns = set(report.get("warnings", []))
    exp_gates = set(expected.get("gates", []))
    exp_warns = set(expected.get("warnings", []))

    if is_good:
        if got_gates:
            problems.append(f"good fixture fired gates {sorted(got_gates)} (false positive)")
        if got_warns:
            problems.append(f"good fixture fired warnings {sorted(got_warns)} (false positive)")
    else:
        if got_gates != exp_gates:
            problems.append(f"gates {sorted(got_gates)} != expected {sorted(exp_gates)}")
        missing_w = exp_warns - got_warns
        if missing_w:
            problems.append(f"missing expected warnings {sorted(missing_w)} (got {sorted(got_warns)})")

    rmin = expected.get("regions_min")
    if rmin is not None:
        n = len(defect_regions(report))
        if n < rmin:
            problems.append(f"defect regions {n} < regions_min {rmin}")

    want_fail = bool(exp_gates)
    if want_fail and rc != 1:
        problems.append(f"expected exit 1 on gate failure, got {rc}")
    if not want_fail and not is_good and rc != 0:
        problems.append(f"expected exit 0, got {rc}")
    if is_good and rc != 0:
        problems.append(f"good fixture expected exit 0, got {rc}")

    if FORBIDDEN.search(stdout):
        problems.append("report contains a forbidden done-state token (verdict inversion breach)")
    if is_good and "NOT YET VERIFIED" not in stdout:
        problems.append("good fixture missing the NOT YET VERIFIED verdict-inversion line")
    return problems


def main():
    names = sorted(f[:-5] for f in os.listdir(EXP_DIR) if f.endswith(".json"))
    if not names:
        print("no expected fixtures found", file=sys.stderr)
        return 1
    failures = 0
    for name in names:
        with open(os.path.join(EXP_DIR, f"{name}.json"), encoding="utf-8") as f:
            expected = json.load(f)
        problems = check(name, expected)
        if problems:
            failures += 1
            print(f"  MISMATCH {name}")
            for p in problems:
                print(f"      - {p}")
        else:
            tag = "clean" if name.startswith("good_") else "reproduced"
            print(f"  matched  {name} ({tag})")
    print("")
    print(f"{len(names)} fixtures checked, {failures} mismatched")
    if failures:
        print(f"FIXTURES RED - {failures} fixture(s) diverge from spec")
        return 1
    print("FIXTURES GREEN - validator behavior matches spec")
    return 0


if __name__ == "__main__":
    sys.exit(main())
