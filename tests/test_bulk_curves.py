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
        assert "_bulk_curves(db, pid)" in src, fn.__name__
        assert "run.curve_data" not in src, f"{fn.__name__} всё ещё ходит по связям ORM"

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
