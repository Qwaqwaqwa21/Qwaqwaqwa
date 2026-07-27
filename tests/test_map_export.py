"""Выгрузка карты файлом и читаемость карты на большом проекте.

На трёх тысячах скважин кружки с подписями закрывали построенную поверхность
целиком — пользователь видел «чёрный экран и точки». Плюс карту нельзя было
ни приблизить, ни выгрузить в отчёт.
"""
import inspect

import numpy as np
import pytest


def _sample_grid():
    return {
        "title": "Толщина коллектора, м", "horizon": "Бобриковский",
        "x0": 400000.0, "x1": 410000.0, "y0": 6200000.0, "y1": 6210000.0,
        "nx": 5, "ny": 5, "vmin": 1.0, "vmax": 5.0, "used": 3, "radius": 900.0,
        "grid": [[1.0, 2.0, None, 4.0, 5.0]] * 5,
        "wells": [{"x": 401000.0, "y": 6201000.0, "name": "1", "value": 2.0}],
    }


def test_geotiff_carries_values_and_georeference():
    """В GeoTIFF идут ЗНАЧЕНИЯ, а не картинка: по ним можно считать в Petrel."""
    from PIL import Image
    import io
    from backend.map_export import to_geotiff

    d = _sample_grid()
    im = Image.open(io.BytesIO(to_geotiff(d)))
    assert im.mode == "F", "значения должны быть вещественными, а не цветом"
    assert im.size == (5, 5)

    t = im.tag_v2
    sx, sy, _ = t[33550]
    assert sx == pytest.approx((d["x1"] - d["x0"]) / (d["nx"] - 1))
    assert sy == pytest.approx((d["y1"] - d["y0"]) / (d["ny"] - 1))
    # привязка идёт к СЕВЕРО-западному углу: строки растра идут сверху вниз
    tie = t[33922]
    assert tie[3] == pytest.approx(d["x0"])
    assert tie[4] == pytest.approx(d["y1"])
    assert t[42113] == "nan"

    a = np.array(im)
    assert np.isnan(a).any(), "пустые ячейки должны остаться пустыми"
    assert np.nanmin(a) == pytest.approx(1.0)


def test_pdf_and_png_render():
    from backend.map_export import to_pdf, to_png

    d = _sample_grid()
    pdf = to_pdf(d, d["wells"])
    assert pdf.startswith(b"%PDF"), "должен получиться настоящий PDF"
    png = to_png(d, d["wells"])
    assert png.startswith(b"\x89PNG")


def test_export_endpoint_offers_three_formats():
    from backend.routers import maps

    src = inspect.getsource(maps.map_export)
    for f in ("pdf", "tiff", "png"):
        assert f in src, f
    # считается ТА ЖЕ сетка, что на экране, иначе файл разойдётся с картинкой
    assert "map_grid(" in src


def test_markers_shrink_and_labels_hide_on_crowded_maps():
    """Иначе поверхность не видна — ровно то, на что жаловался пользователь."""
    js = open("frontend/js/maps.js", encoding="utf-8").read()
    assert "visible.length > 1200" in js, "размер значка не зависит от числа скважин"
    assert "showLabels" in js
    assert "mapLabels" in js


def test_map_has_zoom_and_pan():
    js = open("frontend/js/maps.js", encoding="utf-8").read()
    for name in ("zoomBy", "resetView", "_bindViewControls", "onwheel"):
        assert name in js, name
    # зум относительно курсора, иначе карта уползает из-под мыши
    assert "cx - r * (cx - v.dx)" in js.replace("  ", " ") or "cx - r * (cx - v.dx)" in js


def test_planshet_pages_by_hundred():
    from backend.routers import research

    src = inspect.getsource(research.coverage_log)
    assert 'limit: int = Query(100' in src, "планшет должен идти сотнями"
