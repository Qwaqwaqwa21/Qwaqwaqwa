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

from plotting import calculate_curve_limits, wrap_text

_LINESTYLE_TO_DASH = {'-': 'solid', '--': 'dash', ':': 'dot'}


def _track_x_range(config, curve_instance_pairs):
    """Объединённый диапазон оси X для трека (аналог auto/shared из matplotlib-версии)."""
    if isinstance(config['limits'], tuple):
        return config['limits']

    grid_type = 'log' if config['grid'] == 'log' else 'linear'
    all_vmins, all_vmaxs = [], []
    for mnemonic, instances in curve_instance_pairs:
        for instance in instances:
            values = np.asarray(instance['values'])
            valid = values[np.isfinite(values)]
            if len(valid) == 0:
                continue
            vmin, vmax = calculate_curve_limits(valid, grid_type=grid_type, mnemonic=mnemonic)
            if vmin is not None:
                all_vmins.append(vmin)
                all_vmaxs.append(vmax)

    if not all_vmins:
        return None
    return min(all_vmins), max(all_vmaxs)


def plot_well_panel_plotly(well_name, merged_curves, tracks_config, depth_min, depth_max):
    """
    Строит интерактивный планшет для одной скважины. Возвращает go.Figure,
    либо None, если ни один трек не содержит данных.
    """
    active_tracks = [(0, tracks_config[0])]
    for track_id in sorted(tracks_config.keys()):
        if track_id == 0:
            continue
        config = tracks_config[track_id]
        curves_present = [
            c['mnemonic'] for c in config['curves']
            if c['mnemonic'] in merged_curves and merged_curves[c['mnemonic']]
        ]
        if curves_present:
            active_tracks.append((track_id, config))

    if len(active_tracks) <= 1:
        return None

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

        curve_instance_pairs = [(c['mnemonic'], merged_curves.get(c['mnemonic'], [])) for c in config['curves']]
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
                fig.add_trace(
                    go.Scatter(
                        x=values[valid], y=depth[valid],
                        mode='lines',
                        name=label,
                        line=dict(
                            color=curve_spec['color'],
                            dash=_LINESTYLE_TO_DASH.get(curve_spec['linestyle'], 'solid'),
                            width=curve_spec['linewidth'],
                        ),
                        hovertemplate=f"<b>{label}</b><br>Глубина: %{{y:.2f}} м<br>Значение: %{{x:.3f}}<extra></extra>",
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
