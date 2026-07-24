"""
Research / survey coverage + mnemonic auto-mapping API.

Provides three capabilities layered on top of the existing well/curve model:

  * GET  /api/methods
        Catalogue of every logging method GeoLog recognizes.

  * GET  /api/wells/{wid}/mnemonic-suggestions
        Per-curve canonical-mnemonic suggestions with confidence.
  * POST /api/wells/{wid}/apply-mnemonics
        Auto-apply the suggestions (rename curves to canonical), idempotent.

  * GET  /api/projects/{pid}/research-coverage
        Wells x methods coverage matrix that powers the "карта охвата
        исследованиями" (research coverage map).
"""
from __future__ import annotations

import json
import math
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Well, LogRun, CurveData
    from methods import (
        METHODS,
        methods_catalog,
        method_for_mnemonic,
        suggest_mnemonic,
    )
except ImportError:  # pragma: no cover - package-relative import
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData
    from backend.methods import (
        METHODS,
        methods_catalog,
        method_for_mnemonic,
        suggest_mnemonic,
    )


router = APIRouter(tags=["research"])

_DEPTH_MNEMONICS = {"DEPT", "DEPTH", "MD", "TVD", "TVDSS"}


def _decode(cd: CurveData) -> Optional[np.ndarray]:
    if not cd.data_binary:
        return None
    try:
        return np.frombuffer(cd.data_binary, dtype=np.float64)
    except Exception:
        return None


def _valid_mask(arr: np.ndarray, null_value: Optional[float]) -> np.ndarray:
    mask = np.isfinite(arr)
    if null_value is not None and math.isfinite(null_value):
        mask &= ~np.isclose(arr, null_value, rtol=0, atol=1e-6)
    return mask


# ── Methods catalogue ────────────────────────────────────────────────────────
@router.get("/api/methods")
def list_methods() -> Dict[str, Any]:
    """Every logging method the platform understands, grouped by category."""
    cat = methods_catalog()
    by_category: Dict[str, List[dict]] = {}
    for m in cat:
        by_category.setdefault(m["category"], []).append(m)
    return {"count": len(cat), "methods": cat, "by_category": by_category}


# ── Mnemonic suggestions ─────────────────────────────────────────────────────
@router.get("/api/wells/{wid}/mnemonic-suggestions")
def mnemonic_suggestions(wid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")

    out: List[dict] = []
    seen = set()
    for run in well.log_runs:
        for cd in run.curve_data:
            mnem = (cd.mnemonic or "").strip()
            if not mnem or mnem.upper() in _DEPTH_MNEMONICS:
                continue
            key = (run.id, mnem.upper())
            if key in seen:
                continue
            seen.add(key)
            sug = suggest_mnemonic(mnem)
            d = sug.to_dict()
            d["run_id"] = run.id
            d["run_number"] = run.run_number
            d["unit"] = cd.unit
            d["description"] = cd.description
            out.append(d)

    renamable = [s for s in out if not s["already_canonical"] and s["confidence"] >= 0.6]
    return {
        "well_id": wid,
        "well_name": well.name,
        "curves": out,
        "total": len(out),
        "renamable": len(renamable),
    }


class ApplyMnemonicsRequest(BaseModel):
    min_confidence: float = 0.9
    dry_run: bool = False
    only: Optional[List[str]] = None   # restrict to these raw mnemonics


@router.post("/api/wells/{wid}/apply-mnemonics")
def apply_mnemonics(
    wid: int,
    req: ApplyMnemonicsRequest = ApplyMnemonicsRequest(),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Rename non-standard curves to their canonical mnemonic in-place.

    Safe to re-run: canonical curves are skipped. A rename is skipped when the
    canonical mnemonic already exists in the same run (avoids collisions).
    """
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")

    only = {m.strip().upper() for m in req.only} if req.only else None
    changes: List[dict] = []
    skipped: List[dict] = []

    for run in well.log_runs:
        existing = {(cd.mnemonic or "").strip().upper() for cd in run.curve_data}
        for cd in run.curve_data:
            raw = (cd.mnemonic or "").strip()
            if not raw or raw.upper() in _DEPTH_MNEMONICS:
                continue
            if only is not None and raw.upper() not in only:
                continue
            sug = suggest_mnemonic(raw)
            if sug.already_canonical or sug.confidence < req.min_confidence:
                continue
            target = sug.canonical.upper()
            if target == raw.upper():
                continue
            if target in existing:
                skipped.append({
                    "run_id": run.id, "raw": raw, "canonical": target,
                    "reason": "target already present",
                })
                continue

            record = {
                "run_id": run.id, "run_number": run.run_number,
                "raw": raw, "canonical": target,
                "method_key": sug.method_key, "method_name": sug.method_name,
                "confidence": round(sug.confidence, 3),
            }
            changes.append(record)
            if not req.dry_run:
                cd.mnemonic = target
                existing.discard(raw.upper())
                existing.add(target)
                # keep the run's curve definition list in sync
                try:
                    defs = json.loads(run.curves_json or "[]")
                    for cdef in defs:
                        if str(cdef.get("mnemonic", "")).strip().upper() == raw.upper():
                            cdef["mnemonic"] = target
                    run.curves_json = json.dumps(defs)
                except (ValueError, TypeError):
                    pass

    if not req.dry_run and changes:
        db.commit()

    return {
        "well_id": wid,
        "dry_run": req.dry_run,
        "min_confidence": req.min_confidence,
        "applied": 0 if req.dry_run else len(changes),
        "proposed": len(changes),
        "changes": changes,
        "skipped": skipped,
    }


# ── Research coverage map ────────────────────────────────────────────────────
@router.get("/api/projects/{pid}/research-coverage")
def research_coverage(
    pid: int,
    depth_bins: int = Query(24, ge=4, le=200),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Coverage of logging methods across every well in a project.

    Returns a wells x methods matrix. Each cell reports whether the method was
    run, the fraction of the well's logged interval that carries valid samples,
    the depth interval covered, and the contributing raw mnemonics.
    """
    wells = db.query(Well).filter(Well.project_id == pid).all()
    if not wells:
        raise HTTPException(404, "Project has no wells")

    method_keys = [m.key for m in METHODS]
    method_meta = [
        {"key": m.key, "name": m.name, "category": m.category,
         "color": m.color, "derived": m.derived}
        for m in METHODS
    ]

    well_rows: List[dict] = []
    method_present_count = {k: 0 for k in method_keys}

    for w in wells:
        # well depth extent from runs
        starts, stops = [], []
        for run in w.log_runs:
            if run.start_depth is not None:
                starts.append(run.start_depth)
            if run.stop_depth is not None:
                stops.append(run.stop_depth)
        well_top = min(starts) if starts else None
        well_bot = max(stops) if stops else None
        span = (well_bot - well_top) if (well_top is not None and well_bot is not None
                                         and well_bot > well_top) else None

        # accumulate per-method coverage across runs
        agg: Dict[str, dict] = {}
        for run in w.log_runs:
            null_value = run.null_value
            depth_arr = None
            for cd in run.curve_data:
                if (cd.mnemonic or "").strip().upper() in _DEPTH_MNEMONICS:
                    depth_arr = _decode(cd)
                    break
            for cd in run.curve_data:
                mnem = (cd.mnemonic or "").strip()
                if not mnem or mnem.upper() in _DEPTH_MNEMONICS:
                    continue
                meth = method_for_mnemonic(mnem)
                if meth is None:
                    continue
                arr = _decode(cd)
                if arr is None or arr.size == 0:
                    continue
                mask = _valid_mask(arr, null_value)
                valid = int(mask.sum())
                if valid == 0:
                    continue
                slot = agg.setdefault(meth.key, {
                    "valid": 0, "total": 0, "mnems": set(),
                    "dmin": None, "dmax": None,
                })
                slot["valid"] += valid
                slot["total"] += int(arr.size)
                slot["mnems"].add(mnem.upper())
                if depth_arr is not None and depth_arr.size == arr.size:
                    dvalid = depth_arr[mask]
                    dvalid = dvalid[np.isfinite(dvalid)]
                    if dvalid.size:
                        dlo, dhi = float(dvalid.min()), float(dvalid.max())
                        slot["dmin"] = dlo if slot["dmin"] is None else min(slot["dmin"], dlo)
                        slot["dmax"] = dhi if slot["dmax"] is None else max(slot["dmax"], dhi)

        cells: Dict[str, dict] = {}
        for k in method_keys:
            slot = agg.get(k)
            if not slot:
                cells[k] = {"present": False, "coverage": 0.0}
                continue
            method_present_count[k] += 1
            dmin, dmax = slot["dmin"], slot["dmax"]
            if span and dmin is not None and dmax is not None and dmax > dmin:
                coverage = max(0.0, min(1.0, (dmax - dmin) / span))
            else:
                coverage = 1.0 if slot["valid"] else 0.0
            fill = slot["valid"] / slot["total"] if slot["total"] else 0.0
            cells[k] = {
                "present": True,
                "coverage": round(coverage, 3),
                "fill": round(fill, 3),
                "valid_points": slot["valid"],
                "depth_top": round(dmin, 2) if dmin is not None else None,
                "depth_bottom": round(dmax, 2) if dmax is not None else None,
                "mnemonics": sorted(slot["mnems"]),
            }

        present_keys = [k for k in method_keys if cells[k]["present"]]
        well_rows.append({
            "well_id": w.id,
            "well_name": w.name,
            "uwi": w.uwi,
            "depth_top": well_top,
            "depth_bottom": well_bot,
            "methods_present": len(present_keys),
            "cells": cells,
        })

    n_wells = len(wells)
    method_summary = [
        {**m,
         "wells_present": method_present_count[m["key"]],
         "completeness": round(method_present_count[m["key"]] / n_wells, 3) if n_wells else 0.0}
        for m in method_meta
    ]

    return {
        "project_id": pid,
        "well_count": n_wells,
        "methods": method_summary,
        "wells": well_rows,
    }
