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

from plotting import plot_well_panel, DEFAULT_TRACKS_CONFIG, apply_curve_limit_overrides


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
