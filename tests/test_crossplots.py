# coding: utf-8
import numpy as np
import plotly.graph_objects as go

from crossplots import build_crossplot, build_histogram


class TestBuildCrossplot:
    def test_returns_figure_for_valid_data(self):
        x = np.linspace(1, 100, 50)
        y = 2 * x + 5
        fig = build_crossplot(x, y, 'NPHI', 'RHOB')
        assert isinstance(fig, go.Figure)

    def test_none_when_no_valid_pairs(self):
        x = np.full(10, np.nan)
        y = np.full(10, np.nan)
        fig = build_crossplot(x, y, 'NPHI', 'RHOB')
        assert fig is None

    def test_nan_pairs_are_excluded_not_crashing(self):
        x = np.array([1.0, np.nan, 3.0, 4.0])
        y = np.array([1.0, 2.0, np.nan, 4.0])
        fig = build_crossplot(x, y, 'X', 'Y')
        assert isinstance(fig, go.Figure)
        scatter_trace = fig.data[0]
        assert len(scatter_trace.x) == 2  # только пары (1,1) и (4,4) валидны

    def test_log_axis_excludes_non_positive_values(self):
        x = np.array([-1.0, 0.0, 1.0, 10.0, 100.0])
        y = np.array([2.0, 3.0, 1.0, 5.0, 8.0])
        fig = build_crossplot(x, y, 'X', 'Y', log_x=True, show_regression=False)
        scatter_trace = fig.data[0]
        assert len(scatter_trace.x) == 3  # x=-1 и x=0 не положительны, исключены

    def test_perfect_linear_relationship_gives_r2_near_one(self):
        x = np.linspace(1, 50, 50)
        y = 3 * x + 7
        fig = build_crossplot(x, y, 'X', 'Y', show_regression=True)
        regression_trace = fig.data[1]
        assert 'R²=1.000' in regression_trace.name

    def test_depth_values_used_for_hover(self):
        x = np.linspace(1, 10, 10)
        y = np.linspace(1, 10, 10)
        depth = np.linspace(1000, 1009, 10)
        fig = build_crossplot(x, y, 'X', 'Y', depth_values=depth)
        assert fig.data[0].customdata is not None


class TestBuildHistogram:
    def test_returns_figure_for_valid_data(self):
        values = np.random.default_rng(0).normal(size=100)
        fig = build_histogram(values, 'GK')
        assert isinstance(fig, go.Figure)

    def test_none_when_all_nan(self):
        values = np.full(10, np.nan)
        fig = build_histogram(values, 'GK')
        assert fig is None

    def test_median_line_present(self):
        values = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        fig = build_histogram(values, 'GK')
        assert len(fig.layout.shapes) == 1  # вертикальная линия медианы
