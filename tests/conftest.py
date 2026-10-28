from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from runway import settings
from runway.fake_pve import FakePVE, Faults
from runway.model import VM, Disk, Nic
from runway.proxmox import Proxmox

TZ = ZoneInfo("Europe/Berlin")
TOKEN = "runway@pve!ci=secret"


def vm(name: str, **kw: object) -> VM:
    base: dict[str, object] = {
        "moid": f"vm-{abs(hash(name)) % 9000 + 1}",
        "name": name,
        "guest_family": "linux",
        "guest_id": "rhel9_64Guest",
        "cpus": 2,
        "memory_gib": 4.0,
        "disks": (Disk("Hard disk 1", 40, "hq-ds-1"),),
        "nics": (Nic("pg-servers-110", "00:50:56:aa:bb:01"),),
        "site": "hq",
    }
    base.update(kw)
    return VM(**base)  # type: ignore[arg-type]


@pytest.fixture
def target() -> settings.Target:
    return settings.target()


@pytest.fixture
def windows() -> settings.Windows:
    return settings.windows()


def fake_pve(faults: Faults | None = None) -> tuple[FakePVE, Proxmox]:
    t = settings.target()
    fake = FakePVE({n.name: n.memory_gib for c in t.clusters for n in c.nodes}, faults)
    return fake, Proxmox(TestClient(fake.app), token=TOKEN, poll_s=0)


def at(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=TZ)
