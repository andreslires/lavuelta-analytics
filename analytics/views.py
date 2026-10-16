# Vistas: cada función recibe un request y devuelve HTML. Las gráficas y el
# análisis geográfico se delegan en analytics/services/.
from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse
from django.utils.html import escape
from django.core.cache import cache
from django.db.models import Sum, Count
import folium
import json
import plotly.graph_objects as go
from shapely.wkt import loads

from analytics.models import Edicion, Etapa
from .services.gpx_processor import GPXProcessor
from .services.charts import (
    COLOR_GRID,
    COLOR_ORO,
    COLOR_ROJO,
    COLOR_TEXTO,
    build_charts,
    chart_geo_ediciones,
    chart_layout,
    color_edicion,
)
from .services.geografia import (
    TILE_ATTR,
    TILE_SUBDOMAINS,
    TILE_URL,
    build_mapa_comparativo,
    build_mapa_general,
    build_mapa_par_tramos,
    build_mapa_provincias,
    comunidades_edicion,
    geografia_global,
    capa_base_negra,
    tramos_comunes,
)
from .services.perfiles_similares import (
    etapas_similares,
    indice_similitud,
    metricas,
    perfil_etapa_html,
)
from .services.sparkline import sparkline_svg


def _int_param(request, name):
    try:
        return int(request.GET[name])
    except (TypeError, ValueError, KeyError):
        return None


def mapa_par_tramos(request):
    """Fragmento HTML con el mapa cara a cara de una pareja de etapas.

    Se llama bajo demanda (fetch desde el navegador) al expandir una fila de
    "Zonas comunes". Parámetros: z1 (etapa de referencia) y z2 (la de la lista).
    Reutiliza la geometría del solape ya cacheada por tramos_comunes(z1).
    """
    z1 = _int_param(request, 'z1')
    z2 = _int_param(request, 'z2')
    if not z1 or not z2:
        return HttpResponse('Faltan parámetros', status=400)
    e_ref = get_object_or_404(Etapa, id=z1)
    e_otra = get_object_or_404(Etapa, id=z2)
    geom = None
    for r in tramos_comunes(e_ref):
        if r['etapa'].id == e_otra.id:
            geom = r.get('geom')
            break
    mapa = build_mapa_par_tramos(e_ref, e_otra, geom)
    if mapa is None:
        return HttpResponse('No hay geometría', status=404)
    from folium.elements import Element
    mapa.get_root().html.add_child(Element(
        '<style>html, body { background: #14161a !important; height: 100%; '
        'margin: 0; }</style>'
    ))
    html_doc = mapa.get_root().render()
    return HttpResponse(
        f'<iframe class="zona-map-frame" srcdoc="{escape(html_doc)}" '
        f'title="Mapa de tramos en común"></iframe>'
    )


def _ediciones_filtradas(request):
    qs = Edicion.objects.annotate(
        total_d=Sum('etapas__desnivel'),
        total_km=Sum('etapas__distancia'),
        etapa_count=Count('etapas')
    ).order_by('year')
    seleccion = request.GET.getlist('ediciones')
    if seleccion:
        try:
            qs = qs.filter(year__in=[int(y) for y in seleccion])
        except ValueError:
            pass
    return qs


def dashboard(request):
    ediciones = _ediciones_filtradas(request)
    seleccion = request.GET.getlist('ediciones')
    if seleccion:
        selected_years = [int(y) for y in seleccion]
    else:
        selected_years = [e.year for e in ediciones]

    # Métricas Globales
    total_km = Etapa.objects.aggregate(Sum('distancia'))['distancia__sum'] or 0
    total_desnivel = Etapa.objects.aggregate(Sum('desnivel'))['desnivel__sum'] or 0
    total_etapas = Etapa.objects.count()
    total_ediciones = Edicion.objects.count()

    charts = build_charts(ediciones)

    # --- Geografía global: etapas por comunidad autónoma ---
    geo_res = geografia_global()
    geo = geo_res['geo']
    geo_total = sum(g['etapas'] for g in geo)
    geo_comunidades = len(geo)
    geo_top = geo[0] if geo else None
    geo_fuera = geo_res['fuera']
    geo_chart_html = cache.get('chart_geo_ediciones_html')
    if geo_chart_html is None:
        geo_chart_html = chart_geo_ediciones(geo)
        cache.set('chart_geo_ediciones_html', geo_chart_html, timeout=None)

    filtro_ediciones = [
        {'year': ed.year, 'color': color_edicion(ed.year)}
        for ed in Edicion.objects.all().order_by('-year')
    ]

    map_preview_html = _mapa_html_cached('mapa_etapas_html_preview', lambda: build_mapa_general(
        zoom_start=5, fit=[[35.9, -10.2], [43.9, 4.2]]
    ))

    edicion_tarjetas = [
        {
            'id': e.id,
            'nombre': e.nombre,
            'year': e.year,
            'color': color_edicion(e.year),
            'total_km': e.total_km or 0,
            'total_d': e.total_d or 0,
        }
        for e in ediciones
    ]

    return render(request, 'analytics/dashboard.html', {
        'ediciones': ediciones,
        'edicion_tarjetas': edicion_tarjetas,
        'filtro_ediciones': filtro_ediciones,
        'selected_years': selected_years,
        'total_km': total_km,
        'total_desnivel': total_desnivel,
        'total_etapas': total_etapas,
        'total_ediciones': total_ediciones,
        'geo': geo,
        'geo_comunidades': geo_comunidades,
        'geo_top': geo_top,
        'geo_fuera': geo_fuera,
        'geo_chart_html': geo_chart_html,
        'map_preview_html': map_preview_html,
        **charts,
    })


def dashboard_charts(request):
    ediciones = _ediciones_filtradas(request)
    charts = build_charts(ediciones)
    return render(request, 'analytics/partials/charts.html', charts)


def dashboard_map_preview(request):
    """Mapa preview del dashboard, cargado lazy vía HTMX."""
    map_html = _mapa_html_cached('mapa_etapas_html_preview', lambda: build_mapa_general(
        zoom_start=5, fit=[[35.9, -10.2], [43.9, 4.2]]
    ))
    return render(request, 'analytics/partials/map_preview.html', {'map_html': map_html})


def edicion_detalle(request, year):
    edicion = get_object_or_404(Edicion, year=year)
    etapas = list(edicion.etapas.all().order_by('numero'))

    # Datos factuales de la edición (importados por el comando de importación).
    try:
        gc = json.loads(edicion.gc_json or '[]')
    except (ValueError, TypeError):
        gc = []
    try:
        maillots = json.loads(edicion.maillots_json or '{}')
    except (ValueError, TypeError):
        maillots = {}

    TIPOS_MAILLOT = {
        'points': 'Puntos',
        'kom': 'Montaña',
        'youth': 'Jóvenes',
    }
    maillots_list = []
    for tipo, m in maillots.items():
        if not isinstance(m, dict) or not m.get('rider'):
            continue
        maillots_list.append({
            'tipo': TIPOS_MAILLOT.get(str(tipo).lower(), str(tipo).replace('_', ' ').capitalize()),
            'rider': m.get('rider', ''),
            'team': m.get('team') or '',
        })

    n = len(etapas)
    total_km = sum(e.distancia for e in etapas) or 0
    total_des = sum(e.desnivel for e in etapas) or 0
    avg_km = total_km / n if n else 0
    avg_des = total_des / n if n else 0

    etapas_data = [
        {'etapa': e, 'sparkline': sparkline_svg(e)} for e in etapas
    ]

    dura = max(etapas, key=lambda e: e.desnivel) if etapas else None
    larga = max(etapas, key=lambda e: e.distancia) if etapas else None
    corta = min(etapas, key=lambda e: e.distancia) if etapas else None

    # Índice de dureza: metros de desnivel por kilómetro (media de la edición)
    dureza = total_des / total_km if total_km else 0

    # Gráficas de la edición (cacheadas: dependen solo de la edición).
    desnivel_chart_html = distancia_chart_html = tipos_chart_html = ''
    chart_cache_key = f'edicion_charts_{edicion.id}'
    cached_charts = cache.get(chart_cache_key)
    if cached_charts is not None:
        desnivel_chart_html, distancia_chart_html, tipos_chart_html = cached_charts
    elif etapas:
        nums = [e.numero for e in etapas]
        deses = [e.desnivel for e in etapas]
        kms = [e.distancia for e in etapas]
        color_ed = COLOR_ROJO  # una sola edición: rojo Vuelta

        # 1) Desnivel por etapa
        fig = go.Figure(data=go.Bar(x=nums, y=deses, marker_color=color_ed,
                                    hovertemplate='Etapa %{x} · %{y:.0f} m+<extra></extra>'))
        chart_layout(fig)
        fig.update_layout(
            xaxis=dict(title='Etapa', dtick=1, showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
            yaxis=dict(title='Desnivel (m+)', gridcolor=COLOR_GRID, zeroline=False,
                       tickfont=dict(color=COLOR_TEXTO)),
        )
        desnivel_chart_html = fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # 2) Distancia por etapa
        fig_d = go.Figure(data=go.Bar(x=nums, y=kms, marker_color=color_ed,
                                      hovertemplate='Etapa %{x} · %{y:.0f} km<extra></extra>'))
        chart_layout(fig_d)
        fig_d.update_layout(
            xaxis=dict(title='Etapa', dtick=1, showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
            yaxis=dict(title='Distancia (km)', gridcolor=COLOR_GRID, zeroline=False,
                       tickfont=dict(color=COLOR_TEXTO)),
        )
        distancia_chart_html = fig_d.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # 3) Reparto por tipo de etapa (barras horizontales)
        orden_tipos = ['Contrarreloj', 'Llana', 'Media montaña', 'Montaña', 'Alta montaña']
        conteo = {}
        for e in etapas:
            conteo[e.tipo] = conteo.get(e.tipo, 0) + 1
        tipos = [t for t in orden_tipos if t in conteo]
        valores = [conteo[t] for t in tipos]
        fig_t = go.Figure(data=go.Bar(x=valores, y=tipos, orientation='h',
                                      marker_color=color_ed,
                                      hovertemplate='%{y}: %{x}<extra></extra>'))
        chart_layout(fig_t)
        fig_t.update_layout(
            xaxis=dict(title='Nº de etapas', showgrid=True, gridcolor=COLOR_GRID, zeroline=False,
                       tickfont=dict(color=COLOR_TEXTO)),
            yaxis=dict(title='', showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
        )
        tipos_chart_html = fig_t.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})
        cache.set(chart_cache_key, (desnivel_chart_html, distancia_chart_html, tipos_chart_html), timeout=None)
    else:
        desnivel_chart_html = ''
        distancia_chart_html = ''
        tipos_chart_html = ''

    return render(request, 'analytics/edicion_detalle.html', {
        'edicion': edicion,
        'etapas': etapas,
        'etapas_data': etapas_data,
        'total_km': total_km,
        'total_des': total_des,
        'avg_km': avg_km,
        'avg_des': avg_des,
        'dura': dura,
        'larga': larga,
        'corta': corta,
        'dureza': dureza,
        'desnivel_chart_html': desnivel_chart_html,
        'distancia_chart_html': distancia_chart_html,
        'tipos_chart_html': tipos_chart_html,
        'gc_top': gc[:5],
        'maillots': maillots,
        'maillots_list': maillots_list,
    })


def _figura_perfil(x, y, D, a_max):
    """Perfil altimétrico Plotly con escala adaptativa según el recorrido.

    Argumentos:
        x    : serie de distancias acumuladas (km)
        y    : serie de altitudes (m)
        D    : distancia total (km)
        a_max: cota máxima (m)
    """
    # Base fija bajo 0 (apenas perceptible): algunas etapas bajan de 0 m
    # (p. ej. -1) y, con el suelo del eje pegado a 0, esos puntos se cortan.
    # Con una base de -10 m todos quedan dentro del rango y el perfil se dibuja.
    SUELO = -10

    if D < 45:
        techo = a_max + 150
        alto = 330      # lienzo compacto ~10:4
    elif a_max <= 800:
        techo = 800
        alto = 250      # lienzo panorámico ~16:5
    else:
        techo = max(2500, a_max + 200)
        alto = 250      # lienzo panorámico ~16:5

    # El relleno es 'tozeroy' (una sola traza) para que los tramos con altitud
    # negativa (p. ej. -2.6 m) queden dentro del rango y se dibujen completos.
    fig = go.Figure(data=go.Scatter(
        x=x,
        y=y,
        mode='lines',
        line=dict(color=COLOR_ROJO, width=2.2),
        fill='tozeroy',
        cliponaxis=False,
        fillcolor='rgba(227, 21, 43, 0.22)',
        hovertemplate='%{x:.1f} km · %{y:.0f} m<extra></extra>',
    ))
    chart_layout(fig)
    fig.update_layout(
        height=alto,
        xaxis=dict(title='Distancia (km)', range=[0, D], showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
        yaxis=dict(
            title='Altitud (m)',
            range=[SUELO, techo],
            gridcolor=COLOR_GRID,
            zeroline=False,
            tickfont=dict(color=COLOR_TEXTO),
        ),
        margin=dict(l=0, r=0, t=20, b=20),
    )
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})


def etapa_detalle(request, year, numero):
    etapa = get_object_or_404(Etapa, edicion__year=year, numero=numero)

    # Etapas anterior/siguiente dentro de la misma edición, para navegar
    etapas = Etapa.objects.filter(edicion__year=year).order_by('numero')
    lista = list(etapas)
    idx = next((i for i, e in enumerate(lista) if e.id == etapa.id), 0)
    prev_etapa = lista[idx - 1] if idx > 0 else None
    next_etapa = lista[idx + 1] if idx < len(lista) - 1 else None

    if etapa.file_path:
        map_html, plot_html = _mapa_plot_gpx(etapa)
    else:
        map_html, plot_html = _mapa_plot_sin_gpx(etapa)

    template = (
        'analytics/etapa_detalle_content.html'
        if request.headers.get('HX-Request')
        else 'analytics/etapa_detalle.html'
    )
    # Cargamos resultados de la nueva tabla relacional
    resultados = etapa.resultados_db.all().order_by('posicion')
    return render(request, template, {
        'etapa': etapa,
        'map_html': map_html,
        'plot_html': plot_html,
        'prev_etapa': prev_etapa,
        'next_etapa': next_etapa,
        # Resultado de la etapa (podio, factual)
        'resultados': resultados,
        # Métricas del terreno (precalculadas en BD)
        'altitud_max': etapa.altitud_max,
        'altitud_min': etapa.altitud_min,
        'desnivel_negativo': etapa.desnivel_negativo,
        'pendiente_max': etapa.pendiente_max,
        'pendiente_media': etapa.pendiente_media,
        'n_puertos': etapa.n_puertos,
    })


def _mapa_plot_gpx(etapa):
    """Mapa + perfil de una etapa con archivo GPX local (procesado en caché)."""
    # Cargar datos reales (cacheados por archivo GPX)
    cache_key = f'gpx_data_{etapa.file_path}'
    data = cache.get(cache_key)
    if data is None:
        processor = GPXProcessor(etapa.file_path)
        data = processor.process()
        cache.set(cache_key, data, timeout=None)  # Sin caducidad
    df = data['df']

    # Mapa con tiles oscuros (sin API Key). Se ajusta al tramo completo de la
    # etapa con márgenes para que se vea entera desde el primer render.
    mapa = folium.Map(
        location=[df.latitude.mean(), df.longitude.mean()],
        zoom_start=6,
        tiles=TILE_URL,
        attr=TILE_ATTR,
        subdomains=TILE_SUBDOMAINS,
    )
    coords = df[['latitude', 'longitude']].values
    folium.PolyLine(coords, color=COLOR_ROJO, weight=5, opacity=0.9).add_to(mapa)
    
    if coords.size > 0:
        folium.Marker(
            location=(float(coords[0, 0]), float(coords[0, 1])),
            icon=folium.DivIcon(
                html='<div style="background-color: green; color: white; border-radius: 50%; width: 14px; height: 14px; display: flex; align-items: center; justify-content: center; border: 1px solid white;"><i class="fa fa-play" style="font-size: 7px;"></i></div>',
                icon_size=(14, 14), icon_anchor=(7, 7)
            ),
            tooltip='Inicio'
        ).add_to(mapa)
        folium.Marker(
            location=(float(coords[-1, 0]), float(coords[-1, 1])),
            icon=folium.DivIcon(
                html='<div style="background-color: red; color: white; border-radius: 50%; width: 14px; height: 14px; display: flex; align-items: center; justify-content: center; border: 1px solid white;"><i class="fa fa-flag" style="font-size: 7px;"></i></div>',
                icon_size=(14, 14), icon_anchor=(7, 7)
            ),
            tooltip='Meta'
        ).add_to(mapa)

    mapa.fit_bounds(
        [[df.latitude.min(), df.longitude.min()],
         [df.latitude.max(), df.longitude.max()]],
        padding=(30, 30),
    )
    map_html = capa_base_negra(mapa)._repr_html_()

    # Perfil altimétrico con suavizado (elevation_smooth) y escala adaptativa.
    elev = df['elevation_smooth']
    x = df['dist_accumulated']
    plot_html = _figura_perfil(x, elev, data['distancia_total'], float(elev.max()))
    return map_html, plot_html


def _mapa_plot_sin_gpx(etapa):
    """Mapa + perfil de una etapa importada sin GPX local (track_wkt + perfil_real)."""
    # Mapa desde el track almacenado en WKT.
    geom = loads(etapa.track_wkt)
    coords = [(y, x) for x, y in geom.coords]
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]

    mapa = folium.Map(
        location=[sum(lats) / len(lats), sum(lons) / len(lons)],
        zoom_start=6,
        tiles=TILE_URL,
        attr=TILE_ATTR,
        subdomains=TILE_SUBDOMAINS,
    )
    folium.PolyLine(coords, color=COLOR_ROJO, weight=5, opacity=0.9).add_to(mapa)
    mapa.fit_bounds(
        [[min(lats), min(lons)], [max(lats), max(lons)]],
        padding=(30, 30),
    )
    map_html = capa_base_negra(mapa)._repr_html_()

    # Perfil desde el perfil real persistido (JSON [[km, alt], ...]).
    try:
        profile = json.loads(etapa.perfil_real or '[]')
    except (ValueError, TypeError):
        profile = []
    profile = [p for p in profile if p and len(p) >= 2]
    if profile:
        x = [float(p[0]) for p in profile]
        y = [float(p[1]) for p in profile]
        plot_html = _figura_perfil(x, y, max(x), max(y))
    else:
        plot_html = ''
    return map_html, plot_html


def mapa_general(request):
    tab = request.GET.get('tab')
    if tab not in ('etapas', 'provincias'):
        tab = None
    map_html = _mapa_html_cached('mapa_etapas_html', build_mapa_general)
    provincias_html = _mapa_html_cached('mapa_provincias_html', build_mapa_provincias)
    return render(request, 'analytics/mapa_general.html', {
        'map_html': map_html,
        'provincias_html': provincias_html,
        'tab': tab,
    })


def _mapa_html_cached(key, builder):
    """Devuelve el HTML de un mapa folium, cacheado (los datos son estáticos)."""
    html = cache.get(key)
    if html is None:
        html = builder()._repr_html_()
        cache.set(key, html, timeout=None)
    return html


def comparar(request):
    # Compara dos ediciones completas (parámetros a y b; por defecto las dos
    # últimas): KPIs, gráficas y geografía.
    todas = list(Edicion.objects.all().order_by('year'))
    anyos = [e.year for e in todas]
    if not anyos:
        return render(request, 'analytics/comparador.html', {
            'todas': [], 'todas_etapas': [], 'tab': 'ediciones',
        })

    def _limpiar(val):
        try:
            v = int(val)
            return v if v in anyos else None
        except (TypeError, ValueError):
            return None

    a = _limpiar(request.GET.get('a'))
    b = _limpiar(request.GET.get('b'))
    # La comparación solo se calcula si el usuario eligió dos ediciones
    # distintas (a y b). Si no, la pestaña muestra únicamente el selector.
    comparar_ok = bool(a and b and a != b)

    def _build_ed(anyo):
        ed = Edicion.objects.get(year=anyo)
        etapas = list(ed.etapas.all().order_by('numero'))
        n = len(etapas)
        total_km = sum(e.distancia for e in etapas) or 0
        total_des = sum(e.desnivel for e in etapas) or 0
        conteo = {}
        for e in etapas:
            conteo[e.tipo] = conteo.get(e.tipo, 0) + 1
        return {
            'ed': ed,
            'etapas': etapas,
            'total_km': total_km,
            'total_des': total_des,
            'n': n,
            'avg_km': total_km / n if n else 0,
            'avg_des': total_des / n if n else 0,
            'dureza': total_des / total_km if total_km else 0,
            'dura': max(etapas, key=lambda e: e.desnivel) if etapas else None,
            'larga': max(etapas, key=lambda e: e.distancia) if etapas else None,
            'conteo': conteo,
            'comunidades': comunidades_edicion(ed),
        }

    # Valores por defecto (estado "sin comparación")
    orden_tipos = ['Contrarreloj', 'Llana', 'Media montaña', 'Montaña', 'Alta montaña']
    ed_a = ed_b = None
    color_a = color_b = ''
    des_chart_html = km_chart_html = box_chart_html = ''
    mapa_comparativo_html = ''
    tipos_a = tipos_b = []
    comunidades_a = comunidades_b = comunidades_comunes = []

    if comparar_ok:
        ed_a = _build_ed(a)
        ed_b = _build_ed(b)

        # --- KPIs y gráficas comparativas (una traza por edición) ---
        # Rojo y oro: las dos ediciones enfrentadas siempre se distinguen,
        # independientemente del color que tenga cada año en el resto del sitio.
        # color_a/color_b alimentan el borde superior de las tarjetas de KPIs.
        color_a, color_b = COLOR_ROJO, COLOR_ORO
        colores = [COLOR_ROJO, COLOR_ORO]

        # Gráfica: desnivel por etapa, superpuesto
        fig_des = go.Figure()
        for ed_d, color in zip([ed_a, ed_b], colores):
            fig_des.add_trace(go.Scatter(
                x=[e.numero for e in ed_d['etapas']],
                y=[e.desnivel for e in ed_d['etapas']],
                mode='lines+markers', name=str(ed_d['ed'].year),
                line=dict(color=color, width=2.5), marker=dict(size=6),
                hovertemplate='%{x} · %{y:.0f} m+<extra></extra>'))
        chart_layout(fig_des, show_legend=True)
        fig_des.update_layout(
            xaxis=dict(title='Etapa', dtick=1, showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
            yaxis=dict(title='Desnivel (m+)', gridcolor=COLOR_GRID, zeroline=False, tickfont=dict(color=COLOR_TEXTO)))
        des_chart_html = fig_des.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # Gráfica: distancia por etapa, superpuesto
        fig_km = go.Figure()
        for ed_d, color in zip([ed_a, ed_b], colores):
            fig_km.add_trace(go.Scatter(
                x=[e.numero for e in ed_d['etapas']],
                y=[e.distancia for e in ed_d['etapas']],
                mode='lines+markers', name=str(ed_d['ed'].year),
                line=dict(color=color, width=2.5), marker=dict(size=6),
                hovertemplate='%{x} · %{y:.0f} km<extra></extra>'))
        chart_layout(fig_km, show_legend=True)
        fig_km.update_layout(
            xaxis=dict(title='Etapa', dtick=1, showgrid=False, tickfont=dict(color=COLOR_TEXTO)),
            yaxis=dict(title='Distancia (km)', gridcolor=COLOR_GRID, zeroline=False, tickfont=dict(color=COLOR_TEXTO)))
        km_chart_html = fig_km.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # Gráfica: boxplot del desnivel
        fig_box = go.Figure()
        for ed_d, color in zip([ed_a, ed_b], colores):
            fig_box.add_trace(go.Box(
                y=[e.desnivel for e in ed_d['etapas']], name=str(ed_d['ed'].year),
                marker_color=color, line_color=color, fillcolor=color + '26', boxpoints='outliers'))
        chart_layout(fig_box)
        fig_box.update_layout(yaxis=dict(title='Desnivel (m+)', gridcolor=COLOR_GRID, zeroline=False,
                                         tickfont=dict(color=COLOR_TEXTO)))
        box_chart_html = fig_box.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

        # --- Mapa comparativo: una edición en rojo, la otra en oro ---
        mapa_key = f'mapa_comparativo_{a}_{b}'
        mapa_comparativo_html = cache.get(mapa_key)
        if mapa_comparativo_html is None:
            mapa_comparativo_html = build_mapa_comparativo(
                ed_a['ed'], ed_b['ed'], COLOR_ROJO, COLOR_ORO
            )._repr_html_()
            cache.set(mapa_key, mapa_comparativo_html, timeout=None)

        def _tipos_fila(ed_d):
            return [{'tipo': t, 'n': ed_d['conteo'].get(t, 0)} for t in orden_tipos]

        tipos_a = _tipos_fila(ed_a)
        tipos_b = _tipos_fila(ed_b)
        # Geografía en tres bloques: lo común en el centro y, en los laterales,
        # solo lo exclusivo de cada edición (lo que no aparece en la otra).
        set_comunes = set(ed_a['comunidades']) & set(ed_b['comunidades'])
        comunidades_comunes = sorted(set_comunes)
        comunidades_a = sorted(set(ed_a['comunidades']) - set_comunes)
        comunidades_b = sorted(set(ed_b['comunidades']) - set_comunes)

    # --- Pestaña "Perfiles similares" ---
    # p1/p2 son ids de Etapa. Dos bots ("Buscar similares" con solo p1,
    # "Comparar" con p1 y p2); los enlaces de los resultados llegan con p1 y p2.
    todas_etapas = list(
        Etapa.objects.select_related('edicion').order_by('-edicion__year', 'numero')
    )
    # Dataset para el desplegable en cascada del selector de etapas
    # ("Perfiles similares"): año → etapas de ese año.
    todas_etapas_json = json.dumps([
        {
            'id': e.id,
            'year': e.edicion.year,
            'number': e.numero,
            'tipo': e.tipo,
            'localidad': (
                f"{e.localidad_inicio} → {e.localidad_fin}"
                if e.localidad_fin else ''
            ),
        }
        for e in todas_etapas
    ], ensure_ascii=False)
    p1 = _int_param(request, 'p1')
    p2 = _int_param(request, 'p2')
    z1 = _int_param(request, 'z1')
    accion = request.GET.get('accion')
    # Pestaña activa: se fuerza con ?tab=ediciones|perfiles|zonas; si no se
    # indica (o es inválido) se deduce de los parámetros de cada pestaña.
    tab = request.GET.get('tab')
    if tab not in ('ediciones', 'perfiles', 'zonas'):
        tab = None
    perfiles = {
        'perfil_e1': None,
        'perfil_e2': None,
        'perfil_a_html': '',
        'perfil_b_html': '',
        'perfil_m1': None,
        'perfil_m2': None,
        'perfil_sim_pct': None,
        'perfil_similares': None,
        'perfil_hint': None,
    }
    if p1:
        e1 = get_object_or_404(Etapa, id=p1)
        perfiles['perfil_e1'] = e1
        if p2 and p2 != p1:
            e2 = get_object_or_404(Etapa, id=p2)
            perfiles['perfil_e2'] = e2
            perfiles['perfil_a_html'] = perfil_etapa_html(e1)
            perfiles['perfil_b_html'] = perfil_etapa_html(e2)
            perfiles['perfil_m1'] = metricas(e1)
            perfiles['perfil_m2'] = metricas(e2)
            perfiles['perfil_sim_pct'] = round(indice_similitud(e1, e2) * 100)
        elif accion == 'comparar':
            perfiles['perfil_hint'] = 'Añade una etapa 2 (botón +) para comparar.'
        else:
            perfiles['perfil_a_html'] = perfil_etapa_html(e1)
            perfiles['perfil_similares'] = etapas_similares(e1, limite=6)
    elif p2:
        perfiles['perfil_hint'] = 'Primero elige una etapa 1.'

    # --- Pestaña "Zonas en común" ---
    # z1 es el id de una etapa de referencia. Busca, contra TODAS las ediciones,
    # las etapas que comparten carreteras con ella y construye un mapa con los
    # tramos en común resaltados.
    zona = {
        'zona_e': None,
        'zona_tramos': [],
        'zona_hint': None,
    }
    if z1:
        ze = get_object_or_404(Etapa, id=z1)
        zona['zona_e'] = ze
        zona['zona_tramos'] = tramos_comunes(ze)[:12]

    context = {
        'todas': todas,
        'a': a,
        'b': b,
        'ed_a': ed_a,
        'ed_b': ed_b,
        'color_a': color_a,
        'color_b': color_b,
        'orden_tipos': orden_tipos,
        'tipos_a': tipos_a,
        'tipos_b': tipos_b,
        'comunidades_a': comunidades_a,
        'comunidades_b': comunidades_b,
        'comunidades_comunes': comunidades_comunes,
        'des_chart_html': des_chart_html,
        'km_chart_html': km_chart_html,
        'box_chart_html': box_chart_html,
        'mapa_comparativo_html': mapa_comparativo_html,
        'todas_etapas': todas_etapas,
        'todas_etapas_json': todas_etapas_json,
        'tab': tab,
        **perfiles,
        **zona,
    }
    # Comparación de perfiles "in-situ": si llega una petición AJAX y hay dos
    # etapas elegidas, se devuelve solo el bloque de resultados para que la
    # página no se recargue al pulsar una fila de etapas similares.
    ajax = request.headers.get('X-Requested-With') == 'XMLHttpRequest'
    if ajax and perfiles['perfil_a_html'] and perfiles['perfil_b_html']:
        resultado = {
            'tab': tab,
            'color_a': color_a,
            'color_b': color_b,
            **perfiles,
        }
        return render(request, 'analytics/_perfiles_resultado.html', resultado)
    return render(request, 'analytics/comparador.html', context)


def ayuda(request):
    """Página estática de ayuda / modo de uso del sitio."""
    return render(request, 'analytics/ayuda.html')
