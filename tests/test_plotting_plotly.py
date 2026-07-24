# coding: utf-8
import numpy as np
import pandas as pd
import plotly.graph_objects as go

from plotting import DEFAULT_TRACKS_CONFIG
from plotting_plotly import plot_well_panel_plotly, plot_multi_well_panel_plotly


def make_merged_curves():
    depth = np.arange(1000.0, 1010.0, 0.5)
    return {
        'GK': [{'depth': depth, 'values': np.sin(depth), 'file_name': 'a.las', 'depth_range': (1000.0, 1009.5)}],
        'RS': [{'depth': depth, 'values': np.abs(np.cos(depth)) + 0.1, 'file_name': 'a.las', 'depth_range': (1000.0, 1009.5)}],
    }


def make_well(name, dmin, dmax, mnemonic='GK', zones_df=None):
    depth = np.linspace(dmin, dmax, 200)
    return {
        'well_name': name,
        'merged_curves': {
            mnemonic: [{'depth': depth, 'values': np.full(200, 5.0), 'file_name': f'{name}.las'}],
        },
        'depth_min': dmin,
        'depth_max': dmax,
        'zones_df': zones_df,
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

    def test_explicit_curve_limits_used_for_track_range(self):
        # IK/BK в "Сопротивление" имеют явную границу (0.1, 100) — трек-ось
        # (общая для всех кривых трека в Plotly-версии) должна её учитывать
        # вместо автоподбора по данным (значения тут намеренно за пределами
        # 0.1-100, чтобы отличить от автоподобранного диапазона).
        from plotting_plotly import _track_x_range
        config = DEFAULT_TRACKS_CONFIG[5]
        merged_curves = {
            'IK': [{'depth': None, 'values': np.full(10, 5000.0), 'file_name': 'a.las'}],
        }
        pairs = [(c['mnemonic'], merged_curves.get(c['mnemonic'], [])) for c in config['curves']]
        x_range = _track_x_range(config, pairs)
        assert x_range[0] <= 0.1
        assert x_range[1] >= 100


class TestPlotMultiWellPanelPlotly:
    def test_returns_none_for_empty_well_list(self):
        assert plot_multi_well_panel_plotly([], DEFAULT_TRACKS_CONFIG) is None

    def test_returns_none_when_no_well_has_active_tracks(self):
        wells = [make_well('W1', 1000, 1010, mnemonic='UNKNOWN_CURVE')]
        assert plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG) is None

    def test_column_count_matches_depth_plus_wells_times_tracks(self):
        # W1 has GK (track 'Радиоактивные методы'), W2 has RS (track
        # 'Стандартный каротаж') — union of active tracks is 2, so each
        # well repeats both track columns even though it only has data for one.
        wells = [make_well('W1', 1000, 1010, mnemonic='GK'), make_well('W2', 1005, 1015, mnemonic='RS')]
        fig = plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG)
        assert isinstance(fig, go.Figure)
        n_tracks = 2
        expected_cols = 1 + len(wells) * n_tracks
        assert len(fig.layout.annotations) >= expected_cols  # subplot titles alone already reach this

    def test_shared_depth_axis_spans_all_wells(self):
        wells = [make_well('W1', 1000, 1010), make_well('W2', 990, 1005)]
        fig = plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG)
        assert fig.layout.yaxis.range == (1010, 990)

    def test_well_header_annotations_present(self):
        wells = [make_well('ALPHA', 1000, 1010), make_well('BETA', 1000, 1010)]
        fig = plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG)
        texts = [a.text for a in fig.layout.annotations]
        assert any('ALPHA' in t for t in texts)
        assert any('BETA' in t for t in texts)

    def test_same_track_gets_same_x_range_across_wells(self):
        # Same mnemonic, wildly different value ranges — with a shared
        # per-track scale, both wells' GK columns should get the same x range.
        depth1 = np.linspace(1000, 1010, 50)
        depth2 = np.linspace(1000, 1010, 50)
        wells = [
            {'well_name': 'W1', 'merged_curves': {'GK': [{'depth': depth1, 'values': np.full(50, 2.0), 'file_name': 'a.las'}]},
             'depth_min': 1000, 'depth_max': 1010, 'zones_df': None},
            {'well_name': 'W2', 'merged_curves': {'GK': [{'depth': depth2, 'values': np.full(50, 50.0), 'file_name': 'b.las'}]},
             'depth_min': 1000, 'depth_max': 1010, 'zones_df': None},
        ]
        fig = plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG)
        # col 2 = W1's GK track, col 3 = W2's GK track (1 track, 1 well each after depth col)
        assert list(fig.layout.xaxis2.range) == list(fig.layout.xaxis3.range)

    def test_zones_drawn_only_within_owning_well_columns(self):
        zones_w1 = pd.DataFrame({'Зона': ['Пласт А'], 'Кровля, м': [1002.0], 'Подошва, м': [1004.0]})
        wells = [
            make_well('W1', 1000, 1010, zones_df=zones_w1),
            make_well('W2', 1000, 1010, zones_df=None),
        ]
        fig = plot_multi_well_panel_plotly(wells, DEFAULT_TRACKS_CONFIG)
        # 1 track per well -> col 2 is W1's only track, col 3 is W2's only track.
        shape_axes = {s.xref for s in fig.layout.shapes}
        assert 'x2 domain' in shape_axes
        assert 'x3 domain' not in shape_axes
