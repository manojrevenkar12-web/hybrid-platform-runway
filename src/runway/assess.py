"""Assess each VM against the compatibility rules (config/rules.yaml) and the target (config/target.yaml)."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from runway import settings
from runway.model import VM, Assessment, Finding, Verdict

VERDICTS = {"auto": Verdict.AUTO, "attention": Verdict.ATTENTION, "blocked": Verdict.BLOCKED}


def _matches(vm: VM, when: dict[str, Any]) -> bool:
    for key, want in when.items():
        if key == "disk_datastore_type":
            ok = any(d.datastore_type == want for d in vm.disks)
        elif key == "disk_encrypted":
            ok = any(d.encrypted for d in vm.disks) == bool(want)
        elif key == "disk_backing":
            ok = any(d.backing == want for d in vm.disks)
        elif key == "disk_mode":
            ok = any(d.mode == want for d in vm.disks)
        elif key == "disk_datastore_name_contains":
            ok = any(str(want) in d.datastore for d in vm.disks)
        elif key == "has_passthrough":
            ok = bool(vm.passthrough) == bool(want)
        elif key == "snapshots_min":
            ok = vm.snapshots >= int(want)
        elif key in ("guest_family", "firmware"):
            ok = getattr(vm, key) == want
        elif key in ("vtpm", "tools_installed", "secure_boot"):
            ok = bool(getattr(vm, key)) == bool(want)
        else:
            raise ValueError(f"unknown rule condition {key!r}")
        if not ok:
            return False
    return True


class Assessor:
    def __init__(self, rules: list[dict[str, Any]] | None = None, target: settings.Target | None = None):
        self.rules = rules if rules is not None else settings.rules()
        self.target = target or settings.target()
        self.devices = {d for c in self.target.clusters for n in c.nodes for d in n.devices}
        self.sites = {c.site for c in self.target.clusters}

    def assess(self, vm: VM) -> Assessment:
        found = [
            Finding(r["id"], VERDICTS[r["verdict"]], r["why"], r["action"], r.get("source", ""))
            for r in self.rules
            if _matches(vm, r.get("when", {}))
        ]
        unmapped = sorted({n.portgroup for n in vm.nics if n.portgroup not in self.target.network_map})
        if unmapped:
            found.append(
                Finding(
                    "unmapped-network",
                    Verdict.BLOCKED,
                    f"No Proxmox bridge and VLAN for port group {', '.join(unmapped)}.",
                    "Add the port group to network_map in config/target.yaml.",
                    "config/target.yaml",
                )
            )
        missing = sorted(set(vm.passthrough) - self.devices)
        if missing:
            found.append(
                Finding(
                    "device-not-on-target",
                    Verdict.BLOCKED,
                    f"No target node has {', '.join(missing)}.",
                    "Add a node with the device to config/target.yaml, or keep the VM on vSphere.",
                    "config/target.yaml",
                )
            )
        if vm.site not in self.sites:
            found.append(
                Finding(
                    "no-target-cluster",
                    Verdict.BLOCKED,
                    f"No Proxmox cluster at site {vm.site!r}.",
                    "Keep the VM on vSphere at that site, or add a cluster for it in config/target.yaml.",
                    "config/target.yaml",
                )
            )
        if not vm.disks:
            found.append(
                Finding("no-disks", Verdict.ATTENTION, "The VM has no disks to copy.", "Confirm it is still needed.", "")
            )
        return Assessment(vm, tuple(found))

    def assess_all(self, vms: Iterable[VM]) -> list[Assessment]:
        return [self.assess(v) for v in vms]
