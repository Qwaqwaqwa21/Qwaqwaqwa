# coding: utf-8
import numpy as np

from qc import build_qc_report, compute_well_score, build_well_score_summary


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


class TestOutlierDetectionInReport:
    def test_clean_data_has_zero_outliers(self):
        depth = np.arange(1000, 1030, 1.0)
        values = np.full(30, 50.0)  # константа - без выбросов
        f1 = make_file_data('a.las', 'W1', depth, {'GK': values})
        df = build_qc_report({'W1': [f1]})
        assert df.iloc[0]['Выбросов, %'] == 0.0

    def test_spike_is_detected_as_outlier(self):
        depth = np.arange(1000, 1030, 1.0)
        values = np.full(30, 50.0)
        values[5] = 5000.0  # явный выброс
        f1 = make_file_data('a.las', 'W1', depth, {'GK': values})
        df = build_qc_report({'W1': [f1]})
        assert df.iloc[0]['Выбросов, %'] > 0.0


class TestDepthMonotonicity:
    def test_monotonic_depth_flagged_ok(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1001, 1002], {'GK': [1, 2, 3]})
        df = build_qc_report({'W1': [f1]})
        assert df.iloc[0]['Глубина немонотонна'] == 'нет'

    def test_reversed_depth_flagged(self):
        f1 = make_file_data('a.las', 'W1', [1000, 1002, 1001], {'GK': [1, 2, 3]})
        df = build_qc_report({'W1': [f1]})
        assert df.iloc[0]['Глубина немонотонна'] == 'да'


class TestComputeWellScore:
    def test_perfect_data_scores_high(self):
        rows = [{
            'Заполненность, %': 100.0, 'Выбросов, %': 0.0,
            'Глубина немонотонна': 'нет', 'Шаг непостоянен': 'нет',
            'Дублей по глубине': 0,
        }]
        score, label = compute_well_score(rows)
        assert score == 100.0
        assert label == 'высокая'

    def test_bad_data_scores_low(self):
        rows = [{
            'Заполненность, %': 40.0, 'Выбросов, %': 30.0,
            'Глубина немонотонна': 'да', 'Шаг непостоянен': 'да',
            'Дублей по глубине': 50,
        }]
        score, label = compute_well_score(rows)
        assert score < 70
        assert label == 'низкая'

    def test_empty_rows_scores_zero(self):
        score, label = compute_well_score([])
        assert score == 0.0
        assert label == 'низкая'

    def test_score_never_negative(self):
        rows = [{
            'Заполненность, %': 0.0, 'Выбросов, %': 100.0,
            'Глубина немонотонна': 'да', 'Шаг непостоянен': 'да',
            'Дублей по глубине': 1000,
        }]
        score, _ = compute_well_score(rows)
        assert score >= 0.0


class TestBuildWellScoreSummary:
    def test_empty_qc_df_returns_empty(self):
        import pandas as pd
        summary = build_well_score_summary(pd.DataFrame())
        assert summary.empty

    def test_summary_ranks_wells_by_score(self):
        good = make_file_data('a.las', 'GOOD', np.arange(1000, 1020, 1.0), {'GK': np.full(20, 50.0)})
        bad_values = np.full(20, 50.0)
        bad_values[::2] = np.nan
        bad = make_file_data('b.las', 'BAD', np.arange(1000, 1020, 1.0), {'GK': bad_values})

        qc_df = build_qc_report({'GOOD': [good], 'BAD': [bad]})
        summary = build_well_score_summary(qc_df)

        assert list(summary['Скважина'])[0] == 'GOOD'
        assert summary.iloc[0]['Оценка качества'] > summary.iloc[1]['Оценка качества']
