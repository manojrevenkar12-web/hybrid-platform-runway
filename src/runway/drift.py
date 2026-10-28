"""Drift: what runs on Proxmox VE that differs from what the generated Terraform says.

Manual configuration is a bug, so drift is reported per VM and field, and fixed by changing code
(or by applying it again), never by editing the VM in the web UI.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from runway.proxmox import Proxmox


@dataclass(frozen=True)
class Drift:
    vm: str
    field: str
    want: str
    have: str


def _want(body: dict[str, Any]) -> dict[str, str]:
    w = {
        "cores": str(body["cpu"]["cores"]),
        "memory": str(body["memory"]["dedicated"]),
        "bios": str(body["bios"]),
        "agent": "1",
    }
    for i, n in enumerate(body.get("network_device", [])):
        w[f"net{i}"] = f"{n['mac_address'].upper()}|{n['bridge']}|{n['vlan_id']}"
    return w


def _have(cfg: dict[str, Any]) -> dict[str, str]:
    h = {
        "cores": str(cfg.get("cores", "")),
        "memory": str(cfg.get("memory", "")),
        "bios": str(cfg.get("bios", "seabios")),
        "agent": "1" if "enabled=1" in str(cfg.get("agent", "")) or str(cfg.get("agent", "")) == "1" else "0",
    }
    for k, v in cfg.items():
        if k.startswith("net") and k[3:].isdigit():
            parts = dict(p.split("=", 1) for p in str(v).split(",") if "=" in p)
            mac = next((parts[m] for m in ("virtio", "e1000", "vmxnet3") if m in parts), "")
            h[k] = f"{mac.upper()}|{parts.get('bridge', '')}|{parts.get('tag', '')}"
    return h


def check(pve: Proxmox, terraform_dir: Path) -> tuple[list[Drift], list[str]]:
    """Compare every generated VM with Proxmox. Returns (drift, VMs in code that are missing)."""
    drift: list[Drift] = []
    missing: list[str] = []
    for f in sorted(terraform_dir.glob("wave-*/main.tf.json")):
        for body in json.loads(f.read_text())["resource"]["proxmox_virtual_environment_vm"].values():
            node = pve.find(int(body["vm_id"]))
            if node is None:
                missing.append(body["name"])
                continue
            want, have = _want(body), _have(pve.config(node, int(body["vm_id"])))
            for k, v in want.items():
                if have.get(k, "") != v:
                    drift.append(Drift(body["name"], k, v, have.get(k, "")))
            for k in sorted(set(have) - set(want)):
                if k.startswith("net"):
                    drift.append(Drift(body["name"], k, "", have[k]))
    return drift, missing
