#!/usr/bin/env python3
"""
Каталогизатор LAS-файлов по структуре ГИС_N/N_Месторождение/.../*.las.

Не открывает содержимое LAS-файлов — работает только с именами файлов и
папок через файловую систему, поэтому пригоден для деревьев на сотни
гигабайт: скорость определяется числом файлов, а не их размером.

Структура, которую ожидает скрипт:
    <root>/ГИС_1/1_Ромашкинское/<горизонт>/*.las
    <root>/ГИС_1/1_Ромашкинское/INKl/*.las
    <root>/ГИС_2/2_ДругоеМесторождение/...

Для каждого найденного *.las файла строится строка вида
    <номер_скважины>_<название_месторождения>
где номер скважины — имя файла без расширения, а название месторождения —
имя ближайшей родительской папки вида "N_Название" с отброшенным "N_".

Результат сохраняется в Excel (.xlsx), полные дубликаты (одинаковые
номер+месторождение) удаляются.
"""

from __future__ import annotations

import argparse
import logging
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pandas as pd

LAS_EXTENSIONS = {".las"}
FIELD_DIR_RE = re.compile(r"^\d+_(.+)$")
INKL_NAME_RE = re.compile(r"^inkl$", re.IGNORECASE)

log = logging.getLogger("las_inventory")


def iter_las_files(directory: Path):
    """Рекурсивно обходит directory через os.scandir, отдавая пути к *.las.

    Использует os.scandir напрямую (без открытия файлов), что для чисто
    перечисления имён — самый быстрый доступный способ обхода в Python.
    """
    stack = [directory]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            log.warning("Не удалось прочитать папку %s: %s", current, exc)
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    stack.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    if Path(entry.name).suffix.lower() in LAS_EXTENSIONS:
                        yield Path(entry.path)
            except OSError as exc:
                log.warning("Не удалось прочитать запись %s: %s", entry.path, exc)


def extract_field_name(las_path: Path, root: Path) -> tuple[str, str]:
    """Возвращает (папка_месторождения, название_месторождения_без_N_).

    Ищет ближайшего к файлу родителя с именем вида "N_Название" и убирает
    ведущий "N_". Если такого родителя нет, возвращает исходное имя папки
    прямо над файлом как есть.
    """
    try:
        parts = las_path.relative_to(root).parts[:-1]  # без имени файла
    except ValueError:
        parts = las_path.parts[:-1]

    for folder in reversed(parts):
        match = FIELD_DIR_RE.match(folder)
        if match:
            return folder, match.group(1)

    fallback = parts[-1] if parts else ""
    return fallback, fallback


def classify_category(las_path: Path, root: Path) -> str:
    try:
        parts = las_path.relative_to(root).parts[:-1]
    except ValueError:
        parts = las_path.parts[:-1]
    for folder in parts:
        if INKL_NAME_RE.match(folder):
            return "инклинометрия"
    return "горизонт/прочее"


def scan_root(root: Path, workers: int) -> list[dict]:
    root = root.resolve()
    try:
        top_level_dirs = [Path(e.path) for e in os.scandir(root) if e.is_dir(follow_symlinks=False)]
    except OSError as exc:
        log.error("Не удалось открыть корневую папку %s: %s", root, exc)
        return []

    scan_units = top_level_dirs or [root]

    rows: list[dict] = []
    files_seen = 0
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(lambda d=d: list(iter_las_files(d))): d for d in scan_units}
        for future in as_completed(futures):
            unit = futures[future]
            try:
                las_files = future.result()
            except Exception as exc:  # noqa: BLE001 - логируем и продолжаем остальные юниты
                log.error("Ошибка сканирования %s: %s", unit, exc)
                continue

            gis_batch = unit.name
            for las_path in las_files:
                well_number = las_path.stem.strip()
                field_folder, field_name = extract_field_name(las_path, root)
                category = classify_category(las_path, root)
                well_field = f"{well_number}_{field_name}"
                rows.append(
                    {
                        "well_field": well_field,
                        "well_number": well_number,
                        "field_name": field_name,
                        "gis_batch": gis_batch,
                        "field_folder": field_folder,
                        "category": category,
                        "relative_path": str(las_path.relative_to(root)),
                    }
                )
            files_seen += len(las_files)
            log.info("[%s] найдено %d LAS-файлов (всего: %d, %.1fс)",
                      unit.name, len(las_files), files_seen, time.time() - t0)

    return rows


def build_dataframe(rows: list[dict]) -> tuple[pd.DataFrame, int]:
    df = pd.DataFrame(rows, columns=[
        "well_field", "well_number", "field_name", "gis_batch",
        "field_folder", "category", "relative_path",
    ])
    before = len(df)
    df = df.drop_duplicates(subset=["well_number", "field_name"], keep="first").reset_index(drop=True)
    removed = before - len(df)
    return df, removed


def write_excel(df: pd.DataFrame, output: Path) -> None:
    engine = None
    for candidate in ("xlsxwriter", "openpyxl"):
        try:
            __import__(candidate)
            engine = candidate
            break
        except ImportError:
            continue
    if engine is None:
        raise RuntimeError("Нужен пакет xlsxwriter или openpyxl (pip install xlsxwriter openpyxl)")

    max_rows = 1_048_576 - 1  # лимит листа Excel минус заголовок
    if len(df) > max_rows:
        log.warning(
            "Строк (%d) больше, чем вмещает один лист Excel (%d). "
            "Дополнительно сохраняю полный список в CSV рядом с .xlsx.",
            len(df), max_rows,
        )
        csv_path = output.with_suffix(".csv")
        df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        df = df.iloc[:max_rows]

    with pd.ExcelWriter(output, engine=engine) as writer:
        df.to_excel(writer, index=False, sheet_name="LAS")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("root", type=Path, help="Корневая папка со структурой ГИС_N/N_Месторождение/...")
    parser.add_argument("-o", "--output", type=Path, default=Path("las_inventory.xlsx"),
                         help="Путь к результирующему .xlsx (по умолчанию: las_inventory.xlsx)")
    parser.add_argument("-w", "--workers", type=int, default=min(32, (os.cpu_count() or 4) * 4),
                         help="Число потоков для параллельного сканирования папок")
    parser.add_argument("-v", "--verbose", action="store_true", help="Подробный лог")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )

    if not args.root.is_dir():
        log.error("Папка не найдена: %s", args.root)
        return 1

    t0 = time.time()
    rows = scan_root(args.root, args.workers)
    if not rows:
        log.warning("LAS-файлы не найдены в %s", args.root)

    df, removed = build_dataframe(rows)
    log.info("Всего файлов: %d, уникальных строк: %d, удалено дубликатов: %d",
              len(rows), len(df), removed)

    write_excel(df, args.output)
    log.info("Готово за %.1fс. Результат: %s", time.time() - t0, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
