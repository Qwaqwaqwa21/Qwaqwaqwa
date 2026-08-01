"""
Опись исследований (внешний Excel/CSV-реестр) — сверка полноты.

Отдельно от бумажного каротажа, который оцифровывается и загружается как
LAS, пользователь ведёт Excel-реестр "опись исследований" — какие
исследования должны существовать по проекту: скважина, площадь, вид
исследования, интервал глубин. У реестра, как и у LAS/скан-данных, нет
общего UWI — сверка с фактическими Well/LogRun идёт по имени скважины,
площади и перекрытию интервала глубин (см. backend/routers/duplicates.py,
_normalize_well_name / _depth_overlap_fraction, которые переиспользуются
здесь напрямую).

Это информационная, best-effort сверка ("полнота не всегда может быть"),
а не жёсткая проверка, блокирующая что-либо ещё:

  * POST   /api/projects/{pid}/study-registry/import  — импорт реестра
  * GET    /api/projects/{pid}/study-registry          — сверка с БД (live)
  * DELETE /api/projects/{pid}/study-registry           — очистка реестра
"""
from __future__ import annotations

import csv
import io
import re
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Project, Well, StudyRegistryEntry
    from routers.duplicates import _normalize_well_name, _depth_overlap_fraction
except ImportError:  # pragma: no cover - package-relative import
    from backend.database import get_db
    from backend.models import Project, Well, StudyRegistryEntry
    from backend.routers.duplicates import _normalize_well_name, _depth_overlap_fraction

router = APIRouter(tags=["study-registry"])

DEFAULT_MIN_DEPTH_OVERLAP = 0.5

_WELL_HEADERS = {"скважина", "скв", "well", "номер скважины"}
_FIELD_HEADERS = {"площадь", "field", "месторождение"}
_STUDY_HEADERS = {"исследование", "вид исследования", "study", "study_type"}
_DEPTH_TOP_HEADERS = {"глубина от", "от", "top", "depth_from", "depth_top"}
_DEPTH_BOTTOM_HEADERS = {"глубина до", "до", "bottom", "depth_to", "depth_bottom"}
_DEPTH_COMBINED_HEADERS = {"глубины", "интервал", "depth", "depths"}

_DEPTH_SPLIT_RE = re.compile(r"\s*(?:-|–|—|до)\s*", re.IGNORECASE)


class _RunLike:
    """Minimal stand-in matching the (start_depth, stop_depth) shape
    `_depth_overlap_fraction` expects, so a registry entry's depth range can
    be compared against a real LogRun without duplicating the overlap math."""
    __slots__ = ("start_depth", "stop_depth")

    def __init__(self, start_depth: Optional[float], stop_depth: Optional[float]):
        self.start_depth = start_depth
        self.stop_depth = stop_depth


def _split_combined_depth(raw: str) -> Tuple[Optional[float], Optional[float]]:
    parts = _DEPTH_SPLIT_RE.split(raw.strip())
    parts = [p for p in parts if p.strip()]
    if len(parts) != 2:
        return None, None
    try:
        return float(parts[0].replace(",", ".")), float(parts[1].replace(",", "."))
    except ValueError:
        return None, None


def _parse_float(raw: Any) -> Optional[float]:
    s = str(raw).strip().replace(",", ".")
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_study_registry_table(filename: str, data: bytes) -> List[Dict[str, Any]]:
    """Extract (well_name, field_name, study_type, depth_top, depth_bottom,
    source_row) rows from an uploaded xlsx/csv/tsv study registry table.

    Mirrors routers.research._parse_alias_table: openpyxl for Excel, csv
    module with multi-encoding auto-detection otherwise, header row detected
    by matching known RU/EN synonyms (case-insensitive), positional fallback
    otherwise. A row that can't be depth-parsed is still imported (with null
    depths) rather than dropped — well/field presence alone is useful.
    """
    name = (filename or "").lower()
    rows: List[List[str]] = []

    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(400, "Excel support requires openpyxl on the server")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise HTTPException(400, f"Could not read workbook: {e}")
        ws = wb.active
        for r in ws.iter_rows(values_only=True):
            rows.append([("" if c is None else str(c)) for c in r])
    else:
        text = None
        for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866", "latin-1"):
            try:
                text = data.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        if text is None:
            text = data.decode("latin-1", errors="replace")
        delim = "\t" if ("\t" in text.splitlines()[0] if text.splitlines() else False) else ","
        rows = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]

    rows = [r for r in rows if any(str(c).strip() for c in r)]
    if not rows:
        return []

    # Detect header row + column indices; fall back to fixed positions.
    hdr = [str(c).strip().lower() for c in rows[0]]
    ci_well, ci_field, ci_study = 0, 1, 2
    ci_top: Optional[int] = None
    ci_bottom: Optional[int] = None
    ci_combined: Optional[int] = None
    start = 0

    is_header = any(h in _WELL_HEADERS for h in hdr) or any(h in _STUDY_HEADERS for h in hdr)
    if is_header:
        start = 1
        for i, h in enumerate(hdr):
            if h in _WELL_HEADERS:
                ci_well = i
            elif h in _FIELD_HEADERS:
                ci_field = i
            elif h in _STUDY_HEADERS:
                ci_study = i
            elif h in _DEPTH_TOP_HEADERS:
                ci_top = i
            elif h in _DEPTH_BOTTOM_HEADERS:
                ci_bottom = i
            elif h in _DEPTH_COMBINED_HEADERS:
                ci_combined = i
    else:
        # No recognizable header: positional fallback, no depth columns known.
        ci_combined = 3 if len(hdr) > 3 else None

    out: List[Dict[str, Any]] = []
    for r in rows[start:]:
        if len(r) <= ci_well or not str(r[ci_well]).strip():
            continue
        well_name = str(r[ci_well]).strip()
        field_name = str(r[ci_field]).strip() if len(r) > ci_field else ""
        study_type = str(r[ci_study]).strip() if len(r) > ci_study else ""

        depth_top: Optional[float] = None
        depth_bottom: Optional[float] = None
        if ci_top is not None and ci_bottom is not None:
            if len(r) > ci_top:
                depth_top = _parse_float(r[ci_top])
            if len(r) > ci_bottom:
                depth_bottom = _parse_float(r[ci_bottom])
        elif ci_combined is not None and len(r) > ci_combined and str(r[ci_combined]).strip():
            depth_top, depth_bottom = _split_combined_depth(str(r[ci_combined]))

        out.append({
            "well_name": well_name,
            "field_name": field_name,
            "study_type": study_type,
            "depth_top": depth_top,
            "depth_bottom": depth_bottom,
            "source_row": ",".join(str(c) for c in r),
        })
    return out


@router.post("/api/projects/{pid}/study-registry/import")
async def import_study_registry(
    pid: int,
    file: UploadFile = File(...),
    replace: bool = Query(False),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Project not found")

    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    parsed = _parse_study_registry_table(file.filename or "", data)
    if not parsed:
        raise HTTPException(400, "No study registry rows found in file")

    if replace:
        db.query(StudyRegistryEntry).filter(StudyRegistryEntry.project_id == pid).delete()

    entries = [
        StudyRegistryEntry(
            project_id=pid,
            well_name=row["well_name"],
            field_name=row["field_name"],
            study_type=row["study_type"],
            depth_top=row["depth_top"],
            depth_bottom=row["depth_bottom"],
            source_row=row["source_row"],
        )
        for row in parsed
    ]
    db.bulk_save_objects(entries)
    db.commit()

    return {
        "ok": True,
        "imported": len(entries),
        "project_id": pid,
        "sample": parsed[:10],
    }


def _match_entry(entry: StudyRegistryEntry, wells: List[Well], min_depth_overlap: float) -> Dict[str, Any]:
    target_name = _normalize_well_name(entry.well_name)
    candidates = [w for w in wells if target_name and _normalize_well_name(w.name) == target_name]

    result = {
        "id": entry.id,
        "well_name": entry.well_name,
        "field_name": entry.field_name,
        "study_type": entry.study_type,
        "depth_top": entry.depth_top,
        "depth_bottom": entry.depth_bottom,
        "match_status": "missing",
        "matched_well_id": None,
        "matched_run_id": None,
        "matched_digitization_status": None,
    }
    if not candidates:
        return result

    # A well was found. If the registry entry carries no depth range, name
    # presence alone is all we can check — call it matched.
    if entry.depth_top is None or entry.depth_bottom is None:
        w = candidates[0]
        result["match_status"] = "matched"
        result["matched_well_id"] = w.id
        result["matched_run_id"] = w.log_runs[0].id if w.log_runs else None
        result["matched_digitization_status"] = w.log_runs[0].digitization_status if w.log_runs else None
        return result

    entry_run = _RunLike(entry.depth_top, entry.depth_bottom)
    best_well, best_run, best_overlap = None, None, -1.0
    for w in candidates:
        for run in w.log_runs:
            overlap = _depth_overlap_fraction(entry_run, run)
            if overlap is not None and overlap > best_overlap:
                best_well, best_run, best_overlap = w, run, overlap

    if best_run is not None and best_overlap >= min_depth_overlap:
        result["match_status"] = "matched"
        result["matched_well_id"] = best_well.id
        result["matched_run_id"] = best_run.id
        result["matched_digitization_status"] = best_run.digitization_status
    else:
        result["match_status"] = "well_found_no_depth_match"
        result["matched_well_id"] = candidates[0].id
        if best_run is not None:
            result["matched_run_id"] = best_run.id
            result["matched_digitization_status"] = best_run.digitization_status
    return result


@router.get("/api/projects/{pid}/study-registry")
def get_study_registry(
    pid: int,
    min_depth_overlap: float = Query(DEFAULT_MIN_DEPTH_OVERLAP, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Project not found")

    entries = (
        db.query(StudyRegistryEntry)
        .filter(StudyRegistryEntry.project_id == pid)
        .order_by(StudyRegistryEntry.id)
        .all()
    )
    wells = project.wells

    out = [_match_entry(e, wells, min_depth_overlap) for e in entries]
    matched = sum(1 for e in out if e["match_status"] == "matched")
    partial = sum(1 for e in out if e["match_status"] == "well_found_no_depth_match")
    missing = sum(1 for e in out if e["match_status"] == "missing")

    return {
        "project_id": pid,
        "entry_count": len(out),
        "matched_count": matched,
        "partial_count": partial,
        "missing_count": missing,
        "entries": out,
    }


@router.delete("/api/projects/{pid}/study-registry")
def delete_study_registry(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Project not found")
    deleted = db.query(StudyRegistryEntry).filter(StudyRegistryEntry.project_id == pid).delete()
    db.commit()
    return {"ok": True, "deleted": deleted, "project_id": pid}
