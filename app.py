# coding: utf-8
import streamlit as st
import pandas as pd
import numpy as np
import lasio
from pathlib import Path
import matplotlib.pyplot as plt
import matplotlib
import re
from collections import defaultdict
from datetime import datetime
import traceback
from io import BytesIO
import streamlit.components.v1 as components

from las_io import find_las_files, read_las_robust, load_all_las_with_metadata, merge_curves_by_mnemonic, write_las_file
from mnemonics import get_mnemo_path, load_mnemo_dict, save_mnemo_dict
from plotting import (
    load_tracks_config, plot_well_panel, build_interval_table, apply_curve_limit_overrides,
    active_track_ids, track_x_range, calculate_curve_limits
)
from plotting_plotly import plot_well_panel_plotly, plot_multi_well_panel_plotly
from ui_helpers import render_encoding_preview, stitch_figures_horizontally, scrollable_image_html
from qc import build_qc_report, build_well_score_summary
from crossplots import build_crossplot, build_histogram
from coverage import build_coverage_chart
from zones import (
    load_zones_from_file, validate_zones, build_zone_curve_coverage, zones_to_csv_bytes,
    clean_zones_df
)

# Настройки для кириллицы
matplotlib.rcParams['font.family'] = 'DejaVu Sans'
matplotlib.rcParams['figure.dpi'] = 100

MNEMO_PATH = get_mnemo_path()

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

# === Основной интерфейс ===
st.set_page_config(page_title="LAS Визуализатор", layout="wide")
st.title("📊 LAS Визуализатор")

with st.expander("ℹ️ Как пользоваться приложением"):
    st.markdown(
        "**Шаг 1 (Работа с мнемониками)** — привести названия кривых из разных "
        "LAS-файлов к единому (каноническому) виду по словарю мнемоник и "
        "сохранить обработанные файлы.\n\n"
        "**Шаг 2 (Визуализация планшета)** — построить каротажный планшет по "
        "уже обработанным файлам: статичный PNG для печати или интерактивный "
        "с зумом и подсказками при наведении.\n\n"
        "**🔗 Объединить LAS в 1** — склеить несколько LAS-файлов одной "
        "скважины (например, разные интервалы или повторные рейсы) в один "
        "файл с непрерывной сеткой глубин.\n\n"
        "**📈 Кроссплоты и гистограммы** — статистический анализ: сравнить "
        "две кривые между собой или посмотреть распределение одной кривой.\n\n"
        "Во всех вкладках сначала указывается папка с LAS-файлами, затем "
        "подбирается кодировка (кириллица в заголовках русских LAS-файлов "
        "часто в cp1251/ibm866, а не в utf-8) — правильную кодировку видно "
        "по тому, читаются ли поля заголовка и названия кривых как обычный "
        "текст, а не набор случайных символов."
    )

# Создание вкладок
tab1, tab2, tab3, tab4 = st.tabs([
    "Шаг 1: Работа с мнемониками",
    "Шаг 2: Визуализация планшета",
    "🔗 Объединить LAS в 1",
    "📈 Кроссплоты и гистограммы",
])

with tab1:
    st.header("Шаг 1: Работа с мнемониками")
    st.caption(
        "Разные подрядчики называют одну и ту же физическую величину "
        "по-разному (например, GK, ГК, GR — гамма-каротаж). Этот шаг находит "
        "такие расхождения по словарю мнемоник, даёт привести их к единому "
        "имени и сохраняет результат в новые LAS-файлы."
    )

    # 1. Импорт
    st.subheader("1. Импорт данных")
    st.caption("Укажите папку — приложение найдёт в ней все LAS-файлы (регистр расширения .las/.LAS не важен).")
    folder_path_step1 = st.text_input("Путь к папке с LAS-файлами:", key='folder_step1')

    if folder_path_step1 and Path(folder_path_step1).is_dir():
        las_files = find_las_files(folder_path_step1)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")

            # 2. Кодировка
            st.subheader("2. Выбор кодировки")
            st.caption(
                "Показывает заголовок первого файла в нескольких кодировках сразу — "
                "выберите ту, где поля и названия кривых читаются нормальным текстом, "
                "а не искажёнными символами."
            )
            render_encoding_preview(las_files, 'preview_data_step1', 'preview_step1')

            if 'preview_data_step1' in st.session_state and st.session_state.preview_data_step1:
                chosen_enc = st.radio(
                    "Выберите кодировку:",
                    options=list(st.session_state.preview_data_step1.keys()),
                    key="encoding_radio_step1",
                    horizontal=True
                )
                st.session_state.selected_encoding_step1 = chosen_enc

            # 3. Загрузка данных
            st.subheader("3. Загрузка данных")
            st.caption("Читает все найденные файлы в выбранной кодировке и сохраняет их в памяти для дальнейшей обработки.")
            if st.session_state.selected_encoding_step1 and st.button(
                "📥 Загрузить данные", key="load_step1",
                help="Прочитать все файлы в выбранной кодировке"
            ):
                try:
                    wells_data = load_all_las_with_metadata(
                        las_files,
                        encoding=st.session_state.selected_encoding_step1
                    )
                    st.session_state.step1_data['wells_data'] = wells_data
                    st.success(f"✅ Загружено скважин: {len(wells_data)}")

                    st.write("**Загружено скважин:**")
                    for well, files in wells_data.items():
                        st.write(f"  • {well}: {len(files)} файл(ов)")

                    with st.expander("📋 QC-отчёт по данным", expanded=False):
                        st.caption(
                            "Автоматическая проверка качества данных: заполненность кривых, "
                            "стабильность шага записи, дубли и развороты по глубине, доля "
                            "статистических выбросов. Не заменяет проверку геологом, но "
                            "помогает быстро найти проблемные скважины/файлы."
                        )
                        qc_df = build_qc_report(wells_data)
                        if not qc_df.empty:
                            score_df = build_well_score_summary(qc_df)
                            st.markdown("**Оценка качества по скважинам** (0–100, чем выше — тем надёжнее)")
                            st.dataframe(score_df, use_container_width=True)

                            st.markdown("**Детали по каждой кривой**")
                            st.dataframe(qc_df, use_container_width=True)
                            qc_csv = qc_df.to_csv(index=False, encoding='utf-8-sig')
                            st.download_button(
                                "💾 Скачать QC-отчёт (CSV)",
                                data=qc_csv,
                                file_name="qc_report.csv",
                                mime="text/csv",
                                key="qc_download_step1"
                            )
                        else:
                            st.info("Нет данных для отчёта")
                except Exception as e:
                    st.error(f"❌ Ошибка загрузки: {e}")
                    st.code(traceback.format_exc())

            # 4. Корректировка номера скважины (опционально)
            if 'wells_data' in st.session_state.step1_data:
                st.subheader("4. Корректировка номера скважины")
                st.caption(
                    "Опционально: если название скважины в заголовках LAS-файлов "
                    "различается или указано неверно (например, разные написания "
                    "одной и той же скважины), здесь можно принудительно задать "
                    "один номер для всех загруженных файлов."
                )
                well_names = list(st.session_state.step1_data['wells_data'].keys())
                st.write(f"Текущие скважины: {', '.join(well_names)}")

                change_well = st.radio(
                    "Изменить номер скважины:",
                    ["Оставить как есть", "Задать один номер для всех файлов"],
                    key="change_well_radio"
                )

                if change_well == "Задать один номер для всех файлов":
                    new_well_name = st.text_input("Новый номер скважины:", key="new_well_input")
                    if st.button("✅ Применить номер скважины", key="apply_well_btn") and new_well_name.strip():
                        try:
                            new_well_name = new_well_name.strip()
                            for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                                for file_data in well_files:
                                    file_data['well_name'] = new_well_name

                            old_data = st.session_state.step1_data['wells_data']
                            st.session_state.step1_data['wells_data'] = {new_well_name: []}
                            for files in old_data.values():
                                st.session_state.step1_data['wells_data'][new_well_name].extend(files)

                            st.success(f"✅ Номер скважины изменён на: {new_well_name}")
                            st.write("**Загружено скважин:**")
                            for well, files in st.session_state.step1_data['wells_data'].items():
                                st.write(f"  • {well}: {len(files)} файл(ов)")
                        except Exception as e:
                            st.error(f"❌ Ошибка применения номера: {e}")
                            st.code(traceback.format_exc())

            # 5. Проверка и корректировка мнемоник
            if 'wells_data' in st.session_state.step1_data:
                st.subheader("5. Проверка и корректировка мнемоник")
                st.caption(
                    "Сверяет названия загруженных кривых со словарём канонических "
                    "мнемоник (mnemo.xlsx). Кривые, для которых найдено соответствие, "
                    "будут автоматически переименованы в единый вид; для остальных "
                    "нужно решение — привязать к существующему имени, задать новое "
                    "или оставить как есть."
                )

                # === Анализ кривых ===
                if st.button(
                    "🔍 Анализировать кривые", key="analyze_step1",
                    help="Сравнить названия кривых во всех файлах со словарём мнемоник"
                ):
                    try:
                        canonical_to_aliases, alias_to_canonical = load_mnemo_dict(MNEMO_PATH)

                        all_curves = set()
                        for well_files in st.session_state.step1_data['wells_data'].values():
                            for file_data in well_files:
                                all_curves.update(file_data['curves'].keys())

                        found_curves = {}
                        not_found_curves = []
                        for curve in sorted(all_curves):
                            if curve in alias_to_canonical:
                                canonical = alias_to_canonical[curve]
                                found_curves.setdefault(canonical, []).append(curve)
                            else:
                                not_found_curves.append(curve)

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

                    curve_to_files = defaultdict(set)
                    curve_descriptions = {}
                    for well_files in st.session_state.step1_data['wells_data'].values():
                        for file_data in well_files:
                            for curve in st.session_state.step1_data['not_found_curves']:
                                if curve in file_data['curves']:
                                    curve_to_files[curve].add(file_data['file_name'])
                                    if curve not in curve_descriptions and curve in file_data.get('curve_descriptions', {}):
                                        curve_descriptions[curve] = file_data['curve_descriptions'][curve]

                    if 'curve_actions' not in st.session_state:
                        st.session_state.curve_actions = {}
                    if 'curve_choices' not in st.session_state:
                        st.session_state.curve_choices = {}
                    if 'curve_new_names' not in st.session_state:
                        st.session_state.curve_new_names = {}

                    curves_list = sorted(st.session_state.step1_data['not_found_curves'])
                    mid_point = (len(curves_list) + 1) // 2
                    col_left, col_right = st.columns(2)


                    for col_idx, curve in enumerate(curves_list):
                        current_col = col_left if col_idx < mid_point else col_right

                        with current_col:
                            has_cyrillic = bool(re.search(r'[а-яА-Я]', curve))
                            curve_display = f"`{curve}`" if not has_cyrillic else f"<span style='color:red'>`{curve}`</span>"
                            st.markdown(f"#### {curve_display}", unsafe_allow_html=True)

                            if curve in curve_descriptions:
                                st.caption(f"ℹ️ {curve_descriptions[curve]}")

                            files_list = list(curve_to_files.get(curve, []))
                            if files_list:
                                files_str = ", ".join([Path(f).stem for f in files_list[:3]])
                                if len(files_list) > 3:
                                    files_str += f" и ещё {len(files_list) - 3}"
                                st.caption(f"📁 Файлы: {files_str}")

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

                    # === Редактирование на уровне файлов ===
                    st.markdown("---")
                    st.markdown("#### 📄 Расширенная обработка: переименование кривых в конкретных файлах")

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

                        if 'file_level_renames' not in st.session_state:
                            st.session_state.file_level_renames = {}

                        curve_to_files = defaultdict(set)
                        for well_files in st.session_state.step1_data['wells_data'].values():
                            for file_data in well_files:
                                for curve in st.session_state.step1_data['not_found_curves']:
                                    if curve in file_data['curves']:
                                        curve_to_files[curve].add(file_data['file_name'])

                        all_files = []
                        for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                            for file_data in well_files:
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
                            all_files.sort(key=lambda x: (x['well_name'], x['file_name']))

                            col_left, col_right = st.columns(2)
                            for idx, file_info in enumerate(all_files):
                                current_col = col_left if idx % 2 == 0 else col_right

                                with current_col:
                                    well_name = file_info['well_name']
                                    file_name = file_info['file_name']
                                    curves = file_info['curves']
                                    descriptions = file_info['descriptions']

                                    st.markdown(f"**📄 `{Path(file_name).stem}`**")
                                    st.caption(f"Скважина: {well_name}")

                                    for curve in curves:
                                        has_cyrillic = bool(re.search(r'[а-яА-Я]', curve))
                                        curve_display = f"`{curve}`" if not has_cyrillic else f"<span style='color:red'>`{curve}`</span>"

                                        desc = descriptions.get(curve, "")

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

                        alias_to_canonical = st.session_state.step1_data['alias_to_canonical']
                        canonical_to_aliases = st.session_state.step1_data['canonical_to_aliases']
                        for orig, canon in new_mappings.items():
                            alias_to_canonical[orig] = canon
                            if canon not in canonical_to_aliases:
                                canonical_to_aliases[canon] = []
                            if orig not in canonical_to_aliases[canon]:
                                canonical_to_aliases[canon].append(orig)

                        if enable_file_level_editing and 'file_level_renames' in st.session_state:
                            changes_count = 0
                            for well_name, well_files in st.session_state.step1_data['wells_data'].items():
                                for file_data in well_files:
                                    file_name = file_data['file_name']
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

                        if update_mnemo:
                            if save_mnemo_dict(MNEMO_PATH, canonical_to_aliases):
                                st.success("✅ Словарь мнемоник обновлён!")
                            else:
                                st.warning("⚠️ Не удалось сохранить файл mnemo.xlsx")
                        else:
                            st.info("ℹ️ Соответствия применены только к текущей сессии")

                        st.session_state.step1_data['alias_to_canonical'] = alias_to_canonical
                        st.session_state.step1_data['canonical_to_aliases'] = canonical_to_aliases

                        if new_mappings:
                            st.write("**Применены соответствия:**")
                            for orig, canon in new_mappings.items():
                                files_count = len(curve_to_files.get(orig, []))
                                st.write(f"• `{orig}` → `{canon}` (в {files_count} файлах)")
                        else:
                            st.write("ℹ️ Не выбрано ни одного действия для кривых")

            # 6. Выгрузка обработанных файлов
            st.subheader("6. Сохранение обработанных файлов")
            st.caption(
                "Сохраняет новые LAS-файлы с переименованными по словарю мнемоник "
                "кривыми (в кодировке utf-8-sig). Исходные файлы не изменяются — "
                "результат пишется в отдельную папку."
            )
            if 'alias_to_canonical' in st.session_state.step1_data:
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
                                df = pd.DataFrame()
                                df['DEPT'] = file_data['depth']

                                for orig_name, values in file_data['curves'].items():
                                    new_name = st.session_state.step1_data['alias_to_canonical'].get(orig_name, orig_name)
                                    df[new_name] = values

                                orig_path = Path(folder_path_step1) / file_data['file_name']
                                orig_las = read_las_robust(orig_path, encoding=st.session_state.selected_encoding_step1)

                                new_las = lasio.LASFile()
                                new_las.version = orig_las.version
                                new_las.well = orig_las.well
                                new_las.params = orig_las.params
                                new_las.other = orig_las.other

                                new_las.well.WELL.value = file_data['well_name']

                                new_las.well.STRT.value = float(df['DEPT'].min())
                                new_las.well.STOP.value = float(df['DEPT'].max())
                                if len(df) > 1:
                                    new_las.well.STEP.value = float((df['DEPT'].max() - df['DEPT'].min()) / (len(df) - 1))
                                else:
                                    new_las.well.STEP.value = 0.1

                                if 'DEPT' in orig_las.curves:
                                    orig_curve = orig_las.curves['DEPT']
                                    new_las.append_curve('DEPT', df['DEPT'].values,
                                                       unit=getattr(orig_curve, 'unit', 'M'),
                                                       descr=getattr(orig_curve, 'descr', 'DEPTH'))
                                else:
                                    new_las.append_curve('DEPT', df['DEPT'].values, unit='M', descr='DEPTH')

                                for orig_name, values in file_data['curves'].items():
                                    new_name = st.session_state.step1_data['alias_to_canonical'].get(orig_name, orig_name)

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

                                output_file = output_path / file_data['file_name']
                                write_las_file(new_las, output_file, encoding='utf-8-sig')

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
    st.caption(
        "Строит стандартный каротажный планшет (треки заданы в tracks_config.yaml) "
        "по каждой скважине из указанной папки — по одному планшету на скважину."
    )
    st.subheader("1. Выбор папки с данными")
    st.caption("Обычно это папка с файлами, уже обработанными на Шаге 1 (с приведёнными к единому виду названиями кривых).")
    folder_path_step2 = st.text_input("Путь к папке с обработанными LAS-файлами:", key='folder_step2')
    if folder_path_step2 and Path(folder_path_step2).is_dir():
        las_files = find_las_files(folder_path_step2)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")
            st.subheader("2. Выбор кодировки")
            render_encoding_preview(las_files, 'preview_data_step2', 'preview_step2')

            if 'preview_data_step2' in st.session_state and st.session_state.preview_data_step2:
                chosen_enc = st.radio(
                    "Выберите кодировку:",
                    options=list(st.session_state.preview_data_step2.keys()),
                    key="encoding_radio_step2",
                    horizontal=True
                )
                st.session_state.selected_encoding_step2 = chosen_enc

            # 3. Загрузка данных
            st.subheader("3. Загрузка данных")
            st.caption(
                "Читает файлы и группирует их по скважине (по полю WELL в заголовке "
                "LAS). Если скважина записана в нескольких файлах — с разными "
                "интервалами глубин и/или разным набором кривых, — все они лягут "
                "на один общий планшет."
            )
            if st.session_state.selected_encoding_step2 and st.button(
                "📥 Загрузить данные", key="load_step2",
                help="Прочитать все файлы в выбранной кодировке и сгруппировать по скважинам"
            ):
                try:
                    st.session_state.step2_data['wells_data'] = load_all_las_with_metadata(
                        las_files, encoding=st.session_state.selected_encoding_step2
                    )
                    st.success(f"✅ Загружено скважин: {len(st.session_state.step2_data['wells_data'])}")
                except Exception as e:
                    st.error(f"❌ Ошибка загрузки: {e}")
                    st.code(traceback.format_exc())

            # 4. Объединение скважин (если LAS одной физической скважины
            # попали в разные "скважины" из-за разного написания в заголовке)
            wells_data = st.session_state.step2_data.get('wells_data')
            if wells_data:
                well_names = sorted(wells_data.keys())
                st.write(f"**Обнаружены скважины:** {', '.join(well_names)}")

                if len(well_names) > 1:
                    st.subheader("4. Объединение скважин")
                    st.caption(
                        "Если несколько файлов на самом деле относятся к одной "
                        "физической скважине, но записаны в заголовке по-разному "
                        "(опечатка, другое написание) — выберите их здесь и "
                        "объедините под одним именем, чтобы все исследования легли "
                        "на один планшет."
                    )
                    wells_to_merge = st.multiselect(
                        "Скважины, которые на самом деле одна и та же:",
                        well_names, key='wells_to_merge_step2'
                    )
                    merged_name = st.text_input(
                        "Итоговое имя скважины:",
                        value=wells_to_merge[0] if wells_to_merge else "",
                        key='merged_well_name_step2'
                    )
                    if st.button("🔗 Объединить выбранные скважины", key='merge_wells_step2_btn'):
                        merged_name_clean = merged_name.strip()
                        if len(wells_to_merge) < 2:
                            st.warning("⚠️ Выберите минимум две скважины для объединения")
                        elif not merged_name_clean:
                            st.warning("⚠️ Укажите итоговое имя скважины")
                        else:
                            combined_files = []
                            for name in wells_to_merge:
                                combined_files.extend(wells_data.pop(name))
                            wells_data[merged_name_clean] = wells_data.get(merged_name_clean, []) + combined_files
                            st.session_state.step2_data['wells_data'] = wells_data
                            st.success(f"✅ Объединено {len(wells_to_merge)} скважин в «{merged_name_clean}»")

                well_names = sorted(wells_data.keys())  # могло измениться после объединения

                # 5. Выбор скважин для отображения (чекбоксы) — можно временно
                # отключать скважины на планшете, не удаляя их из загруженных данных.
                st.subheader("5. Выбор скважин для отображения")
                well_selection = st.session_state.step2_data.setdefault('well_selection', {})
                if len(well_names) > 1:
                    st.caption("Отключите скважины чекбоксами, если не хотите видеть их на планшете.")
                    checkbox_cols = st.columns(min(4, len(well_names)))
                    for i, name in enumerate(well_names):
                        with checkbox_cols[i % len(checkbox_cols)]:
                            well_selection[name] = st.checkbox(
                                name, value=well_selection.get(name, True), key=f'well_checkbox_step2_{name}'
                            )
                else:
                    well_selection[well_names[0]] = True
                selected_well_names = [name for name in well_names if well_selection.get(name, True)]
                if not selected_well_names:
                    st.warning("⚠️ Не выбрано ни одной скважины для отображения")

            # 6. Пласты/зоны: загрузка, ручная корректировка отбивок, экспорт
            st.subheader("6. Пласты/зоны (кровля/подошва)")
            st.caption(
                "Загрузите таблицу пластов/зон (CSV или Excel) с колонками «Зона», "
                "«Кровля», «Подошва» (названия колонок могут отличаться — ищем по "
                "распространённым синонимам, включая английские). Если в файле есть "
                "колонка «Скважина» — зоны применяются только к соответствующей "
                "скважине, иначе один и тот же список зон накладывается на все "
                "планшеты. Отбивки можно скорректировать вручную прямо в таблице "
                "ниже, а затем выгрузить результат."
            )
            zones_file = st.file_uploader(
                "Файл с зонами/пластами:", type=['csv', 'xlsx', 'xls'], key='zones_file_step2'
            )
            if zones_file is not None and st.button("📥 Загрузить зоны", key='load_zones_step2_btn'):
                try:
                    zones_df_loaded, zone_load_warnings = load_zones_from_file(zones_file)
                    st.session_state.step2_data['zones_df'] = zones_df_loaded
                    st.success(f"✅ Загружено зон: {len(zones_df_loaded)}")
                    for w in zone_load_warnings:
                        st.warning(f"⚠️ {w}")
                except ValueError as e:
                    st.error(f"❌ {e}")

            zones_df_current = st.session_state.step2_data.get('zones_df')
            if zones_df_current is not None and not zones_df_current.empty:
                try:
                    st.write("**Ручная корректировка отбивок:**")
                    zones_df_current = st.data_editor(
                        zones_df_current, num_rows="dynamic", use_container_width=True,
                        key='zones_editor_step2'
                    )
                    st.session_state.step2_data['zones_df'] = zones_df_current

                    zones_df_for_validation, dropped_rows = clean_zones_df(zones_df_current)
                    if dropped_rows:
                        st.warning(f"⚠️ Строк с незаполненной глубиной (не участвуют в построении): {dropped_rows}")
                    for w in validate_zones(zones_df_for_validation):
                        st.warning(f"⚠️ {w}")

                    st.download_button(
                        label="💾 Экспортировать зоны (CSV)",
                        data=zones_to_csv_bytes(zones_df_current),
                        file_name="zones.csv",
                        mime="text/csv",
                        key="download_zones_step2"
                    )
                except Exception as e:
                    st.error(f"❌ Ошибка обработки таблицы зон: {e}")
                    st.code(traceback.format_exc())
            else:
                st.caption("Зоны не загружены — планшеты будут построены без границ пластов.")

            # 7. Визуализация
            st.subheader("7. Построение планшета")
            display_mode = st.radio(
                "Тип отображения:",
                ["Статичный (PNG, для печати)", "Интерактивный (для анализа на экране)"],
                key="display_mode_step2",
                horizontal=True,
                help=(
                    "Статичный — обычное изображение с несколькими линейками на трек, "
                    "удобно для печати/отчётов. Интерактивный — зум, панорамирование и "
                    "подсказка (название кривой, глубина, значение) при наведении мыши, "
                    "но все кривые трека делят одну общую ось."
                )
            )
            show_coverage = st.checkbox(
                "Показать карту охвата данными", value=False, key='show_coverage_step2',
                help="Упрощённая схема: один столбец на метод, закрашенный там, где для него есть данные"
            )

            if 'curve_limit_overrides' not in st.session_state:
                st.session_state.curve_limit_overrides = {}

            with st.expander("🎛 Настроить масштабы кривых вручную"):
                st.caption(
                    "Границы шкалы по умолчанию берутся из tracks_config.yaml: для "
                    "части кривых заданы жёстко (например, IK/BK — 0.1–100), для "
                    "остальных подбираются автоматически по данным. Здесь можно на "
                    "время текущей сессии переопределить границы для конкретной "
                    "кривой — например, если автоподбор скрывает нужные детали. "
                    "Правки не сохраняются в файл конфигурации."
                )
                col_mn, col_min, col_max = st.columns([2, 1, 1])
                with col_mn:
                    override_mnemonic = st.text_input(
                        "Мнемоника кривой:", key='override_mnemonic_input', placeholder="например, GK"
                    )
                with col_min:
                    override_min = st.number_input("Минимум:", key='override_min_input', value=0.0, format="%.4f")
                with col_max:
                    override_max = st.number_input("Максимум:", key='override_max_input', value=100.0, format="%.4f")

                col_apply, col_reset = st.columns(2)
                with col_apply:
                    if st.button("✅ Применить границу", key='apply_override_btn'):
                        mnemonic_clean = override_mnemonic.strip()
                        if mnemonic_clean and override_max > override_min:
                            st.session_state.curve_limit_overrides[mnemonic_clean] = (override_min, override_max)
                            st.success(f"Граница для {mnemonic_clean} установлена: {override_min:g} – {override_max:g}")
                        else:
                            st.warning("⚠️ Укажите мнемонику и корректный диапазон (максимум больше минимума)")
                with col_reset:
                    if st.button("🗑 Сбросить все ручные границы", key='reset_overrides_btn'):
                        st.session_state.curve_limit_overrides = {}
                        st.info("Ручные границы сброшены — снова используется конфигурация по умолчанию")

                if st.session_state.curve_limit_overrides:
                    st.write("**Текущие ручные границы (на эту сессию):**")
                    for mnem, (mn, mx) in st.session_state.curve_limit_overrides.items():
                        st.write(f"• {mnem}: {mn:g} – {mx:g}")

            if st.button(
                "🎨 Построить планшеты", key="visualize_step2",
                help="Построить планшет для каждой выбранной скважины"
            ):
                if not wells_data:
                    st.warning("⚠️ Сначала загрузите данные (шаг 3)")
                elif not selected_well_names:
                    st.warning("⚠️ Выберите хотя бы одну скважину для отображения (шаг 5)")
                else:
                    try:
                        # Читаем заново на каждый клик, чтобы правки tracks_config.yaml
                        # подхватывались без перезапуска приложения.
                        tracks_config = load_tracks_config()
                        tracks_config = apply_curve_limit_overrides(
                            tracks_config, st.session_state.curve_limit_overrides
                        )
                        interactive = display_mode.startswith("Интерактивный")
                        zones_df_all, _ = clean_zones_df(st.session_state.step2_data.get('zones_df'))

                        # Общий первый проход — считаем данные по каждой выбранной
                        # скважине один раз, они нужны и одиночному, и горизонтальному
                        # сопоставительному режиму.
                        well_entries = []
                        for well_name in selected_well_names:
                            well_files = wells_data[well_name]
                            merged_curves, depth_min, depth_max = merge_curves_by_mnemonic(
                                well_files, overlap_m=100
                            )

                            zones_for_well = None
                            if zones_df_all is not None and not zones_df_all.empty:
                                if 'Скважина' in zones_df_all.columns:
                                    well_key = well_name.strip().casefold()
                                    well_match = zones_df_all['Скважина'].astype(str).str.strip().str.casefold() == well_key
                                    zones_for_well = zones_df_all[well_match]
                                    if zones_for_well.empty:
                                        zones_for_well = None
                                else:
                                    zones_for_well = zones_df_all

                            well_entries.append({
                                'well_name': well_name, 'well_files': well_files,
                                'merged_curves': merged_curves,
                                'depth_min': depth_min, 'depth_max': depth_max,
                                'zones_df': zones_for_well,
                            })

                        if len(well_entries) >= 2:
                            # Несколько скважин — планшет строится рядом друг с другом
                            # (горизонтальная прокрутка), как в ПО для геологической
                            # корреляции, а не одна фигура под другой.
                            st.caption(
                                "Несколько скважин сопоставляются рядом друг с другом "
                                "(прокрутка по горизонтали) — общая шкала глубины и общий "
                                "масштаб каждого трека для всех скважин, чтобы было видно "
                                "геологическую неоднородность между ними."
                            )
                            any_panel = False

                            if interactive:
                                fig_multi = plot_multi_well_panel_plotly(well_entries, tracks_config)
                                if fig_multi:
                                    any_panel = True
                                    # include_plotlyjs=True встраивает библиотеку целиком в HTML —
                                    # рабочий компьютер может быть без доступа в интернет (CDN
                                    # недоступен), а plotly.js всё равно должен подгрузиться.
                                    html_str = fig_multi.to_html(include_plotlyjs=True, full_html=False)
                                    wrapped = (
                                        '<div style="overflow-x:auto; overflow-y:hidden;">'
                                        f'{html_str}</div>'
                                    )
                                    components.html(wrapped, height=980, scrolling=True)
                            else:
                                global_depth_min = min(e['depth_min'] for e in well_entries)
                                global_depth_max = max(e['depth_max'] for e in well_entries)

                                # Общий для всех скважин набор треков (иначе один и тот же
                                # трек мог бы оказаться в разных колонках у разных скважин,
                                # если их наборы кривых отличаются) и общая шкала X по
                                # каждому треку/кривой — иначе амплитуды кривых у разных
                                # скважин были бы несопоставимы просто из-за разного
                                # автоподбора масштаба у каждой в отдельности.
                                multi_track_ids = []
                                seen_tracks = set()
                                for e in well_entries:
                                    for tid in active_track_ids(e['merged_curves'], tracks_config):
                                        if tid not in seen_tracks:
                                            seen_tracks.add(tid)
                                            multi_track_ids.append(tid)
                                multi_track_ids.sort()

                                combined_curves = {}
                                for e in well_entries:
                                    for mnemonic, instances in e['merged_curves'].items():
                                        combined_curves.setdefault(mnemonic, []).extend(instances)

                                multi_track_limits = {}
                                multi_curve_limits = {}
                                for tid in multi_track_ids:
                                    config = tracks_config[tid]
                                    if config['limits'] in ('auto', 'shared'):
                                        pairs = [(c['mnemonic'], combined_curves.get(c['mnemonic'], []))
                                                 for c in config['curves']]
                                        rng = track_x_range(config, pairs)
                                        if rng is not None:
                                            multi_track_limits[tid] = rng
                                    elif config['limits'] == 'auto_per_curve':
                                        grid_type = 'log' if config['grid'] == 'log' else 'linear'
                                        for c in config['curves']:
                                            if isinstance(c.get('limits'), tuple):
                                                continue  # явная граница в конфиге и так приоритетнее
                                            mnemonic = c['mnemonic']
                                            vals = [np.asarray(inst['values']) for inst in combined_curves.get(mnemonic, [])]
                                            vals = [v[np.isfinite(v)] for v in vals]
                                            vals = [v for v in vals if len(v)]
                                            if not vals:
                                                continue
                                            vmin, vmax = calculate_curve_limits(
                                                np.concatenate(vals), grid_type=grid_type, mnemonic=mnemonic
                                            )
                                            if vmin is not None:
                                                multi_curve_limits[mnemonic] = (vmin, vmax)

                                figs = []
                                for e in well_entries:
                                    fig, interval_table = plot_well_panel(
                                        e['well_name'], e['merged_curves'], tracks_config,
                                        global_depth_min, global_depth_max,
                                        figsize_width_cm=50, zones_df=e['zones_df'],
                                        forced_track_ids=multi_track_ids,
                                        forced_track_limits=multi_track_limits,
                                        forced_curve_limits=multi_curve_limits,
                                    )
                                    e['interval_table'] = interval_table
                                    if fig:
                                        figs.append(fig)

                                if figs:
                                    any_panel = True
                                    combined_png = stitch_figures_horizontally(figs)
                                    for fig in figs:
                                        plt.close(fig)
                                    scroll_html, img_height = scrollable_image_html(combined_png)
                                    components.html(scroll_html, height=img_height + 20, scrolling=True)
                                    st.download_button(
                                        label="💾 Скачать общий планшет (PNG)",
                                        data=combined_png,
                                        file_name="planshet_sopostavlenie.png",
                                        mime="image/png",
                                        key="download_multi_panel"
                                    )

                            if not any_panel:
                                st.warning("⚠️ Нет данных ни по одной из выбранных скважин для построения треков")

                            # Таблицы по каждой скважине — под общим планшетом, свёрнуты
                            # в раскрывающиеся блоки, чтобы не мешать сопоставлению панелей.
                            for e in well_entries:
                                well_name = e['well_name']
                                interval_table = e.get('interval_table')
                                if interval_table is None:
                                    interval_table = build_interval_table(e['merged_curves'], tracks_config)
                                with st.expander(f"📊 Таблицы — скважина {well_name}"):
                                    if len(e['well_files']) > 1:
                                        st.caption(f"Собрано из {len(e['well_files'])} файлов: " +
                                                   ", ".join(Path(f['file_name']).stem for f in e['well_files']))
                                    zones_for_well = e['zones_df']
                                    if zones_df_all is not None and not zones_df_all.empty \
                                            and 'Скважина' in zones_df_all.columns and zones_for_well is None:
                                        st.caption(f"ℹ️ В файле зон нет строк со скважиной «{well_name}».")

                                    if interval_table and len(interval_table) > 0:
                                        df_table = pd.DataFrame(interval_table)
                                        st.dataframe(df_table, use_container_width=True)
                                        csv = df_table.to_csv(index=False, encoding='utf-8-sig')
                                        st.download_button(
                                            label="💾 Скачать таблицу интервалов (CSV)",
                                            data=csv,
                                            file_name=f"intervals_{well_name}.csv",
                                            mime="text/csv",
                                            key=f"download_table_multi_{well_name}"
                                        )
                                        if show_coverage:
                                            coverage_fig = build_coverage_chart(
                                                interval_table, e['depth_min'], e['depth_max']
                                            )
                                            if coverage_fig:
                                                st.plotly_chart(coverage_fig, use_container_width=True,
                                                               key=f"coverage_multi_{well_name}")
                                        if zones_for_well is not None and not zones_for_well.empty:
                                            st.write("**🧭 Наличие кривых по зонам:**")
                                            zone_coverage_df = build_zone_curve_coverage(
                                                zones_for_well, interval_table
                                            )
                                            if not zone_coverage_df.empty:
                                                st.dataframe(zone_coverage_df, use_container_width=True)
                                    else:
                                        st.warning("⚠️ Таблица интервалов пуста для этой скважины")

                        else:
                            # Ровно одна выбранная скважина — прежнее поведение без изменений.
                            for e in well_entries:
                                well_name = e['well_name']
                                well_files = e['well_files']
                                merged_curves = e['merged_curves']
                                depth_min, depth_max = e['depth_min'], e['depth_max']
                                zones_for_well = e['zones_df']

                                st.subheader(f"Скважина: {well_name}")
                                if len(well_files) > 1:
                                    st.caption(f"Собрано из {len(well_files)} файлов: " +
                                               ", ".join(Path(f['file_name']).stem for f in well_files))
                                if zones_df_all is not None and not zones_df_all.empty \
                                        and 'Скважина' in zones_df_all.columns and zones_for_well is None:
                                    st.caption(
                                        f"ℹ️ В файле зон нет строк со скважиной «{well_name}» — "
                                        "планшет построен без границ пластов."
                                    )

                                if interactive:
                                    fig_plotly = plot_well_panel_plotly(
                                        well_name, merged_curves, tracks_config, depth_min, depth_max,
                                        zones_df=zones_for_well
                                    )
                                    interval_table = build_interval_table(merged_curves, tracks_config)
                                    if fig_plotly:
                                        st.plotly_chart(fig_plotly, use_container_width=True, key=f"plotly_{well_name}")
                                    fig = fig_plotly
                                else:
                                    fig, interval_table = plot_well_panel(
                                        well_name,
                                        merged_curves,
                                        tracks_config,
                                        depth_min,
                                        depth_max,
                                        figsize_width_cm=50,
                                        zones_df=zones_for_well
                                    )

                                    if fig:
                                        st.pyplot(fig)

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
                                        # Фигуры matplotlib не закрываются автоматически —
                                        # без этого память растёт с числом скважин за сессию.
                                        plt.close(fig)

                                if fig:
                                    if interval_table and len(interval_table) > 0:
                                        st.subheader("📊 Таблица интервалов (кровля / подошва)")
                                        df_table = pd.DataFrame(interval_table)
                                        st.dataframe(df_table, use_container_width=True)

                                        csv = df_table.to_csv(index=False, encoding='utf-8-sig')
                                        st.download_button(
                                            label="💾 Скачать таблицу интервалов (CSV)",
                                            data=csv,
                                            file_name=f"intervals_{well_name}.csv",
                                            mime="text/csv",
                                            key=f"download_table_{well_name}"
                                        )

                                        if show_coverage:
                                            coverage_fig = build_coverage_chart(interval_table, depth_min, depth_max)
                                            if coverage_fig:
                                                st.plotly_chart(coverage_fig, use_container_width=True,
                                                               key=f"coverage_{well_name}")

                                        if zones_for_well is not None and not zones_for_well.empty:
                                            st.subheader("🧭 Наличие кривых по зонам")
                                            st.caption(
                                                "«полностью» — данные кривой покрывают всю зону, "
                                                "«частично» — покрыта только часть, «нет» — данных "
                                                "по кривой в этой зоне не найдено."
                                            )
                                            zone_coverage_df = build_zone_curve_coverage(zones_for_well, interval_table)
                                            if not zone_coverage_df.empty:
                                                st.dataframe(zone_coverage_df, use_container_width=True)
                                    else:
                                        st.warning(f"⚠️ Таблица интервалов пуста для скважины {well_name}. Возможные причины:\n"
                                                   "- Нет данных в кривых (только -999.25)\n"
                                                   "- Все значения кривых являются пропусками (NaN)\n"
                                                   "- Некорректные данные глубины")

                        st.success("✅ Визуализация завершена!")

                    except Exception as e:
                        st.error(f"❌ Ошибка визуализации: {e}")
                        st.code(traceback.format_exc())

with tab3:
    st.header("🔗 Объединение LAS-файлов по скважинам")
    st.info("ℹ️ Умное объединение: файлы группируются по одинаковому шагу глубины (STEP). Для каждой группы строится непрерывная сетка от мин до макс. Данные выравниваются, дубликаты имён сохраняются, источник указывается в DESC.")

    folder_path_merge = st.text_input("📂 Путь к папке с исходными LAS:", key='folder_merge')

    if folder_path_merge and Path(folder_path_merge).is_dir():
        las_files = find_las_files(folder_path_merge)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")

            st.subheader("1. Выбор кодировки")
            render_encoding_preview(las_files, 'preview_data_merge', 'preview_merge')

            if st.session_state.get('preview_data_merge'):
                enc_choice = st.radio("Выберите кодировку:",
                                     options=list(st.session_state.preview_data_merge.keys()),
                                     key="enc_radio_merge", horizontal=True)
                st.session_state.selected_encoding_merge = enc_choice

            # 2. Загрузка
            st.subheader("2. Загрузка и группировка")
            st.caption(
                "Читает все файлы и группирует их по шагу глубины (STEP) — "
                "объединять по непрерывной сетке можно только файлы с одинаковым шагом."
            )
            if st.session_state.get('selected_encoding_merge') and st.button(
                "📥 Загрузить и сгруппировать", key="load_merge",
                help="Прочитать файлы скважины и разбить их на группы по шагу глубины"
            ):
                try:
                    wells_data = load_all_las_with_metadata(las_files, encoding=st.session_state.selected_encoding_merge)
                    st.session_state.merge_data = {'wells_data': wells_data, 'folder': folder_path_merge}
                    st.success(f"✅ Загружено: {len(wells_data)} скважин")
                    for well, files in wells_data.items():
                        st.write(f"• **{well}**: {len(files)} файлов")

                    with st.expander("📋 QC-отчёт по данным", expanded=False):
                        st.caption(
                            "Автоматическая проверка качества данных перед объединением: "
                            "заполненность кривых, стабильность шага записи, дубли и "
                            "развороты по глубине, доля статистических выбросов."
                        )
                        qc_df = build_qc_report(wells_data)
                        if not qc_df.empty:
                            score_df = build_well_score_summary(qc_df)
                            st.markdown("**Оценка качества по скважинам** (0–100, чем выше — тем надёжнее)")
                            st.dataframe(score_df, use_container_width=True)

                            st.markdown("**Детали по каждой кривой**")
                            st.dataframe(qc_df, use_container_width=True)
                            qc_csv = qc_df.to_csv(index=False, encoding='utf-8-sig')
                            st.download_button(
                                "💾 Скачать QC-отчёт (CSV)",
                                data=qc_csv,
                                file_name="qc_report_merge.csv",
                                mime="text/csv",
                                key="qc_download_merge"
                            )
                        else:
                            st.info("Нет данных для отчёта")
                except Exception as e:
                    st.error(f"❌ Ошибка: {e}")

            # 3. Объединение с логикой по STEP
            if 'merge_data' in st.session_state:
                st.subheader("3. Сохранение и запуск")
                st.caption(
                    "Для каждой группы (скважина + шаг глубины) строится единая сетка "
                    "глубин от минимума до максимума; значения всех кривых "
                    "интерполируются на неё. Одноимённые кривые из разных файлов "
                    "сохраняются отдельно, источник указывается в описании кривой."
                )

                default_out = str(Path(st.session_state.merge_data['folder']) / "merged_output")
                out_folder_str = st.text_input("📁 Папка для сохранения объединённых файлов:", value=default_out, key="out_folder_merge")

                if st.button(
                    "🔗 Объединить по STEP + непрерывная глубина", key="do_merge_v4",
                    help="Построить непрерывную сетку глубин для каждой группы и сохранить объединённые LAS-файлы"
                ):
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
                            if not well_files:
                                continue

                            pct = (idx / max(total_wells, 1)) * 0.85
                            progress_bar.progress(pct, text=f"Обработка скважины {idx+1}/{total_wells}: {well_name}")
                            log(f"👉 Скв: {well_name} ({len(well_files)} файлов)")

                            # === 1. Группировка файлов по STEP ===
                            step_groups = defaultdict(list)
                            for fd in well_files:
                                src_path = Path(folder) / fd['file_name']
                                try:
                                    las_tmp = read_las_robust(src_path, encoding=enc)
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

                                all_depths = []
                                for fd, las_tmp in group_data:
                                    d = las_tmp.curves['DEPT'].data if 'DEPT' in las_tmp.curves else las_tmp.curves['DEPTH'].data
                                    all_depths.extend(d)
                                g_min = np.nanmin(all_depths)
                                g_max = np.nanmax(all_depths)
                                log(f"    📏 Диапазон глубин: {g_min:.2f} – {g_max:.2f} м")

                                unified_depth = np.arange(g_min, g_max + step_val/2, step_val)

                                base_fd, base_las = group_data[0]
                                new_las = lasio.LASFile()
                                new_las.version = base_las.version
                                for k, v in base_las.well.items():
                                    new_las.well[k] = v
                                new_las.params = base_las.params
                                new_las.other = base_las.other
                                new_las.well.WELL.value = well_name

                                new_las.append_curve('DEPT', unified_depth, unit='M', descr='Depth')

                                added_count = 0
                                for fd, src_las in group_data:
                                    src_depth = src_las.curves['DEPT'].data if 'DEPT' in src_las.curves else src_las.curves['DEPTH'].data

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

                                        curve_data = getattr(curve, 'data', None)
                                        if curve_data is None:
                                            curve_data = getattr(curve, 'values', None)
                                        if curve_data is None:
                                            log(f"    ⚠️ Нет данных для {mnem} в {fd['file_name']}")
                                            continue

                                        aligned_data = np.interp(unified_depth, src_depth, curve_data, left=np.nan, right=np.nan)

                                        new_las.append_curve(mnem, aligned_data, unit=unit, descr=new_descr)
                                        added_count += 1

                                new_las.well.STRT.value = float(g_min)
                                new_las.well.STOP.value = float(g_max)
                                new_las.well.STEP.value = step_val

                                out_filename = f"merged_{well_name}_Step{step_str}.las"
                                out_path = out_folder / out_filename
                                try:
                                    write_las_file(new_las, out_path, encoding='utf-8-sig')
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

with tab4:
    st.header("📈 Кроссплоты и гистограммы")
    st.caption(
        "Статистический анализ кривых: кроссплот двух кривых с линией линейной "
        "регрессии (R²) — например, RHOB/NPHI для литологического анализа — и "
        "гистограмма распределения одной кривой. Кроссплот и гистограмма строятся "
        "по кривым одного файла, чтобы гарантированно сравнивать значения на "
        "одинаковых глубинах."
    )

    folder_path_cp = st.text_input("Путь к папке с LAS-файлами:", key='folder_crossplot')

    if folder_path_cp and Path(folder_path_cp).is_dir():
        las_files = find_las_files(folder_path_cp)
        if las_files:
            st.success(f"✅ Найдено файлов: {len(las_files)}")

            st.subheader("1. Выбор кодировки")
            render_encoding_preview(las_files, 'preview_data_crossplot', 'preview_crossplot')

            if st.session_state.get('preview_data_crossplot'):
                enc_choice = st.radio(
                    "Выберите кодировку:",
                    options=list(st.session_state.preview_data_crossplot.keys()),
                    key="enc_radio_crossplot", horizontal=True
                )
                st.session_state.selected_encoding_crossplot = enc_choice

            if st.session_state.get('selected_encoding_crossplot') and st.button("📥 Загрузить данные", key="load_crossplot"):
                try:
                    st.session_state.crossplot_data = load_all_las_with_metadata(
                        las_files, encoding=st.session_state.selected_encoding_crossplot
                    )
                    st.success(f"✅ Загружено скважин: {len(st.session_state.crossplot_data)}")
                except Exception as e:
                    st.error(f"❌ Ошибка загрузки: {e}")

            if 'crossplot_data' in st.session_state:
                wells_data = st.session_state.crossplot_data
                well_name = st.selectbox("Скважина:", sorted(wells_data.keys()), key='crossplot_well')

                well_files = wells_data.get(well_name, [])
                file_options = {
                    f"{fd['file_name']} ({len(fd['curves'])} кривых)": fd for fd in well_files
                }

                if not file_options:
                    st.info("Для этой скважины нет загруженных файлов")
                else:
                    file_label = st.selectbox(
                        "Файл:",
                        list(file_options.keys()),
                        key='crossplot_file',
                        help="Кривые сравниваются внутри одного файла, чтобы значения гарантированно совпадали по глубине"
                    )
                    file_data = file_options[file_label]
                    available_curves = sorted(file_data['curves'].keys())

                    st.subheader("2. Кроссплот двух кривых")
                    if len(available_curves) < 2:
                        st.info("В выбранном файле недостаточно кривых для кроссплота (нужно минимум 2)")
                    else:
                        col1, col2 = st.columns(2)
                        with col1:
                            x_curve = st.selectbox("Кривая X:", available_curves, key='crossplot_x')
                            log_x = st.checkbox("Логарифмическая шкала X", key='crossplot_logx')
                        with col2:
                            default_y_index = 1 if len(available_curves) > 1 else 0
                            y_curve = st.selectbox("Кривая Y:", available_curves,
                                                   index=default_y_index, key='crossplot_y')
                            log_y = st.checkbox("Логарифмическая шкала Y", key='crossplot_logy')
                        show_regression = st.checkbox(
                            "Показать линию линейной регрессии (R²)", value=True, key='crossplot_regression',
                            help="Регрессия и R² считаются по тем же координатам, что и оси (по логарифмам значений, если ось логарифмическая)"
                        )

                        if st.button("🎨 Построить кроссплот", key='build_crossplot_btn'):
                            fig_cp = build_crossplot(
                                file_data['curves'][x_curve], file_data['curves'][y_curve],
                                x_curve, y_curve, log_x=log_x, log_y=log_y,
                                show_regression=show_regression, depth_values=file_data['depth']
                            )
                            if fig_cp:
                                st.plotly_chart(fig_cp, use_container_width=True, key='crossplot_fig')
                            else:
                                st.warning("⚠️ Недостаточно валидных пар точек для построения кроссплота")

                    st.subheader("3. Гистограмма распределения")
                    hist_curve = st.selectbox("Кривая:", available_curves, key='hist_curve')
                    bins = st.slider("Число интервалов гистограммы:", 5, 100, 30, key='hist_bins')

                    if st.button("📊 Построить гистограмму", key='build_hist_btn'):
                        fig_hist = build_histogram(file_data['curves'][hist_curve], hist_curve, bins=bins)
                        if fig_hist:
                            st.plotly_chart(fig_hist, use_container_width=True, key='hist_fig')
                        else:
                            st.warning("⚠️ Нет данных для построения гистограммы")
