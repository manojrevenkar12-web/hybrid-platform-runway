#!/usr/bin/env bash
# What runs on any machine in about a minute. CI runs the rest (vcsim, Molecule, Terraform, kind...).
set -euo pipefail
cd "$(dirname "$0")/.."
PATH="$PWD/.venv/bin:$PATH"
echo "== runway"
ruff check . && ruff format --check . && mypy && pytest -q
runway drill --out reports/drill.json | python3 -c "import json,sys;print(json.load(sys.stdin)['headline'])"
echo "== console"
(cd web && npm run --silent typecheck && npm test --silent && npm run --silent build >/dev/null)
echo "all checks passed"
