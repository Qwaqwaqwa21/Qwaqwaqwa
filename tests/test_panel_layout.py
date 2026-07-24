# coding: utf-8
"""
Тесты на разметку планшета: закреплённость ряда линейки за кривой (не должна
"плавать" в зависимости от того, какие ещё кривые есть в конкретной скважине),
логарифмическую сетку для сопротивления/МКЗ и явные ручные границы шкалы.
"""
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

from plotting import (
    plot_well_panel, DEFAULT_TRACKS_CONFIG, apply_curve_limit_overrides,
    active_track_ids, track_x_range
)


def make_instance(mean, scale=1.0, n=50, file_name='a.las'):
    depth = np.arange(1000, 1000 + n, 1.0)
    rng = np.random.default_rng(0)
    values = mean + scale * rng.normal(size=n)
    return {'depth': depth, 'values': values, 'file_name': file_name, 'depth_range': (depth.min(), depth.max())}


def get_curve_row_offset(fig, mnemonic):
    """Находит смещение (offset) линейки нужной кривой по подписи её оси X."""
    for ax in fig.axes:
        if ax.get_xlabel().startswith(mnemonic):
            offset = ax.spines["top"].get_position()
            return offset[1]
    return None


class TestCurveRowStability:
    def test_curve_row_is_stable_regardless_of_other_curves_present(self):
        # Трек "Стандартный каротаж": RS(0), KS(1), PS(2), DS(3) по конфигу.
        # Скважина A: все 4 кривые. Скважина B: только KS и DS (без RS/PS).
        merged_a = {
            'RS': [make_instance(1.2)], 'KS': [make_instance(2.0)],
            'PS': [make_instance(5.0)], 'DS': [make_instance(0.2, 0.01)],
        }
        merged_b = {
            'KS': [make_instance(2.0)], 'DS': [make_instance(0.2, 0.01)],
        }

        fig_a, _ = plot_well_panel('A', merged_a, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        offset_ks_a = get_curve_row_offset(fig_a, 'KS')
        offset_ds_a = get_curve_row_offset(fig_a, 'DS')
        plt.close(fig_a)

        fig_b, _ = plot_well_panel('B', merged_b, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        offset_ks_b = get_curve_row_offset(fig_b, 'KS')
        offset_ds_b = get_curve_row_offset(fig_b, 'DS')
        plt.close(fig_b)

        assert offset_ks_a == offset_ks_b, "KS должна сидеть в одном и том же ряду независимо от наличия RS/PS"
        assert offset_ds_a == offset_ds_b, "DS должна сидеть в одном и том же ряду независимо от наличия RS/PS"

    def test_multi_instance_curve_uses_single_row(self):
        # Если у одной кривой несколько файлов-источников, она всё равно
        # должна занимать только один ряд линейки, а не по ряду на файл.
        merged = {
            'RS': [make_instance(1.2, file_name='run1.las'), make_instance(1.3, file_name='run2.las')],
            'KS': [make_instance(2.0)],
        }
        fig, _ = plot_well_panel('A', merged, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        rs_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('RS')]
        assert len(rs_axes) == 1
        plt.close(fig)


class TestResistivityLogGrid:
    def test_mkz_track_is_log_grid(self):
        assert DEFAULT_TRACKS_CONFIG[11]['name'] == 'МКЗ'
        assert DEFAULT_TRACKS_CONFIG[11]['grid'] == 'log'

    def test_all_ohm_m_tracks_are_log_grid(self):
        for track_id, config in DEFAULT_TRACKS_CONFIG.items():
            if config.get('ylabel') == 'Ом·м':
                assert config['grid'] == 'log', f"Трек {config['name']} с Ом·м должен быть log"


class TestExplicitCurveLimits:
    def test_ik_bk_have_fixed_range(self):
        resist_track = DEFAULT_TRACKS_CONFIG[5]
        curve_limits = {c['mnemonic']: c.get('limits') for c in resist_track['curves']}
        assert curve_limits['IK'] == (0.1, 100)
        assert curve_limits['BK'] == (0.1, 100)
        assert curve_limits.get('RP') is None
        assert curve_limits.get('MBK') is None

    def test_explicit_limits_used_instead_of_autoscale(self):
        # RP без явных границ; принудительно задаём экстремальные данные —
        # если бы автоподбор сработал, диапазон был бы совсем другим.
        merged = {'IK': [make_instance(50, scale=1)]}  # данные далеко за пределами 0.1-100? нет, внутри
        fig, _ = plot_well_panel('A', merged, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        ik_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('IK')]
        assert len(ik_axes) == 1
        vmin, vmax = ik_axes[0].get_xlim()
        assert vmin == 0.1
        assert vmax == 100
        plt.close(fig)


class TestApplyCurveLimitOverrides:
    def test_override_sets_curve_limits(self):
        overrides = {'GK': (0.0, 150.0)}
        new_config = apply_curve_limit_overrides(DEFAULT_TRACKS_CONFIG, overrides)
        gk_spec = next(c for c in new_config[3]['curves'] if c['mnemonic'] == 'GK')
        assert gk_spec['limits'] == (0.0, 150.0)

    def test_override_does_not_mutate_original_config(self):
        overrides = {'GK': (0.0, 150.0)}
        apply_curve_limit_overrides(DEFAULT_TRACKS_CONFIG, overrides)
        gk_spec = next(c for c in DEFAULT_TRACKS_CONFIG[3]['curves'] if c['mnemonic'] == 'GK')
        assert 'limits' not in gk_spec

    def test_no_overrides_returns_same_config(self):
        result = apply_curve_limit_overrides(DEFAULT_TRACKS_CONFIG, {})
        assert result is DEFAULT_TRACKS_CONFIG

    def test_override_affects_rendered_panel(self):
        overrides = {'GK': (0.0, 150.0)}
        new_config = apply_curve_limit_overrides(DEFAULT_TRACKS_CONFIG, overrides)
        merged = {'GK': [make_instance(50, scale=5)]}
        fig, _ = plot_well_panel('A', merged, new_config, 1000, 1050)
        gk_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('GK')]
        vmin, vmax = gk_axes[0].get_xlim()
        assert (vmin, vmax) == (0.0, 150.0)
        plt.close(fig)


def _find_main_axes_colspan(fig, mnemonic):
    """
    Находит колонку (colspan в gridspec) трека, где нарисована линейка
    указанной кривой — по совпадению bbox линейки (twiny-ось) с одной из
    "главных" осей трека (у которых есть subplotspec).
    """
    for ax in fig.axes:
        if ax.get_xlabel().startswith(mnemonic):
            for ax2 in fig.axes:
                ss = ax2.get_subplotspec()
                if ss is not None and ax2.get_position().bounds == ax.get_position().bounds:
                    return ss.colspan
    return None


class TestActiveTrackIds:
    def test_returns_track_ids_with_data_only(self):
        merged = {'RS': [make_instance(5)], 'GK': [make_instance(8)]}
        # RS -> трек 1 (Стандартный каротаж), GK -> трек 3 (Радиоактивные методы)
        assert active_track_ids(merged, DEFAULT_TRACKS_CONFIG) == [1, 3]

    def test_empty_curves_excluded(self):
        merged = {'RS': [], 'GK': [make_instance(8)]}
        assert active_track_ids(merged, DEFAULT_TRACKS_CONFIG) == [3]

    def test_no_data_returns_empty_list(self):
        assert active_track_ids({}, DEFAULT_TRACKS_CONFIG) == []


class TestForcedTrackIdsAlignment:
    def test_without_forced_ids_same_track_lands_in_different_columns(self):
        # Регрессионный кейс, который нашёл ревьюер: у скважины A нет данных
        # для трека 'Стандартный каротаж' (только RS), у B его тоже нет (GK,
        # IK) — но т.к. состав активных треков определяется независимо для
        # каждой скважины, GK оказывается в разных колонках при сопоставлении
        # side-by-side.
        merged_a = {'RS': [make_instance(5)], 'GK': [make_instance(8)]}
        merged_b = {'GK': [make_instance(8)], 'IK': [make_instance(50)]}
        fig_a, _ = plot_well_panel('A', merged_a, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        fig_b, _ = plot_well_panel('B', merged_b, DEFAULT_TRACKS_CONFIG, 1000, 1050)
        col_a = _find_main_axes_colspan(fig_a, 'GK')
        col_b = _find_main_axes_colspan(fig_b, 'GK')
        assert col_a != col_b  # документирует баг без forced_track_ids
        plt.close(fig_a)
        plt.close(fig_b)

    def test_with_forced_ids_same_track_lands_in_same_column(self):
        merged_a = {'RS': [make_instance(5)], 'GK': [make_instance(8)]}
        merged_b = {'GK': [make_instance(8)], 'IK': [make_instance(50)]}
        union = sorted(set(active_track_ids(merged_a, DEFAULT_TRACKS_CONFIG)) |
                        set(active_track_ids(merged_b, DEFAULT_TRACKS_CONFIG)))

        fig_a, _ = plot_well_panel('A', merged_a, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                    forced_track_ids=union)
        fig_b, _ = plot_well_panel('B', merged_b, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                    forced_track_ids=union)
        col_a = _find_main_axes_colspan(fig_a, 'GK')
        col_b = _find_main_axes_colspan(fig_b, 'GK')
        assert col_a == col_b == range(2, 3)
        plt.close(fig_a)
        plt.close(fig_b)

    def test_forced_track_ids_renders_empty_track_for_missing_data(self):
        # Трек 'Сопротивление' (IK) принудительно включён для скважины A,
        # хотя данных по нему у неё нет — колонка должна просто быть пустой,
        # а не приводить к ошибке.
        merged_a = {'GK': [make_instance(8)]}
        fig, _ = plot_well_panel('A', merged_a, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                  forced_track_ids=[3, 5])
        assert fig is not None
        ik_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('IK')]
        assert ik_axes == []
        plt.close(fig)


class TestForcedTrackAndCurveLimits:
    def test_forced_track_limits_overrides_per_well_autoscale(self):
        # Трек 7 'Потенциал' (SP, SP_N) имеет limits: auto — обычный
        # автоподбор по данным именно этой скважины даёт узкий диапазон.
        merged = {'SP': [make_instance(50, scale=1)]}
        fig, _ = plot_well_panel('A', merged, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                  forced_track_ids=[7],
                                  forced_track_limits={7: (0.0, 500.0)})
        # Главная ось трека 7 — единственная с colspan (1, 2) (0 = трек глубины).
        potential_ax = next(
            ax for ax in fig.axes
            if ax.get_subplotspec() is not None and ax.get_subplotspec().colspan == range(1, 2)
        )
        assert potential_ax.get_xlim() == (0.0, 500.0)
        plt.close(fig)

    def test_forced_curve_limits_overrides_auto_per_curve_ruler(self):
        merged = {'GK': [make_instance(50, scale=2)]}
        fig, _ = plot_well_panel('A', merged, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                  forced_track_ids=[3],
                                  forced_curve_limits={'GK': (0.0, 999.0)})
        gk_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('GK')]
        assert gk_axes[0].get_xlim() == (0.0, 999.0)
        plt.close(fig)

    def test_explicit_config_limit_still_wins_over_forced_curve_limits(self):
        # IK (трек 5) имеет жёсткую границу в конфиге кривой (0.1, 100) —
        # она приоритетнее forced_curve_limits.
        merged = {'IK': [make_instance(50, scale=5)]}
        fig, _ = plot_well_panel('A', merged, DEFAULT_TRACKS_CONFIG, 1000, 1050,
                                  forced_track_ids=[5],
                                  forced_curve_limits={'IK': (0.0, 5.0)})
        ik_axes = [ax for ax in fig.axes if ax.get_xlabel().startswith('IK')]
        assert ik_axes[0].get_xlim() == (0.1, 100.0)
        plt.close(fig)


class TestTrackXRange:
    def test_combines_range_across_curve_instances(self):
        config = DEFAULT_TRACKS_CONFIG[3]  # Радиоактивные методы, GK/NGK/...
        pairs = [('GK', [make_instance(50, scale=5)]), ('NGK', [make_instance(10, scale=1)])]
        vmin, vmax = track_x_range(config, pairs)
        assert vmin is not None and vmax > vmin

    def test_explicit_track_limit_tuple_returned_as_is(self):
        config = DEFAULT_TRACKS_CONFIG[5]  # Сопротивление, limits=(0.1, 1000)
        assert track_x_range(config, []) == (0.1, 1000)

    def test_no_data_returns_none(self):
        config = DEFAULT_TRACKS_CONFIG[3]
        assert track_x_range(config, [('GK', [])]) is None
