# coding: utf-8
"""Конфигурация треков и построение каротажных планшетов."""
import os
import textwrap
from pathlib import Path

import numpy as np
import yaml
import matplotlib.pyplot as plt
import streamlit as st

# === Конфигурация треков по умолчанию (используется, если внешний YAML
# отсутствует или не может быть прочитан) ===
DEFAULT_TRACKS_CONFIG = {
    0: {'name': 'Глубина', 'width': 2.0, 'curves': [], 'grid': 'none', 'limits': 'none', 'ylabel': 'Глубина, м'},
    1: {
        'name': 'Стандартный каротаж',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'RS', 'color': 'blue', 'linestyle': '--', 'linewidth': 1.2},
            {'mnemonic': 'KS', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'PS', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'DS', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    2: {
        'name': 'Стандартный каротаж_500',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'KS_500', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'PS_500', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'DS_500', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    3: {
        'name': 'Радиоактивные методы',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GK', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'NGK', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'NKTD', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'NKTS', 'color': 'black', 'linestyle': ':', 'linewidth': 0.7}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    4: {
        'name': 'Радиоактивные методы_500',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GK_500', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'NGK_500', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    5: {
        'name': 'Сопротивление',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'RP', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'IK', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0, 'limits': (0.1, 100)},
            {'mnemonic': 'BK', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0, 'limits': (0.1, 100)},
            {'mnemonic': 'MBK', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    6: {
        'name': 'БКЗ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GZ1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZ5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'GZK', 'color': 'gold', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    7: {
        'name': 'Потенциал',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'SP', 'color': 'brown', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'SP_N', 'color': 'brown', 'linestyle': '--', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto',
        'ylabel': 'мВ'
    },
    8: {
        'name': 'VIKIZ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'VIKIZ1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'VIKIZ5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    9: {
        'name': '5IK',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'IK1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'IK5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    10: {
        'name': '5BK',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'BK1', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK2', 'color': 'black', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK3', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK4', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'BK5', 'color': 'purple', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'log',
        'limits': (0.1, 1000),
        'ylabel': 'Ом·м'
    },
    11: {
        'name': 'МКЗ',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'MGZ', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'MPZ', 'color': 'blue', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'log',
        'limits': 'shared',
        'ylabel': 'Ом·м'
    },
    12: {
        'name': 'Расширенный комплекс',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'DTP', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'GGK-P', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': 'Ед. изм.'
    },
    13: {
        'name': 'ЯМК',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'U1', 'color': 'black', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'U2', 'color': 'green', 'linestyle': '-', 'linewidth': 1.0},
            {'mnemonic': 'U3', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'shared',
        'ylabel': 'Ед. изм.'
    },
    14: {
        'name': 'Газовый',
        'width': 5.0,
        'curves': [
            {'mnemonic': 'GAZ', 'color': 'orange', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'GAZ_500', 'color': 'darkorange', 'linestyle': '--', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_per_curve',
        'ylabel': '%'
    },
    15: {
        'name': 'Кп',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kp', 'color': 'green', 'linestyle': '-', 'linewidth': 1.2},
            {'mnemonic': 'W', 'color': 'red', 'linestyle': '-', 'linewidth': 1.0}
        ],
        'grid': 'linear',
        'limits': 'auto_kp',
        'ylabel': 'Кп'
    },
    16: {
        'name': 'Кгл',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kgl', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'linear',
        'limits': 'auto_k',
        'ylabel': 'Кгл'
    },
    17: {
        'name': 'Кнг',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kn', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'linear',
        'limits': 'auto_k',
        'ylabel': 'Кнг'
    },
    18: {
        'name': 'Кпр',
        'width': 2.0,
        'curves': [
            {'mnemonic': 'Kpr', 'color': 'red', 'linestyle': '-', 'linewidth': 1.2}
        ],
        'grid': 'log',
        'limits': (0.01, 1000),
        'ylabel': 'Кпр'
    }
}

# Обратная совместимость: код/тесты, импортирующие TRACKS_CONFIG напрямую,
# по-прежнему получают дефолтную конфигурацию. Приложение должно вызывать
# load_tracks_config(), чтобы подхватывать правки внешнего YAML без рестарта.
TRACKS_CONFIG = DEFAULT_TRACKS_CONFIG


def get_tracks_config_path():
    """Путь к редактируемому YAML с конфигурацией треков (переопределяется TRACKS_CONFIG_PATH)."""
    return os.environ.get("TRACKS_CONFIG_PATH", str(Path(__file__).parent / "tracks_config.yaml"))


def _as_limits_tuple(limits):
    """Если limits — список из двух чисел (как приходит из YAML), приводит к tuple."""
    if isinstance(limits, list) and len(limits) == 2 and all(isinstance(v, (int, float)) for v in limits):
        return tuple(limits)
    return limits


def _normalize_limits(config):
    """
    YAML не различает tuple/list — числовые пары для 'limits' приводим к tuple.
    Проверяются как лимиты трека, так и опциональные лимиты отдельных кривых
    (curve_spec['limits']), заданные явно в конфигурации.
    """
    config['limits'] = _as_limits_tuple(config.get('limits'))
    for curve_spec in config.get('curves', []):
        if 'limits' in curve_spec:
            curve_spec['limits'] = _as_limits_tuple(curve_spec['limits'])
    return config


def load_tracks_config(path=None):
    """
    Загружает конфигурацию треков из редактируемого YAML-файла, чтобы петрофизик
    мог добавлять новые кривые/треки без правки исходного кода приложения.
    При отсутствии файла или ошибке чтения возвращает встроенную конфигурацию по умолчанию.
    """
    path = Path(path or get_tracks_config_path())
    if not path.exists():
        return DEFAULT_TRACKS_CONFIG

    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw_config = yaml.safe_load(f)
        if not raw_config:
            raise ValueError("Файл конфигурации треков пуст")
        return {
            int(track_id): _normalize_limits(dict(config))
            for track_id, config in raw_config.items()
        }
    except Exception as e:
        st.warning(f"⚠️ Не удалось прочитать {path.name} ({e}), используется конфигурация по умолчанию")
        return DEFAULT_TRACKS_CONFIG


def apply_curve_limit_overrides(tracks_config, overrides):
    """
    Возвращает копию tracks_config с ручными границами шкалы, заданными
    пользователем в интерфейсе (per-mnemonic), поверх настроек из
    tracks_config.yaml — сам файл при этом не изменяется.

    overrides: словарь {мнемоника: (min, max)}. Мнемоника, которой нет в
    overrides, использует границы как обычно (явные из конфигурации или
    автоподбор по данным).
    """
    if not overrides:
        return tracks_config

    new_config = {}
    for track_id, config in tracks_config.items():
        new_curves = []
        for curve_spec in config['curves']:
            curve_spec = dict(curve_spec)
            override = overrides.get(curve_spec['mnemonic'])
            if override is not None:
                curve_spec['limits'] = tuple(override)
            new_curves.append(curve_spec)
        new_config[track_id] = {**config, 'curves': new_curves}
    return new_config


def wrap_text(text, width=20):
    """Перенос текста по словам с заданной шириной"""
    return textwrap.fill(text, width=width, break_long_words=False)


def find_intervals(curve_instances, depth_step=0.5):
    """
    Находит непрерывные интервалы для кривой (кровля/подошва) + мин/макс значения
    """
    intervals = []
    for instance in curve_instances:
        depth = instance['depth']
        values = instance['values']
        file_name = instance['file_name']

        if depth is None or values is None:
            continue

        depth = np.array(depth)
        values = np.array(values)

        valid_mask = np.isfinite(values) & np.isfinite(depth)
        if not np.any(valid_mask):
            continue

        valid_depth = depth[valid_mask]
        valid_values = values[valid_mask]

        if len(valid_depth) == 0:
            continue

        sorted_indices = np.argsort(valid_depth)
        sorted_depth = valid_depth[sorted_indices]
        sorted_values = valid_values[sorted_indices]

        # Порог разрыва определяем по фактическому шагу дискретизации этой
        # кривой, а не по фиксированному аргументу по умолчанию — так интервалы
        # корректно определяются и для логов с шагом, отличным от 0.5 м.
        if len(sorted_depth) > 1:
            actual_step = np.median(np.diff(sorted_depth))
            if actual_step > 0:
                depth_step = actual_step

        intervals_in_instance = []
        start_idx = 0
        start_depth = sorted_depth[0]

        for i in range(1, len(sorted_depth)):
            if sorted_depth[i] - sorted_depth[i-1] > depth_step * 2:
                end_idx = i - 1
                end_depth = sorted_depth[end_idx]

                interval_values = sorted_values[start_idx:end_idx+1]
                min_val = np.nanmin(interval_values) if len(interval_values) > 0 else np.nan
                max_val = np.nanmax(interval_values) if len(interval_values) > 0 else np.nan

                intervals_in_instance.append({
                    'top': start_depth,
                    'bottom': end_depth,
                    'file_name': file_name,
                    'min_value': min_val,
                    'max_value': max_val
                })

                start_idx = i
                start_depth = sorted_depth[i]

        end_idx = len(sorted_depth) - 1
        end_depth = sorted_depth[end_idx]
        interval_values = sorted_values[start_idx:end_idx+1]
        min_val = np.nanmin(interval_values) if len(interval_values) > 0 else np.nan
        max_val = np.nanmax(interval_values) if len(interval_values) > 0 else np.nan

        intervals_in_instance.append({
            'top': start_depth,
            'bottom': end_depth,
            'file_name': file_name,
            'min_value': min_val,
            'max_value': max_val
        })

        intervals.extend(intervals_in_instance)

    intervals.sort(key=lambda x: x['top'])
    return intervals


def calculate_curve_limits(curve_data, grid_type='linear', mnemonic=''):
    """
    Рассчитывает лимиты оси для кривой с корректной обработкой малого разброса.
    """
    valid_vals = curve_data[np.isfinite(curve_data)]
    if len(valid_vals) == 0:
        return None, None

    median = np.nanmedian(valid_vals)
    mad = np.nanmedian(np.abs(valid_vals - median))

    if mad > 0:
        lower_bound = median - 3 * mad
        upper_bound = median + 3 * mad
        filtered_vals = valid_vals[(valid_vals >= lower_bound) & (valid_vals <= upper_bound)]
    else:
        filtered_vals = valid_vals

    if len(filtered_vals) < max(5, len(valid_vals) * 0.3):
        filtered_vals = valid_vals

    if len(filtered_vals) < 5:
        vmin, vmax = np.nanmin(filtered_vals), np.nanmax(filtered_vals)
        if vmin == vmax:
            if mnemonic in ['DS', 'DS_500']:
                return 0.17, 0.25
            elif mnemonic in ['RS', 'RS_500']:
                return 0.9, 1.6
            return vmin - 0.1, vmax + 0.1
        padding = (vmax - vmin) * 0.5
        return vmin - padding, vmax + padding

    if grid_type == 'log':
        valid_positive = filtered_vals[filtered_vals > 0]
        if len(valid_positive) == 0:
            return None, None
        vmin = np.nanpercentile(valid_positive, 5)
        vmax = np.nanpercentile(valid_positive, 95)
        if vmin <= 0:
            vmin = np.min(valid_positive[valid_positive > 0])
        vmin = 10 ** np.floor(np.log10(vmin))
        vmax = 10 ** np.ceil(np.log10(vmax))
        return max(0.1, vmin), min(10000, vmax)
    else:
        small_range_curves = {
            'DS': (0.175, 0.245),
            'DS_500': (0.175, 0.245),
            'RS': (1.0, 1.5),
            'RS_500': (1.0, 1.5),
            'KS': (0.0, 5.0),
            'KS_500': (0.0, 5.0),
            'PS': (0.0, 10.0),
            'PS_500': (0.0, 10.0),
            'GGK-P': (0.0, 5.0)
        }

        if mnemonic in small_range_curves:
            vmin = np.nanpercentile(filtered_vals, 20)
            vmax = np.nanpercentile(filtered_vals, 90)

            min_expected, max_expected = small_range_curves[mnemonic]
            vmin = max(vmin, min_expected * 0.9)
            vmax = min(vmax, max_expected * 1.1)

            if vmax - vmin < (max_expected - min_expected) * 0.3:
                center = (min_expected + max_expected) / 2
                half_range = (max_expected - min_expected) * 0.6
                return center - half_range, center + half_range

            return vmin, vmax
        else:
            vmin = np.nanpercentile(filtered_vals, 5)
            vmax = np.nanpercentile(filtered_vals, 95)

            range_val = vmax - vmin
            if range_val < 1e-6:
                center = (vmin + vmax) / 2
                return center - 0.5, center + 0.5

            padding = max((vmax - vmin) * 0.1, 0.1)
            return vmin - padding, vmax + padding


def plot_well_panel(well_name, merged_curves, tracks_config, depth_min, depth_max, figsize_width_cm=50):
    """
    Строит планшет для одной скважины с корректными лимитами для кривых с малым разбросом
    и таблицей интервалов с мин/макс значениями.

    Вызывающий код отвечает за plt.close(fig) после использования фигуры.
    """
    active_tracks = [(0, tracks_config[0], [])]
    for track_id in sorted(tracks_config.keys()):
        if track_id == 0:
            continue

        config = tracks_config[track_id]
        curves_present = [c['mnemonic'] for c in config['curves']
                         if c['mnemonic'] in merged_curves and len(merged_curves[c['mnemonic']]) > 0]
        if curves_present:
            active_tracks.append((track_id, config, curves_present))

    if len(active_tracks) <= 1:
        st.warning(f"⚠️ Для скважины {well_name} нет данных для построения треков кривых")
        return None, None

    # Для каждой кривой резервируем свой "ряд" линейки по её позиции в
    # tracks_config, а не по порядку появления в данных этой конкретной
    # скважины — иначе одна и та же кривая оказывалась бы в разных рядах
    # (и с виду "плавала") в зависимости от того, какие ещё кривые есть в
    # файлах именно этой скважины.
    max_instances_in_any_track = 0
    track_curve_instances = {}

    for track_id, config, curves_present in active_tracks:
        if track_id == 0:
            continue

        instances_list = []
        max_row_used = -1
        for curve_idx, curve_spec in enumerate(config['curves']):
            mnemonic = curve_spec['mnemonic']
            if mnemonic in merged_curves:
                instances = merged_curves[mnemonic]
                if instances:
                    instances_list.append((mnemonic, instances))
                    max_row_used = max(max_row_used, curve_idx)

        track_curve_instances[track_id] = instances_list
        if max_row_used >= 0:
            max_instances_in_any_track = max(max_instances_in_any_track, max_row_used + 1)

    total_width_cm = sum([config['width'] for _, config, _ in active_tracks])
    total_width_cm += (len(active_tracks) - 1) * 1.0

    figsize_width_inch = total_width_cm * 0.3937
    figsize_height_inch = 14

    fig = plt.figure(figsize=(figsize_width_inch, figsize_height_inch))

    avg_track_width_cm = total_width_cm / len(active_tracks)
    wspace = 1.0 / avg_track_width_cm

    width_ratios = [config['width'] for _, config, _ in active_tracks]
    gs = fig.add_gridspec(1, len(active_tracks), width_ratios=width_ratios, wspace=wspace)

    base_offset = 1.08
    offset_step = 0.075
    unified_title_offset = base_offset + max_instances_in_any_track * offset_step + 0.12

    for idx, (track_id, config, curves_present) in enumerate(active_tracks):
        ax_main = fig.add_subplot(gs[0, idx])
        ax_main.set_ylim(depth_max, depth_min)

        if track_id == 0:
            wrapped_title = wrap_text('Глубина', width=12)
            ax_main.text(0.5, unified_title_offset, wrapped_title, transform=ax_main.transAxes,
                        fontsize=10, fontweight='bold', ha='center', va='bottom')
            ax_main.text(0.5, unified_title_offset - 0.08, 'м', transform=ax_main.transAxes,
                        fontsize=9, ha='center', va='top', color='dimgray')

            depth_range = depth_max - depth_min
            step = 200 if depth_range > 1000 else (100 if depth_range > 500 else (50 if depth_range > 200 else 20))
            ticks = np.arange(np.ceil(depth_min / step) * step,
                            np.floor(depth_max / step) * step + step, step)
            ax_main.set_yticks(ticks)
            ax_main.set_yticklabels([f"{t:.0f}" for t in ticks], fontsize=9)

            ax_main.grid(axis='y', color='lightgray', linestyle='-', linewidth=0.8, alpha=0.8)
            ax_main.grid(axis='x', visible=False)
            ax_main.set_xticks([])
            ax_main.set_xlim(0, 1)
            continue

        if config['grid'] == 'log':
            ax_main.set_xscale('log')
            ax_main.grid(which='both', color='lightgray', linestyle=':', linewidth=0.6, alpha=0.7)
        else:
            ax_main.grid(which='major', color='lightgray', linestyle='-', linewidth=0.6, alpha=0.7)

        ax_main.set_xticks([])
        ax_main.set_xlabel('')

        if idx > 0:
            plt.setp(ax_main.get_yticklabels(), visible=False)
            ax_main.tick_params(axis='y', length=0)

        curve_axes = []
        curve_values_all = []
        instances_in_track = track_curve_instances.get(track_id, [])
        row_index_by_mnemonic = {c['mnemonic']: i for i, c in enumerate(config['curves'])}

        instance_colors = [
            (0.0, 0.0, 1.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (1.0, 0.5, 0.0),
            (0.5, 0.0, 0.5), (0.0, 0.5, 0.5), (0.5, 0.5, 0.0), (1.0, 0.0, 1.0)
        ]

        for mnemonic, instances in instances_in_track:
            curve_spec = next((c for c in config['curves'] if c['mnemonic'] == mnemonic), None)
            if not curve_spec:
                continue

            base_color = curve_spec['color']
            base_linestyle = curve_spec['linestyle']
            base_linewidth = curve_spec['linewidth']

            combined_values = []
            file_names = []
            for inst_idx, instance in enumerate(instances):
                depth = instance['depth']
                values = instance['values']
                file_name = instance['file_name']

                valid_mask = np.isfinite(values) & np.isfinite(depth)
                if not np.any(valid_mask):
                    continue

                if len(instances) == 1:
                    color = base_color
                    linestyle = base_linestyle
                else:
                    color = instance_colors[inst_idx % len(instance_colors)]
                    linestyle = '-' if inst_idx == 0 else '--' if inst_idx == 1 else ':'

                ax_main.plot(values[valid_mask], depth[valid_mask],
                            color=color,
                            linestyle=linestyle,
                            linewidth=base_linewidth * (1.0 if inst_idx == 0 else 0.9),
                            alpha=0.9)

                curve_values_all.append(values[valid_mask])
                combined_values.append(values[valid_mask])
                file_names.append(file_name)

            if not combined_values:
                continue

            # Одна линейка на мнемонику (даже если у неё несколько файлов-
            # источников) в ряду, закреплённом за позицией кривой в
            # tracks_config, — ряд не зависит от того, какие ещё кривые
            # присутствуют именно в этой скважине.
            ax_curve = ax_main.twiny()
            curve_axes.append({
                'ax': ax_curve,
                'color': base_color,
                'mnemonic': mnemonic,
                'row': row_index_by_mnemonic[mnemonic],
                'values': np.concatenate(combined_values),
                'file_names': file_names,
                'curve_spec': curve_spec,
            })

        if config['limits'] == 'auto_per_curve':
            pass
        elif config['limits'] in ('auto', 'shared') and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            vmin, vmax = calculate_curve_limits(
                all_vals, grid_type='log' if config['grid'] == 'log' else 'linear', mnemonic=''
            )
            if vmin is not None and vmax is not None:
                ax_main.set_xlim(vmin, vmax)
        elif config['limits'] in ('auto_kp', 'auto_k') and curve_values_all:
            all_vals = np.concatenate(curve_values_all)
            max_val = np.nanmax(all_vals)
            ax_main.set_xlim(0, 40 if max_val > 1.0 else 0.4)
        elif isinstance(config['limits'], tuple):
            ax_main.set_xlim(*config['limits'])

        if curve_axes:
            for ca in curve_axes:
                # Ряд закреплён за позицией кривой в конфигурации трека, а не
                # за порядковым номером в списке присутствующих кривых.
                offset = base_offset + ca['row'] * offset_step

                ax_curve = ca['ax']
                ax_curve.spines["top"].set_position(("axes", offset))
                ax_curve.spines["top"].set_visible(True)
                ax_curve.spines["top"].set_edgecolor(ca['color'])
                ax_curve.spines["top"].set_linewidth(1.5)

                ax_curve.tick_params(axis='x', colors=ca['color'], labelsize=7,
                                   labeltop=True, labelbottom=False)

                # Явно заданная в конфигурации кривой граница (например, IK/BK
                # 0.1-100) имеет приоритет над автоподбором по данным.
                explicit_limits = ca['curve_spec'].get('limits')
                has_explicit = isinstance(explicit_limits, tuple) and len(explicit_limits) == 2

                if config['grid'] == 'log':
                    vmin, vmax = explicit_limits if has_explicit else calculate_curve_limits(
                        ca['values'], grid_type='log', mnemonic=ca['mnemonic']
                    )
                    if vmin is not None and vmax is not None:
                        ax_curve.set_xlim(vmin, vmax)
                        log_range = np.log10(vmax / vmin)
                        if log_range > 2:
                            ticks = [vmin, 10**((np.log10(vmin) + np.log10(vmax)) / 2), vmax]
                        else:
                            ticks = [vmin, vmax]
                        ax_curve.set_xticks(ticks)
                        ax_curve.set_xscale('log')
                else:
                    vmin, vmax = explicit_limits if has_explicit else calculate_curve_limits(
                        ca['values'], grid_type='linear', mnemonic=ca['mnemonic']
                    )
                    if vmin is not None and vmax is not None:
                        ax_curve.set_xlim(vmin, vmax)
                        range_val = vmax - vmin
                        if range_val > 100:
                            num_ticks = 3
                        elif range_val > 10:
                            num_ticks = 4
                        else:
                            num_ticks = 5
                        ticks = np.linspace(vmin, vmax, num_ticks)
                        ax_curve.set_xticks(ticks)

                unique_files = list(dict.fromkeys(ca['file_names']))
                if len(unique_files) > 1:
                    label = f"{ca['mnemonic']} ({len(unique_files)} файла(ов))"
                else:
                    label = ca['mnemonic']

                ax_curve.set_xlabel(label, fontsize=7.5, color=ca['color'],
                                  fontweight='bold', labelpad=2)

        wrapped_title = wrap_text(config['name'], width=18)
        header_color = curve_axes[0]['color'] if curve_axes else 'black'

        ax_main.text(0.5, unified_title_offset, wrapped_title, transform=ax_main.transAxes,
                     fontsize=10, fontweight='bold', ha='center', va='bottom',
                    color=header_color)

        if idx == len(active_tracks) - 1:
            ax_main.text(0.5, -0.06, config['ylabel'], transform=ax_main.transAxes,
                        fontsize=9, fontweight='bold', ha='center', va='top')

    panel_title_y = unified_title_offset + 0.09
    fig.text(0.5, panel_title_y, 'ПЛАНШЕТ',
            fontsize=18, fontweight='bold', ha='center', va='bottom')
    fig.text(0.5, panel_title_y - 0.03, f"Скважина: {well_name}",
            fontsize=11, ha='center', va='top', style='italic', color='dimgray')

    plt.tight_layout(rect=[0.015, 0.12, 0.985, panel_title_y - 0.05], h_pad=0.1, w_pad=0.1)

    interval_table = build_interval_table(merged_curves, tracks_config)

    return fig, interval_table


def build_interval_table(merged_curves, tracks_config):
    """
    Строит таблицу интервалов записи (кровля/подошва + мин/макс) по всем кривым,
    перечисленным в tracks_config. Вынесено отдельно от plot_well_panel, чтобы
    таблица была доступна и без построения matplotlib-фигуры (например, для
    интерактивного Plotly-планшета).
    """
    interval_table = []

    for track_id, config in tracks_config.items():
        if track_id == 0:
            continue

        for curve_spec in config['curves']:
            mnemonic = curve_spec['mnemonic']
            if mnemonic not in merged_curves:
                continue

            instances = merged_curves[mnemonic]
            intervals = find_intervals(instances)

            for interval in intervals:
                interval_table.append({
                    'Метод': mnemonic,
                    'Кровля, м': f"{interval['top']:.1f}",
                    'Подошва, м': f"{interval['bottom']:.1f}",
                    'Мин. знач.': f"{interval['min_value']:.3f}" if not np.isnan(interval['min_value']) else '-',
                    'Макс. знач.': f"{interval['max_value']:.3f}" if not np.isnan(interval['max_value']) else '-',
                    'LAS-файл': interval['file_name']
                })

    interval_table.sort(key=lambda x: float(x['Кровля, м']))
    return interval_table
