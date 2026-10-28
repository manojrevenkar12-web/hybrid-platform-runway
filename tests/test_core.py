"""Assessment, calendar, planning and translation."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from conftest import at, vm

from runway import calendar, sim, translate
from runway.assess import Assessor
from runway.model import Disk, Nic, Verdict
from runway.plan import Planner


def verdict(v: object, **kw: object) -> tuple[Verdict, set[str]]:
    a = Assessor().assess(v)  # type: ignore[arg-type]
    return a.verdict, {f.rule for f in a.findings}


class TestAssess:
    def test_plain_linux_vm_moves_by_itself(self) -> None:
        v, rules = verdict(vm("web-01"))
        assert v == Verdict.AUTO
        assert rules == {"linux-nic-rename", "vmware-tools"}

    def test_windows_needs_virtio_preparation(self) -> None:
        v, rules = verdict(vm("dc-01", guest_family="windows", guest_id="windows2022srvNext_64Guest", firmware="efi"))
        assert v == Verdict.ATTENTION
        assert {"windows-virtio", "efi-firmware"} <= rules

    def test_storage_the_importer_cannot_read_blocks(self) -> None:
        for disk, rule in [
            (Disk("d", 10, "vsan-1", "vsan"), "vsan-disk"),
            (Disk("d", 10, "ds1", encrypted=True), "encrypted-disk"),
            (Disk("d", 10, "ds1", backing="rdm"), "rdm-disk"),
            (Disk("d", 10, "ds+old"), "datastore-plus"),
        ]:
            v, rules = verdict(vm("x", disks=(disk,)))
            assert v == Verdict.BLOCKED and rule in rules, rule

    def test_target_decides_networks_devices_and_sites(self) -> None:
        assert "unmapped-network" in verdict(vm("x", nics=(Nic("pg-unknown", "00:50:56:00:00:01"),)))[1]
        assert verdict(vm("gpu", passthrough=("gpu-a100",)))[0] == Verdict.ATTENTION
        assert "device-not-on-target" in verdict(vm("fpga", passthrough=("fpga-x",)))[1]
        assert "no-target-cluster" in verdict(vm("pad", site="launch"))[1]

    def test_snapshots_and_vtpm_need_people(self) -> None:
        v, rules = verdict(vm("x", snapshots=2, vtpm=True))
        assert v == Verdict.ATTENTION and {"snapshots", "vtpm"} <= rules


class TestCalendar:
    def test_slots_follow_the_maintenance_rules(self, windows) -> None:  # type: ignore[no-untyped-def]
        slots = list(calendar.maintenance_slots(windows, at(2026, 11, 2), at(2026, 11, 9)))
        assert [s.start.strftime("%a %H:%M") for s in slots] == ["Tue 18:00", "Thu 18:00", "Sat 08:00"]
        assert slots[2].minutes == 12 * 60

    def test_launch_freeze_covers_fourteen_days_before_and_two_after(self, windows) -> None:  # type: ignore[no-untyped-def]
        f3 = next(c for c in windows.campaigns if c.name == "flight-3")
        assert (f3.t0 - f3.freeze_start).days == 14 and (f3.freeze_end - f3.t0).days == 2
        inside = calendar.Slot(at(2026, 12, 1, 18), at(2026, 12, 2, 2))
        assert calendar.frozen_by(windows, "hq", inside) is f3
        assert calendar.frozen_by(windows, "factory", inside) is None  # the factory is not part of flight-3

    def test_year_end_blackout_applies_everywhere(self, windows) -> None:  # type: ignore[no-untyped-def]
        s = calendar.Slot(at(2026, 12, 29, 18), at(2026, 12, 30, 2))
        assert calendar.frozen_by(windows, "factory", s).name == "year-end"  # type: ignore[union-attr]


class TestPlan:
    def plan(self, target, windows, vms, start=None, until=None):  # type: ignore[no-untyped-def]
        return Planner(target, windows).plan(Assessor().assess_all(vms), start or at(2026, 11, 2), until or at(2027, 4, 30))

    def test_the_whole_estate(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        p = self.plan(target, windows, sim.estate(), at(2026, 11, 16))
        placed = [pl for w in p.waves for pl in w.placements]
        assert not p.unplaced
        assert len(placed) + len(p.blocked) == len(sim.estate())
        # no wave in a freeze at its site
        for w in p.waves:
            assert calendar.frozen_by(windows, w.site, w.slot) is None, (w.index, w.site)
        assert p.skipped_for_freeze, "the plan crossed flight-3 and year-end and must have skipped windows"
        # every window keeps its rollback reserve and the VM limit
        for s in {w.slot for w in p.waves}:
            ws = [w for w in p.waves if w.slot == s]
            assert sum(w.minutes for w in ws) <= s.minutes * (1 - windows.migration.rollback_reserve_share) + 1e-6
            assert sum(len(w.placements) for w in ws) <= windows.migration.max_vms_per_wave

    def test_dependencies_move_first(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        p = self.plan(target, windows, sim.estate(), at(2026, 11, 16))
        first = {}
        for w in p.waves:
            for g in w.groups:
                first.setdefault(g, w.slot.start)
        last = {}
        for w in p.waves:
            for g in w.groups:
                last[g] = w.slot.start
        for app in sim.APPS:
            for d in app.depends:
                if app.name in first and d in last:
                    assert last[d] <= first[app.name], f"{app.name} moved before its dependency {d}"

    def test_clusters_can_still_lose_their_largest_node(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        p = self.plan(target, windows, sim.estate(), at(2026, 11, 16))
        for load in p.loads.values():
            assert sum(n.mem_gib for n in load.nodes) <= load.mem_after_node_loss()

    def test_anti_affinity_spreads_a_group(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        p = self.plan(target, windows, sim.estate(), at(2026, 11, 16))
        nodes = Counter((pl.vm.anti_affinity, pl.node) for w in p.waves for pl in w.placements if pl.vm.anti_affinity)
        assert nodes[("ad", "pve-hq-01")] <= 1
        assert max(nodes.values()) <= 2  # six app servers on three factory nodes: two each at most

    def test_gpu_vms_land_on_gpu_nodes(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        p = self.plan(target, windows, [vm(f"train-{i}", passthrough=("gpu-a100",), memory_gib=64) for i in range(2)])
        assert {pl.node for w in p.waves for pl in w.placements} <= {"pve-gpu-01", "pve-gpu-02"}

    def test_a_group_too_big_for_the_cluster_is_reported_not_half_placed(self, target, windows) -> None:  # type: ignore[no-untyped-def]
        huge = [vm(f"big-{i}", app="big", memory_gib=400) for i in range(8)]
        p = self.plan(target, windows, huge)
        assert "big" in p.unplaced and "lose its largest node" in p.unplaced["big"]


class TestTranslate:
    def test_terraform_and_ansible_per_wave(self, target, windows, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
        assessed = Assessor().assess_all(sim.estate())
        p = Planner(target, windows).plan(assessed, at(2026, 11, 16), at(2027, 4, 30))
        files = translate.write(p, assessed, target.network_map, tmp_path)
        tf = json.loads((tmp_path / "terraform" / "wave-01" / "main.tf.json").read_text())
        assert tf["terraform"]["required_providers"]["proxmox"]["source"] == "bpg/proxmox"
        vms = [
            b
            for f in tmp_path.glob("terraform/*/main.tf.json")
            for b in json.loads(f.read_text())["resource"]["proxmox_virtual_environment_vm"].values()
        ]
        assert len(vms) == sum(len(w.placements) for w in p.waves)
        assert len({b["vm_id"] for b in vms}) == len(vms), "VM ids must be unique"
        win = next(b for b in vms if b["operating_system"]["type"].startswith("win"))
        assert all(d["interface"].startswith("sata") for d in win["disk"]), "Windows boots from SATA until VirtIO is in"
        efi = next(b for b in vms if b["bios"] == "ovmf")
        assert efi["efi_disk"]["type"] == "4m"
        gpu = next(b for b in vms if "hostpci" in b)
        assert gpu["hostpci"][0]["mapping"] == "gpu-a100"
        assert len([f for f in files if f.suffix == ".yml"]) == len(vms)

    def test_macs_and_vlans_are_kept(self, target) -> None:  # type: ignore[no-untyped-def]
        from runway.plan import Placement

        v = vm("lic-01", nics=(Nic("pg-servers-110", "00:50:56:12:34:56"),))
        body = translate.terraform_vm(Placement(v, "pve-hq", "pve-hq-01", 10), target.network_map, "ceph-hq")
        assert body["network_device"] == [
            {"bridge": "vmbr0", "vlan_id": 110, "model": "virtio", "mac_address": "00:50:56:12:34:56"}
        ]
