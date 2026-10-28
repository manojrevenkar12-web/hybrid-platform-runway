# 0001: Leave VMware in waves, planned by code, around the launch calendar

Status: accepted

## Context

The VMware estate runs everything from domain controllers to test-stand ingestion and the systems
around a launch campaign. Broadcom's licensing changes make staying expensive; a big-bang move is
not possible, because some VMs cannot move yet (vSAN, encrypted, raw device mappings, devices) and
because nothing may change around a launch.

## Decision

- Every VM gets a verdict from rules with a named source (config/rules.yaml): auto, attention or
  blocked. Blocked VMs stay and appear on a worklist with the action that unblocks them.
- Applications move as a group, after the applications they depend on, inside maintenance windows.
- A window that touches a freeze at its site is not used. Freezes come from one launch calendar.
- Each window keeps a quarter free for rolling back; copy time is planned from the disk sizes and
  the measured throughput, not hoped for.
- Every Proxmox cluster must survive losing its largest node after placement; anti-affinity spreads
  groups (domain controllers, database replicas) across nodes.
- The plan is a file reviewed in a merge request, and so is the Terraform and Ansible it generates.

## Consequences

- The plan is honest about what cannot move and about capacity: a cluster that cannot lose a node
  shows up as unplaced groups, not as an outage later.
- Planning is conservative: sequential copy time per window, a fixed rollback reserve.
