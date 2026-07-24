# coding: utf-8
"""
Кроссплоты и гистограммы для анализа взаимосвязей между кривыми.

Идея взята из открытых инструментов las_explorer и PetrologStudio: scatter
двух кривых с линией линейной регрессии (R²) и гистограмма распределения
одной кривой — базовые инструменты статистического анализа каротажных
данных, дополняющие визуализацию планшета.
"""
import numpy as np
import plotly.graph_objects as go


def build_crossplot(x_values, y_values, x_name, y_name, log_x=False, log_y=False,
                     show_regression=True, depth_values=None):
    """
    Строит интерактивный кроссплот (scatter) двух кривых по одной скважине.

    x_values, y_values: массивы значений одинаковой длины (точки на одной
        и той же глубине).
    log_x, log_y: логарифмическая шкала по соответствующей оси (например,
        для сопротивления). Точки с неположительным значением на
        логарифмической оси из построения исключаются.
    show_regression: рисовать ли линию линейной регрессии и коэффициент
        детерминации R² (регрессия считается в тех же координатах, что и
        оси — то есть по логарифмам значений, если ось логарифмическая).
    depth_values: если передано, глубина точки используется для цветовой
        шкалы маркеров и показывается во всплывающей подсказке.

    Возвращает go.Figure, либо None, если не осталось валидных пар точек.
    """
    x = np.asarray(x_values, dtype=float)
    y = np.asarray(y_values, dtype=float)
    valid = np.isfinite(x) & np.isfinite(y)
    if log_x:
        valid &= x > 0
    if log_y:
        valid &= y > 0

    if not np.any(valid):
        return None

    x_v, y_v = x[valid], y[valid]

    marker = dict(size=5, opacity=0.65)
    customdata = None
    hover_extra = ""
    if depth_values is not None:
        depth_v = np.asarray(depth_values, dtype=float)[valid]
        marker.update(color=depth_v, colorscale='Viridis', showscale=True,
                      colorbar=dict(title='Глубина, м'))
        customdata = depth_v
        hover_extra = "<br>Глубина: %{customdata:.2f} м"

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=x_v, y=y_v, mode='markers', marker=marker, name='Точки',
        customdata=customdata,
        hovertemplate=f"{x_name}: %{{x:.3f}}<br>{y_name}: %{{y:.3f}}{hover_extra}<extra></extra>",
    ))

    if show_regression and len(x_v) >= 2:
        fx = np.log10(x_v) if log_x else x_v
        fy = np.log10(y_v) if log_y else y_v
        if np.std(fx) > 0 and np.std(fy) > 0:
            slope, intercept = np.polyfit(fx, fy, 1)
            r = np.corrcoef(fx, fy)[0, 1]
            r2 = r ** 2

            fx_line = np.linspace(fx.min(), fx.max(), 100)
            fy_line = slope * fx_line + intercept
            x_line = 10 ** fx_line if log_x else fx_line
            y_line = 10 ** fy_line if log_y else fy_line

            fig.add_trace(go.Scatter(
                x=x_line, y=y_line, mode='lines', name=f'Регрессия (R²={r2:.3f})',
                line=dict(color='red', dash='dash'),
            ))

    fig.update_xaxes(title=x_name, type='log' if log_x else 'linear')
    fig.update_yaxes(title=y_name, type='log' if log_y else 'linear')
    fig.update_layout(
        title=f"{y_name} vs {x_name}",
        height=600,
        legend=dict(orientation='h', yanchor='bottom', y=1.02),
    )
    return fig


def build_histogram(values, curve_name, bins=30):
    """
    Строит гистограмму распределения значений одной кривой с отметкой медианы.
    Возвращает go.Figure, либо None, если нет ни одного конечного значения.
    """
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    if len(v) == 0:
        return None

    fig = go.Figure()
    fig.add_trace(go.Histogram(x=v, nbinsx=bins, name=curve_name, marker_color='steelblue'))

    median = float(np.median(v))
    fig.add_vline(x=median, line_dash='dash', line_color='red',
                  annotation_text=f'медиана={median:.3g}', annotation_position='top')

    fig.update_layout(
        title=f"Распределение: {curve_name}",
        xaxis_title=curve_name,
        yaxis_title='Количество точек',
        height=450,
        bargap=0.02,
    )
    return fig
