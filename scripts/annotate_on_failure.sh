#!/usr/bin/env bash
# Run a command; if it fails, show the end of its output as one annotation on the run, because
# annotations are what a reviewer sees first. Usage: annotate_on_failure.sh "title" cmd args...
set -uo pipefail
title="$1"; shift
out="$(mktemp)"
"$@" 2>&1 | tee "$out"
code=${PIPESTATUS[0]}
if [ "$code" -ne 0 ]; then
  python3 - "$title" "$out" <<'PY'
import sys
title, path = sys.argv[1], sys.argv[2]
import re
everything = open(path, errors="replace").read().splitlines()
def emit(t, lines):
    msg = "\n".join(lines).replace("%", "%25").replace("\r", "").replace("\n", "%0A")
    print(f"::error title={t}::{msg}")
errors = [l for l in everything if re.search(r"fatal:|FAILED!|Error:|error:|ERROR", l)]
if errors:
    emit(title + " (errors)", errors[:30])
emit(title, everything[-60:])
PY
fi
exit "$code"
