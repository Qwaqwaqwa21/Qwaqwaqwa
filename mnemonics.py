# coding: utf-8
"""Работа со словарём канонических мнемоник (mnemo.xlsx)."""
import os
import shutil
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

# Путь к словарю мнемоник настраивается через переменную окружения MNEMO_PATH
# (по умолчанию — mnemo.xlsx рядом со скриптом, чтобы приложение запускалось
# без доступа к конкретному сетевому диску).
DEFAULT_MNEMO_PATH = str(Path(__file__).parent / "mnemo.xlsx")


def get_mnemo_path():
    return os.environ.get("MNEMO_PATH", DEFAULT_MNEMO_PATH)


@st.cache_data(show_spinner=False)
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
        load_mnemo_dict.clear()
        return True
    except Exception as e:
        st.error(f"❌ Ошибка сохранения словаря: {e}")
        return False
