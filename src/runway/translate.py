"""Turn a placed VM into code: Terraform for the Proxmox VE VM, Ansible variables for its guest.

Terraform (the bpg/proxmox provider) owns the VM definition from the moment it exists on Proxmox;
the disks arrive through the import (see cutover.py), so Terraform ignores changes to them. Ansible
owns what changes inside the guest: VMware Tools out, qemu-guest-agent in, network configuration
matched by MAC address, VirtIO drivers for Windows.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from runway.model import VM, Assessment
from runway.plan import Placement, Plan

MIB_PER_GIB = 1024


def resource_name(vm: VM) -> str:
    return re.sub(r"[^a-z0-9_]", "_", vm.name.lower())


def os_type(vm: VM) -> str:
    if vm.guest_family == "windows":
        return "win11" if vm.guest_id.startswith("windows9") or "2022" in vm.guest_id else "win10"
    return "l26" if vm.guest_family == "linux" else "other"


def vm_id(vm: VM) -> int:
    # stable across runs: the numeric part of the vSphere managed object id, in Proxmox's free range
    digits = re.sub(r"\D", "", vm.moid) or "0"
    return 10000 + int(digits) % 89999


def terraform_vm(p: Placement, network_map: dict[str, tuple[str, int]], storage: str) -> dict[str, Any]:
    vm = p.vm
    windows = vm.guest_family == "windows"
    disks = []
    for i, d in enumerate(vm.disks):
        # Windows boots from SATA until the VirtIO drivers are in; then Ansible moves it to SCSI
        iface = f"sata{i}" if windows else f"scsi{i}"
        disks.append(
            {
                "datastore_id": storage,
                "interface": iface,
                "size": max(1, round(d.size_gib)),
                "file_format": "raw",
                "discard": "on",
                "iothread": not windows,
            }
        )
    nets = []
    for n in vm.nics:
        bridge, vlan = network_map[n.portgroup]
        # keep the MAC: DHCP reservations, firewall rules and license servers are bound to it
        nets.append({"bridge": bridge, "vlan_id": vlan, "model": "virtio", "mac_address": n.mac.upper()})
    body: dict[str, Any] = {
        "name": vm.name,
        "node_name": p.node,
        "vm_id": vm_id(vm),
        "description": f"Migrated from vSphere {vm.moid} by runway. Owner: {vm.owner or 'unknown'}.",
        "tags": sorted({t for t in ["runway", vm.app, vm.tier, vm.site] if t}),
        "machine": "q35",
        "bios": "ovmf" if vm.firmware == "efi" else "seabios",
        "scsi_hardware": "virtio-scsi-single",
        "cpu": {"cores": vm.cpus, "type": "x86-64-v2-AES"},
        "memory": {"dedicated": int(vm.memory_gib * MIB_PER_GIB)},
        "operating_system": {"type": os_type(vm)},
        "agent": {"enabled": True, "timeout": "5m"},
        "disk": disks,
        "network_device": nets,
        "started": vm.powered_on,
        "on_boot": vm.powered_on,
        "lifecycle": {"ignore_changes": ["disk"]},
    }
    if vm.firmware == "efi":
        body["efi_disk"] = {"datastore_id": storage, "type": "4m", "pre_enrolled_keys": vm.secure_boot}
    if vm.vtpm:
        body["tpm_state"] = {"datastore_id": storage, "version": "v2.0"}
    if vm.passthrough:
        body["hostpci"] = [{"device": f"hostpci{i}", "mapping": dev, "pcie": True} for i, dev in enumerate(vm.passthrough)]
    return body


def ansible_vars(a: Assessment, p: Placement) -> dict[str, Any]:
    vm = a.vm
    rules = {f.rule for f in a.findings}
    return {
        "runway_vm": vm.name,
        "runway_source_moid": vm.moid,
        "runway_target_node": p.node,
        "runway_guest_family": vm.guest_family,
        "runway_remove_vmware_tools": vm.tools_installed,
        "runway_install_guest_agent": True,
        "runway_nics": [{"mac": n.mac.lower(), "portgroup": n.portgroup} for n in vm.nics],
        "runway_windows_virtio": vm.guest_family == "windows",
        "runway_bitlocker_check": "vtpm" in rules,
        "runway_prepared_by_people": sorted(f.rule for f in a.findings if f.verdict.name == "ATTENTION"),
    }


def write(plan: Plan, assessed: list[Assessment], network_map: dict[str, tuple[str, int]], out: Path) -> list[Path]:
    """Write one Terraform root per wave and Ansible host_vars per VM. Returns the files written."""
    by_name = {a.vm.name: a for a in assessed}
    storage = {c.cluster.name: c.cluster.storage for c in plan.loads.values()}
    written: list[Path] = []
    for w in plan.waves:
        d = out / "terraform" / f"wave-{w.index:02d}"
        d.mkdir(parents=True, exist_ok=True)
        resources = {resource_name(p.vm): terraform_vm(p, network_map, storage[p.cluster]) for p in w.placements}
        doc = {
            "terraform": {"required_providers": {"proxmox": {"source": "bpg/proxmox", "version": "~> 0.78"}}},
            "resource": {"proxmox_virtual_environment_vm": resources},
        }
        f = d / "main.tf.json"
        f.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n")
        written.append(f)
        hv = out / "ansible" / "host_vars"
        hv.mkdir(parents=True, exist_ok=True)
        for p in w.placements:
            h = hv / f"{p.vm.name}.yml"
            h.write_text(yaml.safe_dump(ansible_vars(by_name[p.vm.name], p), sort_keys=True))
            written.append(h)
    return written
