"""The API the console uses, the freeze enforcers, and the cutover drill's invariants."""

from __future__ import annotations

import os
from datetime import timedelta
from pathlib import Path

import pytest
import yaml
from conftest import at
from fastapi.testclient import TestClient

from runway import freeze, settings
from runway.api import State, create_app
from runway.cli import main
from runway.drill import run
from runway.fake_pve import Faults


@pytest.fixture(scope="module")
def client(tmp_path_factory: pytest.TempPathFactory) -> TestClient:
    start = at(2026, 11, 16)
    state = State(start, start + timedelta(days=180), Faults(import_failure_rate=0.2, seed=3), tmp_path_factory.mktemp("api"))
    return TestClient(create_app(state))


def test_summary_and_vms(client: TestClient) -> None:
    s = client.get("/api/summary").json()
    assert s["estate"]["vms"] == sum(s["verdicts"].values())
    assert s["plan"]["placed"] + s["verdicts"]["blocked"] == s["estate"]["vms"]
    assert s["plan"]["windowsSkippedForFreezes"] > 0
    assert {b["rule"] for b in s["blockers"]} >= {"vsan-disk", "no-target-cluster"}
    blocked = client.get("/api/vms", params={"verdict": "blocked"}).json()
    assert blocked and all(r["wave"] is None for r in blocked)
    detail = client.get(f"/api/vms/{client.get('/api/vms', params={'q': 'plm-01'}).json()[0]['name']}").json()
    assert detail["terraform"]["bios"] == "ovmf" and detail["ansible"]["runway_windows_virtio"] is True
    assert any(f["rule"] == "windows-virtio" and f["source"].startswith("https://") for f in detail["findingsDetail"])
    assert client.get("/api/vms/nope").status_code == 404


def test_running_a_wave_and_checking_drift(client: TestClient) -> None:
    waves = client.get("/api/waves").json()
    assert all(w["minutes"] <= w["budgetMinutes"] or w["site"] for w in waves)
    r = client.post(f"/api/waves/{waves[0]['index']}/run").json()
    results = {o["result"] for o in r["outcomes"]}
    assert results <= {"done", "rolled_back", "skipped"}
    assert client.get("/api/waves").json()[0]["status"] == "done"
    d = client.get("/api/drift").json()
    assert d["drift"] == [] and d["missingAfterCutover"] == []
    assert "runway_cutover_outcomes_total" in client.get("/metrics").text


def test_calendar_and_capacity(client: TestClient) -> None:
    c = client.get("/api/calendar").json()
    assert {f["name"] for f in c["freezes"]} >= {"flight-3", "year-end"}
    assert all(s["campaign"] for s in c["skipped"])
    cap = client.get("/api/capacity").json()
    for cl in cap:
        assert sum(n["plannedGib"] for n in cl["nodes"]) <= cl["memoryAfterNodeLossGib"]


def test_api_token_is_enforced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("RUNWAY_API_TOKEN", "t0k")
    start = at(2026, 11, 16)
    c = TestClient(create_app(State(start, start + timedelta(days=30), Faults(), tmp_path)))
    assert c.get("/api/summary").status_code == 401
    assert c.get("/api/summary", headers={"Authorization": "Bearer t0k"}).status_code == 200
    assert c.get("/healthz").status_code == 200


class TestFreeze:
    def test_argocd_windows_cover_the_freeze_and_only_its_sites(self) -> None:
        w = settings.windows()
        clusters = yaml.safe_load((settings.CONFIG_DIR / "gitops.yaml").read_text())["site_clusters"]
        wins = freeze.argocd_sync_windows(w, clusters, at(2026, 11, 1))
        f3 = next(x for x in wins if x["schedule"] == "0 11 26 11 *")
        assert f3 == {
            **f3,
            "kind": "deny",
            "schedule": "0 11 26 11 *",
            "duration": "384h",
            "clusters": ["k8s-launch-edge", "ocp-hq"],
            "manualSync": False,
        }
        assert next(x for x in wins if x["schedule"] == "0 0 21 12 *")["clusters"] == ["k8s-launch-edge", "ocp-factory", "ocp-hq"]
        # an ended freeze is dropped, so a yearly cron cannot bring it back next year
        assert not [x for x in freeze.argocd_sync_windows(w, clusters, at(2027, 6, 1)) if x["schedule"] == "0 11 26 11 *"]

    def test_gitlab_freeze_periods(self) -> None:
        periods = freeze.gitlab_freeze_periods(settings.windows(), at(2026, 11, 1))
        assert periods[0] == {"freeze_start": "0 11 26 11 *", "freeze_end": "0 11 12 12 *", "cron_timezone": "Europe/Berlin"}

    def test_the_gate_and_its_audited_override(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        assert main(["freeze", "check", "--site", "hq", "--at", "2026-12-01T12:00:00+01:00"]) == 1
        assert main(["freeze", "check", "--site", "factory", "--at", "2026-12-01T12:00:00+01:00"]) == 0
        monkeypatch.setenv("EMERGENCY_CHANGE_APPROVED_BY", "head-of-it-ops")
        assert main(["freeze", "check", "--site", "hq", "--at", "2026-12-01T12:00:00+01:00"]) == 0
        assert "approved by head-of-it-ops" in capsys.readouterr().out


class TestDrill:
    def test_clean_run_moves_everything(self) -> None:
        r = run(Faults())
        assert r.violations == [] and r.numbers["done"] == r.numbers["vms"]

    def test_failures_and_crashes_never_leave_two_copies_or_a_silent_outage(self) -> None:
        r = run(
            Faults(import_failure_rate=0.15, agent_never_rate=0.1, api_error_rate=0.03, seed=29),
            start_failure_every=7,
            crash_every=5,
        )
        assert r.violations == [], r.violations
        n = r.numbers
        assert n["rolled_back"] > 0 and n["executor_restarts"] == n["faults"]["executor_crashes"] > 0
        assert n["done"] + n["rolled_back"] + n["needs_person"] + n["skipped"] == n["vms"]


def test_cli_plan_and_generate(tmp_path: Path) -> None:
    assert main(["plan", "sim", "--start", "2026-11-16", "--out", str(tmp_path / "plan.json")]) == 0
    assert main(["generate", "sim", "--start", "2026-11-16", "--out", str(tmp_path / "gen")]) == 0
    assert list((tmp_path / "gen" / "terraform").glob("wave-*/main.tf"))
    assert os.path.getsize(tmp_path / "plan.json") > 1000
