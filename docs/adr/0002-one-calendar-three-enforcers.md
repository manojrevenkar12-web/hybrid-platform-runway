# 0002: One launch calendar, three enforcers

Status: accepted

## Context

A change during a launch campaign can cost a launch. Freezes kept in a wiki, a CI variable and a
planning spreadsheet drift apart.

## Decision

`config/launch-calendar.yaml` is the only place a freeze is written. From it:

1. the wave planner skips maintenance windows that touch a freeze at the wave's site;
2. `runway freeze argocd` writes deny sync windows into the Argo CD AppProject (CI fails if the
   committed project misses a current freeze);
3. `runway freeze gitlab` writes GitLab deploy freeze periods, and the `gate:freeze` job checks each
   site before a deploy. An emergency change needs `EMERGENCY_CHANGE_APPROVED_BY`, a protected
   variable, and the job log records the name.

## Consequences

Argo CD expresses windows as cron plus duration, so a one-off freeze becomes a yearly cron; ended
freezes are dropped when the project is regenerated, so they cannot return a year later.
