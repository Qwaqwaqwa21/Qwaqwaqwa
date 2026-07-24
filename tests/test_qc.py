# coding: utf-8
import numpy as np

from qc import build_qc_report


def make_file_data(file_name, well_name, depth, curves):
    depth = np.array(depth, dtype=float)
    return {
        'file_name': file_name,
        'well_name': well_name,
        'depth': depth,
        'curves': {k: np.array(v, dtype=float) for k, v in curves.items()},
        'curve_descriptions': {k: '' for k in curves},
        'depth_range': (np.nanmin(depth), np.nanmax(depth)),
    }


class TestBuildQcReport:
    def test_empty_wells_data_returns_empty_df(self):
        df = build_qc_report({})
        assert df.empty

    def test_completeness_percentage(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1001, 1002, 1003],
                             {'GK': [1.0, np.nan, 3.0, np.nan]})
        df = build_qc_report({'W1': [f1]})
        row = df.iloc[0]
        assert row['Скважина'] == 'W1'
        assert row['Кривая'] == 'GK'
        assert row['Точек всего'] == 4
        assert row['Заполненность, %'] == 50.0

    def test_detects_duplicate_depths(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1000, 1001], {'GK': [1.0, 2.0, 3.0]})
        df = build_qc_report({'W1': [f1]})
        row = df.iloc[0]
        assert row['Дублей по глубине'] == 1

    def test_detects_inconsistent_step_across_files(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1000.1, 1000.2], {'GK': [1.0, 2.0, 3.0]})
        f2 = make_file_data('b.las', 'W1', [1000, 1000.5, 1001.0], {'GK': [4.0, 5.0, 6.0]})
        df = build_qc_report({'W1': [f1, f2]})
        row = df.iloc[0]
        assert row['Шаг непостоянен'] == 'да'
        assert row['Файлов'] == 2

    def test_consistent_step_flagged_as_not_inconsistent(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1000.5, 1001.0], {'GK': [1.0, 2.0, 3.0]})
        df = build_qc_report({'W1': [f1]})
        row = df.iloc[0]
        assert row['Шаг непостоянен'] == 'нет'

    def test_multiple_wells_and_curves(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1001], {'GK': [1.0, 2.0]})
        f2 = make_file_data('b.las', 'W2', [2000, 2001], {'NGK': [3.0, 4.0]})
        df = build_qc_report({'W1': [f1], 'W2': [f2]})
        assert set(df['Скважина']) == {'W1', 'W2'}
        assert set(df['Кривая']) == {'GK', 'NGK'}
