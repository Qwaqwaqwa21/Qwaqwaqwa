# coding: utf-8
"""
Отчёт о качестве данных (QC) по загруженным LAS-файлам.

Идеи для этого модуля частично взяты из открытых QC-инструментов для
каротажных данных (well-data-qc-pipeline, PetrologStudio): композитная
оценка качества скважины 0-100, проверка монотонности глубины и доля
выбросов по кривой — в дополнение к уже имевшимся заполненности, шагу
дискретизации и дублям по глубине.
"""
import numpy as np
import pandas as pd

from las_io import merge_curves_by_mnemonic

# Порог для определения выбросов: значения дальше median ± OUTLIER_MAD_K * MAD
# считаются выбросами. Тот же метод (медиана + MAD), что и в
# plotting.calculate_curve_limits, — устойчивая статистика, не завязанная на
# заранее известные физические диапазоны конкретных кривых (которые зависят
# от прибора/подрядчика и потому ненадёжны как жёсткий порог).
OUTLIER_MAD_K = 3


def _outlier_fraction(values):
    """Доля точек, отклоняющихся от медианы более чем на OUTLIER_MAD_K * MAD."""
    valid = values[np.isfinite(values)]
    if len(valid) < 5:
        return 0.0
    median = np.median(valid)
    mad = np.median(np.abs(valid - median))
    if mad == 0:
        # MAD=0 значит, что не менее половины значений совпадают с медианой;
        # тогда любое отличающееся значение уже является потенциальным выбросом
        # (масштаб "нормального" разброса здесь просто неопределён).
        outliers = np.sum(valid != median)
    else:
        lower, upper = median - OUTLIER_MAD_K * mad, median + OUTLIER_MAD_K * mad
        outliers = np.sum((valid < lower) | (valid > upper))
    return float(outliers) / len(valid) * 100


def build_qc_report(wells_data):
    """
    Строит сводную таблицу качества данных по каждой скважине и кривой:
    заполненность, шаг дискретизации (и его непостоянство), дубли и
    немонотонность по глубине, доля статистических выбросов, число исходных
    файлов и охваченный диапазон глубин.
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
            non_monotonic_files = 0
            outlier_fractions = []
            depth_min = np.inf
            depth_max = -np.inf

            for instance in instances:
                depth = np.asarray(instance['depth'], dtype=float)
                values = np.asarray(instance['values'], dtype=float)

                total_points += len(values)
                valid_points += int(np.sum(np.isfinite(values)))
                outlier_fractions.append(_outlier_fraction(values))

                finite_depth = depth[np.isfinite(depth)]
                if len(finite_depth) > 1:
                    # Немонотонность проверяем в исходном порядке записи (без
                    # сортировки) — именно так проявляется реальная проблема
                    # прибора/каротажа, а не просто дубли после объединения файлов.
                    if np.any(np.diff(finite_depth) <= 0):
                        non_monotonic_files += 1

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
            avg_outlier_pct = float(np.mean(outlier_fractions)) if outlier_fractions else 0.0

            rows.append({
                'Скважина': well_name,
                'Кривая': mnemonic,
                'Файлов': len(instances),
                'Точек всего': total_points,
                'Заполненность, %': round(completeness_pct, 1),
                'Выбросов, %': round(avg_outlier_pct, 1),
                'Шаг, м': step_str,
                'Шаг непостоянен': 'да' if len(unique_steps) > 1 else 'нет',
                'Дублей по глубине': duplicate_depths,
                'Глубина немонотонна': 'да' if non_monotonic_files > 0 else 'нет',
                'Глубина от, м': round(depth_min, 1) if np.isfinite(depth_min) else None,
                'Глубина до, м': round(depth_max, 1) if np.isfinite(depth_max) else None,
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(['Скважина', 'Кривая']).reset_index(drop=True)
    return df


def _score_label(score):
    if score >= 90:
        return 'высокая'
    elif score >= 70:
        return 'средняя'
    return 'низкая'


def compute_well_score(well_rows):
    """
    Считает композитную оценку качества скважины (0-100) по её строкам из
    build_qc_report. Штрафы (в порядке убывания веса): неполнота данных,
    немонотонная глубина, доля выбросов, непостоянный шаг, дубли по глубине.
    Возвращает (score, метка_надёжности).
    """
    if not well_rows:
        return 0.0, _score_label(0.0)

    avg_completeness = float(np.mean([r['Заполненность, %'] for r in well_rows]))
    avg_outliers = float(np.mean([r['Выбросов, %'] for r in well_rows]))
    any_non_monotonic = any(r['Глубина немонотонна'] == 'да' for r in well_rows)
    any_step_inconsistent = any(r['Шаг непостоянен'] == 'да' for r in well_rows)
    total_duplicates = sum(r['Дублей по глубине'] for r in well_rows)

    score = 100.0
    score -= (100 - avg_completeness) * 0.5
    score -= avg_outliers * 0.3
    score -= 15 if any_non_monotonic else 0
    score -= 10 if any_step_inconsistent else 0
    score -= min(10.0, total_duplicates * 0.5)
    score = max(0.0, min(100.0, score))

    return round(score, 1), _score_label(score)


def build_well_score_summary(qc_df):
    """
    Строит сводку по скважинам на основе таблицы из build_qc_report:
    число кривых, средняя заполненность/выбросы и итоговая оценка
    качества скважины (0-100) с текстовой меткой надёжности.
    """
    if qc_df.empty:
        return pd.DataFrame()

    rows = []
    for well_name, group in qc_df.groupby('Скважина'):
        well_rows = group.to_dict('records')
        score, label = compute_well_score(well_rows)
        rows.append({
            'Скважина': well_name,
            'Кривых': len(well_rows),
            'Средняя заполненность, %': round(float(group['Заполненность, %'].mean()), 1),
            'Средняя доля выбросов, %': round(float(group['Выбросов, %'].mean()), 1),
            'Оценка качества': score,
            'Надёжность': label,
        })

    return pd.DataFrame(rows).sort_values('Оценка качества', ascending=False).reset_index(drop=True)
