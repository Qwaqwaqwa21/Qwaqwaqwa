"""Tests for the export sign-off gate
(_check_export_signoff, backend/main.py, commit be265b2 / extended in 66436e1)
via the real export-las endpoint."""
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
STOP.M              120.000 :
STEP.M                1.000 :
NULL.              -999.25  :
~Curve Information
DEPT.M                   :   DEPTH
GR  .GAPI               :   GAMMA RAY
~ASCII
""" + "\n".join(f"{100 + i}.0 {50.0 + i}" for i in range(21)) + "\n"


def _make_well_with_run():
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "ExportSignoffTestProject"})
    assert proj.status_code == 201
    pid = proj.json()["id"]
    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "ExportSignoffWell"})
    assert well.status_code == 201
    wid = well.json()["id"]
    up = client.post(
        f"/api/wells/{wid}/upload-las",
        headers=_h("admin"),
        files={"file": ("signoff.las", SAMPLE_LAS.encode(), "text/plain")},
    )
    assert up.status_code == 200
    lr_id = up.json()["log_run_id"]
    return pid, wid, lr_id


def test_export_las_blocked_when_unreviewed_and_unlocked():
    _pid, wid, _lr_id = _make_well_with_run()
    r = client.get(f"/api/wells/{wid}/export-las")
    assert r.status_code == 409
    detail = r.json()["detail"]
    assert "signed off" in detail["detail"].lower()


def test_export_las_force_bypasses_gate():
    _pid, wid, _lr_id = _make_well_with_run()
    r = client.get(f"/api/wells/{wid}/export-las", params={"force": "true"})
    assert r.status_code == 200
    assert "~Version Information" in r.text


def test_accepting_review_drops_digitization_issue_from_409():
    _pid, wid, lr_id = _make_well_with_run()

    before = client.get(f"/api/wells/{wid}/export-las")
    assert before.status_code == 409
    before_issues = " ".join(before.json()["detail"]["issues"]).lower()
    assert "review" in before_issues or "digitiz" in before_issues

    review = client.post(
        f"/api/log-runs/{lr_id}/review",
        headers=_h("interpreter"),
        json={"status": "accepted"},
    )
    assert review.status_code == 200

    after = client.get(f"/api/wells/{wid}/export-las")
    assert after.status_code == 409  # still blocked: not locked/signed off yet
    after_issues = " ".join(after.json()["detail"]["issues"]).lower()
    assert "review" not in after_issues
    assert "digitiz" not in after_issues
    # sign-off (lock) issue must still be present
    assert "signed off" in after.json()["detail"]["detail"].lower()


SURVEY_LAS = lambda n, stop: """~Version Information
VERS.                  2.0 :
WRAP.                  NO  :
~Well Information
STRT.M              100.000 :
STOP.M              %d.000 :
STEP.M                1.000 :
NULL.              -999.25  :
~Curve Information
MD  .M                   :   MEASURED DEPTH
INKL.DEG                :   INCLINATION
AZIM.DEG                :   AZIMUTH
~ASCII
""" % stop + "\n".join(f"{100 + i}.0 {2.0 + 0.1 * i} {10.0 + i}" for i in range(n)) + "\n"


def test_second_survey_shaped_run_does_not_block_digitization_gate():
    """When a well has two MD/INKL/AZIM-only (deviation-survey-shaped) runs,
    `_find_deviation_survey` only recognizes the larger one as *the* survey.
    The smaller one must still be excluded from the digitization-review
    gate — it's a survey file, not a real curve log needing per-curve
    review — rather than blocking export forever waiting on a review that
    was never meant to apply to it."""
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "SurveyGapProject"})
    pid = proj.json()["id"]
    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "SurveyGapWell"})
    wid = well.json()["id"]

    up1 = client.post(f"/api/wells/{wid}/upload-las", headers=_h("admin"),
                       files={"file": ("survey_big.las", SURVEY_LAS(10, 109).encode(), "text/plain")})
    assert up1.status_code == 200
    up2 = client.post(f"/api/wells/{wid}/upload-las", headers=_h("admin"),
                       files={"file": ("survey_small.las", SURVEY_LAS(5, 104).encode(), "text/plain")})
    assert up2.status_code == 200

    readiness = client.get(f"/api/wells/{wid}/readiness-summary")
    assert readiness.status_code == 200
    issues = readiness.json()["digitization_issues"]
    assert not any("survey_small" in i or "survey_big" in i for i in issues), issues


def test_export_succeeds_after_snapshot_approved():
    _pid, wid, lr_id = _make_well_with_run()

    review = client.post(
        f"/api/log-runs/{lr_id}/review",
        headers=_h("interpreter"),
        json={"status": "accepted"},
    )
    assert review.status_code == 200

    snap = client.post(f"/api/wells/{wid}/snapshots", headers=_h("admin"), json={"label": "signoff-test"})
    assert snap.status_code == 201
    snapshot_id = snap.json()["snapshot_id"]

    approve = client.post(
        f"/api/wells/{wid}/snapshots/{snapshot_id}/approve",
        headers=_h("admin"),
        json={"approved_by": "qa-admin"},
    )
    assert approve.status_code == 200

    r = client.get(f"/api/wells/{wid}/export-las")
    assert r.status_code == 200
    assert "~Version Information" in r.text


def test_export_bundle_with_formation_tops_and_zones():
    """export-bundle used to crash with AttributeError on any well that had
    formation tops or zones — it referenced FormationTop.name (the model
    only has formation_name) and Zone.zone_name / net_to_gross / sw_avg /
    vsh_avg / phie_avg (the model only has name, top_depth, bottom_depth,
    color). Neither field ever existed, so any real well with tops or zones
    (a completely ordinary case) made the client-handoff export unusable."""
    import zipfile
    import io

    _pid, wid, _lr_id = _make_well_with_run()
    top = client.post(f"/api/wells/{wid}/tops", headers=_h("admin"),
                       json={"formation_name": "Test Formation", "depth": 105.0, "color": "#123456"})
    assert top.status_code == 201
    zone = client.post(f"/api/wells/{wid}/zones", headers=_h("admin"),
                        json={"zones": [{"name": "Zone A", "top": 100.0, "bottom": 110.0}]})
    assert zone.status_code == 201

    exp = client.get(f"/api/wells/{wid}/export-bundle", params={"force": "true"})
    assert exp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(exp.content))
    tops_csv = zf.read("tops.csv").decode()
    zones_csv = zf.read("zones.csv").decode()
    report = zf.read("report.md").decode()
    assert "Test Formation" in tops_csv
    assert "Zone A" in zones_csv
    assert "Test Formation" in report
    assert "Zone A" in report


def test_export_las_and_bundle_handle_cyrillic_well_name():
    """Content-Disposition is an HTTP header value, which Starlette encodes
    as latin-1 — a plain filename="{well.name}.las" crashed with a 500 for
    any well with a Cyrillic name, a first-class case in this
    Russian-language app (see tests/test_cyrillic_custom.py)."""
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "CyrillicExportProject"})
    assert proj.status_code == 201
    pid = proj.json()["id"]
    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "СКВ-105"})
    assert well.status_code == 201
    wid = well.json()["id"]
    up = client.post(
        f"/api/wells/{wid}/upload-las", headers=_h("admin"),
        files={"file": ("cyr.las", SAMPLE_LAS.encode(), "text/plain")},
    )
    assert up.status_code == 200

    for path in (f"/api/wells/{wid}/export-las", f"/api/wells/{wid}/export-bundle"):
        r = client.get(path, params={"force": "true"})
        assert r.status_code == 200, r.text
        assert "Content-Disposition" in r.headers
