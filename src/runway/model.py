"""The estate as runway sees it: VMs on vSphere, and the Proxmox VE clusters they move to."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum


class Verdict(IntEnum):
    """How a VM can move. Ordered: a VM gets the worst verdict of its findings."""

    AUTO = 0  # runway does everything
    ATTENTION = 1  # runway does it, after steps a person prepares
    BLOCKED = 2  # someone must change the source first

    @property
    def label(self) -> str:
        return self.name.lower()


@dataclass(frozen=True)
class Disk:
    label: str
    size_gib: float
    datastore: str
    datastore_type: str = "vmfs"  # vmfs | nfs | vsan
    mode: str = "persistent"  # persistent | independent
    backing: str = "flat"  # flat | rdm
    encrypted: bool = False


@dataclass(frozen=True)
class Nic:
    portgroup: str
    mac: str
    adapter: str = "vmxnet3"


@dataclass(frozen=True)
class VM:
    moid: str
    name: str
    guest_family: str  # linux | windows | other
    guest_id: str
    cpus: int
    memory_gib: float
    firmware: str = "bios"  # bios | efi
    secure_boot: bool = False
    vtpm: bool = False
    disks: tuple[Disk, ...] = ()
    nics: tuple[Nic, ...] = ()
    snapshots: int = 0
    tools_installed: bool = True
    passthrough: tuple[str, ...] = ()  # device classes, e.g. "gpu-a100"
    powered_on: bool = True
    site: str = "hq"
    app: str = ""
    tier: str = ""
    depends_on: tuple[str, ...] = ()  # apps this VM's app needs
    anti_affinity: str = ""  # VMs sharing a group never share a node
    owner: str = ""

    @property
    def disk_gib(self) -> float:
        return sum(d.size_gib for d in self.disks)

    @property
    def group(self) -> str:
        """The unit that moves together: the app, or the VM itself when it has none."""
        return self.app or f"vm:{self.name}"


@dataclass(frozen=True)
class Node:
    name: str
    cores: int
    memory_gib: float
    devices: tuple[str, ...] = ()


@dataclass(frozen=True)
class Cluster:
    name: str
    site: str
    nodes: tuple[Node, ...]
    storage: str
    storage_gib: float


@dataclass(frozen=True)
class Finding:
    rule: str
    verdict: Verdict
    why: str
    action: str
    source: str


@dataclass(frozen=True)
class Assessment:
    vm: VM
    findings: tuple[Finding, ...] = field(default_factory=tuple)

    @property
    def verdict(self) -> Verdict:
        return max((f.verdict for f in self.findings), default=Verdict.AUTO)
