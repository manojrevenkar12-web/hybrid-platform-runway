"""Wave planning: which VMs move in which maintenance window, onto which Proxmox node.

The planner moves an application's VMs together, after the applications it depends on, inside a
maintenance window that touches no launch freeze at its site, within the window's copy budget
(with a share kept free for rollback), and onto nodes that keep the cluster able to lose its
largest node. VMs that are blocked stay on vSphere and are listed with the reason.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime

from runway import calendar
from runway.model import VM, Assessment, Cluster, Verdict
from runway.settings import Target, Windows


def copy_minutes(vm: VM, w: Windows) -> float:
    """Time to move one VM: copying its disks at the window's throughput, plus fixed steps."""
    return vm.disk_gib * 1024 / w.migration.copy_mib_per_s / 60 + w.migration.per_vm_overhead_min


@dataclass
class NodeLoad:
    name: str
    cores: int
    memory_gib: float
    devices: tuple[str, ...]
    vcpus: int = 0
    mem_gib: float = 0.0
    groups: Counter[str] = field(default_factory=Counter)


@dataclass
class ClusterLoad:
    cluster: Cluster
    nodes: list[NodeLoad]
    disk_gib: float = 0.0

    @classmethod
    def of(cls, c: Cluster) -> ClusterLoad:
        return cls(c, [NodeLoad(n.name, n.cores, n.memory_gib, n.devices) for n in c.nodes])

    def mem_after_node_loss(self) -> float:
        return sum(n.memory_gib for n in self.nodes) - max(n.memory_gib for n in self.nodes)


@dataclass(frozen=True)
class Placement:
    vm: VM
    cluster: str
    node: str
    minutes: float


@dataclass
class Wave:
    index: int
    slot: calendar.Slot
    site: str
    groups: list[str] = field(default_factory=list)
    placements: list[Placement] = field(default_factory=list)

    @property
    def minutes(self) -> float:
        return sum(p.minutes for p in self.placements)


@dataclass
class Plan:
    waves: list[Wave]
    blocked: list[Assessment]
    unplaced: dict[str, str]  # group -> why it could not be placed
    skipped_for_freeze: list[tuple[calendar.Slot, str, str]]  # slot, site, campaign
    loads: dict[str, ClusterLoad]

    def wave_of(self, vm_name: str) -> Wave | None:
        return next((w for w in self.waves if any(p.vm.name == vm_name for p in w.placements)), None)


def _groups(assessed: list[Assessment]) -> dict[str, list[VM]]:
    g: dict[str, list[VM]] = defaultdict(list)
    for a in assessed:
        g[a.vm.group].append(a.vm)
    return dict(g)


def _order(groups: dict[str, list[VM]]) -> list[str]:
    """Groups in dependency order (dependencies first). Cycles are merged by keeping their members
    adjacent; ties keep the bigger, more central group first so it gets the earliest windows."""
    deps = {g: {d for vm in vms for d in vm.depends_on if d in groups and d != g} for g, vms in groups.items()}
    # Tarjan's strongly connected components gives a reverse topological order of the condensation
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    stack: list[str] = []
    on: set[str] = set()
    out: list[list[str]] = []
    counter = [0]

    def visit(v: str) -> None:
        index[v] = low[v] = counter[0]
        counter[0] += 1
        stack.append(v)
        on.add(v)
        for w in sorted(deps[v]):
            if w not in index:
                visit(w)
                low[v] = min(low[v], low[w])
            elif w in on:
                low[v] = min(low[v], index[w])
        if low[v] == index[v]:
            comp = []
            while True:
                w = stack.pop()
                on.discard(w)
                comp.append(w)
                if w == v:
                    break
            out.append(sorted(comp))

    dependents: defaultdict[str, int] = defaultdict(int)
    for ds in deps.values():
        for d in ds:
            dependents[d] += 1
    for g in sorted(groups, key=lambda g: (-dependents[g], -len(groups[g]), g)):
        if g not in index:
            visit(g)
    return [g for comp in out for g in comp]  # dependencies come out first


class Planner:
    def __init__(self, target: Target, windows: Windows):
        self.target = target
        self.w = windows

    def _cluster_for(self, vm: VM) -> list[Cluster]:
        cs = [c for c in self.target.clusters if c.site == vm.site]
        if vm.passthrough:
            cs = [c for c in cs if any(set(vm.passthrough) <= set(n.devices) for n in c.nodes)]
        else:
            # plain VMs do not take room on device nodes when another cluster at the site can hold them
            plain = [c for c in cs if not any(n.devices for n in c.nodes)]
            cs = plain or cs
        return cs

    def _place(self, vms: list[VM], loads: dict[str, ClusterLoad], group: str, sizes: Counter[str]) -> list[Placement] | str:
        """Place every VM of a group, or none: returns placements or why it does not fit.

        Anti-affinity spreads a group evenly: no node holds more than ceil(members / nodes) of it,
        so two domain controllers never share a node and six app servers sit two to a node on three.
        """
        trial: list[tuple[NodeLoad, ClusterLoad, VM]] = []

        def undo() -> None:
            for node, cl, vm in trial:
                node.vcpus -= vm.cpus
                node.mem_gib -= vm.memory_gib
                if vm.anti_affinity:
                    node.groups[vm.anti_affinity] -= 1
                cl.disk_gib -= vm.disk_gib

        placed: list[Placement] = []
        for vm in sorted(vms, key=lambda v: (-v.memory_gib, v.name)):
            reason = "no cluster at its site"
            done = False
            for c in self._cluster_for(vm):
                cl = loads[c.name]
                if cl.disk_gib + vm.disk_gib > c.storage_gib:
                    reason = f"{c.storage} would be full"
                    continue
                if (
                    self.target.placement.survive_node_loss
                    and sum(n.mem_gib for n in cl.nodes) + vm.memory_gib > cl.mem_after_node_loss()
                ):
                    reason = f"{c.name} could no longer lose its largest node"
                    continue
                candidates = [
                    n
                    for n in cl.nodes
                    if set(vm.passthrough) <= set(n.devices)
                    and n.mem_gib + vm.memory_gib <= n.memory_gib
                    and n.vcpus + vm.cpus <= n.cores * self.target.placement.cpu_overcommit
                    and not (
                        vm.anti_affinity and n.groups[vm.anti_affinity] >= math.ceil(sizes[vm.anti_affinity] / len(cl.nodes))
                    )
                ]
                if not candidates:
                    reason = f"no node in {c.name} has room" + (
                        f" apart from group {vm.anti_affinity}" if vm.anti_affinity else ""
                    )
                    continue
                node = max(
                    candidates,
                    key=lambda n: (
                        -n.groups[vm.anti_affinity] if vm.anti_affinity else 0,
                        n.memory_gib - n.mem_gib,
                        -n.vcpus,
                        n.name,
                    ),
                )
                node.vcpus += vm.cpus
                node.mem_gib += vm.memory_gib
                if vm.anti_affinity:
                    node.groups[vm.anti_affinity] += 1
                cl.disk_gib += vm.disk_gib
                trial.append((node, cl, vm))
                placed.append(Placement(vm, c.name, node.name, copy_minutes(vm, self.w)))
                done = True
                break
            if not done:
                undo()
                return f"{vm.name}: {reason}"
        return placed

    def plan(self, assessed: list[Assessment], start: datetime, until: datetime) -> Plan:
        movable = [a for a in assessed if a.verdict != Verdict.BLOCKED]
        blocked = [a for a in assessed if a.verdict == Verdict.BLOCKED]
        groups = _groups(movable)
        order = _order(groups)
        sizes: Counter[str] = Counter(a.vm.anti_affinity for a in movable if a.vm.anti_affinity)
        loads = {c.name: ClusterLoad.of(c) for c in self.target.clusters}
        slots = list(calendar.maintenance_slots(self.w, start, until))
        budget = [s.minutes * (1 - self.w.migration.rollback_reserve_share) for s in slots]
        waves: dict[tuple[int, str], Wave] = {}
        done_at: dict[str, int] = {}  # group -> slot index of its last VM
        unplaced: dict[str, str] = {}
        skipped: list[tuple[calendar.Slot, str, str]] = []
        skipped_seen: set[tuple[int, str]] = set()

        def used(i: int) -> tuple[float, int]:
            ws = [w for (j, _), w in waves.items() if j == i]
            return sum(w.minutes for w in ws), sum(len(w.placements) for w in ws)

        for g in order:
            vms = groups[g]
            site = vms[0].site
            deps = {d for vm in vms for d in vm.depends_on if d in groups and d != g}
            earliest = max((done_at[d] for d in deps if d in done_at), default=0)
            remaining = sorted(vms, key=lambda v: (-v.memory_gib, v.name))
            i = earliest
            last = -1
            while remaining and i < len(slots):
                slot = slots[i]
                frozen = calendar.frozen_by(self.w, site, slot)
                if frozen:
                    if (i, site) not in skipped_seen:
                        skipped.append((slot, site, frozen.name))
                        skipped_seen.add((i, site))
                    i += 1
                    continue
                spent, count = used(i)
                take: list[VM] = []
                minutes = 0.0
                for vm in remaining:
                    m = copy_minutes(vm, self.w)
                    if spent + minutes + m <= budget[i] and count + len(take) < self.w.migration.max_vms_per_wave:
                        take.append(vm)
                        minutes += m
                if not take:
                    i += 1
                    continue
                result = self._place(take, loads, g, sizes)
                if isinstance(result, str):
                    unplaced[g] = result
                    break
                wave = waves.setdefault((i, site), Wave(0, slot, site))
                wave.groups.append(g)
                wave.placements.extend(result)
                remaining = [v for v in remaining if v not in take]
                last = i
                i += 1
            if remaining and g not in unplaced:
                unplaced[g] = f"no window left before {until.date()} for {len(remaining)} VM(s)"
            if (last >= 0 and not remaining) or last >= 0:
                done_at[g] = last
        ordered = sorted(waves.values(), key=lambda w: (w.slot.start, w.site))
        for n, w in enumerate(ordered, 1):
            w.index = n
        return Plan(ordered, blocked, unplaced, skipped, loads)
