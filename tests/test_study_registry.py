"""Tests for the study-registry import + completeness cross-check
(backend/routers/study_registry.py, added in commit b9de2e4)."""
import io
import os
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from fastapi.testclient import TestClient  # noqa: E402

from routers.study_registry import _parse_study_registry_table  # noqa: E402
from backend.main import app  # noqa: E402

client = TestClient(app)


def _h(role: str):
    return {"X-User-Role": role}


# ─── _parse_study_registry_table: pure unit tests ─────────────────

def test_parse_russian_headers():
    csv_text = (
        "Скважина,Площадь,Вид исследования,Глубина от,Глубина до\n"
        "105,Приобское,ГИС,1000,1200\n"
    )
    rows = _parse_study_registry_table("registry.csv", csv_text.encode("utf-8-sig"))
    assert len(rows) == 1
    r = rows[0]
    assert r["well_name"] == "105"
    assert r["field_name"] == "Приобское"
    assert r["study_type"] == "ГИС"
    assert r["depth_top"] == 1000.0
    assert r["depth_bottom"] == 1200.0


def test_parse_english_headers():
    csv_text = (
        "well,field,study_type,depth_top,depth_bottom\n"
        "Well-1,FieldA,Core,500,600\n"
    )
    rows = _parse_study_registry_table("registry.csv", csv_text.encode("utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["well_name"] == "Well-1"
    assert r["field_name"] == "FieldA"
    assert r["study_type"] == "Core"
    assert r["depth_top"] == 500.0
    assert r["depth_bottom"] == 600.0


def test_parse_combined_single_depth_column():
    csv_text = (
        "well,field,study,depth\n"
        "Well-2,FieldB,GIS,1000-1200\n"
    )
    rows = _parse_study_registry_table("registry.csv", csv_text.encode("utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["depth_top"] == 1000.0
    assert r["depth_bottom"] == 1200.0


def test_unparseable_depth_still_returns_row_with_null_depths():
    """A row that can't be depth-parsed is a deliberate design choice: it is
    still imported (with null depths) rather than dropped, since the
    well/field presence alone is useful."""
    csv_text = (
        "well,field,study,depth\n"
        "Well-3,FieldC,GIS,unknown\n"
    )
    rows = _parse_study_registry_table("registry.csv", csv_text.encode("utf-8"))
    assert len(rows) == 1
    r = rows[0]
    assert r["well_name"] == "Well-3"
    assert r["depth_top"] is None
    assert r["depth_bottom"] is None


def test_parse_xlsx_bytes():
    import openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["well", "field", "study_type", "depth_top", "depth_bottom"])
    ws.append(["Well-X", "FieldX", "Core", 700, 900])
    buf = io.BytesIO()
    wb.save(buf)
    data = buf.getvalue()

    rows = _parse_study_registry_table("registry.xlsx", data)
    assert len(rows) == 1
    r = rows[0]
    assert r["well_name"] == "Well-X"
    assert r["field_name"] == "FieldX"
    assert r["study_type"] == "Core"
    assert r["depth_top"] == 700.0
    assert r["depth_bottom"] == 900.0


# ─── TestClient end-to-end: import + completeness cross-check ─────

def test_import_and_completeness_match_status():
    # Fresh project + well + a real log run so the registry has something to
    # match against (LAS depth range 100-103, see SAMPLE_LAS-style minimal file).
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "StudyRegistryTestProject"})
    assert proj.status_code == 201
    pid = proj.json()["id"]

    well = client.post("/api/wells/", headers=_h("admin"), json={"project_id": pid, "name": "SRTestWell1"})
    assert well.status_code == 201
    wid = well.json()["id"]

    sample_las = (
        "~Version Information\n"
        "VERS.                  2.0 :   CWLS LOG ASCII STANDARD -VERSION 2.0\n"
        "WRAP.                  NO  :   ONE LINE PER DEPTH STEP\n"
        "~Well Information\n"
        "STRT.M              100.000 :\n"
        "STOP.M              103.000 :\n"
        "STEP.M                1.000 :\n"
        "NULL.              -999.25  :\n"
        "~Curve Information\n"
        "DEPT.M                   :   DEPTH\n"
        "GR  .GAPI               :   GAMMA RAY\n"
        "~ASCII\n"
        "100.0 50.0\n"
        "101.0 55.0\n"
        "102.0 60.0\n"
        "103.0 65.0\n"
    )
    up = client.post(
        f"/api/wells/{wid}/upload-las",
        headers=_h("admin"),
        files={"file": ("srtest.las", sample_las.encode(), "text/plain")},
    )
    assert up.status_code == 200

    registry_csv = (
        "well,field,study_type,depth_top,depth_bottom\n"
        "SRTestWell1,FieldA,GIS,100,103\n"          # matched: overlaps LAS depth range
        "SRTestWell1,FieldA,Core,5000,6000\n"       # well found, depth doesn't overlap
        "SRTestWellDoesNotExist,FieldA,GIS,0,10\n"  # missing: no such well
    )
    imp = client.post(
        f"/api/projects/{pid}/study-registry/import",
        headers=_h("admin"),
        files={"file": ("registry.csv", registry_csv.encode(), "text/csv")},
    )
    assert imp.status_code == 200
    assert imp.json()["imported"] == 3

    reg = client.get(f"/api/projects/{pid}/study-registry")
    assert reg.status_code == 200
    data = reg.json()
    assert data["entry_count"] == 3
    by_depth = {(e["study_type"], e["depth_top"]): e["match_status"] for e in data["entries"]}
    assert by_depth[("GIS", 100.0)] == "matched"
    assert by_depth[("Core", 5000.0)] == "well_found_no_depth_match"
    assert by_depth[("GIS", 0.0)] == "missing"
    assert data["matched_count"] == 1
    assert data["partial_count"] == 1
    assert data["missing_count"] == 1


def test_delete_study_registry_clears_entries():
    proj = client.post("/api/projects/", headers=_h("admin"), json={"name": "StudyRegistryDeleteTestProject"})
    pid = proj.json()["id"]

    registry_csv = "well,field,study_type,depth_top,depth_bottom\nAnyWell,FieldA,GIS,0,10\n"
    imp = client.post(
        f"/api/projects/{pid}/study-registry/import",
        headers=_h("admin"),
        files={"file": ("registry.csv", registry_csv.encode(), "text/csv")},
    )
    assert imp.status_code == 200
    assert imp.json()["imported"] == 1

    d = client.delete(f"/api/projects/{pid}/study-registry", headers=_h("admin"))
    assert d.status_code == 200
    assert d.json()["deleted"] == 1

    reg = client.get(f"/api/projects/{pid}/study-registry")
    assert reg.json()["entry_count"] == 0
