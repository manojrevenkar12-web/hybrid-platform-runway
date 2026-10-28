"""Cut a wave over from vSphere to Proxmox VE, one VM at a time, with rollback and a journal.

Each VM goes through: precheck, stop the source, create the VM on Proxmox importing its disks from
the ESXi storage, start it, wait for the guest agent and the VM's own MAC addresses with an IP,
done. Any failure after the source was stopped rolls back: the half-made Proxmox VM is stopped and
destroyed, and the source is started again.

Invariant: a VM never runs on both sides at once (two copies with the same MAC and IP on one VLAN),
and never ends with neither side running unless a person has been told. Every step is written to a
SQLite journal before and after it runs, so a cutover interrupted mid-way resumes or rolls back
correctly when started again.
"""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from runway import calendar
from runway.plan import Placement
from runway.proxmox import Proxmox, ProxmoxError
from runway.settings import Windows
from runway.source import Source
from runway.translate import vm_id

DONE, ROLLED_BACK, NEEDS_PERSON, SKIPPED = "done", "rolled_back", "needs_person", "skipped"


@dataclass(frozen=True)
class Outcome:
    vm: str
    result: str  # done | rolled_back | needs_person | skipped
    step: str  # the step that decided it
    reason: str
    downtime_s: float


def proxmox_params(p: Placement, src: Source, network_map: dict[str, tuple[str, int]], storage: str) -> dict[str, Any]:
    """The create call for Proxmox: the same VM as translate.terraform_vm, as API parameters."""
    vm = p.vm
    win = vm.guest_family == "windows"
    params: dict[str, Any] = {
        "vmid": vm_id(vm),
        "name": vm.name,
        "cores": vm.cpus,
        "memory": int(vm.memory_gib * 1024),
        "machine": "q35",
        "bios": "ovmf" if vm.firmware == "efi" else "seabios",
        "scsihw": "virtio-scsi-single",
        "ostype": "win11" if win else "l26",
        "agent": "enabled=1",
        "tags": ";".join(t for t in ["runway", vm.app, vm.site] if t),
    }
    for i, _d in enumerate(vm.disks):
        bus = f"sata{i}" if win else f"scsi{i}"
        params[bus] = f"{storage}:0,import-from={src.import_path(vm, i)}"
    for i, n in enumerate(vm.nics):
        bridge, vlan = network_map[n.portgroup]
        params[f"net{i}"] = f"virtio={n.mac.upper()},bridge={bridge},tag={vlan}"
    if vm.firmware == "efi":
        params["efidisk0"] = f"{storage}:1,efitype=4m,pre-enrolled-keys={int(vm.secure_boot)}"
    if vm.vtpm:
        params["tpmstate0"] = f"{storage}:1,version=v2.0"
    for i, dev in enumerate(vm.passthrough):
        params[f"hostpci{i}"] = f"mapping={dev},pcie=1"
    return params


class Journal:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS step (vm TEXT, step TEXT, status TEXT, detail TEXT, at TEXT)")
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS outcome (vm TEXT PRIMARY KEY, result TEXT, step TEXT, reason TEXT, downtime_s REAL, at TEXT)"
        )
        self.db.commit()

    def record(self, vm: str, step: str, status: str, detail: str = "") -> None:
        self.db.execute("INSERT INTO step VALUES (?, ?, ?, ?, ?)", (vm, step, status, detail, datetime.now(UTC).isoformat()))
        self.db.commit()

    def last(self, vm: str) -> tuple[str, str] | None:
        row = self.db.execute("SELECT step, status FROM step WHERE vm = ? ORDER BY rowid DESC LIMIT 1", (vm,)).fetchone()
        return (row[0], row[1]) if row else None

    def outcome(self, vm: str) -> Outcome | None:
        row = self.db.execute("SELECT vm, result, step, reason, downtime_s FROM outcome WHERE vm = ?", (vm,)).fetchone()
        return Outcome(*row) if row else None

    def finish(self, o: Outcome) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO outcome VALUES (?, ?, ?, ?, ?, ?)",
            (o.vm, o.result, o.step, o.reason, o.downtime_s, datetime.now(UTC).isoformat()),
        )
        self.db.commit()

    def outcomes(self) -> list[Outcome]:
        return [Outcome(*r) for r in self.db.execute("SELECT vm, result, step, reason, downtime_s FROM outcome ORDER BY vm")]

    def steps(self, vm: str) -> list[dict[str, str]]:
        return [
            dict(zip(("step", "status", "detail", "at"), r, strict=True))
            for r in self.db.execute("SELECT step, status, detail, at FROM step WHERE vm = ? ORDER BY rowid", (vm,))
        ]


class Cutover:
    def __init__(
        self,
        pve: Proxmox,
        source: Source,
        journal: Journal,
        network_map: dict[str, tuple[str, int]],
        storage: dict[str, str],  # cluster -> storage id
        windows: Windows | None = None,
        agent_timeout_s: float = 300,
        grace_s: float = 120,
        poll_s: float = 2.0,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        notify: Callable[[str, str], None] = lambda vm, msg: None,
    ):
        self.pve = pve
        self.src = source
        self.j = journal
        self.network_map = network_map
        self.storage = storage
        self.windows = windows
        self.agent_timeout_s = agent_timeout_s
        self.grace_s = grace_s
        self.poll_s = poll_s
        self.clock = clock
        self.notify = notify

    # --- steps

    def _precheck(self, p: Placement) -> str | None:
        vm = p.vm
        if self.windows:
            for c in calendar.active_freezes(self.windows, self.clock()):
                if not c.sites or vm.site in c.sites:
                    return f"site {vm.site} is frozen for {c.name}"
        if vm.snapshots:
            return f"{vm.snapshots} snapshot(s) not consolidated"
        node = self.pve.find(vm_id(vm))
        if node:
            return f"VM id {vm_id(vm)} already exists on {node}"
        free = {n["node"]: (int(n["maxmem"]) - int(n["mem"])) / 2**30 for n in self.pve.nodes()}
        if free.get(p.node, 0) < vm.memory_gib:
            return f"{p.node} has {free.get(p.node, 0):.0f} GiB free, {vm.name} needs {vm.memory_gib:.0f}"
        return None

    def _verify(self, p: Placement) -> str | None:
        vmid = vm_id(p.vm)
        deadline = time.monotonic() + self.agent_timeout_s
        while time.monotonic() < deadline:
            if self.pve.agent_ping(p.node, vmid):
                ifs = self.pve.agent_interfaces(p.node, vmid)
                seen = {i.get("hardware-address", "").lower(): i for i in ifs}
                for n in p.vm.nics:
                    iface = seen.get(n.mac.lower())
                    if not iface:
                        return f"MAC {n.mac} not seen in the guest"
                    if not any(
                        a.get("ip-address-type") == "ipv4" and not a["ip-address"].startswith("127.")
                        for a in iface.get("ip-addresses", [])
                    ):
                        return f"{iface.get('name')} ({n.mac}) has no IPv4 address"
                return None
            time.sleep(self.poll_s)
        return f"guest agent did not answer within {self.agent_timeout_s:.0f}s"

    def _rollback(self, p: Placement, why: str, step: str, stopped_at: float | None) -> Outcome:
        vm, vmid = p.vm, vm_id(p.vm)
        self.j.record(vm.name, "rollback", "start", why)
        try:
            node = self.pve.find(vmid)
            if node:
                if self.pve.status(node, vmid) == "running":
                    self.pve.stop(node, vmid)
                self.pve.destroy(node, vmid)
            # only now, with no copy left on Proxmox, may the source run again
            if self.src.power_state(vm) != "on" and vm.powered_on:
                self.src.start(vm)
        except Exception as e:
            self.j.record(vm.name, "rollback", "failed", str(e))
            self.notify(vm.name, f"rollback failed after {step}: {e}")
            return self._done(Outcome(vm.name, NEEDS_PERSON, "rollback", f"{why}; rollback failed: {e}", self._down(stopped_at)))
        self.j.record(vm.name, "rollback", "ok")
        return self._done(Outcome(vm.name, ROLLED_BACK, step, why, self._down(stopped_at)))

    def _down(self, stopped_at: float | None) -> float:
        return round(time.monotonic() - stopped_at, 3) if stopped_at is not None else 0.0

    def _done(self, o: Outcome) -> Outcome:
        self.j.finish(o)
        return o

    # --- one VM

    def run_one(self, p: Placement) -> Outcome:
        vm, vmid = p.vm, vm_id(p.vm)
        prior = self.j.outcome(vm.name)
        if prior:
            return prior
        last = self.j.last(vm.name)
        if last and last[0] not in ("precheck",):
            # interrupted after the source may have been stopped: never guess, roll back cleanly
            return self._rollback(p, f"resumed after interruption at {last[0]}/{last[1]}", last[0], None)
        self.j.record(vm.name, "precheck", "start")
        try:
            why = self._precheck(p)
        except (ProxmoxError, RuntimeError, LookupError) as e:
            why = f"precheck could not run: {e}"
        if why:
            self.j.record(vm.name, "precheck", "failed", why)
            return self._done(Outcome(vm.name, SKIPPED, "precheck", why, 0.0))
        self.j.record(vm.name, "precheck", "ok")

        self.j.record(vm.name, "stop_source", "start")
        try:
            self.src.stop(vm, self.grace_s)
        except Exception as e:
            self.j.record(vm.name, "stop_source", "failed", str(e))
            # the source may still be running: nothing was created, so nothing to undo but the source state
            if self.src.power_state(vm) == "on":
                return self._done(Outcome(vm.name, SKIPPED, "stop_source", str(e), 0.0))
            return self._rollback(p, str(e), "stop_source", None)
        stopped_at = time.monotonic()
        self.j.record(vm.name, "stop_source", "ok")

        try:
            self.j.record(vm.name, "import", "start")
            params = proxmox_params(p, self.src, self.network_map, self.storage[p.cluster])
            res = self.pve.wait(p.node, self.pve.create(p.node, params))
            if not res.ok:
                self.j.record(vm.name, "import", "failed", res.exitstatus)
                return self._rollback(p, f"import failed: {res.exitstatus}", "import", stopped_at)
            self.j.record(vm.name, "import", "ok", json.dumps({"vmid": vmid, "node": p.node}))

            self.j.record(vm.name, "boot", "start")
            if vm.powered_on:
                self.pve.wait(p.node, self.pve.start(p.node, vmid))
                why = self._verify(p)
                if why:
                    self.j.record(vm.name, "boot", "failed", why)
                    return self._rollback(p, why, "verify", stopped_at)
            self.j.record(vm.name, "boot", "ok")
        except ProxmoxError as e:
            self.j.record(vm.name, "proxmox", "failed", str(e))
            return self._rollback(p, str(e), "proxmox", stopped_at)
        return self._done(Outcome(vm.name, DONE, "verify", "", self._down(stopped_at)))

    def run_wave(self, placements: list[Placement]) -> list[Outcome]:
        return [self.run_one(p) for p in placements]
