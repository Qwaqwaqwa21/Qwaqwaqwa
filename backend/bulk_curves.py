"""Пакетное чтение кривых проекта.

Сводные экраны — планшет охвата, таблица по горизонтам, инвентаризация, карты
— обходят все скважины проекта. Через связи ORM это выливается в отдельный
запрос на каждый рейс: на 1500 рейсах выходило 1500 запросов и 21 секунда,
причём почти всё время уходило не на чтение данных, а на создание объектов
SQLAlchemy. Тот же материал сырым запросом читается за 0.5 с — распаковка
numpy на его фоне занимает сотые доли.

Здесь данные берутся ОДНИМ запросом на проект и раскладываются в обычные
словари. ORM для этого не нужен: кривые в сводках только читаются.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

import numpy as np
from sqlalchemy import text

# Имена индексных кривых: нужны всегда, по ним строится глубина
DEPTH_NAMES = {"DEPT", "DEPTH", "MD", "TVD", "ГЛУБ", "ГЛУБИНА"}


class RunCurves:
    """Кривые одного рейса: мнемоника → (единица, число точек, массив)."""

    __slots__ = ("run_id", "well_id", "curves")

    def __init__(self, run_id: int, well_id: int):
        self.run_id = run_id
        self.well_id = well_id
        self.curves: Dict[str, Tuple[str, int, np.ndarray]] = {}

    def get(self, mnemonic: str):
        return self.curves.get((mnemonic or "").strip().upper())

    def items(self):
        return self.curves.items()


def load_project_curves(db, pid: int,
                        mnemonics: Optional[Iterable[str]] = None,
                        kinds: Optional[Iterable[str]] = None
                        ) -> Dict[int, Dict[int, RunCurves]]:
    """{well_id: {run_id: RunCurves}} для всего проекта одним запросом.

    ``mnemonics`` ограничивает выборку конкретными именами колонок — если
    сводке нужны только Кп и КОЛЛЕКТОР, незачем поднимать с диска весь ГИС.
    ``kinds`` фильтрует по виду рейса (gis / rigis / inkl).
    """
    sql = ["""
        SELECT lr.well_id, cd.log_run_id, cd.mnemonic, cd.unit,
               cd.num_points, cd.data_binary
        FROM curve_data cd
        JOIN log_runs lr ON lr.id = cd.log_run_id
        JOIN wells w ON w.id = lr.well_id
        WHERE w.project_id = :pid
    """]
    params: Dict[str, object] = {"pid": pid}

    if mnemonics is not None:
        names = sorted({(m or "").strip().upper() for m in mnemonics if (m or "").strip()})
        if not names:
            return {}
        keys = [f"m{i}" for i in range(len(names))]
        sql.append(" AND UPPER(TRIM(cd.mnemonic)) IN (%s)" % ", ".join(f":{k}" for k in keys))
        params.update(dict(zip(keys, names)))

    if kinds is not None:
        vals = sorted({(k or "").strip().lower() for k in kinds if (k or "").strip()})
        if not vals:
            return {}
        keys = [f"k{i}" for i in range(len(vals))]
        sql.append(" AND LOWER(COALESCE(lr.kind, '')) IN (%s)" % ", ".join(f":{k}" for k in keys))
        params.update(dict(zip(keys, vals)))

    out: Dict[int, Dict[int, RunCurves]] = {}
    for well_id, run_id, mnem, unit, npts, blob in db.execute(text("".join(sql)), params):
        by_run = out.setdefault(well_id, {})
        rc = by_run.get(run_id)
        if rc is None:
            rc = by_run[run_id] = RunCurves(run_id, well_id)
        arr = np.frombuffer(blob, dtype=np.float64) if blob else np.empty(0)
        rc.curves[(mnem or "").strip().upper()] = (unit or "", int(npts or arr.size), arr)
    return out


def load_run_curves(db, run_ids: Iterable[int]) -> Dict[int, RunCurves]:
    """{run_id: RunCurves} для перечисленных рейсов — одним запросом.

    Нужна там, где скважины уже отобраны и проект не при чём (например
    сравнение двух версий одного рейса).
    """
    ids = [int(r) for r in run_ids]
    if not ids:
        return {}
    out: Dict[int, RunCurves] = {}
    # SQLite ограничивает число параметров, поэтому идём порциями
    CHUNK = 400
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        keys = [f"r{j}" for j in range(len(part))]
        sql = text("""
            SELECT lr.well_id, cd.log_run_id, cd.mnemonic, cd.unit,
                   cd.num_points, cd.data_binary
            FROM curve_data cd
            JOIN log_runs lr ON lr.id = cd.log_run_id
            WHERE cd.log_run_id IN (%s)
        """ % ", ".join(f":{k}" for k in keys))
        for well_id, run_id, mnem, unit, npts, blob in db.execute(sql, dict(zip(keys, part))):
            rc = out.get(run_id)
            if rc is None:
                rc = out[run_id] = RunCurves(run_id, well_id)
            arr = np.frombuffer(blob, dtype=np.float64) if blob else np.empty(0)
            rc.curves[(mnem or "").strip().upper()] = (unit or "", int(npts or arr.size), arr)
    return out


def load_project_curve_meta(db, pid: int) -> Dict[int, Dict[int, List[Tuple[str, int]]]]:
    """{well_id: {run_id: [(мнемоника, число точек), …]}} без самих данных.

    Сводкам вроде инвентаризации нужен только состав кривых. Тянуть ради
    этого блобы — значит поднять с диска сотни мегабайт впустую.
    """
    sql = text("""
        SELECT lr.well_id, cd.log_run_id, cd.mnemonic, cd.num_points
        FROM curve_data cd
        JOIN log_runs lr ON lr.id = cd.log_run_id
        JOIN wells w ON w.id = lr.well_id
        WHERE w.project_id = :pid
    """)
    out: Dict[int, Dict[int, List[Tuple[str, int]]]] = {}
    for well_id, run_id, mnem, npts in db.execute(sql, {"pid": pid}):
        out.setdefault(well_id, {}).setdefault(run_id, []).append(
            ((mnem or "").strip().upper(), int(npts or 0)))
    return out


def deviation_counts(db, pid: int) -> Dict[int, int]:
    """{well_id: число замеров инклинометрии} одним запросом.

    Подсчёт на каждую скважину отдельно давал сотни запросов там, где хватает
    одной группировки.
    """
    sql = text("""
        SELECT ds.well_id, COUNT(*)
        FROM deviation_surveys ds
        JOIN wells w ON w.id = ds.well_id
        WHERE w.project_id = :pid
        GROUP BY ds.well_id
    """)
    return {int(wid): int(n) for wid, n in db.execute(sql, {"pid": pid})}


def load_curve_arrays(db, curve_ids: Iterable[int]) -> Dict[int, np.ndarray]:
    """{curve_id: массив} только для перечисленных кривых.

    Порциями, потому что SQLite ограничивает число параметров запроса.
    """
    ids = [int(c) for c in curve_ids]
    out: Dict[int, np.ndarray] = {}
    CHUNK = 400
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        keys = [f"c{j}" for j in range(len(part))]
        sql = text("SELECT id, data_binary FROM curve_data WHERE id IN (%s)"
                   % ", ".join(f":{k}" for k in keys))
        for cid, blob in db.execute(sql, dict(zip(keys, part))):
            out[int(cid)] = np.frombuffer(blob, dtype=np.float64) if blob else np.empty(0)
    return out


def load_project_curves_for(db, pid: int, wanted_methods,
                            method_key) -> Dict[int, Dict[int, RunCurves]]:
    """Кривые проекта ТОЛЬКО нужных методов — плюс индексные.

    Сначала читается состав (без данных, доли секунды), затем поднимаются
    блобы одних лишь подходящих кривых. На проекте в 3000 скважин это разница
    между 1.3 ГБ и парой сотен мегабайт: карте пористости незачем поднимать
    с диска весь ГИС.

    ``method_key`` — функция «мнемоника → ключ метода» из вызывающего модуля,
    чтобы отбор шёл ровно по тем же правилам, что и сам расчёт.
    """
    meta_sql = text("""
        SELECT lr.well_id, cd.log_run_id, cd.id, cd.mnemonic, cd.unit, cd.num_points
        FROM curve_data cd
        JOIN log_runs lr ON lr.id = cd.log_run_id
        JOIN wells w ON w.id = lr.well_id
        WHERE w.project_id = :pid
    """)
    wanted = {(k or "").strip().upper() for k in wanted_methods}
    picked: List[tuple] = []
    for well_id, run_id, cid, mnem, unit, npts in db.execute(meta_sql, {"pid": pid}):
        m = (mnem or "").strip().upper()
        if m in DEPTH_NAMES or (method_key(m) or m) in wanted:
            picked.append((well_id, run_id, int(cid), m, unit or "", int(npts or 0)))

    arrays = load_curve_arrays(db, [p[2] for p in picked])
    out: Dict[int, Dict[int, RunCurves]] = {}
    for well_id, run_id, cid, m, unit, npts in picked:
        by_run = out.setdefault(well_id, {})
        rc = by_run.get(run_id)
        if rc is None:
            rc = by_run[run_id] = RunCurves(run_id, well_id)
        rc.curves[m] = (unit, npts, arrays.get(cid, np.empty(0)))
    return out


def load_wells_curves(db, well_ids: Iterable[int]) -> Dict[int, Dict[int, RunCurves]]:
    """{well_id: {run_id: RunCurves}} для перечисленных скважин.

    Нужна сводкам со страничной выдачей: считать три тысячи скважин ради
    трёхсот показанных — впустую поднимать с диска гигабайт данных.
    """
    ids = [int(w) for w in well_ids]
    if not ids:
        return {}
    out: Dict[int, Dict[int, RunCurves]] = {}
    CHUNK = 400
    for i in range(0, len(ids), CHUNK):
        part = ids[i:i + CHUNK]
        keys = [f"w{j}" for j in range(len(part))]
        sql = text("""
            SELECT lr.well_id, cd.log_run_id, cd.mnemonic, cd.unit,
                   cd.num_points, cd.data_binary
            FROM curve_data cd
            JOIN log_runs lr ON lr.id = cd.log_run_id
            WHERE lr.well_id IN (%s)
        """ % ", ".join(f":{k}" for k in keys))
        for well_id, run_id, mnem, unit, npts, blob in db.execute(sql, dict(zip(keys, part))):
            by_run = out.setdefault(well_id, {})
            rc = by_run.get(run_id)
            if rc is None:
                rc = by_run[run_id] = RunCurves(run_id, well_id)
            arr = np.frombuffer(blob, dtype=np.float64) if blob else np.empty(0)
            rc.curves[(mnem or "").strip().upper()] = (unit or "", int(npts or arr.size), arr)
    return out
