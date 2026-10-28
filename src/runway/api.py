"""The runway API behind the control-room console.

Demo mode (the default) assesses the fictional estate, plans it, and runs cutovers against the fake
Proxmox VE API with faults switched on. With RUNWAY_INVENTORY (a JSON dump from `runway inventory`)
it plans a real estate; with RUNWAY_PVE_URL and RUNWAY_PVE_TOKEN it cuts over to a real cluster.
"""

from __future__ import annotations

import os
import tempfile
from collections import Counter as Tally
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Lock
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.testclient import TestClient
from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, generate_latest

from runway import calendar, drift, freeze, inventory, settings, sim, translate
from runway.assess import Assessor
from runway.cutover import Cutover, Journal
from runway.fake_pve import FakePVE, Faults
from runway.model import Assessment, Verdict
from runway.plan import Plan, Planner
from runway.proxmox import Proxmox
from runway.source import FakeSource


class State:
    def __init__(self, start: datetime, until: datetime, faults: Faults, workdir: Path):
        self.target = settings.target()
        self.windows = settings.windows()
        inv = os.environ.get("RUNWAY_INVENTORY")
        self.vms = inventory.load(Path(inv)) if inv else sim.estate()
        self.assessed: list[Assessment] = Assessor(target=self.target).assess_all(self.vms)
        self.by_name = {a.vm.name: a for a in self.assessed}
        self.start, self.until = start, until
        self.plan: Plan = Planner(self.target, self.windows).plan(self.assessed, start, until)
        self.workdir = workdir
        self.generated = workdir / "generated"
        translate.write(self.plan, self.assessed, self.target.network_map, self.generated)
        self.storage = {c.name: c.storage for c in self.target.clusters}
        url, token = os.environ.get("RUNWAY_PVE_URL"), os.environ.get("RUNWAY_PVE_TOKEN")
        if url and token:
            self.fake = None
            self.pve = Proxmox(
                httpx.Client(base_url=url, verify=os.environ.get("RUNWAY_PVE_VERIFY_TLS", "1") == "1", timeout=60), token=token
            )
        else:
            self.fake = FakePVE(
                {n.name: n.memory_gib for c in self.target.clusters for n in c.nodes}, faults, token="runway@pve!demo=secret"
            )
            self.pve = Proxmox(TestClient(self.fake.app), token="runway@pve!demo=secret", poll_s=0)
        self.source = FakeSource(self.vms)
        self.journal = Journal(workdir / "journal.db")
        self.lock = Lock()
        self.registry = CollectorRegistry()
        self.m_vms = Gauge("runway_vms", "VMs by verdict", ["verdict"], registry=self.registry)
        self.m_outcomes = Counter("runway_cutover_outcomes_total", "Cutover outcomes", ["result"], registry=self.registry)
        self.m_frozen = Gauge(
            "runway_site_frozen", "1 while a launch freeze holds the site", ["site", "campaign"], registry=self.registry
        )
        for v in Verdict:
            self.m_vms.labels(v.label).set(sum(a.verdict == v for a in self.assessed))

    def cutover(self) -> Cutover:
        return Cutover(
            self.pve,
            self.source,
            self.journal,
            self.target.network_map,
            self.storage,
            agent_timeout_s=float(os.environ.get("RUNWAY_AGENT_TIMEOUT_S", "0.05")),
            grace_s=0,
            poll_s=0,
        )


def _iso(d: datetime) -> str:
    return d.isoformat()


def create_app(state: State | None = None) -> FastAPI:
    app = FastAPI(title="runway", version="0.1.0")
    tz = ZoneInfo(settings.windows().timezone)
    if state is None:
        start = (
            datetime.fromisoformat(os.environ["RUNWAY_PLAN_START"]) if os.environ.get("RUNWAY_PLAN_START") else datetime.now(tz)
        )
        faults = Faults(
            import_failure_rate=float(os.environ.get("RUNWAY_DEMO_IMPORT_FAILURES", "0.08")),
            agent_never_rate=float(os.environ.get("RUNWAY_DEMO_AGENT_FAILURES", "0.04")),
            seed=5,
        )
        state = State(start, start + timedelta(days=180), faults, Path(tempfile.mkdtemp(prefix="runway-")))
    s = state
    token = os.environ.get("RUNWAY_API_TOKEN")

    def auth(authorization: str | None = Header(default=None)) -> None:
        if token and authorization != f"Bearer {token}":
            raise HTTPException(401, "missing or wrong token")

    def wave_of(name: str) -> int | None:
        w = s.plan.wave_of(name)
        return w.index if w else None

    def placement_of(name: str) -> Any:
        w = s.plan.wave_of(name)
        return next((p for p in w.placements if p.vm.name == name), None) if w else None

    def vm_row(a: Assessment) -> dict[str, Any]:
        p = placement_of(a.vm.name)
        o = s.journal.outcome(a.vm.name)
        return {
            "name": a.vm.name,
            "app": a.vm.app,
            "site": a.vm.site,
            "owner": a.vm.owner,
            "guest": a.vm.guest_family,
            "cpus": a.vm.cpus,
            "memoryGib": a.vm.memory_gib,
            "diskGib": round(a.vm.disk_gib, 1),
            "verdict": a.verdict.label,
            "findings": [f.rule for f in a.findings if f.verdict > Verdict.AUTO],
            "wave": wave_of(a.vm.name),
            "node": p.node if p else None,
            "unplaced": s.plan.unplaced.get(a.vm.group),
            "outcome": o.result if o else None,
        }

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/metrics")
    def metrics() -> Response:
        now = datetime.now(UTC)
        for c in s.windows.campaigns:
            for site in c.sites or [cl.site for cl in s.target.clusters]:
                s.m_frozen.labels(site, c.name).set(1 if c.freeze_start <= now < c.freeze_end else 0)
        return Response(generate_latest(s.registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/api/summary", dependencies=[Depends(auth)])
    def summary() -> dict[str, Any]:
        verdicts = {v.label: sum(a.verdict == v for a in s.assessed) for v in Verdict}
        outcomes = s.journal.outcomes()
        return {
            "estate": {
                "vms": len(s.assessed),
                "memoryGib": sum(a.vm.memory_gib for a in s.assessed),
                "diskTib": round(sum(a.vm.disk_gib for a in s.assessed) / 1024, 1),
            },
            "verdicts": verdicts,
            "plan": {
                "start": _iso(s.start),
                "until": _iso(s.until),
                "waves": len(s.plan.waves),
                "placed": sum(len(w.placements) for w in s.plan.waves),
                "unplaced": len(s.plan.unplaced),
                "lastWave": _iso(s.plan.waves[-1].slot.end) if s.plan.waves else None,
                "windowsSkippedForFreezes": len(s.plan.skipped_for_freeze),
            },
            "cutover": {r: sum(o.result == r for o in outcomes) for r in ("done", "rolled_back", "needs_person", "skipped")},
            "blockers": sorted(
                (
                    {"rule": r, "vms": n}
                    for r, n in Tally(f.rule for a in s.assessed for f in a.findings if f.verdict == Verdict.BLOCKED).items()
                ),
                key=lambda x: -int(x["vms"]),
            ),
        }

    @app.get("/api/vms", dependencies=[Depends(auth)])
    def vms(verdict: str | None = None, site: str | None = None, q: str | None = None) -> list[dict[str, Any]]:
        rows = [vm_row(a) for a in s.assessed]
        if verdict:
            rows = [r for r in rows if r["verdict"] == verdict]
        if site:
            rows = [r for r in rows if r["site"] == site]
        if q:
            rows = [r for r in rows if q.lower() in r["name"].lower() or q.lower() in r["app"].lower()]
        return rows

    @app.get("/api/vms/{name}", dependencies=[Depends(auth)])
    def vm_detail(name: str) -> dict[str, Any]:
        a = s.by_name.get(name)
        if not a:
            raise HTTPException(404, "no such VM")
        p = placement_of(name)
        return {
            **vm_row(a),
            "vm": asdict(a.vm),
            "findingsDetail": [
                {"rule": f.rule, "verdict": f.verdict.label, "why": f.why, "action": f.action, "source": f.source}
                for f in a.findings
            ],
            "terraform": translate.terraform_vm(p, s.target.network_map, s.storage[p.cluster]) if p else None,
            "terraformHcl": translate.hcl({translate.resource_name(a.vm): translate.terraform_vm(p, s.target.network_map, s.storage[p.cluster])}) if p else None,
            "ansible": translate.ansible_vars(a, p) if p else None,
            "steps": s.journal.steps(name),
        }

    @app.get("/api/waves", dependencies=[Depends(auth)])
    def waves() -> list[dict[str, Any]]:
        out = []
        for w in s.plan.waves:
            budget = w.slot.minutes * (1 - s.windows.migration.rollback_reserve_share)
            res = [s.journal.outcome(p.vm.name) for p in w.placements]
            out.append(
                {
                    "index": w.index,
                    "site": w.site,
                    "start": _iso(w.slot.start),
                    "end": _iso(w.slot.end),
                    "groups": w.groups,
                    "vms": len(w.placements),
                    "minutes": round(w.minutes),
                    "budgetMinutes": round(budget),
                    "status": "done" if all(res) else "planned",
                    "outcomes": {
                        r: sum(1 for o in res if o and o.result == r) for r in ("done", "rolled_back", "needs_person", "skipped")
                    },
                }
            )
        return out

    @app.post("/api/waves/{index}/run", dependencies=[Depends(auth)])
    def run_wave(index: int) -> dict[str, Any]:
        w = next((w for w in s.plan.waves if w.index == index), None)
        if not w:
            raise HTTPException(404, "no such wave")
        with s.lock:
            outcomes = s.cutover().run_wave(w.placements)
        for o in outcomes:
            s.m_outcomes.labels(o.result).inc()
        return {"wave": index, "outcomes": [asdict(o) for o in outcomes]}

    @app.get("/api/calendar", dependencies=[Depends(auth)])
    def cal() -> dict[str, Any]:
        return {
            "timezone": s.windows.timezone,
            "freezes": [
                {
                    "name": c.name,
                    "t0": _iso(c.t0),
                    "start": _iso(c.freeze_start),
                    "end": _iso(c.freeze_end),
                    "sites": list(c.sites),
                }
                for c in s.windows.campaigns
            ],
            "slots": [
                {"start": _iso(x.start), "end": _iso(x.end)} for x in calendar.maintenance_slots(s.windows, s.start, s.until)
            ],
            "skipped": [{"start": _iso(sl.start), "site": site, "campaign": c} for sl, site, c in s.plan.skipped_for_freeze],
        }

    @app.get("/api/capacity", dependencies=[Depends(auth)])
    def capacity() -> list[dict[str, Any]]:
        return [
            {
                "cluster": name,
                "site": load.cluster.site,
                "storage": {
                    "name": load.cluster.storage,
                    "usedGib": round(load.disk_gib),
                    "capacityGib": load.cluster.storage_gib,
                },
                "memoryAfterNodeLossGib": load.mem_after_node_loss(),
                "nodes": [
                    {
                        "name": n.name,
                        "memoryGib": n.memory_gib,
                        "plannedGib": n.mem_gib,
                        "cores": n.cores,
                        "plannedVcpus": n.vcpus,
                        "devices": list(n.devices),
                    }
                    for n in load.nodes
                ],
            }
            for name, load in s.plan.loads.items()
        ]

    @app.get("/api/drift", dependencies=[Depends(auth)])
    def drift_report() -> dict[str, Any]:
        d, missing = drift.check(s.pve, s.generated / "terraform")
        done = {o.vm for o in s.journal.outcomes() if o.result == "done"}
        return {
            "drift": [asdict(x) for x in d],
            "notYetOnProxmox": sorted(m for m in missing if m not in done),
            "missingAfterCutover": sorted(m for m in missing if m in done),
        }

    @app.get("/api/freeze/{site}", dependencies=[Depends(auth)])
    def freeze_now(site: str) -> dict[str, Any]:
        c = freeze.check(s.windows, site, datetime.now(UTC))
        return {
            "site": site,
            "frozen": c is not None,
            "campaign": c.name if c else None,
            "until": _iso(c.freeze_end) if c else None,
        }

    return app
