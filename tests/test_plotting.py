# coding: utf-8
import numpy as np
import pytest

from plotting import find_intervals, calculate_curve_limits


def make_instance(depth, values, file_name='well.las'):
    return {
        'depth': np.array(depth, dtype=float),
        'values': np.array(values, dtype=float),
        'file_name': file_name,
    }


class TestFindIntervals:
    def test_single_continuous_interval(self):
        depth = np.arange(1000, 1010, 0.5)
        values = np.ones_like(depth) * 5.0
        intervals = find_intervals([make_instance(depth, values)])
        assert len(intervals) == 1
        assert intervals[0]['top'] == pytest.approx(1000)
        assert intervals[0]['bottom'] == pytest.approx(1009.5)
        assert intervals[0]['min_value'] == pytest.approx(5.0)
        assert intervals[0]['max_value'] == pytest.approx(5.0)

    def test_gap_splits_into_two_intervals(self):
        depth = np.concatenate([np.arange(1000, 1005, 0.5), np.arange(1050, 1055, 0.5)])
        values = np.arange(len(depth), dtype=float)
        intervals = find_intervals([make_instance(depth, values)])
        assert len(intervals) == 2
        assert intervals[0]['bottom'] < intervals[1]['top']

    def test_nan_values_excluded(self):
        depth = np.arange(1000, 1010, 1.0)
        values = np.full_like(depth, np.nan)
        values[2:5] = [1.0, 2.0, 3.0]
        intervals = find_intervals([make_instance(depth, values)])
        assert len(intervals) == 1
        assert intervals[0]['min_value'] == pytest.approx(1.0)
        assert intervals[0]['max_value'] == pytest.approx(3.0)

    def test_no_valid_data_returns_no_intervals(self):
        depth = np.arange(1000, 1005, 1.0)
        values = np.full_like(depth, np.nan)
        intervals = find_intervals([make_instance(depth, values)])
        assert intervals == []

    def test_gap_threshold_adapts_to_actual_step(self):
        # Кривая с шагом 0.1 м: разрыв в 0.5 м не должен считаться непрерывным,
        # если бы порог остался фиксированным на старом дефолте (0.5 * 2 = 1.0),
        # сейчас порог берётся из фактического шага (0.1 * 2 = 0.2).
        depth = np.concatenate([np.arange(1000.0, 1001.0, 0.1), np.arange(1001.5, 1002.5, 0.1)])
        values = np.arange(len(depth), dtype=float)
        intervals = find_intervals([make_instance(depth, values)])
        assert len(intervals) == 2

    def test_multiple_instances_sorted_by_top(self):
        inst_a = make_instance(np.arange(1100, 1105, 1.0), np.arange(5), 'a.las')
        inst_b = make_instance(np.arange(1000, 1005, 1.0), np.arange(5), 'b.las')
        intervals = find_intervals([inst_a, inst_b])
        assert len(intervals) == 2
        assert intervals[0]['file_name'] == 'b.las'
        assert intervals[1]['file_name'] == 'a.las'


class TestCalculateCurveLimits:
    def test_empty_returns_none(self):
        vmin, vmax = calculate_curve_limits(np.array([np.nan, np.nan]))
        assert vmin is None and vmax is None

    def test_typical_linear_range(self):
        rng = np.random.default_rng(0)
        values = rng.normal(loc=50, scale=5, size=200)
        vmin, vmax = calculate_curve_limits(values, grid_type='linear', mnemonic='GK')
        assert vmin < 50 < vmax

    def test_log_grid_only_positive(self):
        values = np.array([1.0, 10.0, 100.0, 1000.0] * 5)
        vmin, vmax = calculate_curve_limits(values, grid_type='log', mnemonic='RP')
        assert vmin is not None and vmax is not None
        assert vmin > 0
        assert vmax > vmin

    def test_constant_value_padding(self):
        values = np.full(10, 3.0)
        vmin, vmax = calculate_curve_limits(values, grid_type='linear', mnemonic='UNKNOWN')
        assert vmin < 3.0 < vmax

    def test_small_range_curve_uses_expected_bounds(self):
        # DS ожидается в диапазоне ~0.175-0.245 (номинал каверномера)
        values = np.full(20, 0.2)
        vmin, vmax = calculate_curve_limits(values, grid_type='linear', mnemonic='DS')
        assert vmin < 0.2 < vmax
