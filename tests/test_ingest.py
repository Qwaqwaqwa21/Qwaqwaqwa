"""Пакетный импорт: скважина из шапки, рейс из папки, инклинометрия отдельно."""
import io
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.las_parser import LASParser
from backend.routers.ingest import _classify, _run_name_from_path, _minimum_curvature


GIS_LAS = (
    "~VERSION\nVERS. 2 :\nWRAP. NO :\n"
    "~WELL\n"
    "WELL        .          444                     :WELL\n"
    "STRT        .m         20.0000                 :First index value\n"
    "STOP        .m         1200.0000               :Last index value\n"
    "X           .m         -17302.000              :X-coordinate of Well Head\n"
    "Y           .m         71819.000               :Y-coordinate of Well Head\n"
    "RKB         .m         194.8000                :RKB\n"
    "~CURVE\nMD .m :\nGK . :\nGZ1 . :\nKS_500 . :\n"
    "~ASCII\n20.0 5.1 12.0 3.0\n20.1 5.4 12.5 3.2\n20.2 5.9 13.0 3.4\n"
)

INKL_LAS = (
    "~Version\nVERS. 2.0 :\nWRAP. NO :\n"
    "~Well\nSTRT .m 0.0 :\nSTOP .m 100.0 :\nWELL . 444 : Well\n"
    "~Curve\nMD .m :\nINCL .deg :\nAZ .deg :\n"
    "~ASCII\n0 0 0\n50 0 0\n100 0 0\n"
)


def test_well_name_comes_from_header_not_description():
    """`WELL . 444 :WELL` — номер стоит ДО двоеточия, после него описание."""
    las = LASParser.parse_bytes(GIS_LAS.encode())
    assert las.well.well_name == "444"


def test_header_gives_units_coordinates_and_altitude():
    las = LASParser.parse_bytes(GIS_LAS.encode())
    assert las.well.depth_unit == "M"
    assert las.well.x == -17302.0
    assert las.well.y == 71819.0
    assert las.well.rkb == 194.8


def test_field_mnemonics_are_kept_as_written():
    """GZ1 и KS_500 не переписываются, но опознаются как БКЗ и КС."""
    las = LASParser.parse_bytes(GIS_LAS.encode())
    names = [c.mnemonic for c in las.curves]
    canon = {c.mnemonic: c.canonical for c in las.curves}
    assert "GZ1" in names and "KS_500" in names
    assert canon["GZ1"] == "BKZ"


def test_run_name_taken_from_folder():
    assert _run_name_from_path("rd/2/C1/444.las", "444.las") == "C1"
    assert _run_name_from_path("rd/2/ГИС_С1/444.las", "444.las") == "ГИС_С1"
    # файл без папки — имя рейса из имени файла
    assert _run_name_from_path("444.las", "444.las") == "444"


def test_inclinometry_detected_by_curves_and_by_folder():
    assert _classify("C1", ["MD", "INCL", "AZ"]) == "inkl"
    assert _classify("INKL", ["MD", "GK"]) == "inkl"
    assert _classify("ИНКЛ", ["MD", "GK"]) == "inkl"
    assert _classify("C1", ["GK", "NGK"]) == "gis"


def test_rigis_detected_by_interpreted_curves():
    assert _classify("C1", ["LITH", "COLL", "SAT"]) == "rigis"
    assert _classify("РИГИС", ["GK"]) == "rigis"


def test_inkl_las_parses_into_md_incl_az():
    las = LASParser.parse_bytes(INKL_LAS.encode())
    names = [c.mnemonic for c in las.curves]
    assert names == ["MD", "INCL", "AZ"]
    assert _classify("INKL", names[1:]) == "inkl"


def test_minimum_curvature_vertical_well_gives_tvd_equal_md():
    md = [0.0, 100.0, 200.0]
    tvd, north, east = _minimum_curvature(md, [0.0, 0.0, 0.0], [0.0, 0.0, 0.0])
    assert abs(tvd[-1] - 200.0) < 1e-6
    assert abs(north[-1]) < 1e-9 and abs(east[-1]) < 1e-9


def test_minimum_curvature_deviated_well_shortens_tvd():
    md = [0.0, 100.0, 200.0]
    tvd, _, east = _minimum_curvature(md, [0.0, 30.0, 30.0], [90.0, 90.0, 90.0])
    assert tvd[-1] < 200.0            # наклон укорачивает вертикаль
    assert east[-1] > 0.0             # смещение на восток при азимуте 90°


def test_curve_config_resolves_field_mnemonics():
    """Настройки трека выводятся для имён вне встроенной таблицы."""
    from backend.main import get_curve_config

    cfg = get_curve_config(mnemonics="GK_500,GZ1,ЛИТОЛОГИЯ,НАСЫЩЕНИЕ,КОЛЛЕКТОР,ЧУШЬ")
    assert "GK_500" in cfg and cfg["GK_500"]["track"] == cfg["GK"]["track"]
    assert "GZ1" in cfg                       # градиент-зонд → трек БКЗ
    # интерпретационные колонки помечаются справочником кодов
    assert cfg["ЛИТОЛОГИЯ"]["categorical"] == "lithology"
    assert cfg["КОЛЛЕКТОР"]["categorical"] == "collector"
    assert cfg["НАСЫЩЕНИЕ"]["categorical"] == "saturation"
    # неизвестная мнемоника не выдумывается
    assert "ЧУШЬ" not in cfg


def test_curve_config_without_query_is_builtin_table():
    from backend.main import get_curve_config

    cfg = get_curve_config()
    assert "GK" in cfg and "LITH" in cfg


def test_track_layout_matches_requested_scheme():
    """Раскладка треков: стандартный / радиоактивный / сопротивление / …"""
    from backend.las_parser import CURVE_TRACKS as C

    assert C["DS"]["track"] == C["KS"]["track"] == C["PS"]["track"] == 1
    assert C["GK"]["track"] == C["NGK"]["track"] == 2
    assert C["IK"]["track"] == C["BK"]["track"] == C["BKZ"]["track"] == 3
    assert C["MKZ"]["track"] == 4
    assert C["YMK"]["track"] == 5
    assert C["AK"]["track"] == C["GGKP"]["track"] == 6
    assert C["GAZ"]["track"] == 7
    assert C["LITH"]["track"] == C["COLL"]["track"] == C["SAT"]["track"] == 11


def test_interpretation_scales_are_fixed():
    """Кп и Кгл 0–0.4, Кнг 0–1; автоподбор их не трогает."""
    from backend.las_parser import CURVE_TRACKS as C

    assert tuple(C["KP"]["scale"]) == (0, 0.4) and C["KP"]["fixed"]
    assert tuple(C["KGL"]["scale"]) == (0, 0.4) and C["KGL"]["fixed"]
    assert tuple(C["KNG"]["scale"]) == (0, 1) and C["KNG"]["fixed"]
    assert C["KP"]["track"] != C["KGL"]["track"] != C["KNG"]["track"]


def test_curve_lookup_finds_russian_and_suffixed_names():
    """Поиск по методу работает для ГК, GK_500 и западного GR одинаково."""
    from backend.curve_lookup import method_key

    assert method_key("GK_500") == "GK"
    assert method_key("ГК") == "GK"
    # западное имя приводится к российскому методу — это одно исследование
    assert method_key("GR") == "GK"
    assert method_key("ЛИТОЛОГИЯ") == "LITH"
    assert method_key("GZ3") == "BKZ"
    assert method_key("НЕТ_ТАКОГО") is None


def test_curve_lookup_treats_russian_and_western_methods_as_equivalent():
    """ГК ищется по запросу GR — расчётные модули писались под западные имена."""
    from backend.curve_lookup import EQUIVALENT

    assert "GK" in EQUIVALENT["GR"]
    assert "NGK" in EQUIVALENT["NPHI"]
    assert "DS" in EQUIVALENT["CAL"]
    assert "PS" in EQUIVALENT["SP"]


def test_curve_colors_follow_customer_scheme():
    """ДС зелёная, КС чёрная, ПС красная, ГК красная, НГК чёрная, ИК зелёная, БК синяя."""
    from backend.las_parser import CURVE_TRACKS as C

    assert C["DS"]["color"] == "#2ecc71"
    assert C["KS"]["color"] == "#000000"
    assert C["PS"]["color"] == "#e74c3c"
    assert C["GK"]["color"] == "#e74c3c"
    assert C["NGK"]["color"] == "#000000"
    assert C["IK"]["color"] == "#2ecc71"
    assert C["BK"]["color"] == "#2980b9"


def test_lithology_falls_back_to_other_runs_for_gamma():
    """ГК ищется по всей скважине: выбранным может быть рейс РИГИС без ГК."""
    import inspect
    from backend import main

    src = inspect.getsource(main.classify_lithology)
    assert "_find_curve_in_well" in src
    assert "ни в одном рейсе" in src


def test_data_table_defaults_to_all_curves():
    """Без явного списка таблица данных показывает все кривые рейса."""
    import inspect
    from backend import main

    src = inspect.getsource(main.get_data_table)
    assert "selected = [n for n in by_name if n.upper() not in depth_names]" in src


def test_well_locations_include_rectangular_coordinates():
    """Промысловые X/Y отдаются вместе с широтой/долготой."""
    import inspect
    from backend import main

    src = inspect.getsource(main.project_well_locations)
    assert "x_coord" in src and "y_coord" in src


def test_standard_track_is_linear():
    """КС стоит в стандартном треке — там линейная шкала."""
    from backend.las_parser import CURVE_TRACKS as C

    assert C["KS"]["track"] == 1
    assert not C["KS"].get("log")
    # логарифм остаётся у бокового и индукционного
    assert C["BK"].get("log") and C["IK"].get("log") and C["BKZ"].get("log")


def test_plot_scale_options_are_geological():
    """Масштабы планшета 1:100…1:1000, по умолчанию 1:250."""
    import re

    html = open("frontend/index.html", encoding="utf-8").read()
    block = re.search(r'<select id="scaleSelect".*?</select>', html, re.S).group(0)
    values = re.findall(r'value="(\d+)"', block)
    assert values == ["100", "200", "250", "500", "1000"]
    assert re.search(r'value="250" selected', block)
    # футо-дюймовых подписей остаться не должно
    assert "ft/in" not in html


def test_duplicate_run_needs_same_interval_and_point_count():
    """Разные проходы одного метода (С1/С2) повтором не считаются."""
    import inspect
    from backend.routers import ingest

    src = inspect.getsource(ingest._find_duplicate_run)
    assert "share >= 0.99 and same_points" in src
    # доля считается по ШИРОКОМУ интервалу — иначе короткий рейс внутри
    # длинного всегда выглядел бы полным повтором
    assert "max(n_hi - n_lo, o_hi - o_lo)" in src


def test_bulk_import_asks_before_touching_existing_data():
    """По умолчанию повтор НЕ грузится: решение за пользователем.

    Те же методы на тот же интервал — это либо повторная загрузка, либо новая
    версия РИГИС. Разница между «заменить», «дополнить» и «копией» меняет и
    карты, и расчёты, поэтому выбирать за пользователя нельзя.
    """
    import inspect
    from backend.routers import ingest

    mod = inspect.getsource(ingest)
    src = inspect.getsource(ingest.bulk_import)
    assert 'on_duplicate: str = Form("ask")' in mod
    for act in ('"replace"', '"merge"', '"copy"'):
        assert act in src, act
    assert 'on_duplicate in ("ask", "skip")' in src


def test_conflict_offers_all_four_choices():
    """Сервер сам перечисляет варианты — интерфейс не хранит их отдельно."""
    from backend.routers import ingest

    vals = [c["value"] for c in ingest._CONFLICT_CHOICES]
    assert vals == ["replace", "merge", "copy", "skip"], vals
    assert all(c.get("title") and c.get("hint") for c in ingest._CONFLICT_CHOICES)


def test_replace_keeps_run_id_for_depth_shift():
    """Замена сохраняет id рейса: к нему привязана поправка глубины."""
    import inspect
    from backend.routers import ingest

    src = inspect.getsource(ingest._replace_run)
    assert "run.id" in src
    assert "delete" in src          # старые кривые убираются
    assert "LogRun(" not in src     # рейс не пересоздаётся


def test_duplicate_finder_endpoint_exists():
    from backend.routers import ingest

    assert hasattr(ingest, "find_duplicates")
    import inspect
    src = inspect.getsource(ingest.find_duplicates)
    for key in ("identical_curves", "duplicate_depths", "duplicate_runs"):
        assert key in src


def test_planshet_uses_union_depth_axis():
    """Кривые всех показываемых рейсов сводятся на объединённую ось глубин.

    Без этого активный короткий рейс (РИГИС по одному пласту) задавал ось, и
    рейсы за его пределами не попадали на планшет вовсе.
    """
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "_collectShownRuns" in js
    assert "_buildUnionAxis" in js
    # окно и границы прокрутки тоже считаются по объединению
    assert "const ext = this._shownRunsExtent();" in js
    renderer = open("frontend/js/log-renderer.js", encoding="utf-8").read()
    assert "window.app?._shownRunsExtent?.()" in renderer


def test_categorical_curves_resampled_by_nearest_value():
    """Коды РИГИС переносятся ближайшим значением, а не интерполяцией."""
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "_resampleOnto(srcDepth, src, dstDepth, nearest = false)" in js
    assert "RigisTracks.isCategorical(mn)" in js


def test_build_info_endpoint_reports_version():
    """Строка состояния показывает версию сборки — так видно старую копию."""
    from backend.main import build_info

    info = build_info()
    assert "commit" in info and "built" in info
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "_showBuildInfo" in js
    html = open("frontend/index.html", encoding="utf-8").read()
    assert 'id="statusBuild"' in html


def test_index_html_busts_static_cache():
    """index.html отдаётся с ?v=… у скриптов — иначе браузер крутит старый app.js."""
    from fastapi.testclient import TestClient
    from backend.main import app, _asset_version

    ver = _asset_version()
    assert ver
    with TestClient(app) as client:
        resp = client.get("/")
        assert resp.status_code == 200
        assert "no-store" in resp.headers.get("cache-control", "")
        assert f'/static/js/app.js?v={ver}' in resp.text
        assert '/static/js/app.js"' not in resp.text  # без версии не осталось
    # фронтенд сравнивает свою версию с серверной и предупреждает о кэше
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "b.assets" in js and "Ctrl+F5" in js


def test_asset_version_changes_with_frontend(tmp_path, monkeypatch):
    """Отпечаток меняется при правке JS — иначе версия не обновится у клиента."""
    import backend.main as m

    before = m._asset_version()
    target = os.path.join(m.frontend_dir, "js", "app.js")
    stat = os.stat(target)
    try:
        os.utime(target, (stat.st_atime, stat.st_mtime + 60))
        assert m._asset_version() != before
    finally:
        os.utime(target, (stat.st_atime, stat.st_mtime))
    assert m._asset_version() == before


def test_no_hardcoded_feet_labels_left():
    """Подписи глубин берут единицу у скважины, а не «ft» намертво."""
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert " ft`" not in js
    assert "_depthUnitLabel" in js


def test_non_overlapping_runs_merge_into_one_curve():
    """Метод из рейсов с непересекающимися интервалами склеивается в одну кривую.

    Три РИГИС по разным пластам — это один разрез, и держать три колонки
    литологии незачем. Там, где интервалы перекрываются, кривые остаются
    раздельными: их нужно сравнивать.
    """
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "const mergeable = overlapping && method && !overlapping.has(method);" in js
    assert "mergedBy[key]" in js
    # переключатель склейки
    tree = open("frontend/js/curve-tree.js", encoding="utf-8").read()
    assert "geolog_merge_runs" in tree
    assert "склеивать рейсы в одну колонку" in tree


def test_merged_curve_label_is_not_duplicated():
    """Пометка о склейке берётся от нетронутого имени, а не дописывается к себе."""
    js = open("frontend/js/app.js", encoding="utf-8").read()
    assert "const pristine = (this._defaultCurveConfig || {})[d.base]" in js
