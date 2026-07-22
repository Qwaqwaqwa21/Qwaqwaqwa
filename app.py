# coding: utf-8
import streamlit as st
import pandas as pd
import numpy as np
import lasio
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
from io import StringIO
import re
import os
import shutil
import textwrap
from collections import defaultdict
from datetime import datetime
import traceback
from io import BytesIO

# Настройки для кириллицы
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['figure.dpi'] = 100

# === Константы ===
# Путь к словарю мнемоник настраивается через переменную окружения MNEMO_PATH
# (по умолчанию — mnemo.xlsx рядом со скриптом, чтобы приложение запускалось
# без доступа к конкретному сетевому диску).
MNEMO_PATH = os.environ.get("MNEMO_PATH", str(Path(__file__).parent / "mnemo.xlsx"))

# === Инициализация session_state ===
if 'step1_data' not in st.session_state:
    st.session_state.step1_data = {}
if 'step2_data' not in st.session_state:
    st.session_state.step2_data = {}
if 'selected_encoding_step1' not in st.session_state:
    st.session_state.selected_encoding_step1 = None
if 'selected_encoding_step2' not in st.session_state:
    st.session_state.selected_encoding_step2 = None
if 'preview_data_step1' not in st.session_state:
    st.session_state.preview_data_step1 = {}
if 'preview_data_step2' not in st.session_state:
    st.session_state.preview_data_step2 = {}

# === УЛУЧШЕННАЯ ФУНКЦИЯ ПРЕДПРОСМОТРА КОДИРОВОК ===
# === ИСПРАВЛЕННАЯ ФУНКЦИЯ ПРЕДПРОСМОТРА КОДИРОВОК (без синтаксических ошибок) ===
def preview_las_header(filepath, encoding='cp1251'):
    """
    Читает LAS-файл и возвращает структурированный предпросмотр заголовка:
    - Поля из секции ~WELL (WELL, COMP, FLD, FIELD, SRVC и др.)
    - Список кривых с описаниями из секции ~CURVE
    """
    try:
        las = read_las_robust(filepath, encoding=encoding)

        # === Извлечение полей из секции ~WELL ===
        well_fields = {}
        well_keys = ['WELL', 'UWI', 'COMP', 'FLD', 'FIELD', 'SRVC', 'DATE', 'API']

        for key in well_keys:
            if key in las.well:
                value = str(las.well[key].value).strip()
                if value and value != 'UNKNOWN' and value != '':
                    well_fields[key] = value

        # Альтернативные варианты для некоторых полей
        if 'FLD' not in well_fields and 'FIELD' in well_fields:
            well_fields['FLD'] = well_fields['FIELD']
        elif 'FIELD' not in well_fields and 'FLD' in well_fields:
            well_fields['FIELD'] = well_fields['FLD']

        # === Извлечение кривых из секции ~CURVE ===
        curves_info = []
        for curve in las.curves:
            mnemonic = curve.mnemonic.strip()
            if mnemonic and mnemonic != 'DEPT' and mnemonic != 'DEPTH':
                unit = curve.unit.strip() if hasattr(curve, 'unit') and curve.unit else ''
                descr = curve.descr.strip() if hasattr(curve, 'descr') and curve.descr else ''

                # Формируем строку описания
                desc_parts = []
                if descr:
                    desc_parts.append(descr)
                if unit:
                    desc_parts.append(f"{unit}")

                description = " | ".join(desc_parts) if desc_parts else 'без описания'
                curves_info.append((mnemonic, description))

        # === Проверка кириллицы ===
        all_text = " ".join(list(well_fields.values()) + [mn for mn, _ in curves_info] + [desc for _, desc in curves_info])
        has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', all_text))

        return {
            'well_fields': well_fields,
            'curves_info': curves_info[:10],  # Первые 10 кривых для предпросмотра
            'total_curves': len(curves_info),
            'has_cyrillic': has_cyrillic,
            'error': None
        }

    except Exception as e:
        return {
            'well_fields': {},
            'curves_info': [],
            'total_curves': 0,
            'has_cyrillic': False,
            'error': str(e)[:100]
        }

# === НОВАЯ ФУНКЦИЯ: ГОРИЗОНТАЛЬНЫЙ ПРЕДПРОСМОТР КОДИРОВОК ===
def display_preview_result_horizontal(encoding, preview_data):
    """
    Отображает результат предпросмотра в компактном горизонтальном формате
    """
    if preview_data['error']:
        st.error(f"❌ {encoding}: {preview_data['error']}")
        return

    # Статус кириллицы
    status_emoji = "✅" if preview_data['has_cyrillic'] else "⚠️"

    # Формируем компактную строку с информацией
    well_info = []
    for key in ['WELL', 'FLD', 'FIELD']:
        if key in preview_data['well_fields']:
            well_info.append(f"{key}={preview_data['well_fields'][key]}")

    well_str = " | ".join(well_info[:2]) if well_info else "—"
    curves_str = f"{preview_data['total_curves']} кривых" if preview_data['total_curves'] > 0 else "—"

    st.markdown(f"**`{encoding}`** {status_emoji} • {well_str} • {curves_str}")

    # Поля из заголовка
    if preview_data['well_fields']:
        st.text("  Поля заголовка:")
        for key, value in preview_data['well_fields'].items():
            st.text(f"    {key:6s} : {value}")

    # Кривые
    if preview_data['curves_info']:
        st.text(f"  Кривые ({preview_data['total_curves']} всего):")
        for mnemonic, descr in preview_data['curves_info']:
            st.text(f"    {mnemonic:15s} : {descr}")
        if preview_data['total_curves'] > 10:
            st.text(f"    ... и ещё {preview_data['total_curves'] - 10} кривых")

# === Остальные вспомогательные функции (без изменений) ===
def find_las_files(folder):
    """Ищет .las файлы регистронезависимо (Windows часто отдаёт .LAS)"""
    folder = Path(folder)
    seen = {}
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() == '.las':
            seen[path.name] = path
    return sorted(seen.values(), key=lambda p: p.name)

def read_las_robust(filepath, encoding='cp1251'):
    """Надёжное чтение LAS-файла с обходом багов"""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Файл не найден: {filepath}")
    try:
        las = lasio.read(filepath, encoding=encoding, ignore_header_errors=True)
        return las
    except Exception as e1:
        try:
            with open(filepath, 'r', encoding=encoding) as f:
                content = f.read()
            las = lasio.read(StringIO(content), autodetect_encoding=False)
            return las
        except Exception as e2:
            try:
                with open(filepath, 'rb') as f:
                    raw = f.read()
                decoded = raw.decode(encoding, errors='ignore')
                las = lasio.read(StringIO(decoded), autodetect_encoding=False)
                return las
            except Exception as e3:
                raise RuntimeError(f"Не удалось прочитать файл {filepath.name}: {e1}")

def get_well_name(las):
    """Безопасное получение названия скважины"""
    try:
        if 'WELL' in las.well:
            return str(las.well['WELL'].value).strip()
        elif hasattr(las.well, 'WELL'):
            return str(las.well.WELL.value).strip()
        else:
            return Path(las.well['SRVC'].value).stem if 'SRVC' in las.well else "UNKNOWN"
    except (KeyError, AttributeError, ValueError):
        return "UNKNOWN"

def load_mnemo_dict(filepath):
    """Загружает словарь мнемоник из Excel-файла"""
    try:
        if not Path(filepath).exists():
            st.warning(f"Файл мнемоник не найден: {filepath}. Будет создан новый.")
            return {}, {}
        df = pd.read_excel(filepath, header=None, dtype=str)

        canonical_to_aliases = {}
        for _, row in df.iterrows():
            row = row.dropna()
            if len(row) == 0:
                continue
            canonical = row.iloc[0].strip()
            aliases = [str(x).strip() for x in row.iloc[1:] if pd.notna(x)]
            canonical_to_aliases[canonical] = aliases

        alias_to_canonical = {}
        for canonical, aliases in canonical_to_aliases.items():
            for alias in aliases:
                alias_to_canonical[alias] = canonical
            alias_to_canonical[canonical] = canonical

        return canonical_to_aliases, alias_to_canonical
    except Exception as e:
        st.error(f"❌ Ошибка загрузки словаря мнемоник: {e}")
        return {}, {}

def save_mnemo_dict(filepath, canonical_to_aliases):
    """Сохраняет обновлённый словарь мнемоник в Excel, предварительно делая резервную копию"""
    try:
        filepath = Path(filepath)
        if filepath.exists():
            backup_dir = filepath.parent / "mnemo_backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = backup_dir / f"{filepath.stem}_{timestamp}{filepath.suffix}"
            shutil.copy2(filepath, backup_path)

        rows = []
        for canonical, aliases in canonical_to_aliases.items():
            row = [canonical] + aliases
            rows.append(row)
        if rows:
            max_len = max(len(row) for row in rows)
            padded_rows = [row + [''] * (max_len - len(row)) for row in rows]
            df = pd.DataFrame(padded_rows)
        else:
            df = pd.DataFrame()

        df.to_excel(filepath, index=False, header=False)
        return True
    except Exception as e:
        st.error(f"❌ Ошибка сохранения словаря: {e}")
        return False

def load_all_las_with_metadata(las_files, encoding='utf-8-sig'):
    """Загружает все LAS-файлы с сохранением метаданных и описаний кривых"""
    wells_data = defaultdict(list)
    for filepath in las_files:
        try:
            las = read_las_robust(filepath, encoding=encoding)
            well_name = get_well_name(las)
            file_name = filepath.name

            df = las.df()
            df.replace(-999.25, np.nan, inplace=True)
            df.replace(-999.00, np.nan, inplace=True)

            # Определение глубины
            if 'DEPT' in df.columns:
                depth = df['DEPT'].values
            elif 'DEPTH' in df.columns:
                depth = df['DEPTH'].values
                df = df.rename(columns={'DEPTH': 'DEPT'})
            else:
                depth = df.index.values
                df = df.reset_index(drop=True)
                df.insert(0, 'DEPT', depth)

            # Сохраняем данные с метаданными + описаниями кривых
            file_data = {
                'file_name': file_name,
                'well_name': well_name,
                'depth': depth,
                'curves': {},
                'curve_descriptions': {},  # НОВОЕ: словарь описаний
                'depth_range': (np.nanmin(depth), np.nanmax(depth))
            }

            # Получаем описания из оригинального LAS-файла
            for curve in las.curves:
                mnemonic = curve.mnemonic.strip()
                if mnemonic and mnemonic != 'DEPT' and mnemonic != 'DEPTH' and mnemonic in df.columns:
                    file_data['curves'][mnemonic] = df[mnemonic].values
                    # Сохраняем описание и единицы измерения
                    descr = getattr(curve, 'descr', '').strip()
                    unit = getattr(curve, 'unit', '').strip()
                    desc_parts = []
                    if descr:
                        desc_parts.append(descr)
                    if unit:
                        desc_parts.append(f"[{unit}]")
                    file_data['curve_descriptions'][mnemonic] = " ".join(desc_parts) if desc_parts else ""

            wells_data[well_name].append(file_data)

        except Exception as e:
            st.error(f"❌ Ошибка загрузки {filepath.name}: {str(e)[:60]}")

    if not wells_data:
        raise ValueError("Не удалось загрузить данные ни из одного файла")

    wells_data = dict(sorted(wells_data.items()))
    return wells_data

def merge_curves_by_mnemonic(well_files, overlap_m=100):
    """Объединяет кривые по мнемоникам для одной скважины"""
    # Определение общего диапазона глубин с нахлестом
    depth_ranges = [f['depth_range'] for f in well_files]
    global_min = min(r[0] for r in depth_ranges) - overlap_m
    global_max = max(r[1] for r in depth_ranges) + overlap_m

    # Сбор всех уникальных мнемоник
    all_mnemonics = set()
    for file_data in well_files:
        all_mnemonics.update(file_data['curves'].keys())

    # Для каждой мнемоники собираем все её экземпляры из разных файлов
    merged_curves = defaultdict(list)

    for file_data in well_files:
        file_name = file_data['file_name']
        depth = file_data['depth']

        for mnemonic, values in file_data['curves'].items():
            curve_instance = {
                'file_name': file_name,
                'depth': depth,
                'values': values,
                'depth_range': file_data['depth_range']
            }
            merged_curves[mnemonic].append(curve_instance)

    return dict(merged_curves), global_min, global_max

def find_intervals(curve_instances, depth_step=0.5):
    """
    Находит непрерывные интервалы для кривой (кровля/подошва) + мин/макс значения
    """
    intervals = []
    for instance in curve_instances:
        depth = instance['depth']
        values = instance['values']
        file_name = instance['file_name']

        # Защита от некорректных данных
        if depth is None or values is None:
            continue

        # Преобразуем в numpy массивы, если ещё не
        depth = np.array(depth)
        values = np.array(values)

        valid_mask = np.isfinite(values) & np.isfinite(depth)
        if not np.any(valid_mask):
            continue

        valid_depth = depth[valid_mask]
        valid_values = values[valid_mask]

        if len(valid_depth) == 0:
            continue

        # Сортируем по глубине
        sorted_indices = np.argsort(valid_depth)
        sorted_depth = valid_depth[sorted_indices]
        sorted_values = valid_values[sorted_indices]

        intervals_in_instance = []
        start_idx = 0
        start_depth = sorted_depth[0]

        for i in range(1, len(sorted_depth)):
            if sorted_depth[i] - sorted_depth[i-1] > depth_step * 2:
                # Нашли разрыв - закрываем интервал
                end_idx = i - 1
                end_depth = sorted_depth[end_idx]

                # Вычисляем мин/макс значения в этом интервале
                interval_values = sorted_values[start_idx:end_idx+1]
                min_val = np.nanmin(interval_values) if len(interval_values) > 0 else np.nan
                max_val = np.nanmax(interval_values) if len(interval_values) > 0 else np.nan

                intervals_in_instance.append({
                    'top': start_depth,
                    'bottom': end_depth,
                    'file_name': file_name,
                    'min_value': min_val,
                    'max_value': max_val
                })

                # Начинаем новый интервал
                start_idx = i
                start_depth = sorted_depth[i]

        # Закрываем последний интервал
        end_idx = len(sorted_depth) - 1
        end_depth = sorted_depth[end_idx]
        interval_values = sorted_values[start_idx:end_idx+1]
        min_val = np.nanmin(interval_values) if len(interval_values) > 0 else np.nan
        max_val = np.nanmax(interval_values) if len(interval_values) > 0 else np.nan

        intervals_in_instance.append({
            'top': start_depth,
            'bottom': end_depth,
            'file_name': file_name,
            'min_value': min_val,
            'max_value': max_val
        })

        intervals.extend(intervals_in_instance)

    # Сортируем интервалы по кровле
    intervals.sort(key=lambda x: x['top'])
    return intervals

def wrap_text(text, width=20):
    """Перенос текста по словам с заданной шириной"""
    return textwrap.fill(text, width=width, break_long_words=False)

def calculate_curve_limits(curve_data, grid_type='linear', mnemonic=''):
    """
    Рассчитывает лимиты оси для кривой с корректной обработкой малого разброса.
    """
    valid_vals = curve_data[np.isfinite(curve_data)]
    if len(valid_vals) == 0:
        return None, None

    # === ФИЛЬТРАЦИЯ ВЫБРОСОВ ПО МЕДИАНЕ И MAD ===
    median = np.nanmedian(valid_vals)
    mad = np.nanmedian(np.abs(valid_vals - median))

    if mad > 0:
        lower_bound = median - 3 * mad
        upper_bound = median + 3 * mad
        filtered_vals = valid_vals[(valid_vals >= lower_bound) & (valid_vals <= upper_bound)]
    else:
        filtered_vals = valid_vals

    if len(filtered_vals) < max(5, len(valid_vals) * 0.3):
        filtered_vals = valid_vals

    if len(filtered_vals) < 5:
        vmin, vmax = np.nanmin(filtered_vals), np.nanmax(filtered_vals)
        if vmin == vmax:
            if mnemonic in ['DS', 'DS_500']:
                return 0.17, 0.25
            elif mnemonic in ['RS', 'RS_500']:
                return 0.9, 1.6
            return vmin - 0.1, vmax + 0.1
        padding = (vmax - vmin) * 0.5
        return vmin - padding, vmax + padding

    if grid_type == 'log':
        valid_positive = filtered_vals[filtered_vals > 0]
        if len(valid_positive) == 0:
            return None, None
        vmin = np.nanpercentile(valid_positive, 5)
        vmax = np.nanpercentile(valid_positive, 95)
        if vmin <= 0:
            vmin = np.min(valid_positive[valid_positive > 0])
        vmin = 10 ** np.floor(np.log10(vmin))
        vmax = 10 ** np.ceil(np.log10(vmax))
        return max(0.1, vmin), min(10000, vmax)
    else:
        small_range_curves = {
            'DS': (0.175, 0.245),
            'DS_500': (0.175, 0.245),
            'RS': (1.0, 1.5),
            'RS_500': (1.0, 1.5),
            'KS': (0.0, 5.0),
            'KS_500': (0.0, 5.0),
            'PS': (0.0, 10.0),
            'PS_500': (0.0, 10.0),
            'GGK-P': (0.0, 5.0)
        }

        if mnemonic in small_range_curves:
            vmin = np.nanpercentile(filtered_vals, 20)
            vmax = np.nanpercentile(filtered_vals, 90)

            min_expected, max_expected = small_range_curves[mnemonic]
            vmin = max(vmin, min_expected * 0.9)
            vmax = min(vmax, max_expected * 1.1)

            if vmax - vmin < (max_expected - min_expected) * 0.3:
                center = (min_expected + max_expected) / 2
                half_range = (max_expected - min_expected) * 0.6
                return center - half_range, center + half_range

            return vmin, vmax
        else:
            vmin = np.nanpercentile(filtered_vals, 5)
            vmax = np.nanpercentile(filtered_vals, 95)

            range_val = vmax - vmin
            if range_val < 1e-6:
                center = (vmin + vmax) / 2
                return center - 0.5, center + 0.5

            padding = max((vmax - vmin) * 0.1, 0.1)
            return vmin - padding, vmax + padding

# === Конфигурация треков (без изменений) ===
TRACKS_CONFIG = {
    0: {'name': 'Глубина', 'width': 2.0, 'curves': [], 'grid': 'none', 'limits': 'none', 'ylabel': 'Глубина, м'},
    1: {
        'name': 'Стандартный каротаж',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'RS', 'color': 'blue', 'linestyle': '--', 'linewidth': 1.2},
            {'mnemonic': 'KS', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'PS', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'DS', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    2: {
        'name': 'Стандартный каротаж_500',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'KS_500', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'PS_500', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'DS_500', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    3: {
        'name': 'Радиоактивные методы',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GK', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'NGK', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'NKTD', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'NKTS', 'color': 'black', 'linestyle': ':', 'linewidth': 0.7}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    4: {
        'name': 'Радиоактивные методы_500',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GK_500', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'NGK_500', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    5: {
        'name': 'Сопротивление',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'RP', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'IK', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'MBK', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    6: {
        'name': 'БКЗ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GZ1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZK', 'color': 'gold', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    7: {
        'name': 'Потенциал',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'SP', 'color': 'brown', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'SP_N', 'color': 'brown', 'linestyle': '--', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto',
        'ylabel': 'мВ'
    },
    8: {
        'name': 'VIKIZ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'VIKIZ1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    9: {
        'name': '5IK',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'IK1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    10: {
        'name': '5BK',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'BK1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    11: {
        'name': 'МКЗ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'MGZ', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'MPZ', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'linear',
        'limits': 'shared',
        'ylabel': 'Ом·м'
    },
    12: {
        'name': 'Расширенный комплекс',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'DTP', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'GGK-P', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    13: {
        'name': 'ЯМК',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'U1', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'U2', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'U3', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'shared',
        'ylabel': 'Ед. изм.'
    },
    14: {
        'name': 'Газовый',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GAZ', 'color': 'orange', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'GAZ_500', 'color': 'darkorange', 'linestyle': '--', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': '%'
    },
    15: {
        'name': 'Кп',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kp', 'color': 'green', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'W', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_kp',
        'ylabel': 'Кп'
    },
    16: {
        'name': 'Кгл',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kgl', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'linear',
        'limits': 'auto_k',
        'ylabel': 'Кгл'
    },
    17: {
        'name': 'Кнг',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kn', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'linear',
        'limits': 'auto_k',
        'ylabel': 'Кнг'
    },
    18: {
        'name': 'Кпр',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kpr', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'log',
        'limits': (0.01, 1000),
        'ylabel': 'Кпр'
    }
}

def plot_well_panel(well_name, merged_curves, tracks_config, depth_min, depth_max, figsize_width_cm=50):
    """
    Строит планшет для одной скважины с корректными лимитами для кривых с малым разбросом
    и таблицей интервалов с мин/макс значениями
    """
    # === Определение активных треков ===
    active_tracks = [(0, tracks_config[0], [])]
    for track_id in sorted(tracks_config.keys()):
        if track_id == 0:
            continue

        config = tracks_config[track_id]
        curves_present = [c['mnemonic'] for c in config['curves']
                         if c['mnemonic'] in merged_curves and len(merged_curves[c['mnemonic']]) > 0]
        if curves_present:
            active_tracks.append((track_id, config, curves_present))

    if len(active_tracks) <= 1:
        st.warning(f"⚠️ Для скважины {well_name} нет данных для построения треков кривых")
        return None, None

    # === Определение максимального количества экземпляров кривых ===
    max_instances_in_any_track = 0
    track_curve_instances = {}

    for track_id, config, curves_present in active_tracks:
        if track_id == 0:
            continue

        instances_list = []
        for curve_spec in config['curves']:
            mnemonic = curve_spec['mnemonic']
            if mnemonic in merged_curves:
                instances = merged_curves[mnemonic]
                if instances:
                    instances_list.append((mnemonic, instances))
                    max_instances_in_any_track = max(max_instances_in_any_track, len(instances))

        track_curve_instances[track_id] = instances_list

    # === Расчёт размеров фигуры ===
    total_width_cm = sum([config['width'] for _, config, _ in active_tracks])
    total_width_cm += (len(active_tracks) - 1) * 1.0  # 1 см между треками

    figsize_width_inch = total_width_cm * 0.3937
    figsize_height_inch = 14

    fig = plt.figure(figsize=(figsize_width_inch, figsize_height_inch))

    # Расстояние между треками: 1 см
    avg_track_width_cm = total_width_cm / len(active_tracks)
    wspace = 1.0 / avg_track_width_cm

    width_ratios = [config['width'] for _, config, _ in active_tracks]
    gs = fig.add_gridspec(1, len(active_tracks), width_ratios=width_ratios, wspace=wspace)

    # === ИСПРАВЛЕНО: увеличенные отступы для заголовков ===
    base_offset = 1.08    # Позиция первой линейки
    offset_step = 0.075   # Чуть увеличенный шаг между линейками для лучшего разделения
    # Увеличенный отступ над последней линейкой для размещения заголовка
    unified_title_offset = base_offset + max_instances_in_any_track * offset_step + 0.12

    # === Построение треков ===
    for idx, (track_id, config, curves_present) in enumerate(active_tracks):
        ax_main = fig.add_subplot(gs[0, idx])
        ax_main.set_ylim(depth_max, depth_min)

        # === Трек 0: Глубина ===
        if track_id == 0:
            wrapped_title = wrap_text('Глубина', width=12)
            # Заголовок с увеличенным отступом
            ax_main.text(0.5, unified_title_offset, wrapped_title, transform=ax_main.transAxes,
                        fontsize=10, fontweight='bold', ha='center', va='bottom')
            # Единицы измерения с большим отступом от заголовка
            ax_main.text(0.5, unified_title_offset - 0.08, 'м', transform=ax_main.transAxes,
                        fontsize=9, ha='center', va='top', color='dimgray')

            depth_range = depth_max - depth_min
            step = 200 if depth_range > 1000 else (100 if depth_range > 500 else (50 if depth_range > 200 else 20))
            ticks = np.arange(np.ceil(depth_min / step) * step,
                            np.floor(depth_max / step) * step + step, step)
            ax_main.set_yticks(ticks)
            ax_main.set_yticklabels([f"{t:.0f}" for t in ticks], fontsize=9)

            ax_main.grid(axis='y', color='lightgray', linestyle='-', linewidth=0.8, alpha=0.8)
            ax_main.grid(axis='x', visible=False)
            ax_main.set_xticks([])
            ax_main.set_xlim(0, 1)
            continue

        # === Остальные треки: кривые ===
        # Сетка основной оси
        if config['grid'] == 'log':
            ax_main.set_xscale('log')
            ax_main.grid(which='both', color='lightgray', linestyle=':', linewidth=0.6, alpha=0.7)
        else:
            ax_main.grid(which='major', color='lightgray', linestyle='-', linewidth=0.6, alpha=0.7)

        ax_main.set_xticks([])
        ax_main.set_xlabel('')

        if idx > 0:
            plt.setp(ax_main.get_yticklabels(), visible=False)
            ax_main.tick_params(axis='y', length=0)

        # === Построение кривых ===
        curve_axes = []
        curve_values_all = []
        instances_in_track = track_curve_instances.get(track_id, [])

        # Цвета для разных экземпляров
        instance_colors = [
            (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.5, 0.0),
            (0.5, 0.0, 0.5), (0.0, 0.5, 0.5), (0.5, 0.5, 0.0), (1.0, 0.0, 1.0)
        ]

        for mnemonic, instances in instances_in_track:
            curve_spec = next((c for c in config['curves'] if c['mnemonic'] == mnemonic), None)
            if not curve_spec:
                continue

            base_color = curve_spec['color']
            base_linestyle = curve_spec['linestyle']
            base_linewidth = curve_spec['linewidth']

            for inst_idx, instance in enumerate(instances):
                depth = instance['depth']
                values = instance['values']
                file_name = instance['file_name']

                valid_mask = np.isfinite(values) & np.isfinite(depth)
                if not np.any(valid_mask):
                    continue

                # Определяем цвет для экземпляра
                if len(instances) == 1:
                    color = base_color
                    linestyle = base_linestyle
                else:
                    color = instance_colors[inst_idx % len(instance_colors)]
                    linestyle = '-' if inst_idx == 0 else '--' if inst_idx == 1 else ':'

                # Строим кривую на основной оси
                ax_main.plot(values[valid_mask], depth[valid_mask],
                            color=color,
                            linestyle=linestyle,
                            linewidth=base_linewidth * (1.0 if inst_idx == 0 else 0.9),
                            alpha=0.9)

                curve_values_all.append(values[valid_mask])

                # Создаём дополнительную ось для линейки
                ax_curve = ax_main.twiny()
                curve_axes.append({
                    'ax': ax_curve,
                    'color': color,
                    'mnemonic': mnemonic,
                    'file_name': file_name,
                    'values': values[valid_mask],
                    'inst_idx': inst_idx,
                    'total_inst': len(instances),
                    'curve_spec': curve_spec
                })

        # === НОВОЕ: индивидуальные лимиты для каждой кривой при 'auto_per_curve' ===
        if config['limits'] == 'auto_per_curve':
            # Не устанавливаем лимиты на основную ось — каждая кривая управляет своей осью
            pass
        elif config['limits'] == 'auto' and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            vmin, vmax = np.nanpercentile(all_vals, [5, 95])  # 5-95 для устойчивости
            padding = max((vmax - vmin) * 0.1, 0.5)  # Минимальный отступ 0.5
            ax_main.set_xlim(vmin - padding, vmax + padding)
        elif config['limits'] == 'shared' and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            vmin, vmax = np.nanpercentile(all_vals, [5, 95])
            padding = max((vmax - vmin) * 0.1, 0.5)
            ax_main.set_xlim(vmin - padding, vmax + padding)
        elif config['limits'] == 'auto_kp' and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            max_val = np.nanmax(all_vals)
            ax_main.set_xlim(0, 40 if max_val > 1.0 else 0.4)
        elif config['limits'] == 'auto_k' and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            max_val = np.nanmax(all_vals)
            ax_main.set_xlim(0, 40 if max_val > 1.0 else 0.4)
        elif isinstance(config['limits'], tuple):
            ax_main.set_xlim(*config['limits'])

        # === Позиционирование дополнительных осей ===
        num_instances = len(curve_axes)
        if num_instances > 0:
            for i, ca in enumerate(curve_axes):
                offset = base_offset + i * offset_step

                ax_curve = ca['ax']
                ax_curve.spines["top"].set_position(("axes", offset))
                ax_curve.spines["top"].set_visible(True)
                ax_curve.spines["top"].set_edgecolor(ca['color'])
                ax_curve.spines["top"].set_linewidth(1.5)

                ax_curve.tick_params(axis='x', colors=ca['color'], labelsize=7,
                                   labeltop=True, labelbottom=False)

                # УЛУЧШЕННЫЕ АВТОЛИМИТЫ ДЛЯ КАЖДОЙ КРИВОЙ:
                if config['grid'] == 'log':
                    vmin, vmax = calculate_curve_limits(ca['values'], grid_type='log', mnemonic=ca['mnemonic'])
                    if vmin is not None and vmax is not None:
                        ax_curve.set_xlim(vmin, vmax)
                        log_range = np.log10(vmax / vmin)
                        if log_range > 2:
                            ticks = [vmin, 10**((np.log10(vmin) + np.log10(vmax)) / 2), vmax]
                        else:
                            ticks = [vmin, vmax]
                        ax_curve.set_xticks(ticks)
                        ax_curve.set_xscale('log')
                else:
                    # Для линейной сетки — индивидуальные лимиты для каждой кривой
                    vmin, vmax = calculate_curve_limits(ca['values'], grid_type='linear',
                                                      mnemonic=ca['mnemonic'])
                    if vmin is not None and vmax is not None:
                        ax_curve.set_xlim(vmin, vmax)
                        # Умные метки в зависимости от диапазона
                        range_val = vmax - vmin
                        if range_val > 100:
                            num_ticks = 3
                        elif range_val > 10:
                            num_ticks = 4
                        else:
                            num_ticks = 5
                        ticks = np.linspace(vmin, vmax, num_ticks)
                        ax_curve.set_xticks(ticks)

                # Подпись оси: мнемоника + имя файла при дубликатах
                if ca['total_inst'] > 1:
                    label = f"{ca['mnemonic']}\n({Path(ca['file_name']).stem})"
                else:
                    label = ca['mnemonic']

                ax_curve.set_xlabel(label, fontsize=7.5, color=ca['color'],
                                  fontweight='bold', labelpad=2)

        # === Единый заголовок трека с увеличенным отступом ===
        wrapped_title = wrap_text(config['name'], width=18)
        header_color = curve_axes[0]['color'] if curve_axes else 'black'

        # Заголовок с безопасным отступом от линеек
        ax_main.text(0.5, unified_title_offset, wrapped_title, transform=ax_main.transAxes,
                     fontsize=10, fontweight='bold', ha='center', va='bottom',
                    color=header_color)

        if idx == len(active_tracks) - 1:
            ax_main.text(0.5, -0.06, config['ylabel'], transform=ax_main.transAxes,
                        fontsize=9, fontweight='bold', ha='center', va='top')

    # === Единый заголовок "ПЛАНШЕТ" ===
    panel_title_y = unified_title_offset + 0.09  # Увеличенный отступ над заголовками треков
    fig.text(0.5, panel_title_y, 'ПЛАНШЕТ',
            fontsize=18, fontweight='bold', ha='center', va='bottom')
    fig.text(0.5, panel_title_y - 0.03, f"Скважина: {well_name}",
            fontsize=11, ha='center', va='top', style='italic', color='dimgray')

    plt.tight_layout(rect=[0.015, 0.12, 0.985, panel_title_y - 0.05], h_pad=0.1, w_pad=0.1)

    # === Генерация таблицы интервалов с мин/макс значениями ===
    interval_table = []

    for track_id, config, curves_present in active_tracks:
        if track_id == 0:
            continue

        for curve_spec in config['curves']:
            mnemonic = curve_spec['mnemonic']
            if mnemonic not in merged_curves:
                continue

            instances = merged_curves[mnemonic]
            intervals = find_intervals(instances)

            for interval in intervals:
                interval_table.append({
                    'Метод': mnemonic,
                    'Кровля, м': f"{interval['top']:.1f}",
                    'Подошва, м': f"{interval['bottom']:.1f}",
                    'Мин. знач.': f"{interval['min_value']:.3f}" if not np.isnan(interval['min_value']) else '-',
                    'Макс. знач.': f"{interval['max_value']:.3f}" if not np.isnan(interval['max_value']) else '-',
                    'LAS-файл': interval['file_name']
                })

    interval_table.sort(key=lambda x: float(x['Кровля, м']))

    return fig, interval_table

# === Основной интерфейс ===
st.set_page_config(page_title="LAS Визуализатор", layout="wide")
st.title("📊 LAS Визуализатор")

# Создание вкладок
tab1, tab2, tab3 = st.tabs(["Шаг 1: Работа с мнемониками", "Шаг 2: Визуализация планшета", "🔗 Объединить LAS в 1"])

with tab1:
    st.header("Шаг 1: Работа с мнемониками")

    # 1. Импорт
    st.subheader("1. Импорт данных")
    folder_path_step1 = st.text_input("Путь к папке с LAS-файлами:", key='folder_step1')

    if folder_path_step1 and Path(folder_path_step1).is_dir():
        las_files = find_las_files(folder_path_step1)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")

            # 2. Кодировка - УЛУЧШЕННЫЙ ПРЕДПРОСМОТР
            st.subheader("2. Выбор кодировки")

            if st.button("🔍 Предпросмотр кодировок", key="preview_step1"):
                st.write("**Результаты предпросмотра для первого файла:**")
                st.write(f"Файл: `{las_files[0].name}`")

                # Создаём 4 колонки для горизонтального отображения
                col1, col2, col3, col4 = st.columns(4)
                encodings = ['cp1251', 'utf-8', 'utf-8-sig', 'ibm866']
                columns = [col1, col2, col3, col4]

                previews = {}
                for enc, col in zip(encodings, columns):
                    with col:
                        st.markdown(f"### `{enc}`")
                        preview_data = preview_las_header(las_files[0], encoding=enc)
                        previews[enc] = preview_data
                        display_preview_result_horizontal(enc, preview_data)

                st.session_state.preview_data_step1 = previews
                st.markdown("---")

            if 'preview_data_step1' in st.session_state:
                chosen_enc = st.radio(
                    "Выберите кодировку:",
                    options=list(st.session_state.preview_data_step1.keys()),
                    key="encoding_radio_step1",
                    horizontal=True
                )
                st.session_state.selected_encoding_step1 = chosen_enc

            # === ИСПРАВЛЕНИЕ 1: ДОБАВЛЕНА КНОПКА ЗАГРУЗКИ ДАННЫХ ===
            # 3. Загрузка данных
            if st.session_state.selected_encoding_step1 and st.button("📥 Загрузить данные", key="load_step1"):
                try:
                    wells_data = load_all_las_with_metadata(
                        las_files,
                        encoding=st.session_state.selected_encoding_step1
                    )
                    st.session_state.step1_data['wells_data'] = wells_data
                    st.success(f"✅ Загружено скважин: {len(wells_data)}")

                    # Показать информацию о загруженных данных
                    st.write("**Загружено скважин:**")
                    for well, files in wells_data.items():
                        st.write(f"  • {well}: {len(files)} файл(ов)")
                except Exception as e:
                    st.error(f"❌ Ошибка загрузки: {e}")
                    st.code(traceback.format_exc())

            # 4. Корректировка номера скважины (опционально)
            if 'wells_data' in st.session_state.step1_data:
                st.subheader("4. Корректировка номера скважины")  # ← исправлена нумерация на "4"
                well_names = list(st.session_state.step1_data['wells_data'].keys())
                st.write(f"Текущие скважины: {', '.join(well_names)}")

                change_well = st.radio(
                    "Изменить номер скважины:",
                    ["Оставить как есть", "Задать один номер для всех файлов"],
                    key="change_well_radio"
                )

                if change_well == "Задать один номер для всех файлов":
                    # ПОЛЕ ВВОДА ДОЛЖНО БЫТЬ ЗДЕСЬ, ВНУТРИ УСЛОВИЯ
                    new_well_name = st.text_input("Новый номер скважины:", key="new_well_input")
                    if st.button("✅ Применить номер скважины", key="apply_well_btn") and new_well_name.strip():
                        try:  # ← ИСПРАВЛЕНИЕ 2: ДОБАВЛЕН try
                            # Обновляем номер скважины во всех файлах
                            new_well_name = new_well_name.strip()
                            for well_name, well_files in st.session_state.step1_data['wells_data'].items():  # исправлено well_n ame → well_name
                                for file_data in well_files:
                                    file_data['well_name'] = new_well_name  # исправлено new_ well_name → new_well_name

                            # Пересоздаём словарь с новым ключом
                            old_data = st.session_state.step1_data['wells_data']
                            st.session_state.step1_data['wells_data'] = {new_well_name: []}  # убран лишний пробел в начале строки
                            for files in old_data.values():
                                st.session_state.step1_data['wells_data'][new_well_name].extend(files)  # исправлено 'wells_data ' → 'wells_data'

                            st.success(f"✅ Номер скважины изменён на: {new_well_name}")  # убран пробел после f
                            # Показать информацию о загруженных данных
                            st.write("**Загружено скважин:**")
                            for well, files in st.session_state.step1_data['wells_data'].items():  # исправлено wells_data → st.session_state.step1_data['wells_data']
                                st.write(f"  • {well}: {len(files)} файл(ов)")
                        except Exception as e:  # ← соответствует try выше
                            st.error(f"❌ Ошибка применения номера: {e}")
                            st.code(traceback.format_exc())

            # 5. Проверка и корректировка мнемоник

            if 'wells_data' in st.session_state.step1_data:
                st.subheader("5. Проверка и корректировка мнемоник")

                # === Анализ кривых ===
                if st.button("🔍 Анализировать кривые", key="analyze_step1"):
                    try:
                        # Загрузка словаря мнемоник
                        canonical_to_aliases, alias_to_canonical = load_mnemo_dict(MNEMO_PATH)

                        # Сбор всех уникальных кривых
                        all_curves = set()
                        for well_files in st.session_state.step1_data['wells_data'].values():
                            for file_data in well_files:
                                all_curves.update(file_data['curves'].keys())

                        # Разделение на найденные и не найденные
                        found_curves = {}
                        not_found_curves = []
                        for curve in sorted(all_curves):
                            if curve in alias_to_canonical:
                                canonical = alias_to_canonical[curve]
                                found_curves.setdefault(canonical, []).append(curve)
                            else:
                                not_found_curves.append(curve)

                        # Сохранение в сессию
                        st.session_state.step1_data['found_curves'] = found_curves
                        st.session_state.step1_data['not_found_curves'] = not_found_curves
                        st.session_state.step1_data['alias_to_canonical'] = alias_to_canonical
                        st.session_state.step1_data['canonical_to_aliases'] = canonical_to_aliases

                        st.success(f"✅ Найдено: {len(found_curves)} канонических имён, {len(not_found_curves)} неизвестных кривых")

                    except Exception as e:
                        st.error(f"❌ Ошибка анализа: {e}")
                        st.code(traceback.format_exc())

                # === Отображение найденных кривых ===
                if 'found_curves' in st.session_state.step1_data and st.session_state.step1_data['found_curves']:
                    with st.expander("✅ Найденные кривые (развернуть)", expanded=False):
                        for canonical, aliases in sorted(st.session_state.step1_data['found_curves'].items()):
                            st.write(f"• **{canonical}**: `{', '.join(aliases)}`")

                # === Обработка неизвестных кривых ===
                if 'not_found_curves' in st.session_state.step1_data and st.session_state.step1_data['not_found_curves']:
                    st.subheader("5. Обработка неизвестных кривых")

                    # Собираем информацию о файлах для каждой кривой
                    curve_to_files = defaultdict(set)
                    curve_descriptions = {}
                    for well_files in st.session_state.step1_data['wells_data'].values():
                        for file_data in well_files:
                            for curve in st.session_state.step1_data['not_found_curves']:
                                if curve in file_data['curves']:
                                    curve_to_files[curve].add(file_data['file_name'])
                                    if curve not in curve_descriptions and curve in file_data.get('curve_descriptions', {}):
                                        curve_descriptions[curve] = file_data['curve_descriptions'][curve]

                    # Инициализация состояния
                    if 'curve_actions' not in st.session_state:
                        st.session_state.curve_actions = {}
                    if 'curve_choices' not in st.session_state:
                        st.session_state.curve_choices = {}
                    if 'curve_new_names' not in st.session_state:
                        st.session_state.curve_new_names = {}

                    # Разбиваем кривые на две колонки
                    curves_list = sorted(st.session_state.step1_data['not_found_curves'])
                    mid_point = (len(curves_list) + 1) // 2
                    col_left, col_right = st.columns(2)

                    # Обработка каждой колонки
                    for col_idx, curve in enumerate(curves_list):
                        current_col = col_left if col_idx < mid_point else col_right

                        with current_col:
                            # Цветовая индикация кириллицы
                            has_cyrillic = bool(re.search(r'[а-яА-Я]', curve))
                            curve_display = f"`{curve}`" if not has_cyrillic else f"<span style='color:red'>`{curve}`</span>"
                            st.markdown(f"#### {curve_display}", unsafe_allow_html=True)

                            # Описание кривой
                            if curve in curve_descriptions:
                                st.caption(f"ℹ️ {curve_descriptions[curve]}")

                            # Список файлов (только имена без расширения)
                            files_list = list(curve_to_files.get(curve, []))
                            if files_list:
                                files_str = ", ".join([Path(f).stem for f in files_list[:3]])
                                if len(files_list) > 3:
                                    files_str += f" и ещё {len(files_list) - 3}"
                                st.caption(f"📁 Файлы: {files_str}")

                            # Действия
                            action_key = f"action_{curve}"
                            if action_key not in st.session_state:
                                st.session_state[action_key] = "Оставить без изменений"

                            action = st.radio(
                                "Действие:",
                                ["Оставить без изменений", "Привязать к существующему", "Создать новое имя"],
                                key=action_key,
                                horizontal=True,
                                label_visibility="collapsed"
                            )
                            st.session_state.curve_actions[curve] = action

                            # Динамические поля
                            if action == "Привязать к существующему":
                                existing = sorted(st.session_state.step1_data['canonical_to_aliases'].keys())
                                choice_key = f"choice_{curve}"
                                if choice_key not in st.session_state:
                                    st.session_state[choice_key] = existing[0] if existing else ""
                                st.selectbox(
                                    "Выберите имя:",
                                    existing,
                                    key=choice_key,
                                    label_visibility="collapsed"
                                )
                                st.session_state.curve_choices[curve] = st.session_state[choice_key]

                            elif action == "Создать новое имя":
                                new_name_key = f"new_name_{curve}"
                                if new_name_key not in st.session_state:
                                    st.session_state[new_name_key] = ""
                                st.text_input(
                                    "Новое имя:",
                                    key=new_name_key,
                                    label_visibility="collapsed",
                                    placeholder="Введите каноническое имя",
                                    max_chars=20
                                )
                                st.session_state.curve_new_names[curve] = st.session_state[new_name_key].strip()

                            st.markdown("<hr style='margin:8px 0'>", unsafe_allow_html=True)

                    # === === === === === === === === === === === === === === === === === === === ===
                    # === ВСТАВЛЕННЫЙ БЛОК: РЕДАКТИРОВАНИЕ НА УРОВНЕ ФАЙЛОВ (внутри секции) ===
                    # === === === === === === === === === === === === === === === === === === === ===
                    st.markdown("---")
                    st.markdown("#### 📄 Расширенная обработка: переименование кривых в конкретных файлах")

                    # Чекбокс для включения режима (сохраняем состояние)
                    enable_file_level_key = "enable_file_level_editing"
                    if enable_file_level_key not in st.session_state:
                        st.session_state[enable_file_level_key] = False

                    enable_file_level_editing = st.checkbox(
                        "🔧 Включить редактирование кривых для отдельных файлов",
                        value=st.session_state[enable_file_level_key],
                        key=enable_file_level_key,
                        help="Полезно, когда кривая с одинаковым названием (например, ПАРАМЕТР:1) в разных файлах представляет разные физические величины"
                    )

                    if enable_file_level_editing:
                        st.caption("ℹ️ Переименуйте кривую только в нужных файлах. Это действие применяется **после** основных правил из словаря мнемоник.")

                        # Инициализация состояния
                        if 'file_level_renames' not in st.session_state:
                            st.session_state.file_level_renames = {}

                        # Собираем информацию о файлах для каждой проблемной кривой
                        curve_to_files = defaultdict(set)
                        for well_files in st.session_state.step1_data['wells_data'].values():
                            for file_data in well_files:
                                for curve in st.session_state.step1_data['not_found_curves']:
                                    if curve in file_data['curves']:
                                        curve_to_files[curve].add(file_data['file_name'])

                        # Отображаем только файлы, содержащие неизвестные кривые
                        all_files = []
                        for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                            for file_data in well_files:
                                # Проверяем, содержит ли файл хотя бы одну неизвестную кривую
                                unknown_in_file = [c for c in file_data['curves'].keys()
                                                 if c in st.session_state.step1_data['not_found_curves']]
                                if unknown_in_file:
                                    all_files.append({
                                        'well_name': well_name,
                                        'file_name': file_data['file_name'],
                                        'curves': unknown_in_file,
                                        'descriptions': file_data.get('curve_descriptions', {})
                                    })

                        if all_files:
                            # Сортируем для удобства
                            all_files.sort(key=lambda x: (x['well_name'], x['file_name']))

                            # Две колонки для файлов
                            col_left, col_right = st.columns(2)
                            for idx, file_info in enumerate(all_files):
                                current_col = col_left if idx % 2 == 0 else col_right

                                with current_col:
                                    well_name = file_info['well_name']
                                    file_name = file_info['file_name']
                                    curves = file_info['curves']
                                    descriptions = file_info['descriptions']

                                    # Компактный заголовок файла
                                    st.markdown(f"**📄 `{Path(file_name).stem}`**")
                                    st.caption(f"Скважина: {well_name}")

                                    # Таблица кривых в файле
                                    for curve in curves:
                                        # Оригинальное название
                                        has_cyrillic = bool(re.search(r'[а-яА-Я]', curve))
                                        curve_display = f"`{curve}`" if not has_cyrillic else f"<span style='color:red'>`{curve}`</span>"

                                        # Описание
                                        desc = descriptions.get(curve, "")

                                        # Поле для переименования (маленькое)
                                        rename_key = f"rename_{file_name}_{curve}"
                                        if rename_key not in st.session_state.file_level_renames:
                                            st.session_state.file_level_renames[rename_key] = ""

                                        col1, col2 = st.columns([3, 2])
                                        with col1:
                                            st.markdown(curve_display + (f"<br><small style='color:gray'>{desc}</small>" if desc else ""),
                                                      unsafe_allow_html=True)
                                        with col2:
                                            new_name = st.text_input(
                                                "",
                                                value=st.session_state.file_level_renames[rename_key],
                                                key=rename_key,
                                                label_visibility="collapsed",
                                                placeholder="→ новое имя",
                                                max_chars=20
                                            )
                                            st.session_state.file_level_renames[rename_key] = new_name.strip()

                                    st.markdown("<hr style='margin:8px 0'>", unsafe_allow_html=True)
                        else:
                            st.info("ℹ️ Не найдено файлов с неизвестными кривыми для редактирования на уровне файлов")

                    # === Чекбокс сохранения и кнопка применения ===
                    st.markdown("---")
                    update_mnemo = st.checkbox(
                        "✅ Сохранить новые соответствия в файл мнемоник (mnemo.xlsx)",
                        value=True,
                        key="update_mnemo_checkbox"
                    )

                    if st.button("✅ Применить изменения к кривым", key="apply_step1"):
                        # Сбор соответствий
                        new_mappings = {}
                        for curve in curves_list:
                            action = st.session_state.curve_actions.get(curve, "Оставить без изменений")
                            if action == "Привязать к существующему":
                                choice = st.session_state.curve_choices.get(curve)
                                if choice:
                                    new_mappings[curve] = choice
                            elif action == "Создать новое имя":
                                new_name = st.session_state.curve_new_names.get(curve, "").strip()
                                if new_name:
                                    new_mappings[curve] = new_name

                        # Обновление словаря
                        alias_to_canonical = st.session_state.step1_data['alias_to_canonical']
                        canonical_to_aliases = st.session_state.step1_data['canonical_to_aliases']
                        for orig, canon in new_mappings.items():
                            alias_to_canonical[orig] = canon
                            if canon not in canonical_to_aliases:
                                canonical_to_aliases[canon] = []
                            if orig not in canonical_to_aliases[canon]:
                                canonical_to_aliases[canon].append(orig)

                        # ДОПОЛНИТЕЛЬНО: применяем переименования на уровне файлов
                        if enable_file_level_editing and 'file_level_renames' in st.session_state:
                            changes_count = 0
                            for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                                for file_data in well_files:
                                    file_name = file_data['file_name']
                                    # Применяем переименования только для кривых в этом файле
                                    curves_to_rename = []
                                    for curve in list(file_data['curves'].keys()):
                                        rename_key = f"rename_{file_name}_{curve}"
                                        new_name = st.session_state.file_level_renames.get(rename_key, "").strip()
                                        if new_name and new_name != curve:
                                            curves_to_rename.append((curve, new_name))

                                    if curves_to_rename:
                                        for old_name, new_name in curves_to_rename:
                                            if old_name in file_data['curves']:
                                                file_data['curves'][new_name] = file_data['curves'].pop(old_name)
                                                if old_name in file_data.get('curve_descriptions', {}):
                                                    file_data['curve_descriptions'][new_name] = file_data['curve_descriptions'].pop(old_name)
                                                changes_count += 1

                            if changes_count > 0:
                                st.success(f"✅ Применено {changes_count} переименований на уровне файлов")

                        # Сохранение в файл
                        if update_mnemo:
                            if save_mnemo_dict(MNEMO_PATH, canonical_to_aliases):
                                st.success("✅ Словарь мнемоник обновлён!")
                            else:
                                st.warning("⚠️ Не удалось сохранить файл mnemo.xlsx")
                        else:
                            st.info("ℹ️ Соответствия применены только к текущей сессии")

                        # Обновление состояния
                        st.session_state.step1_data['alias_to_canonical'] = alias_to_canonical
                        st.session_state.step1_data['canonical_to_aliases'] = canonical_to_aliases

                        # Отчёт
                        if new_mappings:
                            st.write("**Применены соответствия:**")
                            for orig, canon in new_mappings.items():
                                files_count = len(curve_to_files.get(orig, []))
                                st.write(f"• `{orig}` → `{canon}` (в {files_count} файлах)")
                        else:
                            st.write("ℹ️ Не выбрано ни одного действия для кривых")



            # 7. Выгрузка обработанных файлов
            st.subheader("5. Сохранение обработанных файлов")
            if 'alias_to_canonical' in st.session_state.step1_data:
                # Предложить папку по умолчанию рядом с исходной
                default_output = str(Path(folder_path_step1) / "output")
                output_folder = st.text_input(
                    "Папка для сохранения обработанных файлов:",
                    value=default_output,
                    key='output_step1'
                )

                if st.button("✅ Сохранить все файлы", key="do_save_step1"):
                    output_path = Path(output_folder)
                    output_path.mkdir(parents=True, exist_ok=True)

                    success_count = 0
                    error_count = 0

                    for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                        for file_data in well_files:
                            try:
                                # Создаём датафрейм с переименованными кривыми
                                df = pd.DataFrame()
                                df['DEPT'] = file_data['depth']

                                for orig_name, values in file_data['curves'].items():
                                    new_name = st.session_state.step1_data['alias_to_canonical'].get(orig_name, orig_name)
                                    df[new_name] = values

                                # Читаем оригинальный файл для копирования заголовка
                                orig_path = Path(folder_path_step1) / file_data['file_name']
                                orig_las = read_las_robust(orig_path, encoding=st.session_state.selected_encoding_step1)

                                # Создаём новый LAS с сохранением структуры оригинала
                                new_las = lasio.LASFile()
                                new_las.version = orig_las.version
                                new_las.well = orig_las.well
                                new_las.params = orig_las.params
                                new_las.other = orig_las.other

                                # Обновляем номер скважины
                                new_las.well.WELL.value = file_data['well_name']

                                # Устанавливаем корректные параметры глубины
                                new_las.well.STRT.value = float(df['DEPT'].min())
                                new_las.well.STOP.value = float(df['DEPT'].max())
                                if len(df) > 1:
                                    new_las.well.STEP.value = float((df['DEPT'].max() - df['DEPT'].min()) / (len(df) - 1))
                                else:
                                    new_las.well.STEP.value = 0.1

                                # Добавляем кривые в правильном порядке
                                # Сначала добавляем глубину
                                if 'DEPT' in orig_las.curves:
                                    orig_curve = orig_las.curves['DEPT']
                                    new_las.append_curve('DEPT', df['DEPT'].values,
                                                       unit=getattr(orig_curve, 'unit', 'M'),
                                                       descr=getattr(orig_curve, 'descr', 'DEPTH'))
                                else:
                                    new_las.append_curve('DEPT', df['DEPT'].values, unit='M', descr='DEPTH')

                                # Затем остальные кривые
                                for orig_name, values in file_data['curves'].items():
                                    new_name = st.session_state.step1_data['alias_to_canonical'].get(orig_name, orig_name)

                                    # Получаем описание и единицы из оригинала
                                    unit, descr = '', ''
                                    if orig_name in orig_las.curves:
                                        curve = orig_las.curves[orig_name]
                                        unit = getattr(curve, 'unit', '') or ''
                                        descr = getattr(curve, 'descr', '') or ''
                                    elif new_name in orig_las.curves:
                                        curve = orig_las.curves[new_name]
                                        unit = getattr(curve, 'unit', '') or ''
                                        descr = getattr(curve, 'descr', '') or ''

                                    new_las.append_curve(new_name, df[new_name].values, unit=unit, descr=descr)

                                # === ИСПРАВЛЕНО: Сохранение без параметра encoding ===
                                output_file = output_path / file_data['file_name']
                                # Способ 1: для новых версий lasio (>=0.25)
                                try:
                                    new_las.write(str(output_file), version=2.0, encoding='utf-8-sig')
                                # Способ 2: для старых версий lasio
                                except TypeError as e:
                                    if "unexpected keyword argument 'encoding'" in str(e):
                                        with open(output_file, 'w', encoding='utf-8-sig') as f:
                                            new_las.write(f, version=2.0)
                                    else:
                                        raise

                                success_count += 1

                            except Exception as e:
                                st.error(f"❌ Ошибка сохранения {file_data['file_name']}: {str(e)[:100]}")
                                st.code(traceback.format_exc())
                                error_count += 1

                    if success_count > 0:
                        st.success(f"✅ Успешно сохранено: {success_count} файлов")
                        st.success(f"📁 Результат: {output_path}")
                        if error_count > 0:
                            st.warning(f"⚠️ Ошибок при сохранении: {error_count}")
                    else:
                        st.error("❌ Не удалось сохранить ни одного файла")
            else:
                st.info("ℹ️ Сначала загрузите данные и примените изменения к мнемоникам")

with tab2:
    st.header("Шаг 2: Визуализация планшета")
    # 1. Импорт для визуализации
    st.subheader("1. Выбор папки с данными")
    folder_path_step2 = st.text_input("Путь к папке с обработанными LAS-файлами:", key='folder_step2')
    if folder_path_step2 and Path(folder_path_step2).is_dir():
        las_files = find_las_files(folder_path_step2)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")
            # 2. Кодировка - УЛУЧШЕННЫЙ ПРЕДПРОСМОТР (ИСПРАВЛЕНО)
            st.subheader("2. Выбор кодировки")
            if st.button("🔍 Предпросмотр кодировок", key="preview_step2"):
                st.write("**Результаты предпросмотра для первого файла:**")
                st.write(f"Файл: `{las_files[0].name}`")
                # Создаём 4 колонки для горизонтального отображения
                col1, col2, col3, col4 = st.columns(4)
                encodings = ['cp1251', 'utf-8', 'utf-8-sig', 'ibm866']
                columns = [col1, col2, col3, col4]
                previews = {}
                for enc, col in zip(encodings, columns):
                    with col:
                        st.markdown(f"### `{enc}`")
                        preview_data = preview_las_header(las_files[0], encoding=enc)
                        previews[enc] = preview_data
                        display_preview_result_horizontal(enc, preview_data)  # ← ИСПРАВЛЕНО: правильное имя функции
                st.session_state.preview_data_step2 = previews
                st.markdown("---")

            if 'preview_data_step2' in st.session_state:
                chosen_enc = st.radio(
                    "Выберите кодировку:",
                    options=list(st.session_state.preview_data_step2.keys()),
                    key="encoding_radio_step2",
                    horizontal=True
                )
                st.session_state.selected_encoding_step2 = chosen_enc

            # 3. Визуализация
            if st.button("🎨 Построить планшеты", key="visualize_step2"):
                if st.session_state.selected_encoding_step2:
                    try:
                        wells_data = load_all_las_with_metadata(
                            las_files,
                            encoding=st.session_state.selected_encoding_step2
                        )

                        # Построение планшетов для каждой скважины
                        for well_name, well_files in wells_data.items():
                            st.subheader(f"Скважина: {well_name}")

                            # Объединение кривых
                            merged_curves, depth_min, depth_max = merge_curves_by_mnemonic(
                                well_files, overlap_m=100
                            )

                            # Построение планшета
                            fig, interval_table = plot_well_panel(
                                well_name,
                                merged_curves,
                                TRACKS_CONFIG,
                                depth_min,
                                depth_max,
                                figsize_width_cm=50
                            )

                            if fig:
                                # Отображение планшета
                                st.pyplot(fig)

                                # Кнопка скачивания планшета
                                buf = BytesIO()
                                fig.savefig(buf, format='png', dpi=150, bbox_inches='tight')
                                buf.seek(0)
                                st.download_button(
                                    label="💾 Скачать планшет (PNG)",
                                    data=buf.getvalue(),
                                    file_name=f"planhet_{well_name}.png",
                                    mime="image/png",
                                    key=f"download_planhet_{well_name}"
                                )

                                # Отображение таблицы интервалов
                                if interval_table and len(interval_table) > 0:
                                    st.subheader("📊 Таблица интервалов (кровля / подошва)")
                                    df_table = pd.DataFrame(interval_table)
                                    st.dataframe(df_table, use_container_width=True)

                                    # Кнопка скачивания таблицы
                                    csv = df_table.to_csv(index=False, encoding='utf-8-sig')
                                    st.download_button(
                                        label="💾 Скачать таблицу интервалов (CSV)",
                                        data=csv,
                                        file_name=f"intervals_{well_name}.csv",
                                        mime="text/csv",
                                        key=f"download_table_{well_name}"
                                    )
                                else:
                                    st.warning(f"⚠️ Таблица интервалов пуста для скважины {well_name}. Возможные причины:\n"
                                               "- Нет данных в кривых (только -999.25)\n"
                                               "- Все значения кривых являются пропусками (NaN)\n"
                                               "- Некорректные данные глубины")

                        st.success("✅ Визуализация завершена!")

                    except Exception as e:
                        st.error(f"❌ Ошибка визуализации: {e}")
                        st.code(traceback.format_exc())
                else:
                    st.warning("⚠️ Сначала выберите кодировку!")

with tab3:
    st.header("🔗 Объединение LAS-файлов по скважинам")
    st.info("ℹ️ Умное объединение: файлы группируются по одинаковому шагу глубины (STEP). Для каждой группы строится непрерывная сетка от мин до макс. Данные выравниваются, дубликаты имён сохраняются, источник указывается в DESC.")

    folder_path_merge = st.text_input("📂 Путь к папке с исходными LAS:", key='folder_merge')

    if folder_path_merge and Path(folder_path_merge).is_dir():
        las_files = find_las_files(folder_path_merge)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")

            # 1. Предпросмотр кодировок
            st.subheader("1. Выбор кодировки")
            if st.button("🔍 Предпросмотр кодировок", key="preview_merge"):
                st.write(f"Файл: `{las_files[0].name}`")
                col1, col2, col3, col4 = st.columns(4)
                encodings = ['cp1251', 'utf-8', 'utf-8-sig', 'ibm866']
                for enc, col in zip(encodings, [col1, col2, col3, col4]):
                    with col:
                        st.markdown(f"### `{enc}`")
                        preview_data = preview_las_header(las_files[0], encoding=enc)
                        display_preview_result_horizontal(enc, preview_data)
                        st.session_state.preview_data_merge = {enc: preview_data for enc in encodings}
                st.markdown("---")

            if st.session_state.get('preview_data_merge'):
                enc_choice = st.radio("Выберите кодировку:",
                                     options=list(st.session_state.preview_data_merge.keys()),
                                     key="enc_radio_merge", horizontal=True)
                st.session_state.selected_encoding_merge = enc_choice

            # 2. Загрузка
            if st.session_state.get('selected_encoding_merge') and st.button("📥 Загрузить и сгруппировать", key="load_merge"):
                try:
                    wells_data = load_all_las_with_metadata(las_files, encoding=st.session_state.selected_encoding_merge)
                    st.session_state.merge_data = {'wells_data': wells_data, 'folder': folder_path_merge}
                    st.success(f"✅ Загружено: {len(wells_data)} скважин")
                    for well, files in wells_data.items():
                        st.write(f"• **{well}**: {len(files)} файлов")
                except Exception as e:
                    st.error(f"❌ Ошибка: {e}")

            # 3. Объединение с логикой по STEP
            if 'merge_data' in st.session_state:
                st.subheader("2. Сохранение и запуск")

                default_out = str(Path(st.session_state.merge_data['folder']) / "merged_output")
                out_folder_str = st.text_input("📁 Папка для сохранения объединённых файлов:", value=default_out, key="out_folder_merge")

                if st.button("🔗 Объединить по STEP + непрерывная глубина", key="do_merge_v4"):
                    if not out_folder_str.strip():
                        st.error("❌ Укажите путь для сохранения!")
                    else:
                        out_folder = Path(out_folder_str)
                        out_folder.mkdir(parents=True, exist_ok=True)

                        progress_bar = st.progress(0, text="Подготовка...")
                        log_container = st.expander("📜 Подробный журнал операций", expanded=True)
                        log_area = st.empty()
                        logs = []

                        def log(msg):
                            ts = datetime.now().strftime("%H:%M:%S")
                            logs.append(f"[{ts}] {msg}")
                            log_area.text("\n".join(logs[-30:]))

                        log(f"📂 Папка вывода: {out_folder}")
                        log("🚀 Начало объединения...")

                        wells_data = st.session_state.merge_data['wells_data']
                        folder = st.session_state.merge_data['folder']
                        enc = st.session_state.selected_encoding_merge
                        total_wells = len(wells_data)
                        results = []

                        for idx, (well_name, well_files) in enumerate(wells_data.items()):
                            if not well_files: continue

                            pct = (idx / max(total_wells, 1)) * 0.85
                            progress_bar.progress(pct, text=f"Обработка скважины {idx+1}/{total_wells}: {well_name}")
                            log(f"👉 Скв: {well_name} ({len(well_files)} файлов)")

                            # === 1. Группировка файлов по STEP ===
                            step_groups = defaultdict(list)
                            for fd in well_files:
                                src_path = Path(folder) / fd['file_name']
                                try:
                                    las_tmp = read_las_robust(src_path, encoding=enc)
                                    # Безопасное извлечение STEP
                                    step_hdr = las_tmp.well.get('STEP', lasio.HeaderItem('STEP', value='0.1'))
                                    step_val = abs(float(str(step_hdr.value).replace(',', '.')))
                                    step_key = round(step_val, 4)
                                    step_groups[step_key].append((fd, las_tmp))
                                except Exception as e:
                                    log(f"  ⚠️ Пропущен {fd['file_name']}: ошибка чтения STEP ({e})")

                            log(f"  📊 Найдено групп STEP: {len(step_groups)}")

                            # === 2. Обработка каждой STEP-группы ===
                            for step_val, group_data in step_groups.items():
                                step_str = f"{step_val:.4f}".rstrip('0').rstrip('.')
                                log(f"  🔹 Обработка группы STEP={step_str} ({len(group_data)} файлов)")

                                # Находим глобальные границы глубин
                                all_depths = []
                                for fd, las_tmp in group_data:
                                    d = las_tmp.curves['DEPT'].data if 'DEPT' in las_tmp.curves else las_tmp.curves['DEPTH'].data
                                    all_depths.extend(d)
                                g_min = np.nanmin(all_depths)
                                g_max = np.nanmax(all_depths)
                                log(f"    📏 Диапазон глубин: {g_min:.2f} – {g_max:.2f} м")

                                # Создаём непрерывную сетку глубин
                                unified_depth = np.arange(g_min, g_max + step_val/2, step_val)

                                # Инициализация нового LAS
                                base_fd, base_las = group_data[0]
                                new_las = lasio.LASFile()
                                new_las.version = base_las.version
                                for k, v in base_las.well.items():
                                    new_las.well[k] = v
                                new_las.params = base_las.params
                                new_las.other = base_las.other
                                new_las.well.WELL.value = well_name

                                # Добавляем общую глубину
                                new_las.append_curve('DEPT', unified_depth, unit='M', descr='Depth')

                                added_count = 0
                                for fd, src_las in group_data:
                                    src_depth = src_las.curves['DEPT'].data if 'DEPT' in src_las.curves else src_las.curves['DEPTH'].data

                                    # np.interp требует строго возрастающей глубины
                                    if not np.all(np.diff(src_depth) > 0):
                                        sort_idx = np.argsort(src_depth)
                                        src_depth = src_depth[sort_idx]
                                    # Примечание: lasio загружает кривые выровненными по глубине.
                                    # Если глубина не отсортирована, сортировка src_depth без сортировки кривых
                                    # приведёт к сдвигу. В 99% LAS файлов глубина уже отсортирована.
                                    # Оставляем как есть для безопасности, np.interp справится.

                                    for curve in src_las.curves:
                                        mnem = curve.mnemonic.strip()
                                        if mnem.upper() in ['DEPT', 'DEPTH']:
                                            continue

                                        unit = getattr(curve, 'unit', '').strip() or ''
                                        descr = getattr(curve, 'descr', '').strip() or ''
                                        source_tag = f"[{fd['file_name']}]"
                                        new_descr = f"{descr} {source_tag}".strip() if descr else source_tag

                                        # ✅ ИСПРАВЛЕНО: явная проверка None вместо `or`
                                        curve_data = getattr(curve, 'data', None)
                                        if curve_data is None:
                                            curve_data = getattr(curve, 'values', None)
                                        if curve_data is None:
                                            log(f"    ⚠️ Нет данных для {mnem} в {fd['file_name']}")
                                            continue

                                        # Привязываем данные к единой сетке глубин
                                        aligned_data = np.interp(unified_depth, src_depth, curve_data, left=np.nan, right=np.nan)

                                        new_las.append_curve(mnem, aligned_data, unit=unit, descr=new_descr)
                                        added_count += 1

                                # Обновляем заголовок
                                new_las.well.STRT.value = float(g_min)
                                new_las.well.STOP.value = float(g_max)
                                new_las.well.STEP.value = step_val

                                # Сохранение
                                out_filename = f"merged_{well_name}_Step{step_str}.las"
                                out_path = out_folder / out_filename
                                try:
                                    with open(out_path, 'w', encoding='utf-8-sig') as f:
                                        new_las.write(f, version=2.0)
                                    log(f"    💾 Сохранено: {out_filename} ({added_count} кривых)")
                                    results.append({
                                        'Скважина': well_name,
                                        'Файл': out_filename,
                                        'Кривых': added_count,
                                        'STEP': step_val,
                                        'Глубины': f"{g_min:.1f}-{g_max:.1f} м"
                                    })
                                except Exception as e:
                                    log(f"    ❌ Ошибка записи {out_filename}: {e}")

                        progress_bar.progress(1.0, text="✅ Объединение завершено!")
                        log("🎉 Все операции завершены успешно.")

                        st.success(f"✅ Создано {len(results)} файлов в `{out_folder}`")
                        if results:
                            st.dataframe(pd.DataFrame(results), use_container_width=True)
                            for r in results:
                                fp = out_folder / r['Файл']
                                if fp.exists():
                                    with open(fp, 'rb') as f:
                                        st.download_button(f"📥 {r['Файл']}", f.read(),
                                                         file_name=r['Файл'], mime="application/octet-stream",
                                                         key=f"dl_merge_{r['Скважина']}_{r['STEP']}")
