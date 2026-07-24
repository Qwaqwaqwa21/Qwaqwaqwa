# coding: utf-8
"""
Пласты/зоны на планшете: загрузка кровли-подошвы из файла, ручная
корректировка отбивок, экспорт и проверка наличия кривых по каждой зоне.
"""
from io import BytesIO
from pathlib import Path

import numpy as np
import pandas as pd

# Колонки итоговой таблицы зон (в этом порядке и с этими названиями работает
# весь остальной код модуля и UI).
ZONE_COLUMNS = ['Зона', 'Кровля, м', 'Подошва, м']

# Синонимы названий колонок во входных файлах (регистр и пробелы не важны).
_NAME_ALIASES = {'зона', 'пласт', 'пропласток', 'name', 'zone', 'формация', 'formation'}
_TOP_ALIASES = {'кровля', 'кровля, м', 'top', 'from', 'top, m', 'top_m'}
_BOTTOM_ALIASES = {'подошва', 'подошва, м', 'bottom', 'to', 'bottom, m', 'bottom_m'}
_WELL_ALIASES = {'скважина', 'well', 'well_name', 'скв', 'скв.'}


def _normalize_key(col):
    return str(col).strip().lower()


def _find_column(columns, aliases):
    for col in columns:
        if _normalize_key(col) in aliases:
            return col
    return None


def load_zones_from_file(file_obj, filename=None):
    """
    Загружает зоны из CSV или Excel (.xlsx/.xls). Ищет колонки по алиасам
    (регистр/пробелы не важны):
      - имя зоны: Зона / Пласт / Name / Zone / ...
      - кровля:   Кровля / Top / ...
      - подошва:  Подошва / Bottom / ...
      - скважина (необязательно): Скважина / Well / ...

    file_obj: путь, файловый объект или объект st.file_uploader (имеет .name).
    filename: имя файла, если его не удаётся определить из file_obj (например,
        для BytesIO без атрибута .name).

    Возвращает (DataFrame с колонками ZONE_COLUMNS [+ 'Скважина' при наличии],
    список_предупреждений).
    Бросает ValueError, если не удалось найти обязательные колонки.
    """
    name = filename or getattr(file_obj, 'name', None) or (
        str(file_obj) if isinstance(file_obj, (str, Path)) else ''
    )
    suffix = Path(name).suffix.lower()

    if hasattr(file_obj, 'seek'):
        file_obj.seek(0)

    if suffix in ('.xlsx', '.xls'):
        raw = pd.read_excel(file_obj)
    else:
        # По умолчанию считаем CSV (в т.ч. если расширение неизвестно/отсутствует).
        raw = pd.read_csv(file_obj)

    if raw.empty:
        raise ValueError("Файл не содержит данных")

    name_col = _find_column(raw.columns, _NAME_ALIASES)
    top_col = _find_column(raw.columns, _TOP_ALIASES)
    bottom_col = _find_column(raw.columns, _BOTTOM_ALIASES)
    well_col = _find_column(raw.columns, _WELL_ALIASES)

    missing = [label for label, col in
               [('название зоны', name_col), ('кровля', top_col), ('подошва', bottom_col)]
               if col is None]
    if missing:
        raise ValueError(
            f"Не удалось найти колонки: {', '.join(missing)}. "
            f"Найденные колонки в файле: {', '.join(str(c) for c in raw.columns)}"
        )

    result = pd.DataFrame({
        'Зона': raw[name_col].astype(str).str.strip(),
        'Кровля, м': pd.to_numeric(raw[top_col], errors='coerce'),
        'Подошва, м': pd.to_numeric(raw[bottom_col], errors='coerce'),
    })
    if well_col is not None:
        result['Скважина'] = raw[well_col].astype(str).str.strip()

    warnings = []
    bad_rows = result['Кровля, м'].isna() | result['Подошва, м'].isna()
    if bad_rows.any():
        warnings.append(f"Пропущено строк с нечисловой глубиной: {int(bad_rows.sum())}")
        result = result[~bad_rows].reset_index(drop=True)

    if result.empty:
        raise ValueError("После разбора файла не осталось ни одной корректной строки с зоной")

    return result, warnings


def validate_zones(zones_df):
    """
    Проверяет таблицу зон и возвращает список текстовых предупреждений:
    кровля >= подошвы, пересекающиеся зоны, повторяющиеся имена.
    Ничего не бросает — только сообщает, чтобы UI мог показать предупреждения,
    не блокируя работу (данные могут быть намеренно нестандартными).
    """
    warnings = []
    if zones_df is None or zones_df.empty:
        return warnings

    inverted = zones_df['Кровля, м'] >= zones_df['Подошва, м']
    for _, row in zones_df[inverted].iterrows():
        warnings.append(f"«{row['Зона']}»: кровля ({row['Кровля, м']:g}) не меньше подошвы ({row['Подошва, м']:g})")

    dup_names = zones_df['Зона'][zones_df['Зона'].duplicated()].unique()
    for name in dup_names:
        warnings.append(f"Повторяющееся имя зоны: «{name}»")

    # Полный перебор пар (а не только соседних после сортировки по кровле) —
    # иначе короткая зона, целиком вложенная в другую (не соседнюю по кровле),
    # осталась бы незамеченной.
    rows = zones_df.dropna(subset=['Кровля, м', 'Подошва, м']).to_dict('records')
    for i in range(len(rows)):
        a = rows[i]
        for j in range(i + 1, len(rows)):
            b = rows[j]
            if a['Кровля, м'] > b['Кровля, м']:
                a, b = b, a
            if a['Подошва, м'] > b['Кровля, м']:
                warnings.append(
                    f"«{a['Зона']}» и «{b['Зона']}» пересекаются по глубине "
                    f"({a['Подошва, м']:g} > {b['Кровля, м']:g})"
                )

    return warnings


def clean_zones_df(zones_df):
    """
    Приводит колонки глубины к числовому виду и отбрасывает строки без обеих
    глубин — например, недозаполненные новые строки, добавленные через
    st.data_editor. Возвращает (очищенный DataFrame, число отброшенных строк).
    """
    if zones_df is None or zones_df.empty:
        return zones_df, 0

    cleaned = zones_df.copy()
    cleaned['Кровля, м'] = pd.to_numeric(cleaned['Кровля, м'], errors='coerce')
    cleaned['Подошва, м'] = pd.to_numeric(cleaned['Подошва, м'], errors='coerce')
    incomplete = cleaned['Кровля, м'].isna() | cleaned['Подошва, м'].isna()
    dropped = int(incomplete.sum())
    cleaned = cleaned[~incomplete].reset_index(drop=True)
    return cleaned, dropped


def _clip_to_zone(zone_top, zone_bottom, interval_top, interval_bottom):
    lo = max(zone_top, interval_top)
    hi = min(zone_bottom, interval_bottom)
    return (lo, hi) if hi > lo else None


def _union_length(intervals):
    """Суммарная длина объединения интервалов (без двойного счёта перекрытий)."""
    if not intervals:
        return 0.0
    intervals = sorted(intervals)
    total = 0.0
    cur_start, cur_end = intervals[0]
    for start, end in intervals[1:]:
        if start > cur_end:
            total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            cur_end = max(cur_end, end)
    total += cur_end - cur_start
    return total


def build_zone_curve_coverage(zones_df, interval_table):
    """
    Для каждой зоны и каждой кривой из interval_table (см. plotting.build_interval_table)
    определяет, покрыта ли зона данными этой кривой:
      'полностью' — суммарное перекрытие интервалов записи >= длины зоны,
      'частично'  — есть перекрытие, но неполное,
      'нет'       — перекрытий не найдено.

    Возвращает DataFrame с колонками ['Зона', 'Кровля, м', 'Подошва, м', <кривая1>, <кривая2>, ...].
    """
    if zones_df is None or zones_df.empty:
        return pd.DataFrame()

    methods = list(dict.fromkeys(row['Метод'] for row in interval_table)) if interval_table else []

    rows = []
    for _, zone in zones_df.iterrows():
        zone_top, zone_bottom = zone['Кровля, м'], zone['Подошва, м']
        zone_length = max(0.0, zone_bottom - zone_top)
        row = {'Зона': zone['Зона'], 'Кровля, м': zone_top, 'Подошва, м': zone_bottom}

        for method in methods:
            clipped = [
                _clip_to_zone(zone_top, zone_bottom, float(r['Кровля, м']), float(r['Подошва, м']))
                for r in interval_table if r['Метод'] == method
            ]
            overlap = _union_length([c for c in clipped if c is not None])
            if overlap <= 0:
                status = 'нет'
            elif zone_length > 0 and overlap >= zone_length - 1e-6:
                status = 'полностью'
            else:
                status = 'частично'
            row[method] = status

        rows.append(row)

    return pd.DataFrame(rows)


def zones_to_csv_bytes(zones_df):
    """Готовит CSV (utf-8-sig) таблицы зон для скачивания."""
    return zones_df.to_csv(index=False, encoding='utf-8-sig')
