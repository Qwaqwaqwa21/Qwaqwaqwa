# coding: utf-8
import plotly.graph_objects as go

from coverage import build_coverage_chart


def make_interval_table():
    return [
        {'Метод': 'GK', 'Кровля, м': '1000.0', 'Подошва, м': '1049.8', 'Мин. знач.': '4.7', 'Макс. знач.': '11.3', 'LAS-файл': 'a.las'},
        {'Метод': 'NGK', 'Кровля, м': '1000.0', 'Подошва, м': '1049.8', 'Мин. знач.': '3.5', 'Макс. знач.': '8.5', 'LAS-файл': 'a.las'},
        {'Метод': 'RS', 'Кровля, м': '1030.0', 'Подошва, м': '1089.8', 'Мин. знач.': '0.9', 'Макс. знач.': '1.4', 'LAS-файл': 'b.las'},
    ]


class TestBuildCoverageChart:
    def test_returns_none_for_empty_table(self):
        assert build_coverage_chart([], 1000, 1100) is None

    def test_returns_figure_with_one_trace_per_method(self):
        fig = build_coverage_chart(make_interval_table(), 980, 1110)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) == 3  # GK, NGK, RS

    def test_column_order_matches_first_appearance(self):
        fig = build_coverage_chart(make_interval_table(), 980, 1110)
        trace_x_values = [t.x[0] for t in fig.data]
        assert trace_x_values == ['GK', 'NGK', 'RS']

    def test_bar_base_and_height_match_interval(self):
        fig = build_coverage_chart(make_interval_table(), 980, 1110)
        gk_trace = fig.data[0]
        assert gk_trace.base[0] == 1000.0
        assert gk_trace.y[0] == 1049.8 - 1000.0

    def test_depth_axis_reversed(self):
        fig = build_coverage_chart(make_interval_table(), 980, 1110)
        assert fig.layout.yaxis.range[0] > fig.layout.yaxis.range[1]

    def test_multiple_intervals_for_same_method_become_separate_bars(self):
        table = [
            {'Метод': 'GK', 'Кровля, м': '1000.0', 'Подошва, м': '1020.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'a.las'},
            {'Метод': 'GK', 'Кровля, м': '1050.0', 'Подошва, м': '1070.0', 'Мин. знач.': '1', 'Макс. знач.': '2', 'LAS-файл': 'a.las'},
        ]
        fig = build_coverage_chart(table, 1000, 1070)
        assert len(fig.data) == 1  # один trace на метод...
        assert len(fig.data[0].x) == 2  # ...но с двумя барами (разрыв виден по base/height)
