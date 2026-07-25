"""
Пакетный импорт данных и управление рейсами.

  * POST   /api/projects/{pid}/bulk-import        — импорт папки с подпапками
  * GET    /api/wells/{wid}/curve-tree            — дерево «рейс → кривые» с глубинами
  * PATCH  /api/runs/{rid}                        — переименование рейса
  * DELETE /api/runs/{rid}                        — удаление рейса
  * DELETE /api/runs/{rid}/curves/{mnemonic}      — удаление кривой из проекта
  * GET    /api/wells/{wid}/tvd                   — таблица MD → TVD/абс. отметка

Скважина определяется из шапки LAS (~W WELL), а не из имени файла: у заказчика
файл называется по номеру скважины, но встречаются и папки с чужими именами.
Имя рейса по умолчанию берётся из папки (ГИС_С1, РИГИС, INKL…), потому что в
реальных выгрузках рейс = каталог.

Инклинометрия (кривые INCL/INKL + AZ) не становится рейсом на планшете: она
кладётся в таблицу замеров и служит для пересчёта MD → TVD для всех остальных
рейсов скважины.
"""
from __future__ import annotations

import json
import math
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Body, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Well, LogRun, CurveData, Project, DeviationSurvey
    from las_parser import LASParser
    from methods import method_for_mnemonic
except ImportError:  # pragma: no cover
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData, Project, DeviationSurvey
    from backend.las_parser import LASParser
    from backend.methods import method_for_mnemonic

router = APIRouter(tags=["ingest"])

DEPTH_MNEMONICS = {"DEPT", "DEPTH", "MD", "TVD", "ГЛУБ", "ГЛУБИНА"}
INCL_MNEMONICS = {"INCL", "INKL", "INC", "ZENITH", "ZEN", "УГОЛ", "ЗЕНИТ"}
AZIM_MNEMONICS = {"AZ", "AZI", "AZIM", "AZIMUTH", "АЗИМУТ", "АЗ"}


# ── Вспомогательное ──────────────────────────────────────────────────────────

def _clean_name(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()


def _run_name_from_path(rel_path: str, filename: str) -> str:
    """Имя рейса = ближайшая папка; если файл лежит в корне — имя файла."""
    rel = str(rel_path or "").replace("\\", "/").strip("/")
    parts = [p for p in rel.split("/") if p]
    if len(parts) >= 2:
        return _clean_name(parts[-2])
    stem = os.path.splitext(os.path.basename(filename or ""))[0]
    return _clean_name(stem) or "RUN"


def _classify(run_name: str, mnemonics: List[str]) -> str:
    """Тип рейса: inkl / rigis / gis."""
    up = {m.upper() for m in mnemonics}
    if (up & INCL_MNEMONICS) and (up & AZIM_MNEMONICS):
        return "inkl"
    name_up = (run_name or "").upper()
    if "INKL" in name_up or "ИНКЛ" in name_up:
        return "inkl"
    if "RIGIS" in name_up or "РИГИС" in name_up:
        return "rigis"
    keys = {m.key for m in (method_for_mnemonic(x) for x in mnemonics) if m}
    if {"LITH", "COLL", "SAT"} & keys:
        return "rigis"
    return "gis"


def _minimum_curvature(md, inc_deg, azi_deg):
    """Классический minimum curvature: возвращает TVD/N/E."""
    n = len(md)
    tvd = np.zeros(n)
    north = np.zeros(n)
    east = np.zeros(n)
    inc = np.radians(inc_deg)
    azi = np.radians(azi_deg)
    for i in range(1, n):
        dmd = md[i] - md[i - 1]
        if dmd <= 0:
            tvd[i], north[i], east[i] = tvd[i - 1], north[i - 1], east[i - 1]
            continue
        cos_dl = (math.cos(inc[i] - inc[i - 1])
                  - math.sin(inc[i]) * math.sin(inc[i - 1])
                  * (1 - math.cos(azi[i] - azi[i - 1])))
        cos_dl = max(-1.0, min(1.0, cos_dl))
        dl = math.acos(cos_dl)
        rf = 1.0 if dl < 1e-9 else (2.0 / dl) * math.tan(dl / 2.0)
        half = dmd / 2.0 * rf
        tvd[i] = tvd[i - 1] + half * (math.cos(inc[i - 1]) + math.cos(inc[i]))
        north[i] = north[i - 1] + half * (math.sin(inc[i - 1]) * math.cos(azi[i - 1])
                                          + math.sin(inc[i]) * math.cos(azi[i]))
        east[i] = east[i - 1] + half * (math.sin(inc[i - 1]) * math.sin(azi[i - 1])
                                        + math.sin(inc[i]) * math.sin(azi[i]))
    return tvd, north, east


def _store_deviation(db: Session, well: Well, las) -> int:
    """Записать инклинометрию скважины (замещая прежнюю) и посчитать TVD."""
    depth_key = las.depth_key
    md = las.data.get(depth_key)
    if md is None:
        return 0
    inc = azi = None
    for c in las.curves:
        up = c.mnemonic.upper()
        base = re.sub(r"_\d+$", "", up)
        if inc is None and (up in INCL_MNEMONICS or base in INCL_MNEMONICS):
            inc = las.data.get(c.mnemonic)
        elif azi is None and (up in AZIM_MNEMONICS or base in AZIM_MNEMONICS):
            azi = las.data.get(c.mnemonic)
    if inc is None or azi is None:
        return 0

    ok = np.isfinite(md) & np.isfinite(inc) & np.isfinite(azi)
    md_v, inc_v, azi_v = md[ok], inc[ok], azi[ok]
    if len(md_v) < 2:
        return 0

    order = np.argsort(md_v)
    md_v, inc_v, azi_v = md_v[order], inc_v[order], azi_v[order]
    # Дубли по MD (повторные замеры одной глубины) убираем сразу при импорте.
    keep = np.concatenate(([True], np.diff(md_v) > 1e-6))
    md_v, inc_v, azi_v = md_v[keep], inc_v[keep], azi_v[keep]

    tvd, north, east = _minimum_curvature(md_v, inc_v, azi_v)

    db.query(DeviationSurvey).filter(DeviationSurvey.well_id == well.id).delete()
    db.bulk_save_objects([
        DeviationSurvey(well_id=well.id, md=float(m), inc=float(i), azi=float(a),
                        tvd=float(t), northing=float(nn), easting=float(ee))
        for m, i, a, t, nn, ee in zip(md_v, inc_v, azi_v, tvd, north, east)
    ])
    return int(len(md_v))


def _persist_run(db: Session, well: Well, las, filename: str,
                 run_name: str, kind: str) -> LogRun:
    curves_def = [
        {"mnemonic": c.mnemonic, "unit": c.unit, "description": c.description,
         "canonical": c.canonical or c.mnemonic}
        for c in las.curves
    ]
    run = LogRun(
        well_id=well.id,
        run_number=len(well.log_runs) + 1,
        filename=filename,
        name=run_name,
        kind=kind,
        depth_unit=(las.well.depth_unit or "M"),
        las_version=las.version,
        start_depth=las.well.start,
        stop_depth=las.well.stop,
        step=las.well.step,
        null_value=las.well.null,
        num_points=len(las.depth),
        curves_json=json.dumps(curves_def, ensure_ascii=False),
        parameters_json=json.dumps(
            [{"mnemonic": p.mnemonic, "unit": p.unit, "value": p.value} for p in las.parameters],
            ensure_ascii=False),
    )
    db.add(run)
    db.flush()

    for curve in las.curves:
        arr = las.data.get(curve.mnemonic)
        if arr is None:
            continue
        valid = arr[np.isfinite(arr)]
        db.add(CurveData(
            log_run_id=run.id,
            mnemonic=curve.mnemonic,
            unit=curve.unit,
            description=curve.description,
            num_points=len(arr),
            min_value=float(np.min(valid)) if valid.size else None,
            max_value=float(np.max(valid)) if valid.size else None,
            data_binary=arr.tobytes(),
        ))
    return run


def _apply_header_to_well(well: Well, las) -> None:
    """Единицы, координаты и альтитуда из шапки LAS — если их ещё нет."""
    if las.well.depth_unit:
        well.depth_unit = las.well.depth_unit
    if las.well.uwi and not well.uwi:
        well.uwi = las.well.uwi
    if las.well.field and not well.field_name:
        well.field_name = las.well.field
    if las.well.x is not None and well.x_coord is None:
        well.x_coord = las.well.x
    if las.well.y is not None and well.y_coord is None:
        well.y_coord = las.well.y
    if las.well.rkb is not None and well.elevation is None:
        well.elevation = las.well.rkb
    if las.well.stop and (well.total_depth or 0) < las.well.stop:
        well.total_depth = las.well.stop


# ── Пакетный импорт ──────────────────────────────────────────────────────────

@router.post("/api/projects/{pid}/bulk-import")
async def bulk_import(
    pid: int,
    files: List[UploadFile] = File(...),
    paths: str = Form("[]"),
    run_name_mode: str = Form("folder"),   # folder | file | fixed
    run_name: str = Form(""),
    db: Session = Depends(get_db),
):
    """Импорт множества LAS: скважина определяется из шапки, рейс — из папки."""
    project = db.query(Project).filter(Project.id == pid).first()
    if not project:
        raise HTTPException(404, "Проект не найден")

    try:
        rel_paths = json.loads(paths) if paths else []
    except (ValueError, TypeError):
        rel_paths = []

    wells_by_name: Dict[str, Well] = {
        _clean_name(w.name).lower(): w
        for w in db.query(Well).filter(Well.project_id == pid).all()
    }

    results: List[Dict[str, Any]] = []
    created_wells = 0

    for idx, up_file in enumerate(files):
        rel = rel_paths[idx] if idx < len(rel_paths) else (up_file.filename or "")
        fname = os.path.basename(up_file.filename or rel or f"file{idx}.las")
        row: Dict[str, Any] = {"file": rel or fname, "status": "error",
                               "well": "", "run": "", "curves": 0, "error": ""}
        try:
            content = await up_file.read()
            if not content:
                raise ValueError("пустой файл")
            las = LASParser.parse_bytes(content)

            # Имя скважины: шапка → имя файла без расширения.
            wname = _clean_name(las.well.well_name)
            if not wname or wname.upper() in {"WELL", "UNKNOWN", "N/A", "-"}:
                wname = _clean_name(os.path.splitext(fname)[0])
            if not wname:
                raise ValueError("не удалось определить скважину")

            key = wname.lower()
            well = wells_by_name.get(key)
            if well is None:
                well = Well(project_id=pid, name=wname, depth_unit="M")
                db.add(well)
                db.flush()
                wells_by_name[key] = well
                created_wells += 1

            mnems = [c.mnemonic for c in las.curves if c.mnemonic.upper() not in DEPTH_MNEMONICS]
            if run_name_mode == "fixed" and run_name.strip():
                rname = _clean_name(run_name)
            elif run_name_mode == "file":
                rname = _clean_name(os.path.splitext(fname)[0])
            else:
                rname = _run_name_from_path(rel, fname)

            kind = _classify(rname, mnems)
            _apply_header_to_well(well, las)

            if kind == "inkl":
                n = _store_deviation(db, well, las)
                if not n:
                    raise ValueError("инклинометрия без пригодных замеров MD/INCL/AZ")
                row.update(status="ok", well=well.name, run=rname,
                           curves=n, kind="inkl")
            else:
                run = _persist_run(db, well, las, fname, rname, kind)
                row.update(status="ok", well=well.name, run=rname,
                           curves=len(las.curves), kind=kind, run_id=run.id)
            db.commit()
        except Exception as exc:  # noqa: BLE001 — отчёт по каждому файлу отдельно
            db.rollback()
            row["error"] = str(exc)
        results.append(row)

    ok = sum(1 for r in results if r["status"] == "ok")
    return {
        "project_id": pid,
        "files": len(results),
        "imported": ok,
        "failed": len(results) - ok,
        "wells_created": created_wells,
        "results": results,
    }


# ── Отбивки одним файлом на весь проект ──────────────────────────────────────

_TOPS_HEADERS = {
    "well": ("скважина", "скв", "well", "wellname", "well_name", "уwi", "uwi"),
    "horizon": ("горизонт", "пласт", "отбивка", "формация", "horizon", "formation",
                "surface", "marker", "top_name", "zone"),
    "top": ("кровля", "top", "top_depth", "md_top", "глубина", "depth"),
    "base": ("подошва", "base", "bottom", "base_depth", "md_base"),
}


def _read_table(data: bytes, filename: str) -> List[List[str]]:
    """Строки Excel/CSV в виде списка строковых ячеек."""
    import csv as _csv
    import io as _io

    name = (filename or "").lower()
    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(400, "На сервере нет openpyxl")
        try:
            wb = openpyxl.load_workbook(_io.BytesIO(data), read_only=True, data_only=True)
        except Exception as exc:
            raise HTTPException(400, f"Не удалось прочитать книгу: {exc}")
        return [["" if c is None else str(c) for c in r]
                for r in wb.active.iter_rows(values_only=True)]

    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "cp866", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except (UnicodeDecodeError, LookupError):
            continue
    if text is None:
        text = data.decode("latin-1", errors="replace")
    first = text.splitlines()[0] if text.splitlines() else ""
    delim = ";" if first.count(";") > first.count(",") else ","
    return [list(r) for r in _csv.reader(_io.StringIO(text), delimiter=delim)]


def _num(v) -> Optional[float]:
    try:
        return float(str(v).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


@router.post("/api/projects/{pid}/tops/import")
async def import_tops(pid: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Отбивки для всех скважин одним файлом: скважина | горизонт | кровля | подошва."""
    try:
        from models import FormationTop
    except ImportError:  # pragma: no cover
        from backend.models import FormationTop

    if not db.query(Project).filter(Project.id == pid).first():
        raise HTTPException(404, "Проект не найден")
    data = await file.read()
    if not data:
        raise HTTPException(400, "Пустой файл")
    rows = _read_table(data, file.filename or "")
    if not rows:
        raise HTTPException(400, "В файле нет строк")

    # Поиск строки заголовка: сопоставляем ячейки со словарём синонимов.
    col: Dict[str, int] = {}
    header_row = -1
    for ri, row in enumerate(rows[:10]):
        found: Dict[str, int] = {}
        for ci, cell in enumerate(row):
            low = str(cell).strip().lower()
            for key, names in _TOPS_HEADERS.items():
                if key not in found and low in names:
                    found[key] = ci
        if "well" in found and "horizon" in found and "top" in found:
            col, header_row = found, ri
            break
    if header_row < 0:
        # Без заголовка — считаем первые 4 колонки позиционно.
        col, header_row = {"well": 0, "horizon": 1, "top": 2, "base": 3}, -1

    wells = {_clean_name(w.name).lower(): w
             for w in db.query(Well).filter(Well.project_id == pid).all()}

    added = 0
    unknown: Dict[str, int] = {}
    horizons: set = set()
    touched: set = set()
    for row in rows[header_row + 1:]:
        if not row or all(str(c).strip() == "" for c in row):
            continue

        def cell(key):
            i = col.get(key, -1)
            return row[i] if 0 <= i < len(row) else ""

        wname = _clean_name(cell("well"))
        if wname.endswith(".0"):
            wname = wname[:-2]              # Excel отдаёт номера как 2067.0
        hname = _clean_name(cell("horizon"))
        top = _num(cell("top"))
        base = _num(cell("base"))
        if not wname or not hname or top is None:
            continue
        well = wells.get(wname.lower())
        if well is None:
            unknown[wname] = unknown.get(wname, 0) + 1
            continue
        if well.id not in touched:
            db.query(FormationTop).filter(FormationTop.well_id == well.id).delete()
            touched.add(well.id)
        db.add(FormationTop(
            well_id=well.id, formation_name=hname, depth=top,
            top_depth=top, base_depth=base,
            depth_unit=(well.depth_unit or "M"),
        ))
        horizons.add(hname)
        added += 1

    db.commit()
    return {
        "project_id": pid,
        "tops_added": added,
        "wells_updated": len(touched),
        "horizons": sorted(horizons),
        "unknown_wells": sorted(unknown),
        "note": ("Скважины из файла, которых нет в проекте, пропущены"
                 if unknown else "Все скважины из файла найдены"),
    }


# ── Дерево кривых и управление рейсами ───────────────────────────────────────

@router.get("/api/wells/{wid}/curve-tree")
def curve_tree(wid: int, db: Session = Depends(get_db)):
    """Рейсы скважины с кривыми и фактическим интервалом каждой кривой."""
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Скважина не найдена")

    dev_count = db.query(DeviationSurvey).filter(DeviationSurvey.well_id == wid).count()
    runs_out = []
    for run in sorted(well.log_runs, key=lambda r: (r.name or "", r.id)):
        rows = db.query(CurveData).filter(CurveData.log_run_id == run.id).all()
        by_name = {c.mnemonic: c for c in rows}
        depth_key = next((k for k in ("DEPT", "DEPTH", "MD", "TVD") if k in by_name), None)
        depth = None
        if depth_key is not None and by_name[depth_key].data_binary:
            depth = np.frombuffer(by_name[depth_key].data_binary, dtype=np.float64)

        curves = []
        for c in rows:
            if c.mnemonic == depth_key:
                continue
            top = base = None
            pts = 0
            if c.data_binary:
                arr = np.frombuffer(c.data_binary, dtype=np.float64)
                good = np.isfinite(arr)
                pts = int(good.sum())
                if depth is not None and len(depth) == len(arr) and pts:
                    d = depth[good]
                    d = d[np.isfinite(d)]
                    if d.size:
                        top, base = float(np.min(d)), float(np.max(d))
            curves.append({
                "mnemonic": c.mnemonic,
                "unit": c.unit or "",
                "description": c.description or "",
                "method": (_m.key if (_m := method_for_mnemonic(c.mnemonic)) else ""),
                "method_name": (_m.name if _m else ""),
                "color": (_m.color if _m else "#8b949e"),
                "points": pts,
                "empty": pts == 0,
                "top": top,
                "base": base,
                "min": c.min_value,
                "max": c.max_value,
            })
        runs_out.append({
            "id": run.id,
            "name": run.name or run.filename,
            "filename": run.filename,
            "kind": run.kind or "gis",
            "depth_unit": run.depth_unit or well.depth_unit or "M",
            "start_depth": run.start_depth,
            "stop_depth": run.stop_depth,
            "num_points": run.num_points,
            "curves": curves,
        })

    return {
        "well_id": wid,
        "well": well.name,
        "depth_unit": well.depth_unit or "M",
        "elevation": well.elevation,
        "has_inclinometry": dev_count > 0,
        "inclinometry_points": dev_count,
        "runs": runs_out,
    }


@router.patch("/api/runs/{rid}")
def rename_run(rid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    run = db.query(LogRun).filter(LogRun.id == rid).first()
    if not run:
        raise HTTPException(404, "Рейс не найден")
    if "name" in payload:
        new_name = _clean_name(payload.get("name"))
        if not new_name:
            raise HTTPException(400, "Пустое имя рейса")
        run.name = new_name
    if "kind" in payload and payload["kind"] in ("gis", "rigis", "inkl", "other"):
        run.kind = payload["kind"]
    db.commit()
    return {"id": run.id, "name": run.name, "kind": run.kind}


@router.delete("/api/runs/{rid}")
def delete_run(rid: int, db: Session = Depends(get_db)):
    run = db.query(LogRun).filter(LogRun.id == rid).first()
    if not run:
        raise HTTPException(404, "Рейс не найден")
    db.delete(run)
    db.commit()
    return {"status": "ok", "deleted_run": rid}


@router.delete("/api/runs/{rid}/curves/{mnemonic}")
def delete_curve(rid: int, mnemonic: str, db: Session = Depends(get_db)):
    run = db.query(LogRun).filter(LogRun.id == rid).first()
    if not run:
        raise HTTPException(404, "Рейс не найден")
    row = db.query(CurveData).filter(
        CurveData.log_run_id == rid, CurveData.mnemonic == mnemonic).first()
    if not row:
        raise HTTPException(404, "Кривая не найдена")
    db.delete(row)
    try:
        defs = json.loads(run.curves_json or "[]")
        run.curves_json = json.dumps(
            [d for d in defs if d.get("mnemonic") != mnemonic], ensure_ascii=False)
    except (ValueError, TypeError):
        pass
    db.commit()
    return {"status": "ok", "deleted": mnemonic, "run_id": rid}


# ── MD → TVD ─────────────────────────────────────────────────────────────────

@router.get("/api/wells/{wid}/tvd")
def tvd_table(wid: int, db: Session = Depends(get_db)):
    """Таблица пересчёта MD → TVD и абсолютную отметку (альтитуда − TVD).

    Если инклинометрии нет, скважина считается вертикальной: TVD = MD.
    """
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Скважина не найдена")
    pts = (db.query(DeviationSurvey)
           .filter(DeviationSurvey.well_id == wid)
           .order_by(DeviationSurvey.md).all())
    alt = well.elevation
    if not pts:
        return {"well_id": wid, "vertical": True, "elevation": alt,
                "md": [], "tvd": [], "source": "нет инклинометрии — TVD = MD"}
    md = [float(p.md) for p in pts]
    tvd = [float(p.tvd) if p.tvd is not None else float(p.md) for p in pts]
    return {
        "well_id": wid,
        "vertical": False,
        "elevation": alt,
        "md": md,
        "tvd": tvd,
        "abs": [None if alt is None else alt - t for t in tvd],
        "max_inc": max((float(p.inc) for p in pts), default=0.0),
        "source": f"инклинометрия, {len(pts)} замеров",
    }
