# Writing a held-out set for runway

runway moves virtual machines from VMware vSphere to Proxmox VE. A held-out set checks it on cases
nobody tuned it against. Whoever writes a set must not have read runway's code or its tests; this
guide is all you need. Write cases that a careful infrastructure engineer would expect it to get
right, including awkward combinations.

A set has two files in `heldout/<set>/`: `vms.yaml` (does each VM move, and why) and
`scenarios.yaml` (is a wave plan safe). Also write `heldout/<set>/STATUS` containing `blind`.

## Part A: verdicts for single VMs (`vms.yaml`)

Each VM gets a verdict:

- `auto`: runway moves it with no preparation by people.
- `attention`: runway moves it after people prepare something.
- `blocked`: it cannot move until someone changes the source or the target.

A VM's verdict is the worst verdict among the rules it triggers (blocked > attention > auto). These
are the rules. "Any disk" means at least one of the VM's disks.

| rule id | when | verdict |
|---|---|---|
| `vsan-disk` | any disk is on a datastore of type `vsan` | blocked |
| `encrypted-disk` | any disk is encrypted | blocked |
| `rdm-disk` | any disk has backing `rdm` (raw device mapping) | blocked |
| `datastore-plus` | any disk's datastore name contains `+` | blocked |
| `unmapped-network` | any NIC's port group is not in the network map below | blocked |
| `device-not-on-target` | the VM passes through a device class no target node has (see devices below) | blocked |
| `no-target-cluster` | the VM's site has no Proxmox cluster (sites with clusters: `hq`, `factory`) | blocked |
| `pci-passthrough` | the VM passes through any device | attention |
| `independent-disk` | any disk has mode `independent` | attention |
| `snapshots` | the VM has one or more snapshots | attention |
| `windows-virtio` | the guest family is `windows` | attention |
| `vtpm` | the VM has a virtual TPM | attention |
| `no-disks` | the VM has no disks at all | attention |
| `efi-firmware` | firmware is `efi` | auto |
| `linux-nic-rename` | the guest family is `linux` | auto |
| `vmware-tools` | VMware Tools are installed | auto |

A VM that triggers no rule is `auto`.

Network map (port groups that exist on the target): `pg-servers-110`, `pg-db-120`, `pg-dmz-200`,
`pg-mgmt-10`, `pg-ot-310`, `pg-lab-400`. Device classes on target nodes: `gpu-a100` only.

Format:

```yaml
# Written blind from heldout/WRITING_CASES.md on <date>.
vms:
  - id: v001
    vm:
      name: hq-erp-app-01
      guest_family: windows        # linux | windows | other
      guest_id: windows2022srvNext_64Guest
      cpus: 4
      memory_gib: 16
      firmware: efi                # bios | efi
      vtpm: false
      snapshots: 0
      tools_installed: true
      passthrough: []              # device classes, e.g. [gpu-a100]
      site: hq                     # hq | factory | launch | anything else
      disks:
        - {label: "Hard disk 1", size_gib: 80, datastore: hq-ds-1, datastore_type: vmfs, mode: persistent, backing: flat, encrypted: false}
      nics:
        - {portgroup: pg-servers-110, mac: "00:50:56:01:02:03"}
    expect:
      verdict: attention
      rules: [windows-virtio, efi-firmware, vmware-tools]   # every rule it triggers, any order
```

Write about 40 VMs. Cover every rule at least twice, and spend at least a third of the cases on
combinations (a Windows VM with a vSAN disk and snapshots; a Linux VM with two disks where only the
second is encrypted; a VM with no NICs; a GPU VM at a site without a cluster; and so on).

## Part B: wave plans (`scenarios.yaml`)

The planner puts the VMs that are not blocked into waves:

- VMs with the same `app` move as one group; a VM without an app is its own group.
- A group moves after every group named in its VMs' `depends_on` (the same window is allowed;
  dependencies that are blocked or absent are ignored).
- Waves happen only inside maintenance windows. A window is unusable for a site if it overlaps a
  freeze for that site. A campaign freezes its sites from `before_days` before `t0` until
  `after_days` after it; a blackout freezes its sites from `start` to `end`. No `sites` means all.
- In each window, the sum of the VMs' move times must fit in the window's length times
  (1 − `rollback_reserve_share`), and at most `max_vms_per_wave` VMs move. A VM's move time in
  minutes is `disk_gib × 1024 / copy_mib_per_s / 60 + per_vm_overhead_min`.
- A group that does not fit in one window may spread over several consecutive usable windows.
- Placement: a VM goes to a cluster at its own site (VMs with passthrough only to clusters with a
  node that has the device; other VMs prefer clusters without device nodes). Memory is never
  overcommitted on a node; vCPUs may be up to `cpu_overcommit` × the node's cores. After placing,
  the cluster's total placed memory must not exceed its total node memory minus its largest node's
  memory (it must survive losing its largest node). The storage must hold all placed disks.
- Anti-affinity: VMs sharing an `anti_affinity` value are spread so that no node holds more than
  ceil(group members ÷ nodes in the cluster) of them.
- If a group cannot be placed (capacity) or runs out of windows before the plan's end, it is
  reported as unplaced and none of its remaining VMs move.

Format (every scenario is self-contained; VMs use the Part A fields plus `app`, `depends_on`,
`anti_affinity`):

```yaml
scenarios:
  - id: s01
    description: one sentence
    start: "2027-02-01T00:00:00+01:00"
    until: "2027-03-01T00:00:00+01:00"
    timezone: Europe/Berlin
    maintenance_windows: [{days: [tue], start: "18:00", hours: 6}]
    migration: {copy_mib_per_s: 300, per_vm_overhead_min: 10, rollback_reserve_share: 0.25, max_vms_per_wave: 10}
    campaigns: [{name: flight-x, t0: "2027-02-10T11:00:00+01:00", sites: [hq], before_days: 7, after_days: 1}]
    blackouts: [{name: audit, start: "2027-02-20T00:00:00+01:00", end: "2027-02-22T00:00:00+01:00"}]
    clusters:
      - {name: pve-hq, site: hq, storage_gib: 10000, nodes: [{name: n1, cores: 32, memory_gib: 256}, {name: n2, cores: 32, memory_gib: 256}, {name: n3, cores: 32, memory_gib: 256, devices: []}]}
    cpu_overcommit: 4
    vms: [ ... ]
    expect:
      unplaced: [group names that must be reported unplaced]           # optional
      placed: [VM names that must be placed]                           # optional
      blocked: [VM names that must be blocked]                         # optional
      order: [[dependency_group, dependent_group], ...]                # dependency's last window <= dependent's first
      no_wave_between: [[start, end, site], ...]                       # no VM of that site moves in that period
      not_same_node: [[vm_a, vm_b], ...]
      waves_at_most: 3                                                 # optional
```

Write about 12 scenarios. Make some of them hard: a freeze that removes most windows, a dependency
chain across sites, a cluster that only fits the VMs while ignoring the lose-a-node rule, a group
larger than one window, a GPU VM where only one node has the device. Work out every expectation by
hand from the rules above, and only write expectations you are certain of.

The set is run once; its first run is pinned in `reports/heldout/<set>/first_run.json` and never
rewritten. If anyone studies its failures to change runway, the STATUS becomes `regression` and a
new blind set is written.
