"""Cutover against the fake Proxmox API: success, rollback, resume, freeze, and drift."""

from __future__ import annotations

import json
from pathlib import Path

from conftest import at, fake_pve, vm

from runway import drift, settings, translate
from runway.cutover import DONE, NEEDS_PERSON, ROLLED_BACK, SKIPPED, Cutover, Journal
from runway.fake_pve import Faults
from runway.plan import Placement
from runway.source import FakeSource
from runway.translate import vm_id

STORAGE = {c.name: c.storage for c in settings.target().clusters}


def setup(vms, faults=None, tmp: Path | None = None, **kw):  # type: ignore[no-untyped-def]
    fake, pve = fake_pve(faults)
    src = FakeSource(vms, **{k: v for k, v in kw.items() if k in ("stop_failure", "start_failure")})
    j = Journal(":memory:" if tmp is None else tmp / "journal.db")
    c = Cutover(
        pve,
        src,
        j,
        settings.target().network_map,
        STORAGE,
        agent_timeout_s=0.05,
        grace_s=0,
        poll_s=0,
        **{k: v for k, v in kw.items() if k in ("windows", "clock")},
    )
    return fake, pve, src, j, c


def place(v, node="pve-hq-01"):  # type: ignore[no-untyped-def]
    return Placement(v, "pve-hq", node, 10.0)


def test_a_vm_moves_and_only_the_proxmox_copy_runs() -> None:
    v = vm("app-01")
    fake, pve, src, j, c = setup([v])
    o = c.run_one(place(v))
    assert o.result == DONE
    assert src.power_state(v) == "off"
    assert fake.vms[vm_id(v)].status == "running"
    cfg = fake.vms[vm_id(v)].config
    assert cfg["scsi0"].startswith("ceph-hq:0,import-from=esxi-hq:")
    assert cfg["net0"] == "virtio=00:50:56:AA:BB:01,bridge=vmbr0,tag=110"
    assert [s["step"] for s in j.steps(v.name)][-1] == "boot"


def test_failed_import_rolls_back_to_the_source() -> None:
    v = vm("app-02")
    fake, pve, src, j, c = setup([v], Faults(import_failure_rate=1.0))
    o = c.run_one(place(v))
    assert o.result == ROLLED_BACK and o.step == "import"
    assert src.power_state(v) == "on"
    assert vm_id(v) not in fake.vms


def test_a_guest_that_never_answers_is_destroyed_before_the_source_restarts() -> None:
    v = vm("app-03")
    fake, pve, src, j, c = setup([v], Faults(agent_never_rate=1.0))
    o = c.run_one(place(v))
    assert o.result == ROLLED_BACK and "guest agent" in o.reason
    assert vm_id(v) not in fake.vms and src.power_state(v) == "on"
    # the order matters: the Proxmox copy is gone before the source starts (never two with one MAC)
    rollback = [s for s in j.steps(v.name) if s["step"] == "rollback"]
    assert [s["status"] for s in rollback] == ["start", "ok"]


def test_a_rollback_that_cannot_restart_the_source_calls_a_person() -> None:
    v = vm("app-04")
    told: list[str] = []
    fake, pve, src, j, c = setup([v], Faults(import_failure_rate=1.0), start_failure={"app-04"})
    c.notify = lambda name, msg: told.append(f"{name}: {msg}")
    o = c.run_one(place(v))
    assert o.result == NEEDS_PERSON and told


def test_snapshots_and_occupied_ids_stop_before_anything_changes() -> None:
    v = vm("app-05", snapshots=1)
    fake, pve, src, j, c = setup([v])
    assert c.run_one(place(v)).result == SKIPPED and src.power_state(v) == "on"


def test_no_cutover_during_a_launch_freeze() -> None:
    v = vm("app-06")
    fake, pve, src, j, c = setup([v], windows=settings.windows(), clock=lambda: at(2026, 12, 5, 19))
    o = c.run_one(place(v))
    assert o.result == SKIPPED and "flight-3" in o.reason


def test_an_interrupted_cutover_is_rolled_back_when_resumed(tmp_path: Path) -> None:
    v = vm("app-07")
    fake, pve, src, j, c = setup([v], tmp=tmp_path)
    # simulate a crash right after the source was stopped and the import started
    j.record(v.name, "precheck", "ok")
    j.record(v.name, "stop_source", "ok")
    src.state[v.moid] = "off"
    j.record(v.name, "import", "start")
    pve.wait("pve-hq-01", pve.create("pve-hq-01", {"vmid": vm_id(v), "name": v.name}))
    fake2, pve2, src2, j2, c2 = setup([v], tmp=tmp_path)
    c2.pve, c2.src = pve, src
    o = c2.run_one(place(v))
    assert o.result == ROLLED_BACK and "interruption" in o.reason
    assert src.power_state(v) == "on" and vm_id(v) not in fake.vms
    assert c2.run_one(place(v)).result == ROLLED_BACK  # the outcome is final, not re-run


def test_drift_finds_manual_changes(tmp_path: Path, target, windows) -> None:  # type: ignore[no-untyped-def]
    from runway.assess import Assessor
    from runway.plan import Planner

    vms = [vm(f"svc-{i}", moid=f"vm-{500 + i}") for i in range(3)]
    assessed = Assessor().assess_all(vms)
    plan = Planner(target, windows).plan(assessed, at(2026, 11, 2), at(2027, 4, 30))
    translate.write(plan, assessed, target.network_map, tmp_path)
    fake, pve, src, j, c = setup(vms)
    for w in plan.waves:
        assert all(o.result == DONE for o in c.run_wave(w.placements))
    d, missing = drift.check(pve, tmp_path / "terraform")
    assert d == [] and missing == []
    # someone doubles the memory in the web UI and moves a NIC to another VLAN
    fake.vms[vm_id(vms[0])].config["memory"] = "8192"
    fake.vms[vm_id(vms[1])].config["net0"] = "virtio=00:50:56:AA:BB:01,bridge=vmbr0,tag=999"
    del fake.vms[vm_id(vms[2])]
    d, missing = drift.check(pve, tmp_path / "terraform")
    assert {(x.vm, x.field) for x in d} == {("svc-0", "memory"), ("svc-1", "net0")}
    assert missing == ["svc-2"]
    assert json.dumps([x.__dict__ for x in d])  # serialisable for the API
