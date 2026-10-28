"""Cutover drills: a wave of VMs against a Proxmox that fails on purpose, judged by invariants.

The judge looks at the end state on both sides, not at what the executor says happened:
* never both: no VM runs on vSphere and Proxmox at once (same MAC, same IP on one VLAN)
* never neither, silently: a VM that runs nowhere has a NEEDS_PERSON outcome and a notification
* every VM that started on has one running copy at the end
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from runway import settings
from runway.assess import Assessor
from runway.cutover import DONE, NEEDS_PERSON, ROLLED_BACK, Cutover, Journal
from runway.fake_pve import FakePVE, Faults
from runway.model import Verdict
from runway.plan import Placement, Planner
from runway.proxmox import Proxmox
from runway.sim import estate
from runway.source import FakeSource
from runway.translate import vm_id

TOKEN = "runway@pve!drill=secret"


class Crash(BaseException):
    """The executor process dies (kill -9, node reboot): nothing in run_one gets to clean up."""


class CrashingProxmox(Proxmox):
    def __init__(self, *a: Any, crash_on: set[int], **kw: Any):
        super().__init__(*a, **kw)
        self.crash_on = crash_on

    def create(self, node: str, params: dict[str, Any]) -> str:
        upid = super().create(node, params)
        if int(params["vmid"]) in self.crash_on:
            self.crash_on.discard(int(params["vmid"]))
            raise Crash(f"executor died while importing {params['name']}")
        return upid


@dataclass
class DrillResult:
    numbers: dict[str, Any]
    violations: list[str] = field(default_factory=list)


def run(faults: Faults, journal: Path | str = ":memory:", start_failure_every: int = 0, crash_every: int = 0) -> DrillResult:
    t = settings.target()
    w = settings.windows()
    vms = [v for v in estate() if not v.snapshots]  # the precheck would skip these; consolidate first
    assessed = [a for a in Assessor().assess_all(vms) if a.verdict != Verdict.BLOCKED]
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(w.timezone)
    plan = Planner(t, w).plan(assessed, datetime(2027, 1, 12, tzinfo=tz), datetime(2027, 6, 30, tzinfo=tz))
    placements: list[Placement] = [p for wave in plan.waves for p in wave.placements]
    fake = FakePVE({n.name: n.memory_gib for c in t.clusters for n in c.nodes}, faults, token=TOKEN)
    crash_on = {vm_id(p.vm) for i, p in enumerate(placements, 1) if crash_every and i % crash_every == 0}
    pve = CrashingProxmox(TestClient(fake.app), token=TOKEN, poll_s=0, crash_on=crash_on)
    fails = {p.vm.name for i, p in enumerate(placements, 1) if start_failure_every and i % start_failure_every == 0}
    src = FakeSource([p.vm for p in placements], start_failure=fails)
    told: list[str] = []
    j = Journal(journal)

    def executor() -> Cutover:
        return Cutover(
            pve,
            src,
            j,
            t.network_map,
            {cl.name: cl.storage for cl in t.clusters},
            agent_timeout_s=0.01,
            grace_s=0,
            poll_s=0,
            notify=lambda vm, msg: told.append(vm),
        )

    # run the waves; when the executor dies, start a new one on the same journal, as an operator would
    restarts = 0
    while True:
        try:
            for p in placements:
                executor().run_one(p)
            break
        except Crash:
            restarts += 1
    outcomes = [j.outcome(p.vm.name) for p in placements]
    assert all(o is not None for o in outcomes)

    violations = []
    for p, o in zip(placements, outcomes, strict=True):
        assert o is not None
        on_src = src.power_state(p.vm) == "on"
        pv = fake.vms.get(vm_id(p.vm))
        on_pve = pv is not None and pv.status == "running"
        if on_src and on_pve:
            violations.append(f"{p.vm.name}: running on both sides")
        if p.vm.powered_on and not on_src and not on_pve and o.result != NEEDS_PERSON:
            violations.append(f"{p.vm.name}: running nowhere and nobody was told")
        if o.result == NEEDS_PERSON and p.vm.name not in told:
            violations.append(f"{p.vm.name}: needs a person but no notification was sent")
        if o.result == DONE and not on_pve and p.vm.powered_on:
            violations.append(f"{p.vm.name}: reported done but not running on Proxmox")
    counts = Counter(o.result for o in outcomes if o)
    numbers = {
        "vms": len(placements),
        "waves": len(plan.waves),
        "faults": {
            "import_failure_rate": faults.import_failure_rate,
            "agent_never_rate": faults.agent_never_rate,
            "api_error_rate": faults.api_error_rate,
            "source_restart_failures": len(fails),
            "executor_crashes": restarts,
        },
        "executor_restarts": restarts,
        "done": counts[DONE],
        "rolled_back": counts[ROLLED_BACK],
        "needs_person": counts[NEEDS_PERSON],
        "skipped": counts["skipped"],
        "running_on_both_sides": sum("both sides" in v for v in violations),
        "running_nowhere_untold": sum("nobody was told" in v for v in violations),
        "invariant_violations": len(violations),
        "proxmox_api_calls": fake.calls,
    }
    return DrillResult(numbers, violations)
