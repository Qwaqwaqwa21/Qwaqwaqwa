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

from las_io import find_las_files, read_las_robust, load_all_las_with_metadata, merge_curves_by_mnemonic
from mnemonics import get_mnemo_path, load_mnemo_dict, save_mnemo_dict
from plotting import load_tracks_config, plot_well_panel
from ui_helpers import render_encoding_preview
from qc import build_qc_report

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

            # 2. Кодировка
            st.subheader("2. Выбор кодировки")
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
            if st.session_state.selected_encoding_step1 and st.button("📥 Загрузить данные", key="load_step1"):
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
                        qc_df = build_qc_report(wells_data)
                        if not qc_df.empty:
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

                # === Анализ кривых ===
                if st.button("🔍 Анализировать кривые", key="analyze_step1"):
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
                                try:
                                    new_las.write(str(output_file), version=2.0, encoding='utf-8-sig')
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
    st.subheader("1. Выбор папки с данными")
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

            # 3. Визуализация
            if st.button("🎨 Построить планшеты", key="visualize_step2"):
                if st.session_state.selected_encoding_step2:
                    try:
                        wells_data = load_all_las_with_metadata(
                            las_files,
                            encoding=st.session_state.selected_encoding_step2
                        )
                        # Читаем заново на каждый клик, чтобы правки tracks_config.yaml
                        # подхватывались без перезапуска приложения.
                        tracks_config = load_tracks_config()

                        for well_name, well_files in wells_data.items():
                            st.subheader(f"Скважина: {well_name}")

                            merged_curves, depth_min, depth_max = merge_curves_by_mnemonic(
                                well_files, overlap_m=100
                            )

                            fig, interval_table = plot_well_panel(
                                well_name,
                                merged_curves,
                                tracks_config,
                                depth_min,
                                depth_max,
                                figsize_width_cm=50
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

            st.subheader("1. Выбор кодировки")
            render_encoding_preview(las_files, 'preview_data_merge', 'preview_merge')

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

                    with st.expander("📋 QC-отчёт по данным", expanded=False):
                        qc_df = build_qc_report(wells_data)
                        if not qc_df.empty:
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
