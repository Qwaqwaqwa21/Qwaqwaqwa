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

import datetime
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


# Варианты решения при совпадении методов и интервала. Отдаются вместе с
# конфликтом, чтобы интерфейс не хранил их отдельным списком и не разошёлся
# с сервером.
_CONFLICT_CHOICES = [
    {"value": "replace", "title": "Заменить",
     "hint": "Старые кривые рейса удаляются, остаётся только новая версия. "
             "Поправка глубины рейса сохраняется."},
    {"value": "merge", "title": "Дополнить",
     "hint": "В рейс добавляются только те кривые, которых в нём не было. "
             "Имеющиеся значения не трогаются."},
    {"value": "copy", "title": "Сделать копию",
     "hint": "Новая версия ложится отдельным рейсом с пометкой «(версия N)». "
             "Обе версии остаются, для карт и расчётов берётся новейшая."},
    {"value": "skip", "title": "Пропустить",
     "hint": "Файл не загружается, в скважине остаётся прежняя версия."},
]


def _replace_run(db: Session, run: LogRun, las, filename: str, run_name: str, kind: str) -> LogRun:
    """Переписать существующий рейс новой версией, СОХРАНИВ его id.

    Идентификатор не меняется намеренно: к рейсу привязана поправка глубины
    (log_run_depth_shifts), и пересоздание рейса потеряло бы увязку, которую
    интерпретатор выставил руками.
    """
    db.query(CurveData).filter(CurveData.log_run_id == run.id).delete(synchronize_session=False)
    run.filename = filename
    run.name = run_name
    run.kind = kind
    run.depth_unit = las.well.depth_unit or run.depth_unit or "M"
    run.las_version = las.version
    run.start_depth = las.well.start
    run.stop_depth = las.well.stop
    run.step = las.well.step
    run.null_value = las.well.null
    run.num_points = len(las.depth)
    run.curves_json = json.dumps(
        [{"mnemonic": c.mnemonic, "unit": c.unit, "description": c.description,
          "canonical": c.canonical or c.mnemonic} for c in las.curves],
        ensure_ascii=False)
    run.parameters_json = json.dumps(
        [{"mnemonic": p.mnemonic, "unit": p.unit, "value": p.value} for p in las.parameters],
        ensure_ascii=False)
    run.uploaded_at = datetime.datetime.utcnow()
    for curve in las.curves:
        arr = las.data.get(curve.mnemonic)
        if arr is None:
            continue
        valid = arr[np.isfinite(arr)]
        db.add(CurveData(
            log_run_id=run.id, mnemonic=curve.mnemonic, unit=curve.unit,
            description=curve.description, num_points=len(arr),
            min_value=float(np.min(valid)) if valid.size else None,
            max_value=float(np.max(valid)) if valid.size else None,
            data_binary=arr.tobytes(),
        ))
    return run


def _merge_into_run(db: Session, run: LogRun, las) -> List[str]:
    """Дополнить рейс кривыми, которых в нём ещё нет. Имеющиеся не трогаем.

    Возвращает список добавленных мнемоник: пустой означает, что новых
    методов в файле не было и дополнять нечем.
    """
    have = {(cd.mnemonic or "").strip().upper()
            for cd in db.query(CurveData).filter(CurveData.log_run_id == run.id).all()}
    added: List[str] = []
    for curve in las.curves:
        mn = (curve.mnemonic or "").strip()
        if not mn or mn.upper() in have:
            continue
        arr = las.data.get(curve.mnemonic)
        if arr is None:
            continue
        valid = arr[np.isfinite(arr)]
        db.add(CurveData(
            log_run_id=run.id, mnemonic=mn, unit=curve.unit,
            description=curve.description, num_points=len(arr),
            min_value=float(np.min(valid)) if valid.size else None,
            max_value=float(np.max(valid)) if valid.size else None,
            data_binary=arr.tobytes(),
        ))
        added.append(mn)
    if added:
        try:
            defs = json.loads(run.curves_json or "[]")
        except (ValueError, TypeError):
            defs = []
        known = {(d.get("mnemonic") or "").strip().upper() for d in defs}
        for curve in las.curves:
            mn = (curve.mnemonic or "").strip()
            if mn and mn.upper() in {a.upper() for a in added} and mn.upper() not in known:
                defs.append({"mnemonic": mn, "unit": curve.unit,
                             "description": curve.description,
                             "canonical": curve.canonical or mn})
        run.curves_json = json.dumps(defs, ensure_ascii=False)
        run.uploaded_at = datetime.datetime.utcnow()
    return added


def _copy_run_name(db: Session, well: Well, base_name: str) -> str:
    """Имя для копии: «Азево-Салаушское_С1 (версия 2)».

    Без пометки в списке рейсов оказывались две строки с одинаковым именем и
    одинаковым интервалом — выбрать нужную было невозможно.
    """
    existing = {(r.name or "").strip() for r in well.log_runs}
    n = 2
    while f"{base_name} (версия {n})" in existing:
        n += 1
    return f"{base_name} (версия {n})"


def _find_duplicate_run(db: Session, well: Well, las, mnemonics: List[str]):
    """Есть ли в скважине рейс с тем же набором методов и тем же интервалом.

    Считаем повтором, если совпадает набор методов ГИС и интервалы глубин
    перекрываются больше чем на 90 % — именно так выглядит случайная повторная
    загрузка того же файла. Разные интервалы одного метода (С1/С2/D у
    заказчика) повтором НЕ считаются.
    """
    new_keys = {m.key for m in (method_for_mnemonic(x) for x in mnemonics) if m}
    if not new_keys:
        return None
    n_lo, n_hi = float(las.well.start or 0), float(las.well.stop or 0)
    if not (n_hi > n_lo):
        return None

    for run in well.log_runs:
        try:
            defs = json.loads(run.curves_json or "[]")
        except (ValueError, TypeError):
            defs = []
        old_keys = {
            m.key for m in (method_for_mnemonic(d.get("mnemonic", "")) for d in defs) if m
        }
        if not old_keys:
            continue
        common = old_keys & new_keys
        if not common:
            continue
        # Совпадение НЕ обязано быть точным: новая версия РИГИС обычно
        # добавляет кривую (появился Кпр) или, наоборот, что-то в ней не
        # посчитали. Пока пересечение покрывает большую часть меньшего
        # набора, это тот же материал на тот же интервал.
        if len(common) * 2 < min(len(old_keys), len(new_keys)):
            continue
        o_lo, o_hi = float(run.start_depth or 0), float(run.stop_depth or 0)
        if not (o_hi > o_lo):
            continue
        overlap = max(0.0, min(n_hi, o_hi) - max(n_lo, o_lo))
        share = overlap / max(n_hi - n_lo, o_hi - o_lo)   # по ШИРОКОМУ интервалу
        same_points = int(run.num_points or 0) == int(len(las.depth))
        if share >= 0.99 and same_points:
            return {
                "id": run.id,
                "run": run.name or run.filename,
                "overlap": round(share * 100, 1),
                "methods": sorted(common),
                "methods_new": sorted(new_keys - old_keys),
                "methods_missing": sorted(old_keys - new_keys),
            }
    return None


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
    # ask — не грузить, вернуть конфликт на решение пользователя (по умолчанию);
    # replace — заменить данные рейса; merge — дополнить недостающими кривыми;
    # copy — отдельным рейсом с пометкой версии; skip — пропустить
    on_duplicate: str = Form("ask"),
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
    created_ids: set = set()   # скважины, созданные этим импортом

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
                created_ids.add(well.id)
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

            # Скважина уже была в проекте — проверяем, не грузим ли повторно
            # тот же набор методов в том же интервале.
            dup = None
            if kind != "inkl" and well.id not in created_ids:
                dup = _find_duplicate_run(db, well, las, mnems)
            if dup is not None and on_duplicate in ("ask", "skip"):
                # По умолчанию НЕ решаем за пользователя: те же методы в том же
                # интервале — это либо повторная загрузка, либо новая версия
                # РИГИС, и разница между «заменить», «дополнить» и «копия»
                # меняет и карты, и расчёты. Файл не грузится, конфликт
                # возвращается на решение.
                row.update(status="conflict" if on_duplicate == "ask" else "duplicate",
                           well=well.name, well_id=well.id, run=rname,
                           kind=kind, duplicate_of=dup["run"],
                           duplicate_id=dup["id"], overlap=dup["overlap"],
                           methods=dup["methods"],
                           methods_new=dup.get("methods_new", []),
                           methods_missing=dup.get("methods_missing", []),
                           choices=_CONFLICT_CHOICES)
                db.rollback()
                results.append(row)
                continue

            if dup is not None and on_duplicate == "replace":
                old_run = db.query(LogRun).filter(LogRun.id == dup["id"]).first()
                run = _replace_run(db, old_run, las, fname, rname, kind)
                row.update(status="ok", well=well.name, run=rname, kind=kind,
                           curves=len(las.curves), run_id=run.id,
                           action="replaced", duplicate_of=dup["run"],
                           duplicate_id=dup["id"])
                db.commit()
                results.append(row)
                continue

            if dup is not None and on_duplicate == "merge":
                old_run = db.query(LogRun).filter(LogRun.id == dup["id"]).first()
                added = _merge_into_run(db, old_run, las)
                row.update(status="ok", well=well.name, run=old_run.name, kind=kind,
                           curves=len(added), run_id=old_run.id,
                           action="merged", added=added,
                           duplicate_of=dup["run"], duplicate_id=dup["id"])
                db.commit()
                results.append(row)
                continue

            if dup is not None and on_duplicate in ("copy", "load"):
                # отдельный рейс с пометкой версии, иначе в списке две
                # неразличимые строки с одинаковым именем и интервалом
                rname = _copy_run_name(db, well, rname)

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
                if dup is not None:
                    row.update(duplicate_of=dup["run"], duplicate_id=dup["id"],
                               overlap=dup["overlap"], methods=dup["methods"])
            db.commit()
        except Exception as exc:  # noqa: BLE001 — отчёт по каждому файлу отдельно
            db.rollback()
            row["error"] = str(exc)
        results.append(row)

    ok = sum(1 for r in results if r["status"] == "ok")
    dups = sum(1 for r in results if r["status"] == "duplicate")
    conflicts = [r for r in results if r["status"] == "conflict"]
    return {
        "project_id": pid,
        "files": len(results),
        "imported": ok,
        "duplicates": dups,
        "conflicts": len(conflicts),
        "needs_decision": conflicts,
        "choices": _CONFLICT_CHOICES if conflicts else [],
        "failed": len(results) - ok - dups - len(conflicts),
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


# ── Поиск полных дублей ──────────────────────────────────────────────────────

@router.get("/api/wells/{wid}/duplicates")
def find_duplicates(wid: int, db: Session = Depends(get_db)):
    """Полные дубли внутри скважины: одинаковые кривые и повторы по глубине.

    Проверяем три вещи:
      * пары кривых с полностью совпадающими значениями (в т.ч. в разных рейсах);
      * повторяющиеся значения глубины внутри рейса;
      * рейсы с одинаковым набором методов и перекрытием интервала.
    """
    well = db.query(Well).filter(Well.id == wid).first()
    if not well:
        raise HTTPException(404, "Скважина не найдена")

    # ── кривые ──
    series = []            # (рейс, мнемоника, массив)
    depth_dups = []
    for run in well.log_runs:
        rows = db.query(CurveData).filter(CurveData.log_run_id == run.id).all()
        by_name = {c.mnemonic: c for c in rows}
        dkey = next((k for k in ("DEPT", "DEPTH", "MD", "TVD") if k in by_name), None)
        if dkey and by_name[dkey].data_binary:
            d = np.frombuffer(by_name[dkey].data_binary, dtype=np.float64)
            uniq, counts = np.unique(d[np.isfinite(d)], return_counts=True)
            rep = uniq[counts > 1]
            if rep.size:
                depth_dups.append({
                    "run": run.name or run.filename, "run_id": run.id,
                    "count": int(rep.size),
                    "examples": [round(float(x), 3) for x in rep[:10]],
                })
        for c in rows:
            if c.mnemonic == dkey or not c.data_binary:
                continue
            arr = np.frombuffer(c.data_binary, dtype=np.float64)
            if np.isfinite(arr).sum() == 0:
                continue
            series.append((run, c.mnemonic, arr))

    curve_dups = []
    for i in range(len(series)):
        run_a, name_a, a = series[i]
        for j in range(i + 1, len(series)):
            run_b, name_b, b = series[j]
            if len(a) != len(b):
                continue
            same = np.array_equal(np.nan_to_num(a, nan=-9.87e37),
                                  np.nan_to_num(b, nan=-9.87e37))
            if same:
                curve_dups.append({
                    "a": {"run": run_a.name or run_a.filename, "run_id": run_a.id, "curve": name_a},
                    "b": {"run": run_b.name or run_b.filename, "run_id": run_b.id, "curve": name_b},
                    "points": int(len(a)),
                })

    # ── рейсы ──
    run_dups = []
    runs = list(well.log_runs)
    for i in range(len(runs)):
        for j in range(i + 1, len(runs)):
            ra, rb = runs[i], runs[j]
            try:
                ka = {m.key for m in (method_for_mnemonic(d.get("mnemonic", ""))
                                      for d in json.loads(ra.curves_json or "[]")) if m}
                kb = {m.key for m in (method_for_mnemonic(d.get("mnemonic", ""))
                                      for d in json.loads(rb.curves_json or "[]")) if m}
            except (ValueError, TypeError):
                continue
            if not ka or ka != kb:
                continue
            a_lo, a_hi = float(ra.start_depth or 0), float(ra.stop_depth or 0)
            b_lo, b_hi = float(rb.start_depth or 0), float(rb.stop_depth or 0)
            if not (a_hi > a_lo and b_hi > b_lo):
                continue
            ov = max(0.0, min(a_hi, b_hi) - max(a_lo, b_lo))
            share = ov / min(a_hi - a_lo, b_hi - b_lo)
            if share >= 0.9:
                run_dups.append({
                    "a": {"run": ra.name or ra.filename, "run_id": ra.id},
                    "b": {"run": rb.name or rb.filename, "run_id": rb.id},
                    "overlap_pct": round(share * 100, 1),
                    "methods": sorted(ka),
                })

    return {
        "well_id": wid, "well": well.name,
        "identical_curves": curve_dups,
        "duplicate_depths": depth_dups,
        "duplicate_runs": run_dups,
        "total": len(curve_dups) + len(depth_dups) + len(run_dups),
    }


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
