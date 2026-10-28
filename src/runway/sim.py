"""A fictional VMware estate of a launch-services company, for demos, drills and the console.

Three sites: headquarters (hq), the factory with its test stands (factory) and the launch site
(launch). The estate carries the things that make a VMware exit hard in practice: Windows guests,
UEFI and vTPM, snapshots, vSAN and encrypted disks, a raw device mapping, GPUs passed through to
ML training, an operational-technology VLAN, and applications that depend on each other.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from runway.model import VM, Disk, Nic


@dataclass(frozen=True)
class App:
    name: str
    site: str
    count: int
    family: str
    cpus: int
    mem: float
    disk: float
    pg: str
    depends: tuple[str, ...] = ()
    anti: bool = False
    tier: str = "business"
    owner: str = "it-ops"


APPS = [
    App("ad", "hq", 3, "windows", 4, 16, 120, "pg-servers-110", (), True, "core", "identity"),
    App("dns", "hq", 2, "linux", 2, 4, 40, "pg-servers-110", (), True, "core", "network"),
    App("ad-factory", "factory", 2, "windows", 4, 16, 120, "pg-servers-110", ("ad",), True, "core", "identity"),
    App("plm-db", "hq", 2, "linux", 16, 128, 2000, "pg-db-120", ("ad",), True, "critical", "engineering-it"),
    App("plm", "hq", 6, "windows", 8, 32, 200, "pg-servers-110", ("plm-db", "ad", "dns"), True, "critical", "engineering-it"),
    App("cad-licenses", "hq", 2, "windows", 2, 8, 80, "pg-servers-110", ("ad",), True, "critical", "engineering-it"),
    App("git", "hq", 3, "linux", 8, 32, 1500, "pg-servers-110", ("ad", "dns"), True, "critical", "devops"),
    App("artifacts", "hq", 2, "linux", 8, 32, 4000, "pg-servers-110", ("ad", "dns"), True, "critical", "devops"),
    App("ci-runners", "hq", 12, "linux", 8, 16, 200, "pg-lab-400", ("git", "artifacts"), False, "business", "devops"),
    App("monitoring", "hq", 3, "linux", 4, 16, 500, "pg-mgmt-10", ("dns",), True, "core", "it-ops"),
    App("jump-hosts", "hq", 2, "linux", 2, 4, 40, "pg-mgmt-10", ("ad",), True, "core", "it-ops"),
    App("file-server", "hq", 2, "windows", 4, 16, 6000, "pg-servers-110", ("ad",), True, "business", "it-ops"),
    App("hr-portal", "hq", 2, "linux", 4, 8, 100, "pg-dmz-200", ("ad",), True, "business", "hr-it"),
    App("data-lake", "hq", 6, "linux", 16, 64, 3000, "pg-db-120", ("dns",), True, "business", "data"),
    App("ml-training", "hq", 4, "linux", 32, 256, 1000, "pg-lab-400", ("data-lake",), False, "business", "data"),
    App("dev-desktops", "hq", 20, "windows", 4, 16, 120, "pg-lab-400", ("ad",), False, "business", "it-ops"),
    App("test-builds", "hq", 30, "linux", 2, 8, 60, "pg-lab-400", ("git",), False, "lab", "devops"),
    App(
        "mes", "factory", 4, "windows", 8, 32, 300, "pg-servers-110", ("ad-factory", "plm"), True, "critical", "manufacturing-it"
    ),
    App("mes-db", "factory", 2, "linux", 16, 96, 1500, "pg-db-120", ("ad-factory",), True, "critical", "manufacturing-it"),
    App("test-stand-ingest", "factory", 6, "linux", 8, 32, 800, "pg-ot-310", ("data-lake",), True, "critical", "test-data"),
    App("historian", "factory", 2, "windows", 8, 32, 2500, "pg-ot-310", ("ad-factory",), True, "critical", "test-data"),
    App("factory-desktops", "factory", 25, "windows", 2, 8, 100, "pg-lab-400", ("ad-factory",), False, "business", "it-ops"),
    App("range-telemetry", "launch", 6, "linux", 8, 32, 500, "pg-ot-310", (), True, "critical", "launch-ops"),
    App("launch-control-support", "launch", 6, "windows", 4, 16, 200, "pg-servers-110", (), True, "critical", "launch-ops"),
]

LINUX_IDS = ["rhel9_64Guest", "debian12_64Guest", "rhel8_64Guest", "ubuntu64Guest", "rockylinux_64Guest"]
WINDOWS_IDS = ["windows2019srv_64Guest", "windows2022srvNext_64Guest", "windows9_64Guest"]


def estate(seed: int = 26) -> list[VM]:
    rnd = random.Random(seed)
    vms: list[VM] = []
    for app in APPS:
        for i in range(1, app.count + 1):
            name = f"{app.site}-{app.name}-{i:02d}"
            win = app.family == "windows"
            guest = rnd.choice(WINDOWS_IDS if win else LINUX_IDS)
            desktop = guest == "windows9_64Guest" or app.name.endswith("desktops")
            if desktop:
                guest = "windows9_64Guest"
            efi = win or rnd.random() < 0.35
            ds_type = "vsan" if app.site == "factory" and rnd.random() < 0.18 else "vmfs"
            ds = f"{app.site}-{'vsan' if ds_type == 'vsan' else 'ds'}-{rnd.randint(1, 4)}"
            disks = [Disk("Hard disk 1", round(min(app.disk, 120) if app.disk > 120 else app.disk, 1), ds, ds_type)]
            if app.disk > 120:
                disks.append(
                    Disk(
                        "Hard disk 2",
                        round(app.disk - 120, 1),
                        ds,
                        ds_type,
                        "independent" if app.name.endswith("-db") and rnd.random() < 0.4 else "persistent",
                    )
                )
            if app.name == "hr-portal":
                disks = [Disk(d.label, d.size_gib, d.datastore, d.datastore_type, d.mode, d.backing, True) for d in disks]
            if app.name == "plm-db" and i == 2:
                disks.append(Disk("Hard disk 3", 500, ds, "vmfs", "persistent", "rdm"))
            if app.name == "artifacts" and i == 2:
                disks = [Disk(d.label, d.size_gib, "hq-ds+legacy", "vmfs") for d in disks]
            pg = app.pg
            if app.name == "historian" and i == 2:
                pg = "pg-legacy-999"
            mac = f"00:50:56:{rnd.randint(0, 63):02x}:{rnd.randint(0, 255):02x}:{rnd.randint(0, 255):02x}"
            passthrough: tuple[str, ...] = ()
            if app.name == "ml-training":
                passthrough = ("gpu-a100",) if i <= 3 else ("fpga-x",)
            vms.append(
                VM(
                    moid=f"vm-{1000 + len(vms)}",
                    name=name,
                    guest_family="windows" if win else "linux",
                    guest_id=guest,
                    cpus=app.cpus,
                    memory_gib=float(app.mem),
                    firmware="efi" if efi else "bios",
                    secure_boot=efi and win and rnd.random() < 0.5,
                    vtpm=desktop and rnd.random() < 0.6,
                    disks=tuple(disks),
                    nics=(Nic(pg, mac, "vmxnet3" if rnd.random() < 0.85 else "e1000e"),),
                    snapshots=rnd.choice([0, 0, 0, 0, 0, 1, 2]) if app.tier != "lab" else rnd.choice([0, 1, 3]),
                    tools_installed=rnd.random() < 0.95,
                    passthrough=passthrough,
                    powered_on=rnd.random() < 0.97,
                    site=app.site,
                    app=app.name,
                    tier=app.tier,
                    depends_on=app.depends,
                    anti_affinity=app.name if app.anti else "",
                    owner=app.owner,
                )
            )
    return vms
