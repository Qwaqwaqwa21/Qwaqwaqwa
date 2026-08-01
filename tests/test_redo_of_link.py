"""Tests for the rejected-run -> redo link
(POST /api/log-runs/{lr_id}/redo-of, backend/main.py)."""
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


def _upload_run(wid: int, filename: str = "run.las") -> int:
    up = client.post(
        f"/api/wells/{wid}/upload-las",
        headers=_h("admin"),
        files={"file": (filename, SAMPLE_LAS.encode(), "text/plain")},
    )
    assert up.status_code == 200
    return up.json()["log_run_id"]


def _make_well() -> int:
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "RedoOfTestProject"})
    assert proj.status_code == 201
    pid = proj.json()["id"]
    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "RedoOfWell"})
    assert well.status_code == 201
    return well.json()["id"]


def _make_rejected_and_redo_pair():
    wid = _make_well()
    rejected_id = _upload_run(wid, "orig.las")
    r = client.post(f"/api/log-runs/{rejected_id}/review", headers=_h("interpreter"), json={"status": "rejected"})
    assert r.status_code == 200
    redo_id = _upload_run(wid, "orig_corrected.las")
    return wid, rejected_id, redo_id


# ─── Role gating ────────────────────────────────────────────────

def test_viewer_blocked_with_403():
    r = client.post("/api/log-runs/999999/redo-of", headers=_h("viewer"), json={"redo_of": 1})
    assert r.status_code == 403


def test_interpreter_not_blocked_by_role_guard():
    r = client.post("/api/log-runs/999999/redo-of", headers=_h("interpreter"), json={"redo_of": 1})
    assert r.status_code != 403


# ─── Validation ─────────────────────────────────────────────────

def test_nonexistent_log_run_returns_404():
    r = client.post("/api/log-runs/999999/redo-of", headers=_h("interpreter"), json={"redo_of": 1})
    assert r.status_code == 404


def test_self_redo_returns_400():
    wid, rejected_id, _redo_id = _make_rejected_and_redo_pair()
    r = client.post(f"/api/log-runs/{rejected_id}/redo-of", headers=_h("interpreter"),
                     json={"redo_of": rejected_id})
    assert r.status_code == 400


def test_target_not_rejected_returns_400():
    wid, rejected_id, redo_id = _make_rejected_and_redo_pair()
    # redo_id is still pending_review, so linking rejected_id -> redo_id should fail
    r = client.post(f"/api/log-runs/{rejected_id}/redo-of", headers=_h("interpreter"),
                     json={"redo_of": redo_id})
    assert r.status_code == 400


def test_cross_well_link_returns_400():
    wid, rejected_id, _redo_id = _make_rejected_and_redo_pair()
    other_wid = _make_well()
    other_run_id = _upload_run(other_wid, "other.las")
    r = client.post(f"/api/log-runs/{other_run_id}/redo-of", headers=_h("interpreter"),
                     json={"redo_of": rejected_id})
    assert r.status_code == 400


# ─── Happy path ─────────────────────────────────────────────────

def test_link_redo_sets_redo_of_and_reverse_lookup():
    wid, rejected_id, redo_id = _make_rejected_and_redo_pair()
    r = client.post(f"/api/log-runs/{redo_id}/redo-of", headers=_h("interpreter"),
                     json={"redo_of": rejected_id})
    assert r.status_code == 200
    assert r.json()["redo_of"] == rejected_id

    well = client.get(f"/api/wells/{wid}").json()
    rejected_run = next(x for x in well["log_runs"] if x["id"] == rejected_id)
    redo_run = next(x for x in well["log_runs"] if x["id"] == redo_id)
    assert rejected_run["redone_by"] == redo_id
    assert redo_run["redo_of"] == rejected_id
