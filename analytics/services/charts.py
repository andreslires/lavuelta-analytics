import colorsys
from functools import lru_cache

import plotly.graph_objects as go
from django.core.cache import cache

# Colores La Vuelta
COLOR_ROJO = '#E3152B'
COLOR_ORO = '#F5A623'
COLOR_GRID = '#3a2a2b'
COLOR_TEXTO = '#c4a99f'

# Rango de matices de rojo para las ediciones (HSL)
_HUE_INICIO = 350
_HUE_FIN = 370
_LUMINOSIDAD = 0.52
_SATURACION = 0.85


@lru_cache(maxsize=1)
def _anos_ordenados():
    """Años de las ediciones existentes, de menor a mayor"""
    from analytics.models import Edicion
    return tuple(Edicion.objects.order_by('year').values_list('year', flat=True))


def color_edicion(year):
    """Rojo Vuelta con un tono distinto por edición, según el año"""
    years = _anos_ordenados()
    if not years:
        return COLOR_ROJO

    try:
        pos = years.index(year)
    except ValueError:
        return COLOR_ROJO

    posiciones = max(1, len(years) - 1)          # pasos posibles dentro del rango
    hue = _HUE_INICIO + pos * (_HUE_FIN - _HUE_INICIO) / posiciones
    hue = hue % 360                              
    
    return _hsl_a_hex(hue, _SATURACION, _LUMINOSIDAD)


def _hsl_a_hex(h, s, l):
    """Convierte HSL (h en grados 0-360, s/l 0-1) a hex #RRGGBB."""
    r, g, b = colorsys.hls_to_rgb(h / 360.0, l, s)
    return '#{:02X}{:02X}{:02X}'.format(
        round(r * 255), round(g * 255), round(b * 255))


def chart_layout(fig, show_legend=False):
    """Aplica el estilo común de las gráficas Plotly."""
    layout = dict(
        template='plotly_dark',
        paper_bgcolor='rgba(0,0,0,0)',
        plot_bgcolor='rgba(0,0,0,0)',
        margin=dict(l=0, r=0, t=20, b=20),
        font=dict(family='Barlow', color=COLOR_TEXTO),
        xaxis=dict(showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
        yaxis=dict(showgrid=True, gridcolor=COLOR_GRID, zeroline=False, tickfont=dict(color=COLOR_TEXTO), automargin=True),
        hoverlabel=dict(font=dict(family='JetBrains Mono', color='#0B0A08', size=12)),
    )
    if show_legend:
        layout['showlegend'] = True
        layout['legend'] = dict(
            orientation='h', yanchor='bottom', y=1.02, xanchor='right', x=1,
            font=dict(family='Barlow', color=COLOR_TEXTO),
        )
    fig.update_layout(layout)


def _to_html(fig):
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})


def build_charts(ediciones):
    """Construye las 4 gráficas comparativas de varias ediciones."""
    years = [e.year for e in ediciones]
    all_years = _anos_ordenados()
    cache_key = 'charts_' + '_'.join(str(y) for y in years)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    colores = [color_edicion(y) for y in years]

    # 1. Desnivel total por edición
    fig = go.Figure(data=[go.Bar(x=years, y=[e.total_d or 0 for e in ediciones], marker_color=colores)])
    chart_layout(fig)
    fig.update_layout(xaxis=dict(tickvals=all_years, ticktext=[str(y) for y in all_years]))
    plot_html = _to_html(fig)

    # 2. Distancia total por edición
    fig_dist = go.Figure(data=[go.Bar(x=years, y=[e.total_km or 0 for e in ediciones], marker_color=colores)])
    chart_layout(fig_dist)
    fig_dist.update_layout(xaxis=dict(tickvals=all_years, ticktext=[str(y) for y in all_years]))
    plot_dist_html = _to_html(fig_dist)

    # 3. Scatter comparativo: cada etapa (km vs desnivel) coloreada por edición
    fig_scat = go.Figure()
    for ed, color in zip(ediciones, colores):
        fig_scat.add_trace(go.Scatter(
            x=[et.distancia for et in ed.etapas.all()],
            y=[et.desnivel for et in ed.etapas.all()],
            mode='markers',
            name=str(ed.year),
            marker=dict(size=10, color=color, line=dict(width=1, color='#0B0A08')),
            hovertemplate='%{x:.0f} km · %{y:.0f} m+',
        ))
    chart_layout(fig_scat, show_legend=True)
    plot_scat_html = _to_html(fig_scat)

    # 4. Box: distribución del desnivel por etapa, comparativa entre ediciones
    fig_box = go.Figure()
    for ed, color in zip(ediciones, colores):
        fig_box.add_trace(go.Box(
            y=[et.desnivel for et in ed.etapas.all()],
            name=str(ed.year),
            marker_color=color,
            line_color=color,
            fillcolor=color + '26',
            boxpoints='outliers',
        ))
    chart_layout(fig_box)
    plot_box_html = _to_html(fig_box)

    result = {
        'years': years,
        'colores': colores,
        'plot_html': plot_html,
        'plot_dist_html': plot_dist_html,
        'plot_scat_html': plot_scat_html,
        'plot_box_html': plot_box_html,
    }
    cache.set(cache_key, result, timeout=None)
    return result


def chart_geo_ediciones(geo):
    """Gráfica de etapas por comunidad autónoma (barras horizontales)."""
    fig = go.Figure(data=go.Bar(
        x=[g['etapas'] for g in geo],
        y=[g['name'] for g in geo],
        orientation='h',
        marker_color=COLOR_ROJO,
        hovertemplate='%{y}: %{x} etapas<extra></extra>'))
    chart_layout(fig)
    fig.update_layout(
        xaxis=dict(title='Etapas', showgrid=True, gridcolor=COLOR_GRID, zeroline=False,
                   tickfont=dict(color=COLOR_TEXTO), dtick=5),
        yaxis=dict(title='', showgrid=False, tickfont=dict(color=COLOR_TEXTO), autorange='reversed'),
    )
    return _to_html(fig)
