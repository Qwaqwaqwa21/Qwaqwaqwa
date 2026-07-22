# coding: utf-8
"""Чтение, объединение и подготовка данных LAS-файлов."""
import codecs
from pathlib import Path
from io import StringIO
from collections import defaultdict

import numpy as np
import lasio
import streamlit as st

# Значения-заглушки, которые LAS-стандарт традиционно использует для пропусков,
# даже если поле NULL в заголовке отсутствует или заполнено иначе.
FALLBACK_NULL_VALUES = (-999.25, -999.00)

# BOM однозначно определяет кодировку файла — если он есть, доверяем ему больше,
# чем ручному выбору пользователя (lasio делает то же самое внутри себя, но молча;
# здесь это явно и с предупреждением для пользователя).
_BOM_ENCODINGS = (
    (codecs.BOM_UTF8, 'utf-8-sig'),
    (codecs.BOM_UTF16_LE, 'utf-16-le'),
    (codecs.BOM_UTF16_BE, 'utf-16-be'),
)


def find_las_files(folder):
    """Ищет .las файлы регистронезависимо (Windows часто отдаёт .LAS)"""
    folder = Path(folder)
    seen = {}
    for path in folder.iterdir():
        if path.is_file() and path.suffix.lower() == '.las':
            seen[path.name] = path
    return sorted(seen.values(), key=lambda p: p.name)


def _detect_bom_encoding(raw):
    for bom, enc in _BOM_ENCODINGS:
        if raw.startswith(bom):
            return enc
    return None


def read_las_robust(filepath, encoding='cp1251'):
    """
    Читает LAS-файл с явным и предсказуемым контролем кодировки.

    В отличие от передачи encoding= напрямую в lasio.read(), здесь декодирование
    выполняется вручную и один раз:
    - при наличии BOM в файле реальная кодировка переопределяется на неё
      (это достовернее любого ручного выбора), о чём выставляется
      las._encoding_warning;
    - декодирование сначала пробуется строго (errors='strict') — явное
      несовпадение кодировки (типично при перепутанных utf-8/utf-8-sig/ibm866)
      даёт понятную ошибку вместо молчаливой порчи текста символами замены,
      как это происходит при encoding_errors='replace' по умолчанию в lasio;
    - если строгое декодирование всё же не удаётся, используется запасной
      вариант с заменой недопустимых байт, но результат помечается как
      потенциально повреждённый через las._encoding_warning.

    Ограничение: между двумя однобайтовыми кодировками (например, cp1251 и
    ibm866) декодирование почти никогда не «падает» технически — каждый байт
    валиден в обеих, отличается лишь смысл символов. Отличить их автоматически
    нельзя, для этого и нужен визуальный предпросмотр в интерфейсе.
    """
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Файл не найден: {filepath}")

    raw = filepath.read_bytes()

    bom_encoding = _detect_bom_encoding(raw)
    effective_encoding = bom_encoding or encoding
    warning = None
    if bom_encoding and bom_encoding != encoding:
        warning = (f"Обнаружена метка BOM — использована кодировка "
                   f"{bom_encoding} вместо выбранной {encoding}")

    try:
        text = raw.decode(effective_encoding, errors='strict')
    except LookupError:
        raise RuntimeError(f"Неизвестная кодировка: {effective_encoding}")
    except UnicodeDecodeError as e:
        text = raw.decode(effective_encoding, errors='replace')
        lossy_note = (f"Кодировка {effective_encoding} не полностью подходит для "
                      f"{filepath.name} (байт {e.start}) — часть текста могла "
                      f"быть заменена символом '�'. Попробуйте другую кодировку.")
        warning = f"{warning}; {lossy_note}" if warning else lossy_note

    try:
        las = lasio.read(StringIO(text), autodetect_encoding=False, ignore_header_errors=True)
    except Exception as e:
        raise RuntimeError(
            f"Не удалось разобрать LAS {filepath.name} (кодировка {effective_encoding}): {e}"
        ) from e

    las._encoding_warning = warning
    las._effective_encoding = effective_encoding
    return las


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
            if getattr(las, '_encoding_warning', None):
                st.warning(f"⚠️ {filepath.name}: {las._encoding_warning}")
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


def write_las_file(las, output_path, encoding='utf-8-sig', version=2.0):
    """
    Сохраняет LAS-файл в заданной кодировке. Все данные (имена скважин,
    описания кривых и т.д.) к этому моменту уже хранятся в las как обычные
    Python-строки (декодированные read_las_robust'ом), поэтому запись через
    явно открытый в нужной кодировке файловый объект корректно кодирует их
    заново — без риска повторной/неверной перекодировки.
    """
    output_path = Path(output_path)
    with open(output_path, 'w', encoding=encoding) as f:
        las.write(f, version=version)


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
