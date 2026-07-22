# coding: utf-8
"""Отчёт о качестве данных (QC) по загруженным LAS-файлам."""
import numpy as np
import pandas as pd

from las_io import merge_curves_by_mnemonic


def build_qc_report(wells_data):
    """
    Строит сводную таблицу качества данных по каждой скважине и кривой:
    заполненность, шаг дискретизации (и его непостоянство), дубли по глубине,
    число исходных файлов и охваченный диапазон глубин.
    """
    rows = []
    for well_name, well_files in wells_data.items():
        if not well_files:
            continue
        merged_curves, _, _ = merge_curves_by_mnemonic(well_files, overlap_m=0)

        for mnemonic, instances in merged_curves.items():
            total_points = 0
            valid_points = 0
            steps = []
            duplicate_depths = 0
            depth_min = np.inf
            depth_max = -np.inf

            for instance in instances:
                depth = np.asarray(instance['depth'], dtype=float)
                values = np.asarray(instance['values'], dtype=float)

                total_points += len(values)
                valid_points += int(np.sum(np.isfinite(values)))

                finite_depth = depth[np.isfinite(depth)]
                if len(finite_depth) > 1:
                    sorted_depth = np.sort(finite_depth)
                    diffs = np.diff(sorted_depth)
                    positive_diffs = diffs[diffs > 0]
                    if len(positive_diffs) > 0:
                        steps.append(round(float(np.median(positive_diffs)), 4))
                    duplicate_depths += int(np.sum(diffs == 0))
                if len(finite_depth) > 0:
                    depth_min = min(depth_min, float(finite_depth.min()))
                    depth_max = max(depth_max, float(finite_depth.max()))

            completeness_pct = (valid_points / total_points * 100) if total_points else 0.0
            unique_steps = sorted(set(steps))
            step_str = ", ".join(f"{s:g}" for s in unique_steps) if unique_steps else "-"

            rows.append({
                'Скважина': well_name,
                'Кривая': mnemonic,
                'Файлов': len(instances),
                'Точек всего': total_points,
                'Заполненность, %': round(completeness_pct, 1),
                'Шаг, м': step_str,
                'Шаг непостоянен': 'да' if len(unique_steps) > 1 else 'нет',
                'Дублей по глубине': duplicate_depths,
                'Глубина от, м': round(depth_min, 1) if np.isfinite(depth_min) else None,
                'Глубина до, м': round(depth_max, 1) if np.isfinite(depth_max) else None,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(['Скважина', 'Кривая']).reset_index(drop=True)
    return df
