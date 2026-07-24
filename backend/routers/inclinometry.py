"""
Контроль качества инклинометрии + траектория скважины.

  * GET  /api/wells/{wid}/inclinometry      — замеры, DLS, проекции, проблемы
  * POST /api/wells/{wid}/inclinometry/dedupe — удалить дубли замеров
  * GET  /api/wells/{wid}/notes  /  POST     — заметки по качеству (авто+ручные)

DLS (dog-leg severity) считается по минимальной кривизне на 10 м; интервалы с
DLS > порога (по умолчанию 20 °/10 м) помечаются и подсвечиваются на проекциях.
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
except ImportError:  # pragma: no cover
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData


router = APIRouter(tags=["inclinometry"])

_DEPTH = {"DEPT", "DEPTH", "MD", "TVD"}
_INCL = {"INKL", "INCL", "ИНКЛ", "ZENIT", "ZENITH", "DEVI", "ANGLE", "UGOL"}
_AZIM = {"AZ", "AZIM", "AZIMUTH", "АЗИМУТ"}

DLS_DEFAULT_LIMIT = 20.0        # °/10 м
DLS_BASE = 10.0                 # длина интервала нормировки, м


def _decode(cd: CurveData) -> Optional[np.ndarray]:
    if not cd.data_binary:
        return None
    try:
        return np.frombuffer(cd.data_binary, dtype=np.float64).copy()
    except Exception:
        return None


def _find_survey(well: Well):
    """Найти рейс с инклинометрией: MD + зенит (+ азимут)."""
    best = None
    for run in well.log_runs:
        md = incl = azim = None
        for cd in run.curve_data:
            m = (cd.mnemonic or "").strip().upper()
            if m in _DEPTH and md is None:
                md = _decode(cd)
            elif m in _INCL and incl is None:
                incl = _decode(cd)
            elif m in _AZIM and azim is None:
                azim = _decode(cd)
        if md is not None and incl is not None:
            n = min(len(md), len(incl), len(azim) if azim is not None else len(md))
            if n >= 2 and (best is None or n > best[0]):
                best = (n, run, md[:n], incl[:n],
                        azim[:n] if azim is not None else np.zeros(n))
    return best


def _clean(md, incl, azim):
    """Отбросить NaN и дубли по глубине, вернуть отсортированные замеры."""
    ok = np.isfinite(md) & np.isfinite(incl)
    md, incl, azim = md[ok], incl[ok], np.where(np.isfinite(azim[ok]), azim[ok], 0.0)
    order = np.argsort(md, kind="stable")
    md, incl, azim = md[order], incl[order], azim[order]
    # дубли: одинаковая глубина (в пределах 1 мм)
    keep = np.ones(len(md), dtype=bool)
    dup_exact, dup_conflict = 0, 0
    for i in range(1, len(md)):
        if abs(md[i] - md[i - 1]) < 1e-3:
            keep[i] = False
            if abs(incl[i] - incl[i - 1]) < 1e-6 and abs(azim[i] - azim[i - 1]) < 1e-6:
                dup_exact += 1
            else:
                dup_conflict += 1
    return md[keep], incl[keep], azim[keep], dup_exact, dup_conflict


def _trajectory(md, incl, azim):
    """Минимальная кривизна: TVD/N/E + DLS на DLS_BASE метров."""
    n = len(md)
    tvd = np.zeros(n); north = np.zeros(n); east = np.zeros(n); dls = np.zeros(n)
    i_r = np.radians(incl); a_r = np.radians(azim)
    for k in range(1, n):
        dmd = md[k] - md[k - 1]
        if dmd <= 0:
            tvd[k], north[k], east[k] = tvd[k - 1], north[k - 1], east[k - 1]
            continue
        i1, i2, a1, a2 = i_r[k - 1], i_r[k], a_r[k - 1], a_r[k]
        cos_dl = (math.cos(i2 - i1)
                  - math.sin(i1) * math.sin(i2) * (1 - math.cos(a2 - a1)))
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)                       # угол пространств. искривления
        rf = 1.0 if dl < 1e-9 else (2.0 / dl) * math.tan(dl / 2.0)
        tvd[k] = tvd[k - 1] + dmd / 2 * (math.cos(i1) + math.cos(i2)) * rf
        north[k] = north[k - 1] + dmd / 2 * (
            math.sin(i1) * math.cos(a1) + math.sin(i2) * math.cos(a2)) * rf
        east[k] = east[k - 1] + dmd / 2 * (
            math.sin(i1) * math.sin(a1) + math.sin(i2) * math.sin(a2)) * rf
        dls[k] = math.degrees(dl) * (DLS_BASE / dmd)
    return tvd, north, east, dls


@router.get("/api/wells/{wid}/inclinometry")
def inclinometry(
    wid: int,
    dls_limit: float = Query(DLS_DEFAULT_LIMIT, ge=1.0, le=200.0),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    found = _find_survey(well)
    if not found:
        raise HTTPException(404, "Инклинометрия не найдена (нужны MD и зенитный угол)")
    _, run, md, incl, azim = found

    md, incl, azim, dup_exact, dup_conflict = _clean(md, incl, azim)
    if len(md) < 2:
        raise HTTPException(400, "Недостаточно замеров инклинометрии")
    tvd, north, east, dls = _trajectory(md, incl, azim)

    # ── проблемы качества ──
    problems: List[dict] = []
    # Превышения DLS группируем в интервалы, иначе на плотной записи
    # получаются тысячи однотипных сообщений.
    hi = np.where(dls > dls_limit)[0]
    if hi.size:
        seg_start = hi[0]
        prev = hi[0]
        for j in list(hi[1:]) + [None]:
            if j is not None and j == prev + 1:
                prev = j
                continue
            i0, i1 = seg_start, prev
            seg = dls[i0:i1 + 1]
            problems.append({
                "type": "dls", "severity": "high",
                "depth": round(float(md[i0]), 2),
                "depth_to": round(float(md[i1]), 2),
                "value": round(float(seg.max()), 2),
                "message": (f"DLS до {seg.max():.1f}°/10м > {dls_limit:.0f} "
                            f"на {md[i0]:.1f}–{md[i1]:.1f} м"),
            })
            if j is None:
                break
            seg_start = prev = j
    if dup_exact or dup_conflict:
        problems.append({
            "type": "duplicates",
            "severity": "high" if dup_conflict else "medium",
            "depth": None, "value": dup_exact + dup_conflict,
            "message": (f"Дубли замеров: {dup_exact} полных"
                        + (f", {dup_conflict} с расхождением значений" if dup_conflict else "")),
        })
    bad_incl = int(np.sum((incl < 0) | (incl > 120)))
    if bad_incl:
        problems.append({"type": "range", "severity": "high", "depth": None,
                         "value": bad_incl,
                         "message": f"Зенитный угол вне диапазона 0–120°: {bad_incl} замер(ов)"})
    bad_az = int(np.sum((azim < -0.001) | (azim > 360.001)))
    if bad_az:
        problems.append({"type": "range", "severity": "medium", "depth": None,
                         "value": bad_az,
                         "message": f"Азимут вне диапазона 0–360°: {bad_az} замер(ов)"})
    gaps = np.diff(md)
    big = np.where(gaps > 100.0)[0]
    for i in big:
        problems.append({"type": "gap", "severity": "medium",
                         "depth": round(float(md[i]), 2), "value": round(float(gaps[i]), 1),
                         "message": f"Пропуск {gaps[i]:.0f} м между замерами на {md[i]:.0f} м"})

    return {
        "well_id": wid, "well_name": well.name, "log_run_id": run.id,
        "count": int(len(md)), "dls_limit": dls_limit,
        "duplicates": {"exact": dup_exact, "conflicting": dup_conflict},
        "max_dls": round(float(dls.max()), 2) if len(dls) else 0.0,
        "max_incl": round(float(incl.max()), 2),
        "td_md": round(float(md[-1]), 2), "td_tvd": round(float(tvd[-1]), 2),
        "displacement": round(float(math.hypot(north[-1], east[-1])), 2),
        "survey": {
            "md": [round(float(x), 2) for x in md],
            "incl": [round(float(x), 3) for x in incl],
            "azim": [round(float(x), 2) for x in azim],
            "tvd": [round(float(x), 2) for x in tvd],
            "north": [round(float(x), 2) for x in north],
            "east": [round(float(x), 2) for x in east],
            "dls": [round(float(x), 2) for x in dls],
        },
        "problems": problems,
        "problem_count": len(problems),
    }


@router.post("/api/wells/{wid}/inclinometry/dedupe")
def inclinometry_dedupe(wid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Удалить дублирующиеся по глубине замеры инклинометрии (перезаписывает кривые)."""
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    found = _find_survey(well)
    if not found:
        raise HTTPException(404, "Инклинометрия не найдена")
    _, run, md, incl, azim = found
    before = len(md)
    md2, incl2, azim2, dup_exact, dup_conflict = _clean(md, incl, azim)
    removed = before - len(md2)
    if removed <= 0:
        return {"ok": True, "removed": 0, "message": "Дублей не найдено"}

    for cd in run.curve_data:
        m = (cd.mnemonic or "").strip().upper()
        new = None
        if m in _DEPTH:
            new = md2
        elif m in _INCL:
            new = incl2
        elif m in _AZIM:
            new = azim2
        if new is not None:
            cd.data_binary = np.asarray(new, dtype=np.float64).tobytes()
            cd.num_points = len(new)
            valid = new[np.isfinite(new)]
            cd.min_value = float(valid.min()) if valid.size else None
            cd.max_value = float(valid.max()) if valid.size else None
    run.num_points = len(md2)
    db.commit()
    return {"ok": True, "removed": removed, "kept": int(len(md2)),
            "exact": dup_exact, "conflicting": dup_conflict,
            "message": f"Удалено дублей: {removed}"}


# ── Заметки по качеству (авто + ручные) ─────────────────────────────────────
class NoteBody(BaseModel):
    text: str
    curve: Optional[str] = None
    severity: str = "medium"
    depth: Optional[float] = None


def _notes_load(well: Well) -> List[dict]:
    try:
        data = json.loads(well.notes or "[]") if hasattr(well, "notes") else []
        return data if isinstance(data, list) else []
    except (ValueError, TypeError):
        return []


@router.get("/api/wells/{wid}/notes")
def get_notes(wid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    return {"well_id": wid, "notes": _notes_load(well)}


@router.post("/api/wells/{wid}/notes")
def add_note(wid: int, body: NoteBody, db: Session = Depends(get_db)) -> Dict[str, Any]:
    import datetime
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    notes = _notes_load(well)
    note = {
        "id": (max([n.get("id", 0) for n in notes]) + 1) if notes else 1,
        "text": body.text.strip(),
        "curve": body.curve, "severity": body.severity, "depth": body.depth,
        "source": "user",
        "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds"),
    }
    if not note["text"]:
        raise HTTPException(400, "Пустая заметка")
    notes.append(note)
    well.notes = json.dumps(notes, ensure_ascii=False)
    db.commit()
    return {"ok": True, "note": note, "count": len(notes)}


@router.delete("/api/wells/{wid}/notes/{note_id}")
def delete_note(wid: int, note_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    notes = [n for n in _notes_load(well) if n.get("id") != note_id]
    well.notes = json.dumps(notes, ensure_ascii=False)
    db.commit()
    return {"ok": True, "count": len(notes)}


@router.post("/api/wells/{wid}/notes/auto")
def auto_notes(wid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Записать авто-заметки по выявленным проблемам инклинометрии."""
    import datetime
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Well not found")
    try:
        res = inclinometry(wid, DLS_DEFAULT_LIMIT, db)
    except HTTPException:
        return {"ok": True, "added": 0, "message": "Инклинометрия не найдена"}

    notes = _notes_load(well)
    existing = {(n.get("text") or "") for n in notes}
    nid = (max([n.get("id", 0) for n in notes]) + 1) if notes else 1
    added = 0
    for p in res["problems"]:
        txt = p["message"]
        if txt in existing:
            continue
        notes.append({"id": nid, "text": txt, "curve": "ИНКЛ",
                      "severity": p["severity"], "depth": p.get("depth"),
                      "source": "auto",
                      "created_at": datetime.datetime.utcnow().isoformat(timespec="seconds")})
        nid += 1
        added += 1
    well.notes = json.dumps(notes, ensure_ascii=False)
    db.commit()
    return {"ok": True, "added": added, "count": len(notes)}
