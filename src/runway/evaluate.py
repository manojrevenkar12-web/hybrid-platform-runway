"""Run a held-out set (heldout/<set>/) once and pin its first run.

The set was written from heldout/WRITING_CASES.md by someone who had not seen this code. Its first
run is written to reports/heldout/<set>/first_run.json with the sha256 of the set's files and is
never rewritten; later runs go to latest.json, and a changed set is refused.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from runway import calendar, settings
from runway.assess import Assessor
from runway.model import VM, Cluster, Disk, Nic, Node, Verdict
from runway.plan import Planner
from runway.settings import Campaign, Migration, Placement, Target, WindowRule, Windows

ROOT = Path(__file__).resolve().parents[2]


def vm_from(d: dict[str, Any], i: int) -> VM:
    return VM(
        moid=f"vm-{9000 + i}",
        name=str(d["name"]),
        guest_family=str(d.get("guest_family", "linux")),
        guest_id=str(d.get("guest_id", "")),
        cpus=int(d.get("cpus", 2)),
        memory_gib=float(d.get("memory_gib", 4)),
        firmware=str(d.get("firmware", "bios")),
        secure_boot=bool(d.get("secure_boot", False)),
        vtpm=bool(d.get("vtpm", False)),
        disks=tuple(
            Disk(
                str(x.get("label", f"disk{j}")),
                float(x.get("size_gib", 10)),
                str(x.get("datastore", "ds")),
                str(x.get("datastore_type", "vmfs")),
                str(x.get("mode", "persistent")),
                str(x.get("backing", "flat")),
                bool(x.get("encrypted", False)),
            )
            for j, x in enumerate(d.get("disks") or [])
        ),
        nics=tuple(
            Nic(str(n["portgroup"]), str(n.get("mac", f"00:50:56:00:{i // 256:02x}:{i % 256:02x}"))) for n in d.get("nics") or []
        ),
        snapshots=int(d.get("snapshots", 0)),
        tools_installed=bool(d.get("tools_installed", True)),
        passthrough=tuple(d.get("passthrough") or []),
        powered_on=bool(d.get("powered_on", True)),
        site=str(d.get("site", "hq")),
        app=str(d.get("app", "") or ""),
        depends_on=tuple(d.get("depends_on") or []),
        anti_affinity=str(d.get("anti_affinity", "") or ""),
    )


def _vms_part(path: Path) -> dict[str, Any]:
    cases = yaml.safe_load(path.read_text())["vms"]
    a = Assessor()
    rows = []
    for i, c in enumerate(cases):
        got = a.assess(vm_from(c["vm"], i))
        want_rules = set(c["expect"].get("rules", []))
        got_rules = {f.rule for f in got.findings}
        rows.append(
            {
                "id": c["id"],
                "want": c["expect"]["verdict"],
                "got": got.verdict.label,
                "verdict_right": got.verdict.label == c["expect"]["verdict"],
                "rules_right": got_rules == want_rules,
                "missing_rules": sorted(want_rules - got_rules),
                "extra_rules": sorted(got_rules - want_rules),
            }
        )
    n = len(rows)
    should_block = [r for r in rows if r["want"] == "blocked"]
    return {
        "cases": n,
        "verdict_right": round(sum(r["verdict_right"] for r in rows) / n, 4) if n else None,
        "rules_right": round(sum(r["rules_right"] for r in rows) / n, 4) if n else None,
        "blocked_vms_let_through": sum(r["got"] != "blocked" for r in should_block),
        "rows": rows,
    }


def _scenario(sc: dict[str, Any], base: Target) -> dict[str, Any]:
    tz = sc.get("timezone", "Europe/Berlin")
    w = Windows(
        timezone=tz,
        maintenance=tuple(WindowRule(tuple(r["days"]), str(r["start"]), float(r["hours"])) for r in sc["maintenance_windows"]),
        migration=Migration(
            **{
                k: sc["migration"][k]
                for k in ("copy_mib_per_s", "per_vm_overhead_min", "rollback_reserve_share", "max_vms_per_wave")
            }
        ),
        campaigns=tuple(
            Campaign(
                c["name"],
                datetime.fromisoformat(str(c["t0"])),
                tuple(c.get("sites", [])),
                timedelta(days=float(c.get("before_days", 14))),
                timedelta(days=float(c.get("after_days", 2))),
            )
            for c in sc.get("campaigns", []) or []
        )
        + tuple(
            Campaign(
                b["name"],
                datetime.fromisoformat(str(b["start"])),
                tuple(b.get("sites", [])),
                timedelta(0),
                datetime.fromisoformat(str(b["end"])) - datetime.fromisoformat(str(b["start"])),
            )
            for b in sc.get("blackouts", []) or []
        ),
    )
    t = Target(
        clusters=tuple(
            Cluster(
                c["name"],
                c["site"],
                tuple(
                    Node(n["name"], int(n["cores"]), float(n["memory_gib"]), tuple(n.get("devices") or [])) for n in c["nodes"]
                ),
                c.get("storage", f"{c['name']}-storage"),
                float(c.get("storage_gib", 1e9)),
            )
            for c in sc["clusters"]
        ),
        placement=Placement(float(sc.get("cpu_overcommit", 4)), True),
        network_map=base.network_map,
    )
    vms = [vm_from(v, i) for i, v in enumerate(sc["vms"])]
    assessed = Assessor(target=t).assess_all(vms)
    plan = Planner(t, w).plan(assessed, datetime.fromisoformat(str(sc["start"])), datetime.fromisoformat(str(sc["until"])))
    placed = {p.vm.name: (w_.slot, p) for w_ in plan.waves for p in w_.placements}
    first: dict[str, datetime] = {}
    last: dict[str, datetime] = {}
    for w_ in plan.waves:
        for p in w_.placements:
            g = p.vm.group
            first[g] = min(first.get(g, w_.slot.start), w_.slot.start)
            last[g] = max(last.get(g, w_.slot.start), w_.slot.start)
    e = sc.get("expect", {})
    checks: list[tuple[str, bool]] = []
    for g in e.get("unplaced", []) or []:
        checks.append((f"unplaced {g}", g in plan.unplaced))
    for v in e.get("placed", []) or []:
        checks.append((f"placed {v}", v in placed))
    for v in e.get("blocked", []) or []:
        checks.append((f"blocked {v}", any(b.vm.name == v for b in plan.blocked)))
    for dep, dependent in e.get("order", []) or []:
        ok = dep not in last or dependent not in first or last[dep] <= first[dependent]
        checks.append((f"order {dep} before {dependent}", ok and dependent in first))
    for start, end, site in e.get("no_wave_between", []) or []:
        s0, s1 = datetime.fromisoformat(str(start)), datetime.fromisoformat(str(end))
        bad = [n for n, (slot, p) in placed.items() if p.vm.site == site and slot.overlaps(s0, s1)]
        checks.append((f"no {site} wave {start}..{end}", not bad))
    for a_, b_ in e.get("not_same_node", []) or []:
        ok = a_ in placed and b_ in placed and placed[a_][1].node != placed[b_][1].node
        checks.append((f"{a_} and {b_} apart", ok))
    if "waves_at_most" in e:
        slots = {w_.slot for w_ in plan.waves}
        checks.append((f"at most {e['waves_at_most']} windows", len(slots) <= int(e["waves_at_most"])))
    # invariants the guide states, checked on every scenario whatever its expectations say
    inv: list[str] = []
    for w_ in plan.waves:
        if calendar.frozen_by(w, w_.site, w_.slot):
            inv.append(f"wave {w_.index} at {w_.site} in a freeze")
    for slot in {w_.slot for w_ in plan.waves}:
        ws = [x for x in plan.waves if x.slot == slot]
        if sum(x.minutes for x in ws) > slot.minutes * (1 - w.migration.rollback_reserve_share) + 1e-6:
            inv.append(f"window {slot.start} over budget")
        if sum(len(x.placements) for x in ws) > w.migration.max_vms_per_wave:
            inv.append(f"window {slot.start} over the VM limit")
    for load in plan.loads.values():
        if sum(n.mem_gib for n in load.nodes) > load.mem_after_node_loss() + 1e-6:
            inv.append(f"{load.cluster.name} cannot lose its largest node")
        for n in load.nodes:
            if n.mem_gib > n.memory_gib + 1e-6:
                inv.append(f"{n.name} memory overcommitted")
    sizes: dict[str, int] = {}
    for a in assessed:
        if a.verdict != Verdict.BLOCKED and a.vm.anti_affinity:
            sizes[a.vm.anti_affinity] = sizes.get(a.vm.anti_affinity, 0) + 1
    per_node: dict[tuple[str, str], int] = {}
    for _n, (_slot, p) in placed.items():
        if p.vm.anti_affinity:
            per_node[(p.vm.anti_affinity, p.node)] = per_node.get((p.vm.anti_affinity, p.node), 0) + 1
    for (grp, node), cnt in per_node.items():
        nodes = next(len(c.nodes) for c in t.clusters if any(n.name == node for n in c.nodes))
        if cnt > math.ceil(sizes[grp] / nodes):
            inv.append(f"anti-affinity {grp} has {cnt} on {node}")
    return {
        "id": sc["id"],
        "checks": [{"check": c, "ok": ok} for c, ok in checks],
        "all_ok": all(ok for _, ok in checks),
        "invariant_violations": inv,
    }


def _scenarios_part(path: Path) -> dict[str, Any]:
    base = settings.target()
    rows = [_scenario(sc, base) for sc in yaml.safe_load(path.read_text())["scenarios"]]
    checks = [c for r in rows for c in r["checks"]]
    return {
        "scenarios": len(rows),
        "scenarios_fully_right": sum(r["all_ok"] for r in rows),
        "checks": len(checks),
        "checks_right": sum(c["ok"] for c in checks),
        "invariant_violations": sum(len(r["invariant_violations"]) for r in rows),
        "rows": rows,
    }


def evaluate(set_dir: Path) -> dict[str, Any]:
    vms = _vms_part(set_dir / "vms.yaml")
    sc = _scenarios_part(set_dir / "scenarios.yaml")
    headline = (
        f"{vms['cases']} VMs: verdict right {100 * (vms['verdict_right'] or 0):.1f}%, every rule right {100 * (vms['rules_right'] or 0):.1f}%, "
        f"blocked VMs let through {vms['blocked_vms_let_through']}; {sc['scenarios']} plans: {sc['scenarios_fully_right']} fully right, "
        f"{sc['checks_right']}/{sc['checks']} checks, invariant violations {sc['invariant_violations']}."
    )
    return {"headline": headline, "vms": vms, "scenarios": sc}


def sha(set_dir: Path) -> str:
    h = hashlib.sha256()
    for f in ("vms.yaml", "scenarios.yaml"):
        h.update((set_dir / f).read_bytes())
    return h.hexdigest()


def run(name: str, root: Path = ROOT) -> dict[str, Any]:
    set_dir = root / "heldout" / name
    out = root / "reports" / "heldout" / name
    out.mkdir(parents=True, exist_ok=True)
    report = evaluate(set_dir)
    first = out / "first_run.json"
    digest = sha(set_dir)
    if first.exists():
        if json.loads(first.read_text())["sha256"] != digest:
            raise SystemExit(f"{name}: the set changed after its first run")
        (out / "latest.json").write_text(json.dumps(report, indent=2) + "\n")
    else:
        status = (set_dir / "STATUS").read_text().strip()
        first.write_text(
            json.dumps(
                {
                    "set": name,
                    "status_at_first_run": status,
                    "sha256": digest,
                    "ran_at": datetime.now(UTC).isoformat(timespec="seconds"),
                    **report,
                },
                indent=2,
            )
            + "\n"
        )
    return report
