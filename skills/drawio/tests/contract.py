#!/usr/bin/env python3
"""Exit-code contract test (docker-free). Freezes the public exit-code API of the
CLIs and asserts every observed code is documented in the README consumer contract.

The docker-present codes (render 0 rendered / 3 blank, layout_auto 0 laid-out / 4
split) are exercised by smoke.sh against the real image, not here. stdlib only,
no pytest. Exit 1 on any mismatch.
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
SCR = os.path.join(HERE, "..", "scripts")
FIX = os.path.join(HERE, "fixtures")


def run(args, env=None):
    return subprocess.run(args, capture_output=True, text=True, env=env).returncode


def path_without(binary, needed):
    """A PATH pointing at a fresh bin with `needed` tools symlinked but not `binary`."""
    d = tempfile.mkdtemp()
    for t in needed:
        src = shutil.which(t)
        if src and t != binary:
            os.symlink(src, os.path.join(d, t))
    env = dict(os.environ)
    env["PATH"] = d
    return env, d


def main():
    py = sys.executable
    validate = os.path.join(SCR, "validate.py")
    render = os.path.join(SCR, "render.sh")
    layout = os.path.join(SCR, "layout_auto.py")
    emit = os.path.join(SCR, "emit_crops.py")
    blank = os.path.join(SCR, "blankguard.py")

    fd, dtd = tempfile.mkstemp(suffix=".drawio"); os.close(fd)
    open(dtd, "w").write('<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><mxfile/>')
    fd, badsvg = tempfile.mkstemp(suffix=".svg"); os.close(fd)
    open(badsvg, "w").write("<svg xmlns='http://www.w3.org/2000/svg'></svg>")

    # render.sh needs these; give it everything but docker to prove the no-docker exit 2.
    nodocker_env, nodocker_bin = path_without("docker", [
        "bash", "env", "python3", "python3.10", "realpath", "dirname",
        "basename", "mv", "timeout", "cat", "rm", "mktemp", "grep", "sed"])

    # (label, argv, env, expected code)
    cases = [
        ("validate clean", [py, validate, os.path.join(FIX, "good_baseline.drawio"),
                            "--stage", "hand", "--fixture-mode"], None, 0),
        ("validate gating", [py, validate, os.path.join(FIX, "bad_legend_missing.drawio"),
                            "--stage", "hand", "--fixture-mode"], None, 1),
        ("validate missing file", [py, validate, "/no/such.drawio"], None, 2),
        ("validate hostile DTD", [py, validate, dtd], None, 1),
        ("render usage", ["bash", render], None, 2),
        ("render missing file", ["bash", render, "/no/such.drawio"], None, 2),
        ("render no-docker", ["bash", render, os.path.join(FIX, "good_baseline.drawio")],
         nodocker_env, 2),
        ("layout missing file", [py, layout, "/no/such.drawio"], None, 2),
        ("emit missing inputs", [py, emit, "/no/a.drawio", "/no/a.png", "/no/r.json"], None, 2),
        ("blankguard bad svg", [py, blank, badsvg], None, 1),
    ]

    observed = set()
    failures = 0
    for label, argv, env, want in cases:
        got = run(argv, env)
        observed.add(want)
        mark = "ok" if got == want else "MISMATCH"
        if got != want:
            failures += 1
        print(f"  [{mark}] {label}: exit {got} (want {want})")

    readme = open(os.path.join(ROOT, "README.md"), encoding="utf-8").read()
    for code in sorted(observed):
        if not re.search(rf"\b{code}\b", readme):
            print(f"  [MISMATCH] exit code {code} not documented in README")
            failures += 1

    os.remove(dtd); os.remove(badsvg); shutil.rmtree(nodocker_bin, ignore_errors=True)
    print("")
    if failures:
        print(f"CONTRACT RED - {failures} exit-code mismatch(es)")
        return 1
    print("CONTRACT GREEN - exit codes match the documented contract")
    return 0


if __name__ == "__main__":
    sys.exit(main())
