"""Пакетное чтение кривых: скорость сводных экранов держится на нём.

Обход связями ORM давал запрос на каждый рейс — на 1500 рейсах это
21 секунда против 0.5 с одним запросом, причём время уходило не на данные,
а на создание объектов SQLAlchemy. Тесты закрепляют, что сводки читают
данные пакетно и что метаданные берутся без блобов.
"""
import inspect


def test_summaries_do_not_walk_orm_relations():
    from backend.routers import research, maps

    for fn in (research.coverage_log, research._coverage_by_horizon,
               research.research_coverage):
        src = inspect.getsource(fn)
        assert "_bulk_curves_for_wells(db," in src, fn.__name__
        assert "run.curve_data" not in src, f"{fn.__name__} всё ещё ходит по связям ORM"
        # связи тоже пакетно, иначе запрос на каждую скважину
        assert "selectinload" in src, fn.__name__

    src = inspect.getsource(maps.project_inventory)
    assert "load_project_curve_meta" in src
    assert "deviation_counts" in src
    assert "run.curve_data" not in src


def test_inventory_reads_metadata_without_blobs():
    """Инвентаризации нужен состав кривых, а не их значения."""
    from backend import bulk_curves

    src = inspect.getsource(bulk_curves.load_project_curve_meta)
    assert "data_binary" not in src


def test_project_summary_counts_with_group_by():
    """Сводка считает группировкой, а не запросом на скважину."""
    from backend import main

    src = inspect.getsource(main.project_summary)
    assert "group_by" in src
    assert "for lr in log_runs" not in src


def test_bulk_loader_returns_arrays_by_run():
    from backend import bulk_curves

    rc = bulk_curves.RunCurves(7, 1)
    rc.curves["КП_W"] = ("д.ед.", 3, None)
    assert rc.get("кп_w") is not None      # регистр не важен
    assert rc.get(" КП_W ") is not None    # пробелы тоже
    assert rc.get("НЕТУ") is None


def test_summaries_are_paged():
    """Сводки отдают страницу: 3000 скважин разом нечитаемы и считаются долго."""
    from backend.routers import research

    for fn in (research.coverage_log, research.coverage_by_horizon,
               research.research_coverage):
        src = inspect.getsource(fn)
        assert "limit" in src and "offset" in src, fn.__name__
    assert "has_more" in inspect.getsource(research._page_wells)


def test_full_output_still_available_for_export():
    """limit=0 возвращает всё — выгрузка не должна обрезаться страницей."""
    from backend.routers import research

    src = inspect.getsource(research._page_wells)
    assert "if limit and limit > 0" in src
    # экспорт зовёт расчёт без ограничения
    assert "_coverage_by_horizon(pid, db)" in inspect.getsource(
        research.coverage_by_horizon_export)


def test_foreign_keys_are_indexed():
    """Без индексов на внешних ключах каждый запрос сканирует таблицу целиком.

    На 48 000 кривых и 6 млн замеров инклинометрии это секунды на ровном
    месте, причём в базах, созданных до появления индексов, — тоже.
    """
    import sys

    # Часть тестов кладёт в sys.path саму папку backend/, из-за чего модели
    # доступны и как `models`, и как `backend.models`. Импортировать второй
    # вариант поверх первого нельзя: таблицы регистрируются в одной metadata
    # и SQLAlchemy падает на «Table 'projects' is already defined».
    main = sys.modules.get("main") or sys.modules.get("backend.main")
    models = sys.modules.get("models") or sys.modules.get("backend.models")
    if main is None or models is None:  # pragma: no cover — запуск в одиночку
        from backend import main, models  # noqa: F811

    src = inspect.getsource(main._ensure_foreign_key_indexes)
    for table, col in (("curve_data", "log_run_id"), ("log_runs", "well_id"),
                       ("deviation_surveys", "well_id"), ("wells", "project_id")):
        assert table in src and col in src, (table, col)
    assert "CREATE INDEX IF NOT EXISTS" in src

    assert models.CurveData.__table__.c.log_run_id.index
    assert models.LogRun.__table__.c.well_id.index
    assert models.Well.__table__.c.project_id.index
