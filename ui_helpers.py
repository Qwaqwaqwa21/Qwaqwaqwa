# coding: utf-8
"""Общие Streamlit-виджеты, используемые во всех вкладках приложения."""
import re

import streamlit as st

from las_io import read_las_robust

ENCODINGS = ['cp1251', 'utf-8', 'utf-8-sig', 'ibm866', 'koi8-r']


def preview_las_header(filepath, encoding='cp1251'):
    """
    Читает LAS-файл и возвращает структурированный предпросмотр заголовка:
    - Поля из секции ~WELL (WELL, COMP, FLD, FIELD, SRVC и др.)
    - Список кривых с описаниями из секции ~CURVE
    """
    try:
        las = read_las_robust(filepath, encoding=encoding)

        well_fields = {}
        well_keys = ['WELL', 'UWI', 'COMP', 'FLD', 'FIELD', 'SRVC', 'DATE', 'API']

        for key in well_keys:
            if key in las.well:
                value = str(las.well[key].value).strip()
                if value and value != 'UNKNOWN' and value != '':
                    well_fields[key] = value

        if 'FLD' not in well_fields and 'FIELD' in well_fields:
            well_fields['FLD'] = well_fields['FIELD']
        elif 'FIELD' not in well_fields and 'FLD' in well_fields:
            well_fields['FIELD'] = well_fields['FLD']

        curves_info = []
        for curve in las.curves:
            mnemonic = curve.mnemonic.strip()
            if mnemonic and mnemonic != 'DEPT' and mnemonic != 'DEPTH':
                unit = curve.unit.strip() if hasattr(curve, 'unit') and curve.unit else ''
                descr = curve.descr.strip() if hasattr(curve, 'descr') and curve.descr else ''

                desc_parts = []
                if descr:
                    desc_parts.append(descr)
                if unit:
                    desc_parts.append(f"{unit}")

                description = " | ".join(desc_parts) if desc_parts else 'без описания'
                curves_info.append((mnemonic, description))

        all_text = " ".join(list(well_fields.values()) + [mn for mn, _ in curves_info] + [desc for _, desc in curves_info])
        has_cyrillic = bool(re.search(r'[а-яА-ЯёЁ]', all_text))

        return {
            'well_fields': well_fields,
            'curves_info': curves_info[:10],
            'total_curves': len(curves_info),
            'has_cyrillic': has_cyrillic,
            'encoding_warning': getattr(las, '_encoding_warning', None),
            'error': None
        }

    except Exception as e:
        return {
            'well_fields': {},
            'curves_info': [],
            'total_curves': 0,
            'has_cyrillic': False,
            'encoding_warning': None,
            'error': str(e)[:100]
        }


def display_preview_result_horizontal(encoding, preview_data):
    """Отображает результат предпросмотра в компактном горизонтальном формате"""
    if preview_data['error']:
        st.error(f"❌ {encoding}: {preview_data['error']}")
        return

    status_emoji = "✅" if preview_data['has_cyrillic'] else "⚠️"

    well_info = []
    for key in ['WELL', 'FLD', 'FIELD']:
        if key in preview_data['well_fields']:
            well_info.append(f"{key}={preview_data['well_fields'][key]}")

    well_str = " | ".join(well_info[:2]) if well_info else "—"
    curves_str = f"{preview_data['total_curves']} кривых" if preview_data['total_curves'] > 0 else "—"

    st.markdown(f"**`{encoding}`** {status_emoji} • {well_str} • {curves_str}")

    if preview_data.get('encoding_warning'):
        st.warning(f"⚠️ {preview_data['encoding_warning']}")

    if preview_data['well_fields']:
        st.text("  Поля заголовка:")
        for key, value in preview_data['well_fields'].items():
            st.text(f"    {key:6s} : {value}")

    if preview_data['curves_info']:
        st.text(f"  Кривые ({preview_data['total_curves']} всего):")
        for mnemonic, descr in preview_data['curves_info']:
            st.text(f"    {mnemonic:15s} : {descr}")
        if preview_data['total_curves'] > 10:
            st.text(f"    ... и ещё {preview_data['total_curves'] - 10} кривых")


def render_encoding_preview(las_files, state_key, button_key):
    """
    Общий блок "Предпросмотр кодировок", ранее продублированный в трёх вкладках.
    Показывает первый файл во всех кандидатах из ENCODINGS и сохраняет результат
    в st.session_state[state_key] для последующего выбора кодировки.
    """
    if st.button("🔍 Предпросмотр кодировок", key=button_key):
        st.write("**Результаты предпросмотра для первого файла:**")
        st.write(f"Файл: `{las_files[0].name}`")

        columns = st.columns(len(ENCODINGS))
        previews = {}
        for enc, col in zip(ENCODINGS, columns):
            with col:
                st.markdown(f"### `{enc}`")
                preview_data = preview_las_header(las_files[0], encoding=enc)
                previews[enc] = preview_data
                display_preview_result_horizontal(enc, preview_data)

        st.session_state[state_key] = previews
        st.markdown("---")
