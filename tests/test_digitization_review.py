"""Tests for the digitization review state machine
(POST /api/log-runs/{lr_id}/review, backend/main.py, commit 66436e1)."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend.main import app  # noqa: E402

client = TestClient(app)


def _h(role: str):
    return {"X-User-Role": role}


SAMPLE_LAS = """~Version Information
VERS.                  2.0 :   CWLS LOG ASCII STANDARD -VERSION 2.0
WRAP.                  NO  :   ONE LINE PER DEPTH STEP
~Well Information
STRT.M              100.000 :
STOP.M              103.000 :
STEP.M                1.000 :
NULL.              -999.25  :
~Curve Information
DEPT.M                   :   DEPTH
GR  .GAPI               :   GAMMA RAY
~ASCII
100.0 50.0
101.0 55.0
102.0 60.0
103.0 65.0
"""


def _make_well_with_run():
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "DigiReviewTestProject"})
    assert proj.status_code == 201
    pid = proj.json()["id"]
    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "DigiReviewWell"})
    assert well.status_code == 201
    wid = well.json()["id"]
    up = client.post(
        f"/api/wells/{wid}/upload-las",
        headers=_h("admin"),
        files={"file": ("digi.las", SAMPLE_LAS.encode(), "text/plain")},
    )
    assert up.status_code == 200
    lr_id = up.json()["log_run_id"]
    return pid, wid, lr_id


# ─── Role gating ────────────────────────────────────────────────

def test_viewer_blocked_with_403():
    r = client.post("/api/log-runs/999999/review", headers=_h("viewer"), json={"status": "accepted"})
    assert r.status_code == 403


def test_interpreter_not_blocked_by_role_guard():
    r = client.post("/api/log-runs/999999/review", headers=_h("interpreter"), json={"status": "accepted"})
    assert r.status_code != 403


def test_admin_not_blocked_by_role_guard():
    r = client.post("/api/log-runs/999999/review", headers=_h("admin"), json={"status": "accepted"})
    assert r.status_code != 403


# ─── Validation ─────────────────────────────────────────────────

def test_invalid_status_returns_400():
    _pid, _wid, lr_id = _make_well_with_run()
    r = client.post(f"/api/log-runs/{lr_id}/review", headers=_h("interpreter"), json={"status": "bogus"})
    assert r.status_code == 400


def test_nonexistent_log_run_returns_404():
    r = client.post("/api/log-runs/999999/review", headers=_h("interpreter"), json={"status": "accepted"})
    assert r.status_code == 404


# ─── Full round trip ────────────────────────────────────────────

def test_default_status_is_pending_review_on_creation():
    _pid, wid, lr_id = _make_well_with_run()
    well = client.get(f"/api/wells/{wid}").json()
    run = next(r for r in well["log_runs"] if r["id"] == lr_id)
    assert run["digitization_status"] == "pending_review"


def test_accept_then_reject_round_trip():
    _pid, wid, lr_id = _make_well_with_run()

    accepted = client.post(
        f"/api/log-runs/{lr_id}/review",
        headers=_h("interpreter"),
        json={"status": "accepted", "reviewer": "qa-bot"},
    )
    assert accepted.status_code == 200
    body = accepted.json()
    assert body["digitization_status"] == "accepted"
    assert body["reviewed_by"] == "qa-bot"
    assert body["reviewed_at"] is not None

    well = client.get(f"/api/wells/{wid}").json()
    run = next(r for r in well["log_runs"] if r["id"] == lr_id)
    assert run["digitization_status"] == "accepted"
    assert run["reviewed_by"] == "qa-bot"
    assert run["reviewed_at"] is not None

    rejected = client.post(
        f"/api/log-runs/{lr_id}/review",
        headers=_h("interpreter"),
        json={"status": "rejected", "notes": "digits don't match scan at 101m"},
    )
    assert rejected.status_code == 200
    rbody = rejected.json()
    assert rbody["digitization_status"] == "rejected"
    assert rbody["digitization_notes"] == "digits don't match scan at 101m"

    well2 = client.get(f"/api/wells/{wid}").json()
    run2 = next(r for r in well2["log_runs"] if r["id"] == lr_id)
    assert run2["digitization_status"] == "rejected"
    assert run2["digitization_notes"] == "digits don't match scan at 101m"
