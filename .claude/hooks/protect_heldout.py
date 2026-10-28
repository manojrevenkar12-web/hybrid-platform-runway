#!/usr/bin/env python3
"""Block edits to blind held-out sets and their pinned first runs (AGENTS.md, held-out rule)."""

import json
import re
import sys

path = str(json.load(sys.stdin).get("tool_input", {}).get("file_path", ""))
if re.search(r"heldout/[^/]+/(vms|scenarios)\.yaml$|reports/heldout/[^/]+/first_run\.json$", path):
    print(
        "Held-out sets and first runs are not edited. Mark the set 'regression' and write a new one from heldout/WRITING_CASES.md.",
        file=sys.stderr,
    )
    sys.exit(2)
