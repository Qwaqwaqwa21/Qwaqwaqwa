# coding: utf-8
"""
Упрощённая карта охвата данными: один столбец на метод (кривую), закрашенный
там, где для этой кривой реально есть непрерывные данные — удобно, чтобы
одним взглядом увидеть, какие методы записаны на каких глубинах, особенно
когда скважина собрана из нескольких LAS-файлов с разными интервалами.
"""
import plotly.graph_objects as go

_PALETTE = [
    '#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
    '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf',
]


def build_coverage_chart(interval_table, depth_min, depth_max):
    """
    Строит карту охвата данными по таблице интервалов (см. plotting.build_interval_table
    / plot_well_panel: список словарей с полями 'Метод', 'Кровля, м', 'Подошва, м').
    Возвращает go.Figure, либо None, если таблица интервалов пуста.
    """
    if not interval_table:
        return None

    # Порядок столбцов — порядок первого появления метода в таблице (то есть
    # порядок треков в конфигурации), а не алфавитный.
    methods = list(dict.fromkeys(row['Метод'] for row in interval_table))

    fig = go.Figure()
    for i, method in enumerate(methods):
        color = _PALETTE[i % len(_PALETTE)]
        rows = [r for r in interval_table if r['Метод'] == method]
        tops = [float(r['Кровля, м']) for r in rows]
        bottoms = [float(r['Подошва, м']) for r in rows]
        heights = [b - t for t, b in zip(tops, bottoms)]

        fig.add_trace(go.Bar(
            x=[method] * len(rows),
            y=heights,
            base=tops,
            marker_color=color,
            width=0.6,
            name=method,
            showlegend=False,
            customdata=bottoms,
            hovertemplate=(
                f"<b>{method}</b><br>Кровля: %{{base:.1f}} м"
                "<br>Подошва: %{customdata:.1f} м<extra></extra>"
            ),
        ))

    fig.update_yaxes(title='Глубина, м', range=[depth_max, depth_min])
    fig.update_xaxes(title='Метод')
    fig.update_layout(
        title='Карта охвата данными',
        height=700,
        bargap=0.3,
        showlegend=False,
    )
    return fig
