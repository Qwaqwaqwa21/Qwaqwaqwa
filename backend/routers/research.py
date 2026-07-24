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

import csv
import io
import json
import math
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Body, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Well, LogRun, CurveData
    import methods as _methods
    from methods import (
        METHODS,
        methods_catalog,
        method_for_mnemonic,
        suggest_mnemonic,
    )
except ImportError:  # pragma: no cover - package-relative import
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData
    from backend import methods as _methods
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


def _known_canonicals() -> List[str]:
    return sorted({m.canonical for m in METHODS})


# ── Custom mnemonic aliases (editable defaults + Excel/CSV import) ────────────
@router.get("/api/mnemonic-aliases")
def get_aliases() -> Dict[str, Any]:
    """Built-in default aliases plus user-defined custom aliases."""
    defaults = []
    for m in METHODS:
        for c in m.curves:
            if c.upper() != m.canonical.upper():
                defaults.append({"raw": c.upper(), "canonical": m.canonical,
                                 "method_key": m.key, "method_name": m.name})
    custom = [{"raw": k, "canonical": v,
               "method_key": (method_for_mnemonic(v).key if method_for_mnemonic(v) else None),
               "method_name": (method_for_mnemonic(v).name if method_for_mnemonic(v) else None)}
              for k, v in sorted(_methods.CUSTOM_ALIASES.items())]
    return {
        "canonicals": _known_canonicals(),
        "defaults": defaults,
        "custom": custom,
        "custom_count": len(custom),
    }


class AliasBody(BaseModel):
    raw: str
    canonical: str


@router.post("/api/mnemonic-aliases")
def add_alias(body: AliasBody) -> Dict[str, Any]:
    try:
        rec = _methods.set_custom_alias(body.raw, body.canonical)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"ok": True, "alias": rec, "custom_count": len(_methods.CUSTOM_ALIASES)}


@router.delete("/api/mnemonic-aliases/{raw}")
def delete_alias(raw: str) -> Dict[str, Any]:
    removed = _methods.remove_custom_alias(raw)
    if not removed:
        raise HTTPException(404, "Alias not found")
    return {"ok": True, "removed": raw.strip().upper(), "custom_count": len(_methods.CUSTOM_ALIASES)}


def _parse_alias_table(filename: str, data: bytes) -> List[tuple]:
    """Extract (raw, canonical) pairs from an uploaded xlsx/csv/tsv table.

    Accepts two- (or more) column tables; a header row naming columns
    raw/mnemonic and canonical/target is honoured, otherwise the first two
    columns are used. Encoding is auto-detected for CSV.
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
        # CSV / TSV with encoding auto-detection
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

    if not rows:
        return []

    # Detect and skip a header row
    start = 0
    hdr = [str(c).strip().lower() for c in rows[0]]
    ci_raw, ci_canon = 0, 1
    if any(h in ("raw", "mnemonic", "vendor", "alias", "мнемоника") for h in hdr):
        start = 1
        for i, h in enumerate(hdr):
            if h in ("raw", "mnemonic", "vendor", "alias", "мнемоника"):
                ci_raw = i
            if h in ("canonical", "target", "standard", "canon", "канон"):
                ci_canon = i

    pairs: List[tuple] = []
    for r in rows[start:]:
        if len(r) <= max(ci_raw, ci_canon):
            continue
        raw = str(r[ci_raw]).strip()
        canon = str(r[ci_canon]).strip()
        if raw and canon:
            pairs.append((raw, canon))
    return pairs


@router.post("/api/mnemonic-aliases/import")
async def import_aliases(
    file: UploadFile = File(...),
    replace: bool = Query(False),
) -> Dict[str, Any]:
    """Import custom aliases from an Excel (.xlsx) or CSV/TSV file."""
    data = await file.read()
    if not data:
        raise HTTPException(400, "Empty file")
    pairs = _parse_alias_table(file.filename or "", data)
    if not pairs:
        raise HTTPException(400, "No (raw, canonical) pairs found in file")
    result = _methods.import_custom_aliases(pairs, replace=replace)
    return {"ok": True, **result, "sample": [{"raw": p[0], "canonical": p[1]} for p in pairs[:10]]}


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


# ── Method coverage planshet (depth-resolved presence columns) ───────────────
@router.get("/api/projects/{pid}/coverage-log")
def coverage_log(
    pid: int,
    bins: int = Query(160, ge=20, le=1000),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Depth-resolved method coverage for a project's wells.

    Returns a shared depth grid plus, for every well and method, a per-bin
    presence array (1 = valid data somewhere in that depth bin). This drives a
    correlation-style planshet of filled columns instead of drawn curves.
    """
    wells = db.query(Well).filter(Well.project_id == pid).all()
    if not wells:
        raise HTTPException(404, "Project has no wells")

    # Global depth extent across all runs.
    g_top, g_bot = None, None
    for w in wells:
        for run in w.log_runs:
            if run.start_depth is not None:
                g_top = run.start_depth if g_top is None else min(g_top, run.start_depth)
            if run.stop_depth is not None:
                g_bot = run.stop_depth if g_bot is None else max(g_bot, run.stop_depth)
    if g_top is None or g_bot is None or g_bot <= g_top:
        raise HTTPException(400, "Wells have no usable depth range")

    span = g_bot - g_top
    bin_size = span / bins

    def to_bin(d: float) -> int:
        idx = int((d - g_top) / bin_size)
        return 0 if idx < 0 else (bins - 1 if idx >= bins else idx)

    present_union = set()
    well_rows: List[dict] = []

    for w in wells:
        methods_bins: Dict[str, np.ndarray] = {}
        w_top, w_bot = None, None
        for run in w.log_runs:
            null_value = run.null_value
            depth_arr = None
            for cd in run.curve_data:
                if (cd.mnemonic or "").strip().upper() in _DEPTH_MNEMONICS:
                    depth_arr = _decode(cd)
                    break
            if depth_arr is None:
                continue
            for cd in run.curve_data:
                mnem = (cd.mnemonic or "").strip()
                if not mnem or mnem.upper() in _DEPTH_MNEMONICS:
                    continue
                meth = method_for_mnemonic(mnem)
                if meth is None:
                    continue
                arr = _decode(cd)
                if arr is None or arr.size != depth_arr.size:
                    continue
                mask = _valid_mask(arr, null_value) & np.isfinite(depth_arr)
                if not mask.any():
                    continue
                dvals = depth_arr[mask]
                w_top = float(dvals.min()) if w_top is None else min(w_top, float(dvals.min()))
                w_bot = float(dvals.max()) if w_bot is None else max(w_bot, float(dvals.max()))
                col = methods_bins.setdefault(meth.key, np.zeros(bins, dtype=bool))
                idx = ((dvals - g_top) / bin_size).astype(int)
                idx = np.clip(idx, 0, bins - 1)
                col[idx] = True
                present_union.add(meth.key)

        well_rows.append({
            "well_id": w.id,
            "well_name": w.name,
            "depth_top": w_top,
            "depth_bottom": w_bot,
            "present": {k: v.astype(int).tolist() for k, v in methods_bins.items()},
        })

    # Column layout = union of methods present anywhere, in catalogue order.
    columns = [
        {"key": m.key, "name": m.name, "category": m.category, "color": m.color,
         "derived": m.derived}
        for m in METHODS if m.key in present_union
    ]

    return {
        "project_id": pid,
        "depth_top": round(g_top, 2),
        "depth_bottom": round(g_bot, 2),
        "bins": bins,
        "bin_size": round(bin_size, 4),
        "columns": columns,
        "wells": well_rows,
    }
