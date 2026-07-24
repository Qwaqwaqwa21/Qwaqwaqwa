# coding: utf-8
"""
Интерактивная (Plotly) версия каротажного планшета.

В отличие от статичной matplotlib-версии (plotting.plot_well_panel), где
каждая кривая в треке получает свою собственную линейку-ось сверху, здесь
все кривые одного трека делят одну общую ось X — Plotly не даёт удобного
способа рисовать несколько независимых X-осей на одной панели так же, как
matplotlib.twiny(). Взамен появляется зум, панорамирование и всплывающая
подсказка с точным значением/глубиной/файлом-источником при наведении —
то, чего не хватало статичным PNG для точечной проверки данных.
"""
from pathlib import Path

import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from plotting import (
    calculate_curve_limits, wrap_text,
    active_track_ids as _active_track_ids,
    track_x_range as _track_x_range,
)

_LINESTYLE_TO_DASH = {'-': 'solid', '--': 'dash', ':': 'dot'}


def _add_track_traces(fig, col_idx, config, merged_curves, x_range=None, name_suffix=''):
    """
    Добавляет линии всех кривых трека в указанную колонку и настраивает её
    ось X. Общая часть логики между одно- и много-скважинным планшетами.
    x_range, если передан, используется вместо автоподбора по данным этого
    вызова (нужно для сопоставимости шкал между скважинами на общем планшете).
    """
    curve_instance_pairs = [(c['mnemonic'], merged_curves.get(c['mnemonic'], [])) for c in config['curves']]
    if x_range is None:
        x_range = _track_x_range(config, curve_instance_pairs)

    for curve_spec in config['curves']:
        mnemonic = curve_spec['mnemonic']
        instances = merged_curves.get(mnemonic, [])
        for instance in instances:
            depth = np.asarray(instance['depth'])
            values = np.asarray(instance['values'])
            valid = np.isfinite(depth) & np.isfinite(values)
            if not np.any(valid):
                continue

            label = mnemonic if len(instances) == 1 else f"{mnemonic} ({Path(instance['file_name']).stem})"
            legend_label = f"{label}{name_suffix}"
            fig.add_trace(
                go.Scatter(
                    x=values[valid], y=depth[valid],
                    mode='lines',
                    name=legend_label,
                    line=dict(
                        color=curve_spec['color'],
                        dash=_LINESTYLE_TO_DASH.get(curve_spec['linestyle'], 'solid'),
                        width=curve_spec['linewidth'],
                    ),
                    hovertemplate=f"<b>{legend_label}</b><br>Глубина: %{{y:.2f}} м<br>Значение: %{{x:.3f}}<extra></extra>",
                ),
                row=1, col=col_idx,
            )

    xaxis_kwargs = dict(title=config['ylabel'])
    if config['grid'] == 'log':
        xaxis_kwargs['type'] = 'log'
        if x_range is not None:
            xaxis_kwargs['range'] = [np.log10(max(x_range[0], 1e-6)), np.log10(max(x_range[1], 1e-5))]
    elif x_range is not None:
        xaxis_kwargs['range'] = list(x_range)
    fig.update_xaxes(row=1, col=col_idx, **xaxis_kwargs)


def _add_zone_shapes(fig, col_idx, zones_df, depth_min, depth_max, with_label):
    """Пунктирные линии кровли/подошвы зон в одной колонке + опционально подписи."""
    if zones_df is None or zones_df.empty:
        return
    visible_zones = zones_df.dropna(subset=['Кровля, м', 'Подошва, м'])
    visible_zones = visible_zones[
        (visible_zones['Кровля, м'] <= depth_max) & (visible_zones['Подошва, м'] >= depth_min)
    ]
    if visible_zones.empty:
        return

    xref = 'x domain' if col_idx == 1 else f'x{col_idx} domain'
    yref = 'y' if col_idx == 1 else f'y{col_idx}'
    for _, zone in visible_zones.iterrows():
        for zone_depth in (zone['Кровля, м'], zone['Подошва, м']):
            fig.add_shape(
                type='line', xref=xref, yref=yref,
                x0=0, x1=1, y0=zone_depth, y1=zone_depth,
                line=dict(color='saddlebrown', width=1, dash='dash'),
                layer='above',
            )

    if with_label:
        for _, zone in visible_zones.iterrows():
            mid_depth = (max(zone['Кровля, м'], depth_min) + min(zone['Подошва, м'], depth_max)) / 2
            fig.add_annotation(
                x=0.5, xref=xref, y=mid_depth, yref=yref,
                text=str(zone['Зона']), showarrow=False,
                textangle=-90, font=dict(color='saddlebrown', size=10),
                bgcolor='rgba(255,255,255,0.7)',
            )


def plot_well_panel_plotly(well_name, merged_curves, tracks_config, depth_min, depth_max, zones_df=None):
    """
    Строит интерактивный планшет для одной скважины. Возвращает go.Figure,
    либо None, если ни один трек не содержит данных.

    zones_df: необязательная таблица зон/пластов (колонки 'Зона', 'Кровля, м',
    'Подошва, м' — см. zones.py) — если передана, поверх всех треков рисуются
    границы зон, а название зоны подписывается в треке "Глубина".
    """
    active_track_ids = _active_track_ids(merged_curves, tracks_config)
    if not active_track_ids:
        return None
    active_tracks = [(0, tracks_config[0])] + [(tid, tracks_config[tid]) for tid in active_track_ids]

    widths = [config['width'] for _, config in active_tracks]
    total_width = sum(widths)

    fig = make_subplots(
        rows=1, cols=len(active_tracks),
        shared_yaxes=True,
        horizontal_spacing=0.015,
        column_widths=[w / total_width for w in widths],
        subplot_titles=[wrap_text(config['name'], width=18).replace('\n', '<br>') for _, config in active_tracks],
    )

    for col_idx, (track_id, config) in enumerate(active_tracks, start=1):
        if track_id == 0:
            fig.add_trace(
                go.Scatter(x=[0], y=[depth_min], mode='markers',
                           marker=dict(opacity=0), showlegend=False, hoverinfo='skip'),
                row=1, col=col_idx,
            )
            fig.update_xaxes(visible=False, row=1, col=col_idx)
            continue

        _add_track_traces(fig, col_idx, config, merged_curves)

    for col_idx in range(1, len(active_tracks) + 1):
        _add_zone_shapes(fig, col_idx, zones_df, depth_min, depth_max, with_label=(col_idx == 1))

    # Глубина растёт вниз: верхняя граница диапазона — depth_max
    fig.update_yaxes(range=[depth_max, depth_min])
    fig.update_yaxes(title='Глубина, м', row=1, col=1)
    for col_idx in range(2, len(active_tracks) + 1):
        fig.update_yaxes(showticklabels=False, row=1, col=col_idx)

    fig.update_layout(
        title=f"Планшет — скважина {well_name}",
        height=900,
        hovermode='closest',
        legend=dict(orientation='h', yanchor='bottom', y=1.04, x=0),
        margin=dict(t=120),
    )
    return fig


def plot_multi_well_panel_plotly(wells, tracks_config):
    """
    Строит один общий планшет для сопоставления нескольких скважин рядом
    друг с другом (горизонтальная прокрутка), как принято в программах
    геологической корреляции разрезов: одна общая шкала глубины слева и
    одинаковый набор треков-колонок повторяется для каждой скважины — даже
    если для части скважин конкретный трек пуст, — чтобы один и тот же трек
    было легко сопоставлять по горизонтали. Шкала X каждого трека общая для
    всех скважин (посчитана по объединённым данным), иначе визуальное
    сравнение формы кривых между скважинами было бы обманчивым.

    wells: список словарей по одному на скважину:
        {'well_name': str, 'merged_curves': dict, 'depth_min': float,
         'depth_max': float, 'zones_df': DataFrame или None}

    Возвращает go.Figure, либо None, если ни для одной скважины нет ни
    одного активного трека.
    """
    if not wells:
        return None

    global_depth_min = min(w['depth_min'] for w in wells)
    global_depth_max = max(w['depth_max'] for w in wells)

    active_track_ids = []
    seen = set()
    for w in wells:
        for tid in _active_track_ids(w['merged_curves'], tracks_config):
            if tid not in seen:
                seen.add(tid)
                active_track_ids.append(tid)
    active_track_ids.sort()

    if not active_track_ids:
        return None

    n_wells = len(wells)
    n_tracks = len(active_track_ids)
    total_cols = 1 + n_wells * n_tracks

    widths = [tracks_config[0]['width']]
    subplot_titles = ['Глубина']
    for w in wells:
        for tid in active_track_ids:
            widths.append(tracks_config[tid]['width'])
            subplot_titles.append(wrap_text(tracks_config[tid]['name'], width=14).replace('\n', '<br>'))

    total_width = sum(widths)
    horizontal_spacing = min(0.012, 0.9 / max(total_cols - 1, 1))

    fig = make_subplots(
        rows=1, cols=total_cols,
        shared_yaxes=True,
        horizontal_spacing=horizontal_spacing,
        column_widths=[w / total_width for w in widths],
        subplot_titles=subplot_titles,
    )

    # Общий диапазон X на трек считаем один раз по данным всех скважин —
    # иначе одинаковая по форме кривая в двух скважинах могла бы выглядеть
    # по-разному просто из-за разного автоподбора масштаба у каждой.
    shared_x_range = {}
    for tid in active_track_ids:
        config = tracks_config[tid]
        combined_curves = {}
        for w in wells:
            for mnemonic, instances in w['merged_curves'].items():
                combined_curves.setdefault(mnemonic, []).extend(instances)
        curve_instance_pairs = [(c['mnemonic'], combined_curves.get(c['mnemonic'], [])) for c in config['curves']]
        shared_x_range[tid] = _track_x_range(config, curve_instance_pairs)

    fig.add_trace(
        go.Scatter(x=[0], y=[global_depth_min], mode='markers',
                   marker=dict(opacity=0), showlegend=False, hoverinfo='skip'),
        row=1, col=1,
    )
    fig.update_xaxes(visible=False, row=1, col=1)

    for w_idx, w in enumerate(wells):
        for t_idx, tid in enumerate(active_track_ids):
            col_idx = 2 + w_idx * n_tracks + t_idx
            config = tracks_config[tid]
            _add_track_traces(fig, col_idx, config, w['merged_curves'], x_range=shared_x_range[tid])

        zones_df = w.get('zones_df')
        for t_idx, tid in enumerate(active_track_ids):
            col_idx = 2 + w_idx * n_tracks + t_idx
            _add_zone_shapes(fig, col_idx, zones_df, w['depth_min'], w['depth_max'], with_label=(t_idx == 0))

    fig.update_yaxes(range=[global_depth_max, global_depth_min])
    fig.update_yaxes(title='Глубина, м', row=1, col=1)
    for col_idx in range(2, total_cols + 1):
        fig.update_yaxes(showticklabels=False, row=1, col=col_idx)

    # Подпись со скважиной над каждой группой её треков — читаем реальные
    # координаты доменов осей X, которые make_subplots уже выставил.
    for w_idx, w in enumerate(wells):
        first_col = 2 + w_idx * n_tracks
        last_col = first_col + n_tracks - 1
        # first_col/last_col всегда >= 2 (колонка 1 — общий трек глубины),
        # поэтому суффикс оси есть всегда — веток без него не бывает.
        first_axis = fig.layout[f'xaxis{first_col}']
        last_axis = fig.layout[f'xaxis{last_col}']
        mid_x = (first_axis.domain[0] + last_axis.domain[1]) / 2
        fig.add_annotation(
            x=mid_x, xref='paper', y=1.10, yref='paper',
            text=f"Скважина: {w['well_name']}", showarrow=False,
            font=dict(size=13, color='black'),
        )

    width_px = max(1100, total_cols * 95)
    fig.update_layout(
        title="Планшет — сопоставление скважин",
        height=900,
        width=width_px,
        showlegend=False,
        hovermode='closest',
        margin=dict(t=170),
    )
    return fig
