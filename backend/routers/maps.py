"""
Картопостроение: карта устьев и карты параметров по горизонтам.

  * GET  /api/crs/presets                     — системы координат (СК-63, Татарстан)
  * POST /api/projects/{pid}/wells/coordinates — импорт координат (Excel/CSV/JSON)
  * POST /api/projects/{pid}/wells/coordinates/import — импорт координат из Excel/CSV
  * GET  /api/projects/{pid}/map/wellheads    — карта устьев
  * GET  /api/projects/{pid}/map/grid         — сеточная карта параметра по горизонту
  * POST /api/projects/{pid}/shapes           — импорт контуров из SHP
  * GET  /api/projects/{pid}/shapes           — контуры лицензий/месторождений

Карты параметров считаются по РИГИС-кривым в интервале горизонта:
  thickness  — суммарная мощность коллектора (КОЛЛЕКТОР = 1)
  porosity   — средневзвешенно-ГАРМОНИЧЕСКАЯ пористость коллектора
               Кп_ср = Σh / Σ(h / Кп)
  oil_thick  — нефтенасыщенная толщина (коллектор + нефтегазовое насыщение)
"""
from __future__ import annotations

import csv
import datetime
import io
import json
import math
import struct
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

try:
    from database import get_db
    from models import Well, LogRun, CurveData, FormationTop, Project
    from curve_lookup import method_key as _method_key
except ImportError:  # pragma: no cover
    from backend.database import get_db
    from backend.models import Well, LogRun, CurveData, FormationTop, Project
    from backend.curve_lookup import method_key as _method_key

router = APIRouter(tags=["maps"])

_DEPTH = {"DEPT", "DEPTH", "MD", "TVD"}
# Коды насыщения, считающиеся нефте/газонасыщенными (справочник заказчика)
OIL_SAT_CODES = {26, 88, 96, 97, 98, 510, 27, 89, 99, 508}
COLLECTOR_CODE = 1

# ── Системы координат ────────────────────────────────────────────────────────
# СК-63 — проекция Гаусса-Крюгера на эллипсоиде Красовского 1940.
# Для Татарстана используются 3-градусные зоны; осевой меридиан уточняется
# по .prj из SHP заказчика (см. параметр cm).
KRASSOVSKY = {"a": 6378245.0, "f": 1 / 298.3}

CRS_PRESETS = {
    "sk63_tatarstan_z1": {
        "name": "СК-63, Татарстан (зона 1, ОМ 49°)",
        "ellipsoid": "Krassovsky 1940", "cm": 49.0,
        "false_easting": 1300000.0, "false_northing": 0.0, "k0": 1.0,
    },
    "sk63_tatarstan_z2": {
        "name": "СК-63, Татарстан (зона 2, ОМ 52°)",
        "ellipsoid": "Krassovsky 1940", "cm": 52.0,
        "false_easting": 2300000.0, "false_northing": 0.0, "k0": 1.0,
    },
    "local": {
        "name": "Условные (местные) координаты, м",
        "ellipsoid": "—", "cm": None,
        "false_easting": 0.0, "false_northing": 0.0, "k0": 1.0,
    },
}


@router.get("/api/crs/presets")
def crs_presets() -> Dict[str, Any]:
    return {"presets": CRS_PRESETS, "default": "sk63_tatarstan_z2"}


def gk_to_latlon(x: float, y: float, cm: float, fe: float, fn: float) -> Tuple[float, float]:
    """Гаусс-Крюгер (Красовский) → широта/долгота, для подложек и экспорта."""
    a, f = KRASSOVSKY["a"], KRASSOVSKY["f"]
    e2 = 2 * f - f * f
    n = (x - fn)  # northing
    e = (y - fe)  # easting
    m = n
    mu = m / (a * (1 - e2 / 4 - 3 * e2 ** 2 / 64))
    e1 = (1 - math.sqrt(1 - e2)) / (1 + math.sqrt(1 - e2))
    phi = (mu + (3 * e1 / 2 - 27 * e1 ** 3 / 32) * math.sin(2 * mu)
           + (21 * e1 ** 2 / 16) * math.sin(4 * mu))
    sp, cp = math.sin(phi), math.cos(phi)
    n1 = a / math.sqrt(1 - e2 * sp * sp)
    t1 = (sp / cp) ** 2
    c1 = e2 / (1 - e2) * cp * cp
    r1 = a * (1 - e2) / (1 - e2 * sp * sp) ** 1.5
    d = e / n1
    lat = phi - (n1 * (sp / cp) / r1) * (d * d / 2 - (5 + 3 * t1) * d ** 4 / 24)
    lon = math.radians(cm) + (d - (1 + 2 * t1 + c1) * d ** 3 / 6) / cp
    return math.degrees(lat), math.degrees(lon)


# ── Импорт координат ─────────────────────────────────────────────────────────
class CoordRow(BaseModel):
    well: str
    x: float
    y: float
    altitude: Optional[float] = None


@router.post("/api/projects/{pid}/wells/coordinates")
def import_coordinates(pid: int, rows: List[CoordRow], db: Session = Depends(get_db)) -> Dict[str, Any]:
    wells = {w.name.strip().lower(): w for w in db.query(Well).filter(Well.project_id == pid).all()}
    updated, missing = 0, []
    for r in rows:
        w = wells.get(r.well.strip().lower())
        if not w:
            missing.append(r.well)
            continue
        w.latitude, w.longitude = None, None
        w.x_coord, w.y_coord = float(r.x), float(r.y)
        if r.altitude is not None:
            w.elevation = float(r.altitude)
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "missing": missing}


@router.post("/api/projects/{pid}/wells/coordinates/import")
async def import_coordinates_file(
    pid: int,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    """Импорт координат из Excel (.xlsx) или CSV.

    Колонки распознаются по заголовку: скважина / X / Y / альтитуда.
    Поддерживаются русские и английские названия; если заголовок не найден,
    берутся первые 3–4 колонки (скважина, X, Y, [альтитуда]).
    """
    data = await file.read()
    if not data:
        raise HTTPException(400, "Пустой файл")
    name = (file.filename or "").lower()
    rows: List[List[str]] = []

    if name.endswith((".xlsx", ".xlsm", ".xltx")):
        try:
            import openpyxl
        except ImportError:
            raise HTTPException(400, "На сервере нет openpyxl")
        try:
            wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        except Exception as e:
            raise HTTPException(400, f"Не удалось прочитать книгу: {e}")
        for r in wb.active.iter_rows(values_only=True):
            rows.append(["" if c is None else str(c) for c in r])
    else:
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
        rows = [list(r) for r in csv.reader(io.StringIO(text), delimiter=delim)]

    if not rows:
        raise HTTPException(400, "В файле нет строк")

    NAME_H = {"скважина", "скв", "well", "name", "имя"}
    X_H = {"x", "х", "x, м", "координата x", "east", "easting"}
    Y_H = {"y", "у", "y, м", "координата y", "north", "northing"}
    ALT_H = {"альтитуда", "alt", "altitude", "kb", "rkb", "elevation", "абс.отм"}

    hdr = [str(c).strip().lower().rstrip(",.") for c in rows[0]]
    ci = {"name": 0, "x": 1, "y": 2, "alt": 3 if len(hdr) > 3 else None}
    start = 0
    if any(h in NAME_H for h in hdr) or any(h in X_H for h in hdr):
        start = 1
        for i, h in enumerate(hdr):
            if h in NAME_H:
                ci["name"] = i
            elif h in X_H:
                ci["x"] = i
            elif h in Y_H:
                ci["y"] = i
            elif h in ALT_H:
                ci["alt"] = i

    wells = {w.name.strip().lower(): w for w in db.query(Well).filter(Well.project_id == pid).all()}
    updated, missing, bad = 0, [], 0
    for r in rows[start:]:
        need = max(v for v in (ci["name"], ci["x"], ci["y"]) if v is not None)
        if len(r) <= need:
            continue
        wname = str(r[ci["name"]]).strip()
        if not wname:
            continue
        try:
            x = float(str(r[ci["x"]]).replace(",", ".").strip())
            y = float(str(r[ci["y"]]).replace(",", ".").strip())
        except (TypeError, ValueError):
            bad += 1
            continue
        w = wells.get(wname.lower())
        if not w:
            missing.append(wname)
            continue
        w.x_coord, w.y_coord = x, y
        if ci["alt"] is not None and len(r) > ci["alt"]:
            try:
                w.elevation = float(str(r[ci["alt"]]).replace(",", ".").strip())
            except (TypeError, ValueError):
                pass
        updated += 1
    db.commit()
    return {"ok": True, "updated": updated, "missing": missing,
            "unparsed_rows": bad, "total_rows": len(rows) - start}


# ── Расчёт параметров по горизонтам ─────────────────────────────────────────
def _decode(cd) -> Optional[np.ndarray]:
    if not cd.data_binary:
        return None
    try:
        return np.frombuffer(cd.data_binary, dtype=np.float64)
    except Exception:
        return None


def _runs_newest_first(well: Well):
    """Рейсы скважины от новых к старым.

    Порядок задаёт, какая версия победит при равном перекрытии интервала:
    для двух версий РИГИС на одну глубину это должна быть свежая.
    """
    return sorted(
        well.log_runs,
        key=lambda r: (r.uploaded_at or datetime.datetime.min, r.id),
        reverse=True,
    )


def _well_curves(well: Well) -> Dict[str, List[Tuple[np.ndarray, np.ndarray]]]:
    """{мнемоника: [(глубины, значения), …]} — все рейсы, т.к. РИГИС С1/С2
    покрывают РАЗНЫЕ интервалы и нужный выбирается по горизонту."""
    # Ключ — МЕТОД, а не имя колонки: в промысловых РИГИС кривые называются
    # КОЛЛЕКТОР / НАСЫЩЕНИЕ / КП_W / КГЛ / КНГ_W, а не COLL / SAT / KP.
    wanted = {"COLL", "SAT", "KP", "KGL", "KNG"}
    out: Dict[str, List[Tuple[np.ndarray, np.ndarray]]] = {}
    # Рейсы перебираем от НОВЫХ к старым: если пользователь загрузил новую
    # версию РИГИС на тот же интервал отдельным рейсом, карта обязана считать
    # по ней. При равном перекрытии выигрывает первый в этом порядке.
    for run in _runs_newest_first(well):
        depth = None
        for cd in run.curve_data:
            if (cd.mnemonic or "").strip().upper() in _DEPTH:
                depth = _decode(cd)
                break
        if depth is None:
            continue
        for cd in run.curve_data:
            m = (cd.mnemonic or "").strip().upper()
            if m in _DEPTH:
                continue
            key = m if m in wanted else _method_key(m)
            if key not in wanted:
                continue
            arr = _decode(cd)
            if arr is None or arr.size != depth.size:
                continue
            out.setdefault(key, []).append((depth, arr))
    return out


def horizon_value(well: Well, horizon: str, param: str) -> Optional[float]:
    """Значение параметра для скважины в интервале горизонта.

    Возвращает None, если горизонта нет / нет РИГИС-кривых (скважина не
    участвует в интерполяции), и 0.0 если горизонт есть, но коллектора нет —
    такая скважина ОГРАНИЧИВАЕТ залежь нулём.
    """
    tops = sorted([t for t in well.formation_tops if t.depth is not None], key=lambda t: t.depth)
    h = None
    for i, t in enumerate(tops):
        if (t.formation_name or "").strip().lower() == horizon.strip().lower():
            base = t.base_depth if t.base_depth is not None else (
                tops[i + 1].depth if i + 1 < len(tops) else None)
            if base and base > t.depth:
                h = (t.depth, base)
            break
    if h is None:
        return None
    cur = _well_curves(well)
    if "COLL" not in cur:
        return None
    # выбираем рейс, реально перекрывающий интервал горизонта
    best = None
    for d, coll in cur["COLL"]:
        sel = (d >= h[0]) & (d <= h[1]) & np.isfinite(coll)
        if sel.sum() > (0 if best is None else best[2].sum()):
            best = (d, coll, sel)
    if best is None or not best[2].any():
        return None
    d, coll, sel = best
    step = float(np.median(np.diff(d[sel]))) if sel.sum() > 1 else 0.1
    is_coll = sel & (np.round(coll) == COLLECTOR_CODE)

    def _aligned(name):
        for dd, vv in cur.get(name, []):
            if dd.size == d.size and np.allclose(dd[:5], d[:5]):
                return vv
        return None

    if param == "thickness":
        return float(is_coll.sum() * step)

    if param == "oil_thick":
        sat = _aligned("SAT")
        if sat is None:
            return None
        oil = is_coll & np.isin(np.round(np.nan_to_num(sat, nan=-1)), list(OIL_SAT_CODES))
        return float(oil.sum() * step)

    if param == "porosity":
        kp = _aligned("KP")
        if kp is None:
            return None
        m = is_coll & np.isfinite(kp) & (kp > 1e-6)
        if not m.any():
            return 0.0
        # средневзвешенное ГАРМОНИЧЕСКОЕ: Σh / Σ(h/Кп); шаг постоянный → n / Σ(1/Кп)
        return float(m.sum() / np.sum(1.0 / kp[m]))

    raise HTTPException(400, f"Неизвестный параметр: {param}")


# ── Сеточная интерполяция ────────────────────────────────────────────────────
def idw_grid(xs, ys, vs, nx, ny, power=2.0, radius=None):
    x0, x1 = float(np.min(xs)), float(np.max(xs))
    y0, y1 = float(np.min(ys)), float(np.max(ys))
    padx = max((x1 - x0) * 0.12, 250.0)
    pady = max((y1 - y0) * 0.12, 250.0)
    x0, x1, y0, y1 = x0 - padx, x1 + padx, y0 - pady, y1 + pady
    gx = np.linspace(x0, x1, nx)
    gy = np.linspace(y0, y1, ny)
    GX, GY = np.meshgrid(gx, gy)
    Z = np.zeros_like(GX)
    W = np.zeros_like(GX)
    for x, y, v in zip(xs, ys, vs):
        d2 = (GX - x) ** 2 + (GY - y) ** 2
        d2 = np.maximum(d2, 1e-6)
        w = 1.0 / d2 ** (power / 2.0)
        Z += w * v
        W += w
    Z = Z / np.maximum(W, 1e-12)

    # маска: дальше предельного радиуса от любой скважины — нет данных
    if radius is None:
        # половина среднего расстояния между соседями × 3
        if len(xs) > 1:
            dm = []
            for i in range(len(xs)):
                dd = np.hypot(np.array(xs) - xs[i], np.array(ys) - ys[i])
                dd[i] = np.inf
                dm.append(dd.min())
            radius = float(np.median(dm)) * 1.6
        else:
            radius = max(padx, pady)
    dmin = np.full_like(GX, np.inf)
    for x, y in zip(xs, ys):
        dmin = np.minimum(dmin, np.hypot(GX - x, GY - y))
    Z[dmin > radius] = np.nan
    return gx, gy, Z, radius


def zero_pinch_mask(gx, gy, xs, ys, vs, Z):
    """«Пустота» на половине расстояния до скважин с нулевой толщиной.

    Узел гасится, если он ближе к скважине с нулевым значением, чем к любой
    скважине с ненулевым — это даёт выклинивание примерно посередине.
    """
    zero = [(x, y) for x, y, v in zip(xs, ys, vs) if v is not None and v <= 1e-9]
    pos = [(x, y) for x, y, v in zip(xs, ys, vs) if v is not None and v > 1e-9]
    if not zero or not pos:
        return Z
    GX, GY = np.meshgrid(gx, gy)
    dz = np.full_like(GX, np.inf)
    for x, y in zero:
        dz = np.minimum(dz, np.hypot(GX - x, GY - y))
    dp = np.full_like(GX, np.inf)
    for x, y in pos:
        dp = np.minimum(dp, np.hypot(GX - x, GY - y))
    Z = Z.copy()
    Z[dz <= dp] = np.nan       # ближе к «пустой» скважине → залежи нет
    return Z


@router.get("/api/projects/{pid}/map/wellheads")
def map_wellheads(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    wells = db.query(Well).filter(Well.project_id == pid).all()
    pts = [{"id": w.id, "name": w.name, "x": w.x_coord, "y": w.y_coord,
            "altitude": w.elevation, "td": w.total_depth}
           for w in wells if w.x_coord is not None and w.y_coord is not None]
    if not pts:
        raise HTTPException(404, "Нет скважин с координатами — импортируйте координаты")
    return {"project_id": pid, "count": len(pts), "wells": pts}


@router.get("/api/projects/{pid}/map/grid")
def map_grid(
    pid: int,
    param: str = Query("thickness", pattern="^(thickness|porosity|oil_thick|altitude)$"),
    horizon: str = Query(""),
    nx: int = Query(140, ge=30, le=400),
    ny: int = Query(140, ge=30, le=400),
    power: float = Query(2.0, ge=0.5, le=6.0),
    pinch: bool = Query(True),
    exclude: str = Query("", description="ID скважин через запятую — исключить из интерполяции"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    excluded = set()
    for part in (exclude or "").split(","):
        part = part.strip()
        if part.isdigit():
            excluded.add(int(part))
    wells = db.query(Well).filter(Well.project_id == pid).all()
    wells = [w for w in wells if w.x_coord is not None and w.y_coord is not None]
    if len(wells) < 3:
        raise HTTPException(400, "Нужно не менее 3 скважин с координатами")

    pts = []
    for w in wells:
        if param == "altitude":
            v = w.elevation
        else:
            if not horizon:
                raise HTTPException(400, "Укажите горизонт")
            v = horizon_value(w, horizon, param)
        pts.append({"id": w.id, "name": w.name, "x": w.x_coord, "y": w.y_coord,
                    "value": v, "excluded": w.id in excluded})

    used = [p for p in pts if p["value"] is not None and not p["excluded"]]
    if len(used) < 3:
        raise HTTPException(400, f"Недостаточно скважин с данными по «{horizon}» ({len(used)})")

    xs = [p["x"] for p in used]
    ys = [p["y"] for p in used]
    vs = [p["value"] for p in used]
    gx, gy, Z, radius = idw_grid(xs, ys, vs, nx, ny, power)
    if pinch and param in ("thickness", "oil_thick"):
        Z = zero_pinch_mask(gx, gy, xs, ys, vs, Z)
        Z = np.where(Z <= 1e-9, np.nan, Z)     # нулевые площади не заливаем

    finite = Z[np.isfinite(Z)]
    titles = {"thickness": "Толщина коллектора, м",
              "porosity": "Пористость (ср. гармоническая), д.ед.",
              "oil_thick": "Нефтенасыщенная толщина, м",
              "altitude": "Альтитуда устья, м"}
    return {
        "project_id": pid, "param": param, "horizon": horizon,
        "title": titles.get(param, param),
        "nx": nx, "ny": ny,
        "x0": float(gx[0]), "x1": float(gx[-1]),
        "y0": float(gy[0]), "y1": float(gy[-1]),
        "radius": round(radius, 1),
        "vmin": float(finite.min()) if finite.size else 0.0,
        "vmax": float(finite.max()) if finite.size else 0.0,
        "grid": [[None if not np.isfinite(v) else round(float(v), 4) for v in row] for row in Z],
        "wells": pts,
        "used": len(used),
        "excluded": sorted(excluded),
    }


@router.get("/api/projects/{pid}/horizons")
def project_horizons(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    wells = db.query(Well).filter(Well.project_id == pid).all()
    names: List[str] = []
    for w in wells:
        for t in w.formation_tops:
            n = (t.formation_name or "").strip()
            if n and n not in names:
                names.append(n)
    return {"horizons": names}


# ── SHP: контуры лицензий и месторождений ───────────────────────────────────
def _read_shp(data: bytes) -> List[dict]:
    """Минимальный чтец SHP: точки, полилинии и полигоны (без зависимостей)."""
    if len(data) < 100:
        raise HTTPException(400, "Файл слишком мал для SHP")
    if struct.unpack(">i", data[0:4])[0] != 9994:
        raise HTTPException(400, "Это не shapefile (.shp)")
    shapes: List[dict] = []
    pos = 100
    while pos + 8 <= len(data):
        _, clen = struct.unpack(">ii", data[pos:pos + 8])
        pos += 8
        end = pos + clen * 2
        if end > len(data):
            break
        stype = struct.unpack("<i", data[pos:pos + 4])[0]
        if stype == 1:                                   # точка
            x, y = struct.unpack("<dd", data[pos + 4:pos + 20])
            shapes.append({"type": "point", "points": [[x, y]]})
        elif stype in (3, 5):                            # полилиния / полигон
            nparts, npoints = struct.unpack("<ii", data[pos + 36:pos + 44])
            p = pos + 44
            parts = list(struct.unpack("<%di" % nparts, data[p:p + 4 * nparts]))
            p += 4 * nparts
            coords = struct.unpack("<%dd" % (npoints * 2), data[p:p + 16 * npoints])
            rings = []
            for i, s in enumerate(parts):
                e = parts[i + 1] if i + 1 < len(parts) else npoints
                rings.append([[coords[2 * k], coords[2 * k + 1]] for k in range(s, e)])
            shapes.append({"type": "polygon" if stype == 5 else "line", "rings": rings})
        pos = end
    return shapes


@router.post("/api/projects/{pid}/shapes")
async def import_shapes(
    pid: int,
    file: UploadFile = File(...),
    label: str = Query("контур"),
    db: Session = Depends(get_db),
) -> Dict[str, Any]:
    data = await file.read()
    shapes = _read_shp(data)
    if not shapes:
        raise HTTPException(400, "В файле нет объектов")
    proj = db.query(Project).filter(Project.id == pid).first()
    if not proj:
        raise HTTPException(404, "Проект не найден")
    try:
        store = json.loads(proj.description or "{}")
        if not isinstance(store, dict):
            store = {}
    except (ValueError, TypeError):
        store = {}
    store.setdefault("shapes", []).append({"label": label, "shapes": shapes})
    proj.description = json.dumps(store, ensure_ascii=False)
    db.commit()
    return {"ok": True, "label": label, "objects": len(shapes)}


@router.get("/api/projects/{pid}/shapes")
def get_shapes(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    proj = db.query(Project).filter(Project.id == pid).first()
    if not proj:
        raise HTTPException(404, "Проект не найден")
    try:
        store = json.loads(proj.description or "{}")
        layers = store.get("shapes", []) if isinstance(store, dict) else []
    except (ValueError, TypeError):
        layers = []
    return {"layers": layers}


# ── Инвентаризация: что есть в скважине ─────────────────────────────────────
@router.get("/api/projects/{pid}/inventory")
def project_inventory(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    """Сводка наличия данных по каждой скважине: координаты, альтитуда,
    инклинометрия, ГИС (методы), РИГИС, отбивки."""
    try:
        from methods import method_for_mnemonic
        from models import DeviationSurvey
    except ImportError:  # pragma: no cover
        from backend.methods import method_for_mnemonic
        from backend.models import DeviationSurvey

    # Ключи методов инклинометрии плюс сырые имена на случай, когда
    # мнемоника вне справочника и _method_key вернул None
    INKL_M = {"INKL", "AZIM", "AZ", "INCL", "ZENIT", "ZENITH", "DEVI",
              "ЗЕНИТ", "ЗЕН", "УГОЛ", "АЗИМУТ", "АЗ"}
    RIGIS_M = {"KP", "KGL", "KNG", "KPR", "LITH", "COLL", "SAT"}

    wells = db.query(Well).filter(Well.project_id == pid).order_by(Well.name).all()
    rows: List[dict] = []
    for w in wells:
        gis, rigis, inkl_pts = set(), set(), 0
        pts_total, depth_min, depth_max = 0, None, None
        for run in w.log_runs:
            pts_total += run.num_points or 0
            if run.start_depth is not None:
                depth_min = run.start_depth if depth_min is None else min(depth_min, run.start_depth)
            if run.stop_depth is not None:
                depth_max = run.stop_depth if depth_max is None else max(depth_max, run.stop_depth)
            for cd in run.curve_data:
                m = (cd.mnemonic or "").strip().upper()
                if m in _DEPTH:
                    continue
                # Сверяем МЕТОД, а не имя колонки: в промысловых файлах пишут
                # КП_W и КОЛЛЕКТОР, поэтому счёт по мнемоникам давал «РИГИС 0».
                key = _method_key(m) or m
                if key in INKL_M:
                    inkl_pts = max(inkl_pts, cd.num_points or 0)
                    continue
                if key in RIGIS_M:
                    rigis.add(key)
                    continue
                meth = method_for_mnemonic(m)
                if meth is not None:
                    gis.add(meth.canonical)

        # Инклинометрия чаще приходит отдельным файлом и лежит в таблице замеров
        if inkl_pts == 0:
            inkl_pts = (db.query(DeviationSurvey)
                        .filter(DeviationSurvey.well_id == w.id).count())

        rows.append({
            "well_id": w.id, "well_name": w.name,
            "coords": (w.x_coord is not None and w.y_coord is not None),
            "x": w.x_coord, "y": w.y_coord,
            "altitude": w.elevation,
            "inkl": inkl_pts > 0, "inkl_points": inkl_pts,
            "gis": sorted(gis), "gis_count": len(gis),
            "rigis": sorted(rigis), "rigis_count": len(rigis),
            "tops": len(w.formation_tops),
            "runs": len(w.log_runs),
            "points": pts_total,
            "depth_from": round(depth_min, 1) if depth_min is not None else None,
            "depth_to": round(depth_max, 1) if depth_max is not None else None,
            "notes": len(json.loads(w.notes or "[]")) if (w.notes or "").strip() else 0,
        })

    def pct(key):
        return round(100 * sum(1 for r in rows if r[key]) / len(rows)) if rows else 0
    summary = {
        "wells": len(rows),
        "with_coords": sum(1 for r in rows if r["coords"]),
        "with_altitude": sum(1 for r in rows if r["altitude"] is not None),
        "with_inkl": sum(1 for r in rows if r["inkl"]),
        "with_gis": sum(1 for r in rows if r["gis_count"]),
        "with_rigis": sum(1 for r in rows if r["rigis_count"]),
        "with_tops": sum(1 for r in rows if r["tops"]),
        "coords_pct": pct("coords"), "inkl_pct": pct("inkl"),
    }
    return {"project_id": pid, "summary": summary, "rows": rows}


# ── Clipboard: библиотека построенных карт ──────────────────────────────────
class ClipItem(BaseModel):
    param: str
    horizon: str = ""
    power: float = 2.0
    levels: int = 8
    reverse: bool = False
    title: str = ""
    frozen: bool = False


def _proj_store(db: Session, pid: int):
    proj = db.query(Project).filter(Project.id == pid).first()
    if not proj:
        raise HTTPException(404, "Проект не найден")
    try:
        store = json.loads(proj.description or "{}")
        if not isinstance(store, dict):
            store = {}
    except (ValueError, TypeError):
        store = {}
    return proj, store


@router.get("/api/projects/{pid}/clipboard")
def clipboard_list(pid: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    _, store = _proj_store(db, pid)
    return {"items": store.get("clipboard", [])}


@router.post("/api/projects/{pid}/clipboard")
def clipboard_add(pid: int, item: ClipItem, db: Session = Depends(get_db)) -> Dict[str, Any]:
    import datetime
    proj, store = _proj_store(db, pid)
    items = store.setdefault("clipboard", [])
    rec = item.model_dump() if hasattr(item, "model_dump") else item.dict()
    # без дублей: тот же параметр+горизонт обновляется
    for ex in items:
        if ex.get("param") == rec["param"] and ex.get("horizon") == rec["horizon"]:
            ex.update(rec)
            proj.description = json.dumps(store, ensure_ascii=False)
            db.commit()
            return {"ok": True, "updated": True, "count": len(items)}
    rec["id"] = (max([i.get("id", 0) for i in items]) + 1) if items else 1
    rec["created_at"] = datetime.datetime.utcnow().isoformat(timespec="seconds")
    items.append(rec)
    proj.description = json.dumps(store, ensure_ascii=False)
    db.commit()
    return {"ok": True, "item": rec, "count": len(items)}


@router.delete("/api/projects/{pid}/clipboard/{item_id}")
def clipboard_delete(pid: int, item_id: int, db: Session = Depends(get_db)) -> Dict[str, Any]:
    proj, store = _proj_store(db, pid)
    items = [i for i in store.get("clipboard", []) if i.get("id") != item_id]
    store["clipboard"] = items
    proj.description = json.dumps(store, ensure_ascii=False)
    db.commit()
    return {"ok": True, "count": len(items)}
