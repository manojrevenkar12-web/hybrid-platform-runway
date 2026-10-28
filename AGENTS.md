# Working in this repository

runway moves a VMware estate to Proxmox VE in waves around launch freezes, and the repository also
holds the platform code around it. Decisions are in `docs/adr/`, procedures in `docs/runbooks/`.

| Path | What |
|---|---|
| `src/runway/` | assess, plan, translate, cutover, drift, freeze, API, CLI (Python) |
| `config/` | rules with sources, target clusters and network map, windows, launch calendar |
| `web/` | the control-room console (React) |
| `infra/terraform` | AWS (VPN, offsite backups) and Proxmox cluster config |
| `infra/bicep` | Azure hub |
| `infra/ansible` | baseline, guest cutover, Proxmox node network; Molecule |
| `platform/gitops` | Argo CD projects, ApplicationSets, apps with OpenShift and kind overlays |
| `.gitlab-ci.yml`, `ci/gitlab` | the GitLab pipeline (run in CI with gitlab-ci-local) |

## Fast feedback

`scripts/check.sh`: ruff, mypy, pytest, the cutover drill, the console's typecheck, unit tests and
build. CI adds vcsim, Molecule, Terraform, Bicep, kind with Argo CD, gitlab-ci-local and Playwright.

## Invariants (each has a test, a drill or a CI check)

1. A VM never runs on vSphere and Proxmox at once, and never runs nowhere without a notification.
2. No wave touches a freeze at its site; one calendar drives the planner, Argo CD and GitLab.
3. Every cluster can lose its largest node after placement; memory is never overcommitted.
4. Every rule in `config/rules.yaml` names its source; thresholds and mappings live in `config/`.
5. Manual configuration is drift: generated code is the record, not the Proxmox UI.
6. Secrets never sit in the repository; tokens are least-privilege (see `infra/terraform/proxmox.tf`).

## Held-out rule

Never change runway to pass `heldout/<set>`. A set's first run (`reports/heldout/<set>/first_run.json`)
is never rewritten. If you study a set's failures, write `regression` to `heldout/<set>/STATUS` and
have someone who has not seen the code write a new set from `heldout/WRITING_CASES.md` only.
