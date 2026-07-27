"""Общая подготовка данных для тестов.

Часть проверок (RBAC, зонация, отчёты) работает не с моками, а с реальными
таблицами и молча полагалась на то, что в `backend/geolog.db` уже кто-то
загрузил скважину. На чистой машине они падали с «len(data) > 0». Здесь
создаётся минимальный, но полноценный набор: скважина с рейсом ГИС, кривыми
и отбивками — если в базе действительно ничего нет.
"""
from pathlib import Path
import os
import sys

# Тесты не должны трогать боевую базу: до импорта backend.database уводим
# подключение в отдельный файл, иначе засеянные фикстурой строки осядут
# в данных заказчика.
os.environ.setdefault(
    "GEOLOG_DB_PATH",
    str(Path(__file__).resolve().parent / "_test_geolog.db"),
)

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="session", autouse=True)
def seed_minimal_project():
    # Часть тестов кладёт в sys.path саму папку backend/, из-за чего модели
    # доступны и как `models`, и как `backend.models`. Импортировать второй
    # вариант поверх первого нельзя: таблицы регистрируются в одной и той же
    # metadata и SQLAlchemy падает на «Table 'projects' is already defined».
    # Поэтому берём тот модуль, который уже загружен.
    import importlib

    def _mod(short, full):
        return (sys.modules.get(short) or sys.modules.get(full)
                or importlib.import_module(full))

    models = _mod("models", "backend.models")
    database = _mod("database", "backend.database")
    Project, Well, LogRun, CurveData, FormationTop = (
        models.Project, models.Well, models.LogRun, models.CurveData,
        models.FormationTop)
    engine, SessionLocal = database.engine, database.SessionLocal

    Well.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Well).count() > 0:
            yield
            return

        proj = Project(name="Тестовый проект", field_name="Тестовое",
                       operator="GeoLog", country="Россия")
        db.add(proj)
        db.flush()

        depth = np.arange(1000.0, 1200.0, 0.1)
        n = len(depth)
        rng = np.random.default_rng(42)
        # Пласт-коллектор в середине интервала: низкий ГК, высокое сопротивление
        pay = (depth > 1080) & (depth < 1120)
        gr = np.where(pay, 25.0, 95.0) + rng.normal(0, 4, n)
        rt = np.where(pay, 40.0, 3.0) * np.exp(rng.normal(0, 0.1, n))
        nphi = np.where(pay, 0.22, 0.32) + rng.normal(0, 0.01, n)
        rhob = np.where(pay, 2.28, 2.55) + rng.normal(0, 0.02, n)

        # Две скважины: часть проверок (корреляция, аудит записей) требует пары
        for idx, (wname, shift) in enumerate((("TEST-01", 0.0), ("TEST-02", 8.0))):
            d = depth + shift
            well = Well(project_id=proj.id, name=wname,
                        uwi=f"00-000-0000{idx + 1}", operator="GeoLog",
                        total_depth=float(d[-1]), depth_unit="M")
            db.add(well)
            db.flush()

            lr = LogRun(well_id=well.id, run_number=1,
                        filename=f"{wname.lower()}.las", name="ГИС", kind="gis",
                        depth_unit="M", las_version="2.0",
                        start_depth=float(d[0]), stop_depth=float(d[-1]),
                        step=0.1, num_points=n)
            db.add(lr)
            db.flush()

            for mnem, unit, arr in (("DEPT", "M", d), ("GR", "API", gr),
                                    ("RT", "OHMM", rt), ("NPHI", "V/V", nphi),
                                    ("RHOB", "G/C3", rhob)):
                db.add(CurveData(log_run_id=lr.id, mnemonic=mnem, unit=unit,
                                 description=mnem, num_points=n,
                                 min_value=float(np.min(arr)),
                                 max_value=float(np.max(arr)),
                                 data_binary=arr.astype(np.float64).tobytes()))

            for name, top, base, color in (("Пласт А", 1020.0, 1080.0, "#e74c3c"),
                                           ("Пласт Б", 1080.0, 1120.0, "#3498db"),
                                           ("Пласт В", 1120.0, 1190.0, "#2ecc71")):
                db.add(FormationTop(well_id=well.id, formation_name=name,
                                    depth=top + shift, top_depth=top + shift,
                                    base_depth=base + shift, depth_unit="M",
                                    color=color))

        db.commit()
    finally:
        db.close()
    yield
