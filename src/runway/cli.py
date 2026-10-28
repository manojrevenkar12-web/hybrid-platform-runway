"""runway: leave VMware for Proxmox VE without touching a launch campaign."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

from runway import freeze, inventory, settings, sim, translate
from runway.assess import Assessor
from runway.plan import Planner


def _vms(src: str) -> list:  # type: ignore[type-arg]
    return sim.estate() if src == "sim" else inventory.load(Path(src))


def _date(s: str | None, tz: ZoneInfo) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=tz) if s else datetime.now(tz)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="runway", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("inventory", help="read the estate from vCenter into a JSON file")
    i.add_argument("--vcenter", default=os.environ.get("RUNWAY_VCENTER_URL"))
    i.add_argument("--user", default=os.environ.get("RUNWAY_VCENTER_USER"))
    i.add_argument("--password-env", default="RUNWAY_VCENTER_PASSWORD")
    i.add_argument("--insecure", action="store_true", help="skip TLS verification (lab and simulator only)")
    i.add_argument("--out", type=Path, required=True)

    for name, helptext in (
        ("assess", "verdict per VM"),
        ("plan", "waves, placements, freezes"),
        ("generate", "Terraform and Ansible per wave"),
    ):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("inventory", help="inventory JSON, or 'sim' for the fictional estate")
        p.add_argument("--start")
        p.add_argument("--until")
        p.add_argument("--out", type=Path)

    d = sub.add_parser("drill", help="cutover drill against a failing Proxmox; exits 1 on any invariant violation")
    d.add_argument("--import-failures", type=float, default=0.1)
    d.add_argument("--agent-failures", type=float, default=0.05)
    d.add_argument("--api-errors", type=float, default=0.02)
    d.add_argument("--restart-failure-every", type=int, default=17)
    d.add_argument("--crash-every", type=int, default=9)
    d.add_argument("--seed", type=int, default=11)
    d.add_argument("--out", type=Path)

    f = sub.add_parser("freeze", help="launch freezes for Argo CD and GitLab, or check one site now")
    f.add_argument("what", choices=["argocd", "gitlab", "check"])
    f.add_argument("--site", default="hq")
    f.add_argument("--at", help="ISO time to check instead of now")
    f.add_argument("--clusters", type=Path, default=settings.CONFIG_DIR / "gitops.yaml")
    f.add_argument("--check", type=Path, help="argocd: compare a committed AppProject with the calendar instead of printing one")

    sub.add_parser("serve", help="the API behind the console").add_argument("--port", type=int, default=8070)

    a = ap.parse_args(argv)
    w = settings.windows()
    tz = ZoneInfo(w.timezone)

    if a.cmd == "inventory":
        if not a.vcenter or not a.user:
            ap.error("--vcenter and --user (or RUNWAY_VCENTER_URL/USER) are required")
        with inventory.connect(a.vcenter, a.user, os.environ.get(a.password_env, ""), verify_tls=not a.insecure) as si:
            vms = inventory.discover(si)
        inventory.dump(vms, a.out)
        print(f"{len(vms)} VMs written to {a.out}")
        return 0

    if a.cmd in ("assess", "plan", "generate"):
        t = settings.target()
        assessed = Assessor(target=t).assess_all(_vms(a.inventory))
        if a.cmd == "assess":
            print(json.dumps(dict(Counter(x.verdict.label for x in assessed)), indent=2))
            for x in assessed:
                if x.findings:
                    print(f"{x.vm.name:40} {x.verdict.label:9} {', '.join(f.rule for f in x.findings if f.verdict.value)}")
            return 0
        start = _date(a.start, tz)
        until = _date(a.until, tz) if a.until else start + timedelta(days=180)
        plan = Planner(t, w).plan(assessed, start, until)
        if a.cmd == "plan":
            doc = {
                "waves": [
                    {
                        "wave": x.index,
                        "site": x.site,
                        "start": x.slot.start.isoformat(),
                        "groups": x.groups,
                        "minutes": round(x.minutes),
                        "vms": [{"vm": p.vm.name, "node": p.node} for p in x.placements],
                    }
                    for x in plan.waves
                ],
                "blocked": {b.vm.name: [f.rule for f in b.findings if f.verdict.value == 2] for b in plan.blocked},
                "unplaced": plan.unplaced,
                "skipped_for_freeze": [
                    {"start": s.start.isoformat(), "site": site, "campaign": c} for s, site, c in plan.skipped_for_freeze
                ],
            }
            text = json.dumps(doc, indent=2)
            (a.out.write_text(text + "\n") if a.out else print(text))
            return 0
        files = translate.write(plan, assessed, t.network_map, a.out or Path("generated"))
        print(f"{len(files)} files written under {a.out or 'generated'}")
        return 0

    if a.cmd == "drill":
        from runway.drill import run
        from runway.fake_pve import Faults

        r = run(
            Faults(a.import_failures, a.agent_failures, a.api_errors, a.seed),
            start_failure_every=a.restart_failure_every,
            crash_every=a.crash_every,
        )
        n = r.numbers
        n["headline"] = (
            f"{n['vms']} cutovers under {a.import_failures:.0%} failed imports, {a.agent_failures:.0%} silent guests, {a.api_errors:.0%} API errors "
            f"and {n['faults']['executor_crashes']} executor crashes: {n['done']} moved, {n['rolled_back']} rolled back, {n['needs_person']} handed to a person; "
            f"running on both sides {n['running_on_both_sides']}, running nowhere unannounced {n['running_nowhere_untold']}."
        )
        n["violations"] = r.violations
        text = json.dumps(n, indent=2)
        if a.out:
            a.out.parent.mkdir(parents=True, exist_ok=True)
            a.out.write_text(text + "\n")
        print(text)
        return 1 if r.violations else 0

    if a.cmd == "freeze":
        now = datetime.fromisoformat(a.at) if a.at else datetime.now(UTC)
        if a.what == "check":
            c = freeze.check(w, a.site, now)
            if c is None:
                print(f"{a.site}: not frozen at {now.isoformat()}")
                return 0
            approver = os.environ.get("EMERGENCY_CHANGE_APPROVED_BY")
            if approver:
                print(f"{a.site}: frozen for {c.name} until {c.freeze_end.isoformat()}; emergency change approved by {approver}")
                return 0
            print(
                f"{a.site}: frozen for {c.name} until {c.freeze_end.isoformat()}. Set EMERGENCY_CHANGE_APPROVED_BY to override."
            )
            return 1
        clusters = yaml.safe_load(a.clusters.read_text())["site_clusters"]
        if a.what == "argocd" and a.check:
            want = freeze.argocd_sync_windows(w, clusters, now)
            have = yaml.safe_load(a.check.read_text())["spec"].get("syncWindows", [])
            missing = [x["description"] for x in want if x not in have]
            stale = [x.get("description", x.get("schedule")) for x in have if x not in want]
            for d in stale:
                print(f"::warning::{a.check}: '{d}' has ended or changed; regenerate with `runway freeze argocd`")
            if missing:
                print(f"{a.check} is missing current freezes: {', '.join(missing)}. Regenerate with `runway freeze argocd`.")
                return 1
            print(f"{a.check}: every current freeze is enforced")
            return 0
        if a.what == "argocd":
            print(yaml.safe_dump(freeze.argocd_project(w, clusters, now), sort_keys=False))
        else:
            print(json.dumps(freeze.gitlab_freeze_periods(w, now), indent=2))
        return 0

    if a.cmd == "serve":
        import uvicorn

        uvicorn.run("runway.api:create_app", factory=True, host="0.0.0.0", port=a.port)
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
