"""
Проверка кривых на полное дублирование данных.

В отличие от инклинометрии (backend/routers/inclinometry.py), где дедуп ищет
повторные точки замера по глубине внутри одной кривой, здесь ищутся пары
РАЗНЫХ кривых (в одной или разных скважинах), чьи значения совпадают на
общем интервале глубин — типичный симптом ошибки экспорта/копирования
(один и тот же ГИС записан дважды под разными мнемониками, или файл
случайно загружен повторно под другой скважиной).

  * GET /api/wells/{wid}/duplicate-curves     — проверка внутри одной скважины
  * GET /api/projects/{pid}/duplicate-curves  — проверка по всему проекту
    (в т.ч. между разными скважинами)

Совпадение фиксируется только там, где обе кривые имеют реальные (не NULL)
значения — NULL-заполнение (-999.25 и т.п.) уже приведено парсером к NaN
при загрузке, так что протяжённые пустые интервалы не дают ложных срабатываний.

Отдельная, более грубая проверка — на уровне ИССЛЕДОВАНИЯ (study), а не
значений кривых:

  * GET /api/projects/{pid}/duplicate-studies

В реальном workflow бумажный каротаж оцифровывается внешней группой и
загружается как LAS. UWI в исходных данных нет вообще (он есть только во
внешнем Excel-реестре — отдельная, более поздняя задача), поэтому проверка
"это не тот же самый physical study, оцифрованный второй раз" не может
опираться на идентификаторы и должна работать по тому, что реально есть в
БД: имя скважины, площадь (field_name), интервал глубин и набор методов/
кривых рейса. Это ловит два сценария, которые duplicate-curves пропускает,
потому что там значения совпадают не побайтово:
  - тот же рейс оцифрован повторно (другой проход OCR/оператора → немного
    другие числа, но тот же ствол, тот же интервал, те же методы);
  - одна и та же скважина заведена дважды под разными именами
    (опечатка/варианты написания: "105" / "Скв. 105" / "105-Б").
"""
from __future__ import annotations

import itertools
import json
import re
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Well, LogRun, CurveData, Project
except ImportError:  # pragma: no cover
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData, Project

router = APIRouter(tags=["duplicates"])

_DEPTH_NAMES = {"MD", "DEPT", "DEPTH", "TVD"}

DEFAULT_TOLERANCE = 1e-6
DEFAULT_MIN_POINTS = 20
DEFAULT_MIN_COVERAGE = 0.9

DEFAULT_MIN_DEPTH_OVERLAP = 0.5
DEFAULT_MIN_METHOD_OVERLAP = 0.5

_NAME_NOISE_RE = re.compile(r"скв\.|скважина|well|№|[.\-_]")
_WS_RE = re.compile(r"\s+")


def _decode(cd: CurveData) -> Optional[np.ndarray]:
    if not cd.data_binary:
        return None
    try:
        return np.frombuffer(cd.data_binary, dtype=np.float64).copy()
    except Exception:
        return None


def _run_depth(run: LogRun, curve_rows: List[CurveData]) -> Optional[np.ndarray]:
    for cd in curve_rows:
        if (cd.mnemonic or "").strip().upper() in _DEPTH_NAMES:
            d = _decode(cd)
            if d is not None:
                return d
    if run.step and run.num_points and run.start_depth is not None:
        return run.start_depth + np.arange(run.num_points) * run.step
    return None


def _well_curves(well: Well) -> List[Dict[str, Any]]:
    """Flatten every non-depth curve of a well into comparable (depth, value) series."""
    out: List[Dict[str, Any]] = []
    for run in well.log_runs:
        rows = list(run.curve_data)
        depth = _run_depth(run, rows)
        if depth is None:
            continue
        depth_mnemonics = {(cd.mnemonic or "").strip().upper() for cd in rows} & _DEPTH_NAMES
        for cd in rows:
            m = (cd.mnemonic or "").strip().upper()
            if m in _DEPTH_NAMES and m in depth_mnemonics:
                depth_mnemonics.discard(m)  # only skip the one used as reference
                continue
            val = _decode(cd)
            if val is None:
                continue
            n = min(len(depth), len(val))
            if n < 2:
                continue
            out.append({
                "well_id": well.id,
                "well_name": well.name,
                "run_id": run.id,
                "filename": run.filename,
                "mnemonic": cd.mnemonic,
                "unit": cd.unit,
                "depth": depth[:n],
                "value": val[:n],
            })
    return out


def _compare_pair(
    a: Dict[str, Any], b: Dict[str, Any], tol: float, min_points: int, min_coverage: float
) -> Optional[Dict[str, Any]]:
    va, vb = a["value"], b["value"]
    da, db_ = a["depth"], b["depth"]

    valid_a = int(np.count_nonzero(np.isfinite(va)))
    valid_b = int(np.count_nonzero(np.isfinite(vb)))
    if valid_a == 0 or valid_b == 0:
        return None

    if a["run_id"] == b["run_id"] and len(va) == len(vb):
        # Same run → same index = same depth, compare directly (fast path).
        both = np.isfinite(va) & np.isfinite(vb)
        overlap = int(np.count_nonzero(both))
        if overlap < min_points:
            return None
        matches = np.isclose(va[both], vb[both], rtol=0.0, atol=tol)
        if not matches.all():
            return None
    else:
        # Different runs/wells → join on rounded depth.
        ka = {round(float(d), 3): v for d, v in zip(da, va) if np.isfinite(v)}
        kb = {round(float(d), 3): v for d, v in zip(db_, vb) if np.isfinite(v)}
        common = ka.keys() & kb.keys()
        overlap = len(common)
        if overlap < min_points:
            return None
        diffs = [abs(ka[k] - kb[k]) for k in common]
        if max(diffs) > tol:
            return None

    coverage = overlap / min(valid_a, valid_b)
    if coverage < min_coverage:
        return None

    return {
        "well_a": {"id": a["well_id"], "name": a["well_name"], "run_id": a["run_id"],
                   "filename": a["filename"], "mnemonic": a["mnemonic"], "unit": a["unit"]},
        "well_b": {"id": b["well_id"], "name": b["well_name"], "run_id": b["run_id"],
                   "filename": b["filename"], "mnemonic": b["mnemonic"], "unit": b["unit"]},
        "overlap_points": overlap,
        "coverage": round(coverage, 4),
        "cross_well": a["well_id"] != b["well_id"],
    }


def _find_duplicates(
    curves: List[Dict[str, Any]], tol: float, min_points: int, min_coverage: float
) -> List[Dict[str, Any]]:
    results = []
    for a, b in itertools.combinations(curves, 2):
        if a["run_id"] == b["run_id"] and a["mnemonic"] == b["mnemonic"]:
            continue
        match = _compare_pair(a, b, tol, min_points, min_coverage)
        if match:
            results.append(match)
    results.sort(key=lambda r: (-r["coverage"], -r["overlap_points"]))
    return results


@router.get("/api/wells/{wid}/duplicate-curves")
def well_duplicate_curves(
    wid: int,
    tolerance: float = Query(DEFAULT_TOLERANCE, ge=0.0),
    min_points: int = Query(DEFAULT_MIN_POINTS, ge=2),
    min_coverage: float = Query(DEFAULT_MIN_COVERAGE, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    curves = _well_curves(well)
    dupes = _find_duplicates(curves, tolerance, min_points, min_coverage)
    return {
        "well_id": wid, "well_name": well.name,
        "curve_count": len(curves), "duplicate_count": len(dupes),
        "duplicates": dupes,
    }


@router.get("/api/projects/{pid}/duplicate-curves")
def project_duplicate_curves(
    pid: int,
    tolerance: float = Query(DEFAULT_TOLERANCE, ge=0.0),
    min_points: int = Query(DEFAULT_MIN_POINTS, ge=2),
    min_coverage: float = Query(DEFAULT_MIN_COVERAGE, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Project not found")
    curves: List[Dict[str, Any]] = []
    for well in project.wells:
        curves.extend(_well_curves(well))
    dupes = _find_duplicates(curves, tolerance, min_points, min_coverage)
    return {
        "project_id": pid,
        "well_count": len(project.wells),
        "curve_count": len(curves),
        "duplicate_count": len(dupes),
        "cross_well_duplicate_count": sum(1 for d in dupes if d["cross_well"]),
        "duplicates": dupes,
    }


def _normalize_well_name(name: Optional[str]) -> str:
    """Lowercase + strip common RU/EN well-name noise so '105', 'Скв. 105' and
    'well-105' compare equal."""
    s = (name or "").strip().lower()
    s = _NAME_NOISE_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def _run_methods(run: LogRun) -> set:
    """Mnemonics (uppercased, depth/index excluded) present in a run's curves_json —
    the cheapest available signal for "what methods this study contains"."""
    try:
        curves = json.loads(run.curves_json or "[]")
    except (ValueError, TypeError):
        return set()
    out = set()
    for c in curves:
        m = (c.get("mnemonic") or "").strip().upper()
        if m and m not in _DEPTH_NAMES:
            out.add(m)
    return out


def _depth_overlap_fraction(run_a: LogRun, run_b: LogRun) -> Optional[float]:
    """Overlap of [start_depth, stop_depth] between two runs, relative to the
    shorter run's range. None if either run has no usable depth range."""
    if run_a.start_depth is None or run_a.stop_depth is None:
        return None
    if run_b.start_depth is None or run_b.stop_depth is None:
        return None
    lo_a, hi_a = sorted((run_a.start_depth, run_a.stop_depth))
    lo_b, hi_b = sorted((run_b.start_depth, run_b.stop_depth))
    range_a, range_b = hi_a - lo_a, hi_b - lo_b
    if range_a <= 0 or range_b <= 0:
        return None
    overlap = min(hi_a, hi_b) - max(lo_a, lo_b)
    if overlap <= 0:
        return 0.0
    return overlap / min(range_a, range_b)


def _run_side(well: Well, run: LogRun) -> Dict[str, Any]:
    return {
        "id": well.id, "name": well.name, "field_name": well.field_name,
        "run_id": run.id, "run_number": run.run_number, "filename": run.filename,
        "start_depth": run.start_depth, "stop_depth": run.stop_depth,
        "digitization_status": run.digitization_status,
    }


def _compare_study_pair(
    well_a: Well, run_a: LogRun, well_b: Well, run_b: LogRun,
    min_depth_overlap: float, min_method_overlap: float,
) -> Optional[Dict[str, Any]]:
    depth_overlap = _depth_overlap_fraction(run_a, run_b)
    if depth_overlap is None or depth_overlap < min_depth_overlap:
        return None

    methods_a, methods_b = _run_methods(run_a), _run_methods(run_b)
    if not methods_a or not methods_b:
        return None
    shared = methods_a & methods_b
    method_overlap = len(shared) / min(len(methods_a), len(methods_b))
    if method_overlap < min_method_overlap:
        return None

    same_well = well_a.id == well_b.id
    if same_well:
        reason = "same_well"
    else:
        # Cross-well pairs are only meaningful within the same площадь — same
        # well ⇒ same field by definition, so only cross-well pairs need this
        # check. Unrelated (or both-blank/unspecified) fields are too noisy
        # to flag as duplicates — an empty field_name means "unknown", not
        # "same field", so it must not match another empty field_name.
        field_a = (well_a.field_name or "").strip().lower()
        field_b = (well_b.field_name or "").strip().lower()
        if not field_a or not field_b or field_a != field_b:
            return None
        name_a = _normalize_well_name(well_a.name)
        name_b = _normalize_well_name(well_b.name)
        if name_a and name_a == name_b:
            reason = "cross_well_same_name"
        else:
            reason = "cross_well_similar_field"

    return {
        "well_a": _run_side(well_a, run_a),
        "well_b": _run_side(well_b, run_b),
        "depth_overlap_fraction": round(depth_overlap, 4),
        "method_overlap_fraction": round(method_overlap, 4),
        "shared_methods": sorted(shared),
        "reason": reason,
        "cross_well": not same_well,
    }


def _find_duplicate_studies(
    wells: List[Well], min_depth_overlap: float, min_method_overlap: float
) -> List[Dict[str, Any]]:
    runs = [(well, run) for well in wells for run in well.log_runs]
    results = []
    for (well_a, run_a), (well_b, run_b) in itertools.combinations(runs, 2):
        match = _compare_study_pair(well_a, run_a, well_b, run_b, min_depth_overlap, min_method_overlap)
        if match:
            results.append(match)
    results.sort(key=lambda r: (-r["depth_overlap_fraction"], -r["method_overlap_fraction"]))
    return results


@router.get("/api/projects/{pid}/duplicate-studies")
def project_duplicate_studies(
    pid: int,
    min_depth_overlap: float = Query(DEFAULT_MIN_DEPTH_OVERLAP, ge=0.0, le=1.0),
    min_method_overlap: float = Query(DEFAULT_MIN_METHOD_OVERLAP, ge=0.0, le=1.0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Project not found")
    wells = project.wells
    study_count = sum(len(w.log_runs) for w in wells)
    dupes = _find_duplicate_studies(wells, min_depth_overlap, min_method_overlap)
    return {
        "project_id": pid,
        "well_count": len(wells),
        "study_count": study_count,
        "duplicate_count": len(dupes),
        "cross_well_duplicate_count": sum(1 for d in dupes if d["cross_well"]),
        "duplicates": dupes,
    }
