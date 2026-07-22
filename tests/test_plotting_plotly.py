# coding: utf-8
import numpy as np
import plotly.graph_objects as go

from plotting import DEFAULT_TRACKS_CONFIG
from plotting_plotly import plot_well_panel_plotly


def make_merged_curves():
    depth = np.arange(1000.0, 1010.0, 0.5)
    return {
        'GK': [{'depth': depth, 'values': np.sin(depth), 'file_name': 'a.las', 'depth_range': (1000.0, 1009.5)}],
        'RS': [{'depth': depth, 'values': np.abs(np.cos(depth)) + 0.1, 'file_name': 'a.las', 'depth_range': (1000.0, 1009.5)}],
    }


class TestPlotWellPanelPlotly:
    def test_returns_figure_with_expected_traces(self):
        merged_curves = make_merged_curves()
        fig = plot_well_panel_plotly('WELL-1', merged_curves, DEFAULT_TRACKS_CONFIG, 1000.0, 1010.0)
        assert isinstance(fig, go.Figure)
        # Хотя бы по одной линии для GK (трек "Радиоактивные методы") и RS (трек "Стандартный каротаж")
        trace_names = [t.name for t in fig.data if t.name]
        assert 'GK' in trace_names
        assert 'RS' in trace_names

    def test_no_matching_curves_returns_none(self):
        empty_curves = {'UNKNOWN_CURVE': []}
        fig = plot_well_panel_plotly('WELL-1', empty_curves, DEFAULT_TRACKS_CONFIG, 1000.0, 1010.0)
        assert fig is None

    def test_depth_axis_is_reversed(self):
        merged_curves = make_merged_curves()
        fig = plot_well_panel_plotly('WELL-1', merged_curves, DEFAULT_TRACKS_CONFIG, 1000.0, 1010.0)
        assert fig.layout.yaxis.range[0] > fig.layout.yaxis.range[1]

    def test_multiple_instances_labelled_by_file(self):
        depth = np.arange(1000.0, 1005.0, 1.0)
        merged_curves = {
            'GK': [
                {'depth': depth, 'values': depth * 0 + 50, 'file_name': 'run1.las', 'depth_range': (1000.0, 1004.0)},
                {'depth': depth, 'values': depth * 0 + 60, 'file_name': 'run2.las', 'depth_range': (1000.0, 1004.0)},
            ]
        }
        fig = plot_well_panel_plotly('WELL-1', merged_curves, DEFAULT_TRACKS_CONFIG, 1000.0, 1005.0)
        trace_names = [t.name for t in fig.data if t.name]
        assert any('run1' in n for n in trace_names)
        assert any('run2' in n for n in trace_names)
