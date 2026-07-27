"""Выгрузка построенной карты: PNG, PDF и GeoTIFF.

Экран годится, чтобы посмотреть, но в отчёт и в стороннюю программу карту
надо отдавать файлом. GeoTIFF пишется с координатной привязкой — такой файл
открывается в Petrel и QGIS поверх остальных слоёв; PDF годится в отчёт.

Растр рисуется здесь же, а не берётся с холста браузера: на выгрузку нужна
полная площадь в исходном разрешении сетки, без зума и без подписей, которые
пользователь мог отключить на экране.
"""
from __future__ import annotations

import io
import math
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

# Палитра как на экране: синий → зелёный → жёлтый → красный.
_RAMP = [(0.0, (13, 60, 130)), (0.25, (18, 130, 160)), (0.5, (40, 170, 90)),
         (0.75, (232, 196, 60)), (1.0, (200, 60, 40))]


def _color(t: float) -> Tuple[int, int, int]:
    t = 0.0 if t < 0 else (1.0 if t > 1 else t)
    for i in range(len(_RAMP) - 1):
        a, ca = _RAMP[i]
        b, cb = _RAMP[i + 1]
        if a <= t <= b:
            k = 0.0 if b == a else (t - a) / (b - a)
            return tuple(int(round(ca[j] + (cb[j] - ca[j]) * k)) for j in range(3))
    return _RAMP[-1][1]


def grid_to_rgb(grid: List[List[Optional[float]]], vmin: float, vmax: float,
                nodata=(13, 17, 23)) -> np.ndarray:
    """Сетка значений → массив RGB. Пустые ячейки — цветом фона."""
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    img = np.zeros((ny, nx, 3), dtype=np.uint8)
    img[:, :] = nodata
    rng = (vmax - vmin) or 1.0
    for j in range(ny):
        row = grid[j]
        for i in range(nx):
            v = row[i]
            if v is None:
                continue
            img[j, i] = _color((v - vmin) / rng)
    return img


def _grid_array(grid: List[List[Optional[float]]]) -> np.ndarray:
    """Сетка в float32 с NaN на месте пустых ячеек — как ждут ГИС-программы."""
    ny = len(grid)
    nx = len(grid[0]) if ny else 0
    out = np.full((ny, nx), np.nan, dtype=np.float32)
    for j in range(ny):
        row = grid[j]
        for i in range(nx):
            if row[i] is not None:
                out[j, i] = float(row[i])
    return out


def to_geotiff(data: Dict[str, Any]) -> bytes:
    """GeoTIFF со значениями карты и координатной привязкой.

    Пишутся сами значения (float32), а не картинка: в Petrel и QGIS с такой
    сеткой можно считать, а не только смотреть. Строки идут с севера на юг —
    как принято в растрах, поэтому сетку переворачиваем.
    """
    from PIL import Image, TiffImagePlugin

    arr = _grid_array(data["grid"])
    ny, nx = arr.shape
    if ny < 2 or nx < 2:
        raise ValueError("сетка слишком мелкая для выгрузки")

    x0, x1 = float(data["x0"]), float(data["x1"])
    y0, y1 = float(data["y0"]), float(data["y1"])
    px = (x1 - x0) / (nx - 1)
    py = (y1 - y0) / (ny - 1)

    # в растре первая строка — САМАЯ СЕВЕРНАЯ
    arr = np.flipud(arr)

    info = TiffImagePlugin.ImageFileDirectory_v2()
    # ModelPixelScale: размер пикселя по X, Y, Z
    info[33550] = (float(px), float(py), 0.0)
    # ModelTiepoint: пиксель (0,0) ↔ левый ВЕРХНИЙ угол в координатах площади
    info[33922] = (0.0, 0.0, 0.0, float(x0), float(y1), 0.0)
    # GeoKeyDirectory: растр привязан к плоским координатам, единицы — метры
    info[34735] = (1, 1, 0, 3,
                   1024, 0, 1, 1,      # GTModelType = projected
                   1025, 0, 1, 1,      # GTRasterType = PixelIsArea
                   3076, 0, 1, 9001)   # ProjLinearUnits = metre
    info[42112] = (
        '<GDALMetadata>'
        f'<Item name="DESCRIPTION" sample="0">{data.get("title", "")}</Item>'
        f'<Item name="HORIZON">{data.get("horizon", "")}</Item>'
        '</GDALMetadata>'
    )
    info[42113] = "nan"      # GDAL_NODATA

    buf = io.BytesIO()
    Image.fromarray(arr, mode="F").save(buf, format="TIFF", tiffinfo=info)
    return buf.getvalue()


def to_png(data: Dict[str, Any], wells: Optional[List[dict]] = None,
           scale: int = 6) -> bytes:
    """Растровая картинка карты с подписью, шкалой и точками скважин."""
    from PIL import Image, ImageDraw

    img = grid_to_rgb(data["grid"], data["vmin"], data["vmax"])
    ny, nx = img.shape[:2]
    pic = Image.fromarray(np.flipud(img), mode="RGB")     # север вверх
    pic = pic.resize((nx * scale, ny * scale), Image.NEAREST)

    W, H = pic.size
    pad_t, pad_b = 46, 54
    canvas = Image.new("RGB", (W, H + pad_t + pad_b), (13, 17, 23))
    canvas.paste(pic, (0, pad_t))
    d = ImageDraw.Draw(canvas)

    x0, x1 = float(data["x0"]), float(data["x1"])
    y0, y1 = float(data["y0"]), float(data["y1"])

    def PX(v):
        return (v - x0) / (x1 - x0) * (W - 1)

    def PY(v):
        return pad_t + (y1 - v) / (y1 - y0) * (H - 1)

    for p in (wells or []):
        if p.get("x") is None or p.get("y") is None:
            continue
        cx, cy = PX(p["x"]), PY(p["y"])
        r = 2 if len(wells) > 500 else 3
        d.ellipse([cx - r, cy - r, cx + r, cy + r],
                  fill=(255, 255, 255), outline=(13, 17, 23))

    title = f'{data.get("title", "Карта")}'
    if data.get("horizon"):
        title += f' · горизонт {data["horizon"]}'
    d.text((10, 14), title, fill=(220, 226, 232))

    # шкала значений
    bar_w, bar_h, bx, by = 240, 12, 10, H + pad_t + 16
    for i in range(bar_w):
        d.line([(bx + i, by), (bx + i, by + bar_h)], fill=_color(i / (bar_w - 1)))
    d.rectangle([bx, by, bx + bar_w, by + bar_h], outline=(110, 118, 129))
    d.text((bx, by + bar_h + 4), f'{data["vmin"]:.3g}', fill=(180, 188, 196))
    d.text((bx + bar_w - 40, by + bar_h + 4), f'{data["vmax"]:.3g}', fill=(180, 188, 196))
    d.text((bx + bar_w + 20, by), f'скважин: {data.get("used", 0)}', fill=(180, 188, 196))

    buf = io.BytesIO()
    canvas.save(buf, format="PNG")
    return buf.getvalue()


def to_pdf(data: Dict[str, Any], wells: Optional[List[dict]] = None) -> bytes:
    """Карта в PDF: картинка на лист A4 с заголовком и подписью площади."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas as pdfcanvas

    png = to_png(data, wells, scale=6)
    buf = io.BytesIO()
    W, H = landscape(A4)
    c = pdfcanvas.Canvas(buf, pagesize=landscape(A4))

    title = data.get("title", "Карта")
    horizon = data.get("horizon") or ""
    c.setFillColorRGB(0.08, 0.09, 0.11)
    c.rect(0, 0, W, H, stroke=0, fill=1)
    c.setFillColorRGB(0.86, 0.89, 0.92)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(18 * mm, H - 16 * mm, title)
    if horizon:
        c.setFont("Helvetica", 10)
        c.drawString(18 * mm, H - 22 * mm, f"horizon: {horizon}")

    img = ImageReader(io.BytesIO(png))
    iw, ih = img.getSize()
    avail_w, avail_h = W - 36 * mm, H - 46 * mm
    k = min(avail_w / iw, avail_h / ih)
    c.drawImage(img, 18 * mm, 16 * mm, width=iw * k, height=ih * k,
                preserveAspectRatio=True, mask=None)

    c.setFont("Helvetica", 8)
    c.setFillColorRGB(0.55, 0.6, 0.65)
    c.drawString(18 * mm, 9 * mm,
                 f'X {data.get("x0", 0):.0f}–{data.get("x1", 0):.0f} м, '
                 f'Y {data.get("y0", 0):.0f}–{data.get("y1", 0):.0f} м, '
                 f'скважин {data.get("used", 0)}, R={data.get("radius", 0)} м')
    c.showPage()
    c.save()
    return buf.getvalue()
