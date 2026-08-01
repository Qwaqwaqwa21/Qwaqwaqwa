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
"""
from __future__ import annotations

import itertools
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
