# 0003: A cutover never leaves two copies running, or an outage nobody knows about

Status: accepted

## Context

The VM keeps its MAC address on Proxmox (DHCP reservations, firewall rules and license servers are
bound to it). Two running copies on one VLAN would fight over the same MAC and IP.

## Decision

- The source is stopped before the import; the Proxmox VM is started only after the import task
  succeeded.
- Verification is by the guest agent: the VM's own MACs must be present with an IPv4 address.
- Any failure after the source stopped rolls back: stop and destroy the Proxmox copy first, then
  start the source. If that fails, the outcome is `needs_person` and someone is notified.
- Every step is journalled in SQLite before and after it runs. An executor that dies mid-step and is
  restarted does not guess: anything past the precheck is rolled back cleanly.
- Creating a VM is never retried blindly (it could act twice); other API calls retry transient errors.

## Consequences

The drill (`runway drill`) runs the whole estate against a Proxmox that fails imports, never answers
from some guests, returns API errors, and an executor that is killed mid-import, and judges the end
state on both sides: 0 VMs running twice, 0 outages unannounced. Resuming after a crash rolls back
even imports that may have succeeded: slower, never wrong.
