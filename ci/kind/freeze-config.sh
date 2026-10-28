#!/usr/bin/env bash
# A copy of config/ with a launch campaign that freezes the kind cluster right now, for the e2e test.
set -euo pipefail
dst="$1"
cp -r config/. "$dst/"
t0=$(date -u -d "+3 days" +%Y-%m-%dT%H:%M:%S+00:00)
cat > "$dst/launch-calendar.yaml" <<YAML
campaigns:
  - {name: ci-flight, t0: "$t0", sites: [kind], freeze_before_days: 7, freeze_after_days: 1}
YAML
cat > "$dst/gitops.yaml" <<YAML
site_clusters:
  kind: [in-cluster]
YAML
