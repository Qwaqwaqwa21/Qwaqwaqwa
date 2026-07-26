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
    # Результаты интерпретации: расчёты просят западные обозначения величин,
    # а в РИГИС они записаны как Кп/Кгл/Кнг/Кпр. Без этих пар петрофизика на
    # промысловых файлах отвечала «PHIE not found» при наличии Кп в рейсе.
    # Кв (SW) НЕ приравнивается к Кнг: это дополняющие величины, пересчёт
    # делается явно (см. water_saturation).
    "PHIE": ("KP",), "PHIT": ("KP",), "KP": ("PHIE",),
    "VSH": ("KGL",), "VCL": ("KGL",), "KGL": ("VSH",),
    "PERM": ("KPR",), "KPR": ("PERM",),
    "SW": ("KV",), "KV": ("SW",),
    "LITH": ("LITH",), "COLL": ("COLL",), "SAT": ("SAT",),
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


def find_curve_in_well(db, well, *keys: str):
    """Кривая метода в любом рейсе скважины.

    Возвращает `(CurveData, log_run_id)`. Нужна там, где расчёт привязан к
    активному рейсу, но сам метод записан в соседнем: у заказчика ГК лежит в
    рейсе ГИС, а выбран может быть рейс РИГИС.
    """
    best = None
    for run in getattr(well, "log_runs", []) or []:
        cd = find_curve(db, run.id, *keys)
        if cd is not None and (best is None or (cd.num_points or 0) > (best[0].num_points or 0)):
            best = (cd, run.id)
    return best if best else (None, None)


def find_depth(db, log_run_id: int) -> Optional[CurveData]:
    """Индексная кривая рейса (DEPT/DEPTH/MD/TVD — как записано в файле)."""
    rows = db.query(CurveData).filter(CurveData.log_run_id == log_run_id).all()
    for name in DEPTH_NAMES:
        for cd in rows:
            if (cd.mnemonic or "").strip().upper() == name:
                return cd
    return None


def water_saturation(db, well, log_run_id=None):
    """Кв для расчётов: своя кривая либо явный пересчёт из Кнг (Кв = 1 − Кнг).

    РИГИС отдаёт нефтегазонасыщенность, а формулы просят водонасыщенность.
    Пересчёт именно ЯВНЫЙ и подписывается в ответе: молчаливая подстановка Кнг
    вместо Кв инвертирует отбор коллектора (в пласт попадают обводнённые
    интервалы). Возвращает ``(значения, подпись, log_run_id)``.
    """
    import numpy as np

    def _vals(cd):
        if cd is None or not cd.data_binary:
            return None
        return np.frombuffer(cd.data_binary, dtype=np.float64).copy()

    if log_run_id is not None:
        cd = find_curve(db, log_run_id, "SW")
        if cd is not None:
            return _vals(cd), cd.mnemonic, log_run_id
        cd = find_curve(db, log_run_id, "KNG")
        if cd is not None:
            v = _vals(cd)
            return (np.clip(1.0 - v, 0.0, 1.0) if v is not None else None,
                    f"1 - {cd.mnemonic}", log_run_id)
        return None, None, None

    cd, rid = find_curve_in_well(db, well, "SW")
    if cd is not None:
        return _vals(cd), cd.mnemonic, rid
    cd, rid = find_curve_in_well(db, well, "KNG")
    if cd is not None:
        v = _vals(cd)
        return (np.clip(1.0 - v, 0.0, 1.0) if v is not None else None,
                f"1 - {cd.mnemonic}", rid)
    return None, None, None


# Единицы, в которых значение действительно является пористостью.
_POROSITY_FRACTION_UNITS = {"V/V", "VV", "DEC", "FRAC", "Д.ЕД", "Д.ЕД.", "ДЕК",
                            "ДОЛ.ЕД", "ДОЛ.ЕД.", "ДОЛИ", "M3/M3", "М3/М3"}
_POROSITY_PERCENT_UNITS = {"%", "PU", "P.U.", "PERC", "PCT", "PERCENT", "%V/V", "ПРОЦ"}


def as_porosity(values, unit=""):
    """Привести кривую к пористости в долях единицы или отказаться.

    НГК в усл. ед. (значения 1–5) — это НЕ пористость: если подставить его в
    формулы напрямую, Кп упирается в верхнюю отсечку 0.6 и Sw считается по
    мусору. Поэтому кривая принимается, только когда единицы прямо говорят о
    пористости либо диапазон значений сам по себе допустим.

    Возвращает ``(массив|None, подпись)``.
    """
    import numpy as np

    if values is None:
        return None, "нет кривой"
    arr = np.asarray(values, dtype=float)
    if not np.any(np.isfinite(arr)):
        return None, "пусто"
    u = (unit or "").strip().upper().replace(" ", "")
    hi = float(np.nanmax(arr[np.isfinite(arr)]))

    if u in _POROSITY_PERCENT_UNITS:
        return arr / 100.0, f"{unit} → д.ед."
    if u in _POROSITY_FRACTION_UNITS:
        return arr, unit or "д.ед."
    # Единицы не указаны (обычное дело в промысловых LAS) — решаем по диапазону
    if hi <= 1.0:
        return arr, "д.ед. (по диапазону)"
    if 1.0 < hi <= 100.0 and float(np.nanmedian(arr[np.isfinite(arr)])) > 1.0:
        # 1–100 без единиц: проценты только если и медиана выше единицы
        if hi > 5.0:
            return arr / 100.0, "% (по диапазону) → д.ед."
    return None, f"единицы «{unit or 'не заданы'}», диапазон до {hi:g} — не пористость"
