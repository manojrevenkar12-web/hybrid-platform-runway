"""Settings live in config/; this module only reads them."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from runway.model import Cluster, Node

CONFIG_DIR = Path(os.environ.get("RUNWAY_CONFIG", Path(__file__).resolve().parents[2] / "config"))


def load(name: str, root: Path | None = None) -> dict[str, Any]:
    data = yaml.safe_load(((root or CONFIG_DIR) / name).read_text())
    return data if isinstance(data, dict) else {}


@dataclass(frozen=True)
class Placement:
    cpu_overcommit: float
    survive_node_loss: bool


@dataclass(frozen=True)
class Target:
    clusters: tuple[Cluster, ...]
    placement: Placement
    network_map: dict[str, tuple[str, int]]


def target(root: Path | None = None) -> Target:
    raw = load("target.yaml", root)
    clusters = tuple(
        Cluster(
            name=c["name"],
            site=c["site"],
            nodes=tuple(
                Node(n["name"], int(n["cores"]), float(n["memory_gib"]), tuple(n.get("devices", []))) for n in c["nodes"]
            ),
            storage=c["storage"]["name"],
            storage_gib=float(c["storage"]["capacity_gib"]),
        )
        for c in raw["clusters"]
    )
    p = raw.get("placement", {})
    return Target(
        clusters=clusters,
        placement=Placement(float(p.get("cpu_overcommit", 4.0)), bool(p.get("survive_node_loss", True))),
        network_map={k: (v["bridge"], int(v["vlan"])) for k, v in raw.get("network_map", {}).items()},
    )


@dataclass(frozen=True)
class Migration:
    copy_mib_per_s: float
    per_vm_overhead_min: float
    rollback_reserve_share: float
    max_vms_per_wave: int


@dataclass(frozen=True)
class WindowRule:
    days: tuple[str, ...]
    start: str
    hours: float


@dataclass(frozen=True)
class Campaign:
    name: str
    t0: datetime
    sites: tuple[str, ...]
    freeze_before: timedelta
    freeze_after: timedelta

    @property
    def freeze_start(self) -> datetime:
        return self.t0 - self.freeze_before

    @property
    def freeze_end(self) -> datetime:
        return self.t0 + self.freeze_after


@dataclass(frozen=True)
class Windows:
    timezone: str
    maintenance: tuple[WindowRule, ...]
    migration: Migration
    campaigns: tuple[Campaign, ...]


def windows(root: Path | None = None) -> Windows:
    w = load("windows.yaml", root)
    cal = load("launch-calendar.yaml", root)
    policy = w.get("freeze_policy", {})
    m = w["migration"]
    return Windows(
        timezone=w.get("timezone", "UTC"),
        maintenance=tuple(WindowRule(tuple(r["days"]), str(r["start"]), float(r["hours"])) for r in w["maintenance_windows"]),
        migration=Migration(
            float(m["copy_mib_per_s"]),
            float(m["per_vm_overhead_min"]),
            float(m["rollback_reserve_share"]),
            int(m["max_vms_per_wave"]),
        ),
        campaigns=tuple(
            Campaign(
                name=c["name"],
                t0=datetime.fromisoformat(str(c["t0"])),
                sites=tuple(c.get("sites", [])),
                freeze_before=timedelta(days=float(c.get("freeze_before_days", policy.get("before_days", 14)))),
                freeze_after=timedelta(days=float(c.get("freeze_after_days", policy.get("after_days", 2)))),
            )
            for c in cal.get("campaigns", [])
        )
        + tuple(
            Campaign(
                name=b["name"],
                t0=datetime.fromisoformat(str(b["start"])),
                sites=tuple(b.get("sites", [])),
                freeze_before=timedelta(0),
                freeze_after=datetime.fromisoformat(str(b["end"])) - datetime.fromisoformat(str(b["start"])),
            )
            for b in cal.get("blackouts", [])
        ),
    )


def rules(root: Path | None = None) -> list[dict[str, Any]]:
    return list(load("rules.yaml", root).get("rules", []))
