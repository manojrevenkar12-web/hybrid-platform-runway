"""Read the VMware estate from vCenter (pyVmomi) and turn it into runway's model.

Ownership metadata (application, dependencies, site, anti-affinity group, owner) is read from the
VM's notes, one ``runway.<key>=<value>`` per line, so it travels with the VM and needs no CMDB:

    runway.app=plm
    runway.depends=ad,plm-db
    runway.site=hq
    runway.anti_affinity=plm-app
"""

from __future__ import annotations

import json
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from runway.model import VM, Disk, Nic

LINUX_HINTS = ("linux", "rhel", "centos", "debian", "ubuntu", "sles", "rocky", "alma", "oracle", "photon", "fedora")


def guest_family(guest_id: str) -> str:
    g = guest_id.lower()
    if g.startswith("win"):
        return "windows"
    if any(h in g for h in LINUX_HINTS):
        return "linux"
    return "other"


def parse_notes(notes: str | None) -> dict[str, str]:
    meta: dict[str, str] = {}
    for line in (notes or "").splitlines():
        line = line.strip()
        if line.startswith("runway.") and "=" in line:
            k, v = line[len("runway.") :].split("=", 1)
            meta[k.strip()] = v.strip()
    return meta


def _datastore_of(file_name: str) -> str:
    # "[datastore1] vm/vm.vmdk" -> "datastore1"
    return file_name[1 : file_name.index("]")] if file_name.startswith("[") and "]" in file_name else ""


def _count_snapshots(tree: Any) -> int:
    return sum(1 + _count_snapshots(t.childSnapshotList) for t in tree or [])


def _snapshots(vm: Any) -> int:
    """Snapshot count from the snapshot tree; older and newer API versions disagree on the tree's
    fields, so fall back to the disk layout, which lists one entry per snapshot."""
    try:
        return _count_snapshots(vm.snapshot.rootSnapshotList) if vm.snapshot else 0
    except Exception:
        layout = getattr(vm, "layoutEx", None)
        return len(layout.snapshot) if layout and layout.snapshot else 0


def vm_from_pyvmomi(vm: Any, datastore_types: dict[str, str], portgroups: dict[str, str]) -> VM:
    """Map one pyVmomi VirtualMachine to the runway model."""
    from pyVmomi import vim

    cfg = vm.config
    meta = parse_notes(cfg.annotation)
    disks: list[Disk] = []
    nics: list[Nic] = []
    passthrough: list[str] = []
    vtpm = False
    for dev in cfg.hardware.device:
        if isinstance(dev, vim.vm.device.VirtualDisk):
            b = dev.backing
            name = _datastore_of(getattr(b, "fileName", "") or "")
            rdm = isinstance(b, vim.vm.device.VirtualDisk.RawDiskMappingVer1BackingInfo)
            mode = str(getattr(b, "diskMode", "persistent") or "persistent")
            disks.append(
                Disk(
                    label=dev.deviceInfo.label if dev.deviceInfo else f"disk-{dev.key}",
                    size_gib=round((dev.capacityInKB or 0) / 1024 / 1024, 2),
                    datastore=name,
                    datastore_type=datastore_types.get(name, "vmfs"),
                    mode="independent" if mode.startswith("independent") else "persistent",
                    backing="rdm" if rdm else "flat",
                    encrypted=getattr(b, "keyId", None) is not None,
                )
            )
        elif isinstance(dev, vim.vm.device.VirtualEthernetCard):
            b = dev.backing
            if hasattr(b, "deviceName"):
                pg = b.deviceName
            elif hasattr(b, "port") and b.port is not None:
                pg = portgroups.get(b.port.portgroupKey, b.port.portgroupKey)
            else:
                pg = ""
            nics.append(Nic(pg, dev.macAddress or "", type(dev).__name__.replace("Virtual", "").lower()))
        elif isinstance(dev, vim.vm.device.VirtualPCIPassthrough):
            passthrough.append(meta.get("passthrough", "pci-device"))
        elif type(dev).__name__ == "VirtualTPM":
            vtpm = True
    boot = getattr(cfg, "bootOptions", None)
    tools = vm.guest.toolsStatus if vm.guest else None
    return VM(
        moid=vm._moId,
        name=vm.name,
        guest_family=guest_family(cfg.guestId or ""),
        guest_id=cfg.guestId or "",
        cpus=int(cfg.hardware.numCPU),
        memory_gib=round(cfg.hardware.memoryMB / 1024, 2),
        firmware="efi" if cfg.firmware == "efi" else "bios",
        secure_boot=bool(boot and getattr(boot, "efiSecureBootEnabled", False)),
        vtpm=vtpm or meta.get("vtpm") == "true",
        disks=tuple(disks),
        nics=tuple(nics),
        snapshots=_snapshots(vm),
        tools_installed=tools not in (None, "toolsNotInstalled"),
        passthrough=tuple(passthrough),
        powered_on=str(vm.runtime.powerState) == "poweredOn",
        site=meta.get("site", "hq"),
        app=meta.get("app", ""),
        tier=meta.get("tier", ""),
        depends_on=tuple(d for d in (x.strip() for x in meta.get("depends", "").split(",")) if d),
        anti_affinity=meta.get("anti_affinity", ""),
        owner=meta.get("owner", ""),
    )


@contextmanager
def connect(url: str, user: str, password: str, verify_tls: bool = True) -> Iterator[Any]:
    from pyVim.connect import Disconnect, SmartConnect

    u = urlparse(url)
    ctx = None if verify_tls else ssl._create_unverified_context()
    si = SmartConnect(host=u.hostname, port=u.port or 443, user=user, pwd=password, sslContext=ctx)
    try:
        yield si
    finally:
        Disconnect(si)


def discover(si: Any) -> list[VM]:
    """Every VM (templates excluded) visible to the session, mapped to the runway model."""
    from pyVmomi import vim

    content = si.RetrieveContent()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
    datastore_types = {ds.name: _ds_type(ds.summary.type) for ds in view.view}
    view.Destroy()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.dvs.DistributedVirtualPortgroup], True)
    portgroups = {pg.key: pg.name for pg in view.view}
    view.Destroy()
    view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
    try:
        return sorted(
            (
                vm_from_pyvmomi(v, datastore_types, portgroups)
                for v in view.view
                if v.config is not None and not v.config.template
            ),
            key=lambda v: v.name,
        )
    finally:
        view.Destroy()


def _ds_type(t: str | None) -> str:
    t = (t or "").lower()
    return "vsan" if t == "vsan" else "nfs" if t.startswith("nfs") else "vmfs"


# --- snapshots of an inventory on disk, so plans can be made and reviewed without vCenter


def dump(vms: list[VM], path: Path) -> None:
    path.write_text(json.dumps([asdict(v) for v in vms], indent=1, sort_keys=True) + "\n")


def load(path: Path) -> list[VM]:
    out = []
    for d in json.loads(path.read_text()):
        d["disks"] = tuple(Disk(**x) for x in d.get("disks", []))
        d["nics"] = tuple(Nic(**x) for x in d.get("nics", []))
        for k in ("passthrough", "depends_on"):
            d[k] = tuple(d.get(k, []))
        out.append(VM(**d))
    return out
