"""
Поиск кривой по методу ГИС, а не по жёстко зашитому имени.

Расчётные модули исторически искали кривые списками западных мнемоник
(`["GR","SGR","CGR"]`), поэтому на промысловых файлах с именами ГК, GK_500 или
ЛИТОЛОГИЯ они ничего не находили. Здесь имя разбирается через справочник
методов, так что подходит любой синоним метода и его вариант с суффиксом.
"""
from __future__ import annotations

from typing import Iterable, Optional

try:
    from models import CurveData
    from methods import method_for_mnemonic
except ImportError:  # pragma: no cover
    from backend.models import CurveData
    from backend.methods import method_for_mnemonic

DEPTH_NAMES = ("DEPT", "DEPTH", "MD", "TVD", "ГЛУБ", "ГЛУБИНА")

# Соответствие «западный» метод → российский, чтобы один запрос находил обе
# формы записи одного и того же исследования.
EQUIVALENT = {
    "GR": ("GK",),
    "GK": ("GR",),
    "NPHI": ("NGK",),
    "NGK": ("NPHI",),
    "RHOB": ("GGKP",),
    "GGKP": ("RHOB",),
    "DT": ("AK",),
    "AK": ("DT",),
    "CAL": ("DS",),
    "DS": ("CAL",),
    "SP": ("PS",),
    "PS": ("SP",),
    "RT": ("KS", "BK", "IK"),
    "KS": ("RT",),
    "BK": ("RT",),
    "IK": ("RT",),
    "RXO": ("MKZ",),
    "MKZ": ("RXO",),
}


def method_key(mnemonic: str) -> Optional[str]:
    """Ключ метода для мнемоники (GK_500 → GK, ЛИТОЛОГИЯ → LITH)."""
    meth = method_for_mnemonic(mnemonic or "")
    return meth.key if meth else None


def _wanted(keys: Iterable[str]) -> set:
    out = set()
    for k in keys:
        k = (k or "").upper()
        if not k:
            continue
        out.add(k)
        out.update(EQUIVALENT.get(k, ()))
    return out


def find_curve(db, log_run_id: int, *keys: str) -> Optional[CurveData]:
    """Первая кривая рейса, относящаяся к одному из методов `keys`.

    Кривые с большим числом точек предпочитаются: в реальных выгрузках рядом
    лежат «пустая» и рабочая запись одного метода.
    """
    wanted = _wanted(keys)
    if not wanted:
        return None
    rows = db.query(CurveData).filter(CurveData.log_run_id == log_run_id).all()
    best = None
    for cd in rows:
        name = (cd.mnemonic or "").strip()
        if name.upper() in DEPTH_NAMES:
            continue
        mk = method_key(name)
        if mk and mk in wanted:
            if best is None or (cd.num_points or 0) > (best.num_points or 0):
                best = cd
    if best is not None:
        return best
    # прямое совпадение по имени — на случай мнемоник вне справочника
    for cd in rows:
        if (cd.mnemonic or "").strip().upper() in wanted:
            return cd
    return None


def find_depth(db, log_run_id: int) -> Optional[CurveData]:
    """Индексная кривая рейса (DEPT/DEPTH/MD/TVD — как записано в файле)."""
    rows = db.query(CurveData).filter(CurveData.log_run_id == log_run_id).all()
    for name in DEPTH_NAMES:
        for cd in rows:
            if (cd.mnemonic or "").strip().upper() == name:
                return cd
    return None
