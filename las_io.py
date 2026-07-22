# coding: utf-8
"""Чтение, объединение и подготовка данных LAS-файлов."""
from pathlib import Path
from io import StringIO
from collections import defaultdict

import numpy as np
import lasio
import streamlit as st

# Значения-заглушки, которые LAS-стандарт традиционно использует для пропусков,
# даже если поле NULL в заголовке отсутствует или заполнено иначе.
FALLBACK_NULL_VALUES = (-999.25, -999.00)


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
        except Exception:
            try:
                with open(filepath, 'rb') as f:
                    raw = f.read()
                decoded = raw.decode(encoding, errors='ignore')
                las = lasio.read(StringIO(decoded), autodetect_encoding=False)
                return las
            except Exception:
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


def get_null_values(las):
    """Собирает значения-пропуски: NULL из заголовка LAS + стандартные заглушки"""
    null_values = set(FALLBACK_NULL_VALUES)
    try:
        if 'NULL' in las.well:
            null_values.add(float(str(las.well['NULL'].value).replace(',', '.')))
    except (KeyError, AttributeError, ValueError, TypeError):
        pass
    return null_values


@st.cache_data(show_spinner=False)
def load_all_las_with_metadata(las_files, encoding='utf-8-sig'):
    """Загружает все LAS-файлы с сохранением метаданных и описаний кривых"""
    wells_data = defaultdict(list)
    for filepath in las_files:
        try:
            las = read_las_robust(filepath, encoding=encoding)
            well_name = get_well_name(las)
            file_name = filepath.name

            df = las.df()
            for null_value in get_null_values(las):
                df.replace(null_value, np.nan, inplace=True)

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
                'curve_descriptions': {},
                'depth_range': (np.nanmin(depth), np.nanmax(depth))
            }

            # Получаем описания из оригинального LAS-файла
            for curve in las.curves:
                mnemonic = curve.mnemonic.strip()
                if mnemonic and mnemonic != 'DEPT' and mnemonic != 'DEPTH' and mnemonic in df.columns:
                    file_data['curves'][mnemonic] = df[mnemonic].values
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
    depth_ranges = [f['depth_range'] for f in well_files]
    global_min = min(r[0] for r in depth_ranges) - overlap_m
    global_max = max(r[1] for r in depth_ranges) + overlap_m

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
