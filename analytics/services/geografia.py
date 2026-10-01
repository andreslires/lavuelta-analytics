"""Servicios de geografía: mapas y análisis por comunidades autónomas."""

import json
import math
from functools import lru_cache

import folium
import geopandas as gpd
from django.core.cache import cache
from django.urls import reverse
from folium.elements import Element
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely.wkt import loads

from analytics.models import Edicion, Etapa

from .charts import COLOR_ORO, COLOR_ROJO, color_edicion

# --- Tile layer settings  ---
TILE_URL = 'https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Dark_Gray_Base/MapServer/tile/{z}/{y}/{x}'
TILE_ATTR = '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors &copy; <a href="https://www.esri.com">Esri</a>, HERE, Garmin'
TILE_SUBDOMAINS = ''
TILE_NAME = 'Mapa base'


def capa_base():
    """TileLayer base con nombre legible para el control de capas."""
    return folium.TileLayer(
        tiles=TILE_URL,
        attr=TILE_ATTR,
        subdomains=TILE_SUBDOMAINS,
        name=TILE_NAME,
    )


def capa_base_negra(mapa):
    """Inyecta CSS para el modo noche del mapa (los tiles ya son oscuros)."""
    estilo = Element("""
    <style>
    .leaflet-control-attribution {
        background: rgba(10, 10, 10, 0.75);
        color: #888;
    }
    .leaflet-control-attribution a { color: #aaa; }
    .leaflet-control-layers {
        border: 1px solid #333;
        box-shadow: none;
    }
    .leaflet-control-layers-expanded {
        background: #141414 !important;
        color: #ccc;
    }
    .leaflet-control-layers-expanded label { color: #ccc; }
    .leaflet-control-layers-toggle { background-color: #141414 !important; }
    </style>
    """)
    mapa.get_root().html.add_child(estilo)
    return mapa


def _estilos_popup_dark(mapa):
    """Inyecta CSS para popups con estética dark (sin contenedor blanco)."""
    css = Element("""
    <style>
    .leaflet-popup-content-wrapper {
        background: #141414 !important;
        color: #e0e0e0 !important;
        border-radius: 8px !important;
        box-shadow: 0 2px 16px rgba(0,0,0,.6) !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
    }
    .leaflet-popup-content {
        margin: 0 !important;
        padding: 12px 14px !important;
        font-family: 'Barlow', sans-serif !important;
        color: #e0e0e0 !important;
        line-height: 1.4 !important;
    }
    .leaflet-popup-tip {
        background: #141414 !important;
        border: 1px solid rgba(255,255,255,0.08) !important;
    }
    .leaflet-popup-close-button {
        color: #666 !important;
        font-size: 18px !important;
    }
    .leaflet-popup-close-button:hover {
        color: #E3152B !important;
    }
    .leaflet-popup-content a.btn-ver-etapa {
        display: block;
        text-align: center;
        border: 1px solid #4a3233;
        color: #F0E7DC;
        text-decoration: none;
        padding: 5px 10px;
        font-size: 11px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: .06em;
        transition: all .15s;
    }
    .leaflet-popup-content a.btn-ver-etapa:hover {
        background: #E3152B;
        border-color: #E3152B;
        color: #fff;
    }
    </style>
    """)
    mapa.get_root().html.add_child(css)


@lru_cache(maxsize=None)
def cargar_ccaa():
    """Carga el GeoJSON de comunidades autónomas."""
    with open('mapa_ccaa_cache.geojson', encoding='utf-8') as f:
        return gpd.GeoDataFrame.from_features(json.load(f)['features'], crs='EPSG:4326')


@lru_cache(maxsize=None)
def cargar_provincias():
    """Carga el GeoJSON de provincias."""
    with open('mapa_provincias_cache.geojson', encoding='utf-8') as f:
        return gpd.GeoDataFrame.from_features(json.load(f)['features'], crs='EPSG:4326')


def _puntos_etapa(geom):
    """Devuelve los puntos de una geometría de etapa o None si no aplica."""
    if geom.geom_type not in ('LineString', 'MultiLineString'):
        return None
    coords = list(geom.coords)
    if not coords:
        return None
    return gpd.GeoDataFrame(
        geometry=gpd.points_from_xy([p[0] for p in coords], [p[1] for p in coords]),
        crs='EPSG:4326')


def geografia_global():
    """Etapas por comunidad autónoma, agregadas en TODAS las ediciones."""
    cache_key = 'geografia_global'
    result = cache.get(cache_key)
    if result is not None:
        return result

    ccaa = cargar_ccaa()
    conta = {}
    fuera = 0
    con_datos = 0
    for etapa in Etapa.objects.all():
        if not etapa.track_wkt:
            continue
        geom = loads(etapa.track_wkt)
        pts = _puntos_etapa(geom)
        if pts is None:
            continue
        con_datos += 1
        res = gpd.sjoin(pts, ccaa, how='inner', predicate='intersects')
        toca = set(res['name'].tolist())
        if not toca:
            fuera += 1
        for nombre in toca:
            conta[nombre] = conta.get(nombre, 0) + 1
    result = {
        'geo': [{'name': k, 'etapas': v} for k, v in sorted(conta.items(), key=lambda x: -x[1])],
        'fuera': fuera,
        'con_datos': con_datos,
    }
    cache.set(cache_key, result, timeout=None)
    return result


def comunidades_edicion(edicion):
    """Comunidades autónomas que atraviesa una edición completa.
    """
    cache_key = f'comunidades_edicion_{edicion.id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    ccaa = cargar_ccaa()
    comunidades = set()
    for etapa in edicion.etapas.all():
        if not etapa.track_wkt:
            continue
        geom = loads(etapa.track_wkt)
        pts = _puntos_etapa(geom)
        if pts is None:
            continue
        res = gpd.sjoin(pts, ccaa, how='inner', predicate='intersects')
        comunidades.update(res['name'].tolist())
    result = comunidades
    cache.set(cache_key, result, timeout=None)
    return result


def build_mapa_general(zoom_start=6, fit=None):
    """Mapa con todas las ediciones."""
    mapa = folium.Map(
        location=[40.4637, -3.7492],
        zoom_start=zoom_start,
        tiles=capa_base(),
    )
    _estilos_popup_dark(mapa)

    ediciones = Edicion.objects.all().order_by('year')
    for edicion in ediciones:
        grupo = folium.FeatureGroup(name=edicion.nombre)
        color = color_edicion(edicion.year)
        for etapa in edicion.etapas.all():
            if not etapa.track_wkt:
                continue
            geom = loads(etapa.track_wkt)
            linea = geom.simplify(tolerance=0.002, preserve_topology=True)
            coords = [(round(y, 5), round(x, 5)) for x, y in linea.coords]
            url = reverse('etapa_detalle', args=[edicion.year, etapa.numero])
            popup_html = (
                '<div style="min-width:180px">'
                f'<div style="font-weight:700;text-transform:uppercase;letter-spacing:.02em;font-size:13px">'
                f'<span style="color:#E3152B">{edicion.year}</span> · Etapa {etapa.numero}</div>'
                f'<div style="font-size:11px;color:#777;margin:3px 0 8px">{etapa.distancia:.0f} km · '
                f'{etapa.desnivel:.0f} m+</div>'
                f'<a href="{url}" target="_top" class="btn-ver-etapa">Ver etapa</a>'
                '</div>'
            )
            popup = folium.Popup(popup_html, max_width=220)
            folium.PolyLine(coords, color=color, weight=3.2, opacity=0.9,
                            popup=popup).add_to(grupo)
        grupo.add_to(mapa)

    if fit:
        mapa.fit_bounds(fit)

    folium.LayerControl().add_to(mapa)
    return capa_base_negra(mapa)


def build_mapa_comparativo(ed_a, ed_b, color_a=COLOR_ROJO, color_b=COLOR_ORO):
    """Mapa con las etapas de dos ediciones, cada una en su color."""
    mapa = folium.Map(
        location=[40.4637, -3.7492],
        zoom_start=6,
        tiles=capa_base(),
    )
    _estilos_popup_dark(mapa)

    bounds = []
    for edicion, color in ((ed_a, color_a), (ed_b, color_b)):
        grupo = folium.FeatureGroup(name=f'{edicion.nombre} ({edicion.year})')
        for etapa in edicion.etapas.all():
            if not etapa.track_wkt:
                continue
            geom = loads(etapa.track_wkt)
            linea = geom.simplify(tolerance=0.002, preserve_topology=True)
            coords = [(round(y, 5), round(x, 5)) for x, y in linea.coords]
            if not coords:
                continue
            bounds += coords
            url = reverse('etapa_detalle', args=[edicion.year, etapa.numero])
            popup_html = (
                '<div style="min-width:180px">'
                f'<div style="font-weight:700;text-transform:uppercase;letter-spacing:.02em;font-size:13px">'
                f'<span style="color:{color}">{edicion.year}</span> · Etapa {etapa.numero}</div>'
                f'<div style="font-size:11px;color:#777;margin:3px 0 8px">{etapa.distancia:.0f} km · '
                f'{etapa.desnivel:.0f} m+</div>'
                f'<a href="{url}" target="_top" class="btn-ver-etapa">Ver etapa</a>'
                '</div>'
            )
            popup = folium.Popup(popup_html, max_width=220)
            folium.PolyLine(coords, color=color, weight=3.2, opacity=0.9,
                            popup=popup).add_to(grupo)
        grupo.add_to(mapa)

    if bounds:
        sur = min(lat for lat, _ in bounds)
        oeste = min(lon for _, lon in bounds)
        norte = max(lat for lat, _ in bounds)
        este = max(lon for _, lon in bounds)
        mapa.fit_bounds([[sur, oeste], [norte, este]])

    folium.LayerControl().add_to(mapa)
    return capa_base_negra(mapa)


def ultima_etapa_por_provincia():
    """Devuelve, por cada provincia, la última etapa que la atravesó"""
    cache_key = 'ultima_etapa_por_provincia'
    result = cache.get(cache_key)
    if result is not None:
        return result

    prov = cargar_provincias()
    # Recorremos las etapas de más reciente a más antigua.
    etapas = (
        Etapa.objects.filter(track_wkt__isnull=False)
        .select_related('edicion')
        .order_by('-edicion__year', '-numero')
    )
    resultado = {}
    vistos = set()
    for etapa in etapas:
        geom = loads(etapa.track_wkt)
        pts = _puntos_etapa(geom)
        if pts is None:
            continue
        res = gpd.sjoin(pts, prov, how='inner', predicate='intersects')
        for nombre in set(res['name'].tolist()):
            if nombre in vistos:
                continue
            vistos.add(nombre)
            resultado[nombre] = {
                'year': etapa.edicion.year,
                'numero': etapa.numero,
                'nombre': etapa.nombre,
                'url': reverse('etapa_detalle', args=[etapa.edicion.year, etapa.numero]),
            }
    cache.set(cache_key, resultado, timeout=None)
    return resultado


def _popup_provincia_html(nombre):
    """HTML del popup de una provincia según su última etapa."""
    info = ultima_etapa_por_provincia().get(nombre)
    if not info:
        return (
            f'<div style="min-width:170px">'
            f'<div style="font-weight:700;text-transform:uppercase;font-size:13px;'
            f'letter-spacing:.03em">{nombre}</div>'
            '<div style="color:#777;margin-top:5px;font-size:12px">Sin etapas registradas</div>'
            '</div>'
        )
    return (
        f'<div style="min-width:200px">'
        f'<div style="font-weight:700;text-transform:uppercase;letter-spacing:.03em;'
        f'font-size:13px">{nombre}</div>'
        f'<div style="font-size:11px;color:#777;margin:3px 0 8px;text-transform:uppercase;'
        f'letter-spacing:.06em">Última etapa · '
        f'<span style="color:#E3152B;font-weight:700">{info["year"]}</span></div>'
        f'<div style="font-size:13px;color:#ccc;margin-bottom:8px">{info["nombre"]}</div>'
        f'<a href="{info["url"]}" target="_top" class="btn-ver-etapa">Ver etapa</a>'
        '</div>'
    )


def _leyenda_provincias_html():
    """HTML de la leyenda del mapa de provincias (dark theme)."""
    return """
    <div style="
        position:fixed;bottom:28px;left:14px;z-index:999;
        background:rgba(20,20,20,0.92);border:1px solid rgba(255,255,255,0.08);
        border-radius:8px;padding:12px 16px;
        font-family:'Barlow',sans-serif;font-size:12px;color:#ccc;
        box-shadow:0 2px 16px rgba(0,0,0,0.5);backdrop-filter:blur(4px);
        min-width:155px">
        <div style="font-weight:700;text-transform:uppercase;letter-spacing:.08em;
             font-size:10px;color:#777;margin-bottom:8px">Leyenda</div>
        <div style="display:flex;align-items:center;gap:8px;margin-bottom:5px">
            <span style="width:14px;height:10px;border-radius:2px;background:#E3152B;
                  display:inline-block"></span>
            <span>Provincia visitada</span>
        </div>
        <div style="display:flex;align-items:center;gap:8px">
            <span style="width:14px;height:10px;border-radius:2px;background:#2a2a2a;
                  border:1px solid #444;display:inline-block"></span>
            <span style="color:#777">Sin etapas</span>
        </div>
    </div>
    """


def build_mapa_provincias():
    """Mapa de provincias clickable sobre fondo oscuro."""
    mapa = folium.Map(
        location=[40.4637, -3.7492],
        zoom_start=6,
        tiles=None,
        zoom_control=False,
        scroll_wheel_zoom=False,
        double_click_zoom=False,
        dragging=False,
        prefer_canvas=True,
    )

    folium.TileLayer(
        tiles=TILE_URL,
        attr=TILE_ATTR,
        subdomains=TILE_SUBDOMAINS,
        name=TILE_NAME,
        opacity=0,
        show=False,
    ).add_to(mapa)

    bg_css = Element("""
    <style>
    .leaflet-container { background: #0B0A08 !important; }
    </style>
    """)
    mapa.get_root().html.add_child(bg_css)
    _estilos_popup_dark(mapa)

    ult = ultima_etapa_por_provincia()
    prov = cargar_provincias()

    for _, row in prov.iterrows():
        nombre = row['name']
        visitada = nombre in ult

        def _style(_feature, _vis=visitada):
            if _vis:
                return {
                    'fillColor': '#E3152B',
                    'color': '#555',
                    'weight': 1,
                    'fillOpacity': 0.45,
                }
            return {
                'fillColor': '#2a2a2a',
                'color': '#444',
                'weight': 0.8,
                'fillOpacity': 1,
            }

        def _highlight(_feature, _vis=visitada):
            if _vis:
                return {
                    'fillColor': '#F5A623',
                    'color': '#F5A623',
                    'weight': 1.5,
                    'fillOpacity': 0.6,
                }
            return {
                'fillColor': '#3a3a3a',
                'color': '#666',
                'weight': 1,
                'fillOpacity': 1,
            }

        gj = folium.GeoJson(
            row.geometry,
            style_function=_style,
            highlight_function=_highlight,
        )
        popup = folium.Popup(_popup_provincia_html(nombre), max_width=280)
        gj.add_child(popup)
        gj.add_to(mapa)

    return mapa


# --- TRAMOS COMUNES --- etapas que comparten carreteras con una etapa de referencia

# Tolerancia para considerar que dos tracks van por la misma carretera (m).
BUFFER_TRAMO_M = 50.0

# Proyección local (mercator aproximado) anclada en la etapa de referencia.
# k1 = m por grado de latitud; k2 = m por grado de longitud en esa latitud.


def _ancla_proyeccion(linea):
    """Punto medio de una línea como ancla (lat0, lon0, k1, k2)."""
    coords = list(linea.coords)
    mid = coords[len(coords) // 2]
    lat0, lon0 = mid[1], mid[0]
    return lat0, lon0, 111320.0, 111320.0 * math.cos(math.radians(lat0))


def _proyectar(linea, lat0, lon0, k1, k2):
    """Proyecta una LineString (lon, lat) al plano local en metros."""
    return LineString([(k2 * (x - lon0), -k1 * (y - lat0)) for x, y in linea.coords])


def _wkt_a_linea(wkt):
    """Convierte un track WKT (LINESTRING lon lat, ...) en una LineString."""
    if not wkt:
        return None
    try:
        geom = loads(wkt)
    except (ValueError, TypeError):
        return None
    if geom.geom_type == 'LineString':
        return geom
    if geom.geom_type == 'MultiLineString':
        partes = [p for p in geom.geoms if p.geom_type == 'LineString' and not p.is_empty]
        return unary_union(partes) if partes else None
    return None


def _tramo_comun_geom(ref_local, ref_buffer, linea_otra, distancia_m,
                      lat0, lon0, k1, k2):
    """Geometría (en proyección local) de ref que cae a <= distancia_m de otra."""
    otra_local = _proyectar(linea_otra, lat0, lon0, k1, k2).simplify(10)
    if ref_local.length == 0 or otra_local.length == 0:
        return LineString(), ref_local.length

    from shapely import STRtree
    pts_otra = list(otra_local.coords)
    segs = [LineString([p, q]) for p, q in zip(pts_otra[:-1], pts_otra[1:])]
    tree = STRtree(segs)
    hits = tree.query(ref_buffer)
    if hits.size == 0:
        return LineString(), ref_local.length

    union = unary_union([segs[i] for i in hits]).buffer(distancia_m)
    solape = ref_local.intersection(union)
    return solape, ref_local.length


def _fragmentos_solape(solape):
    """Devuelve los tramos (LineString) continuos de un solape."""
    if solape.is_empty:
        return []
    if solape.geom_type == 'LineString':
        return [solape]
    geoms = solape.geoms if hasattr(solape, 'geoms') else []
    tramos = []
    for g in geoms:
        if g.geom_type == 'LineString':
            tramos.append(g)
        elif g.geom_type == 'MultiLineString':
            tramos.extend(g.geoms)
    return tramos


def _solape_a_wgs(geom, lat0, lon0, k1, k2):
    """Desproyecta una geometría local (metros) a WGS84 (lon, lat)."""
    def _pto(x, y):
        return (lon0 + x / k2, lat0 - y / k1)
    if geom.geom_type == 'LineString':
        return LineString([_pto(x, y) for x, y in geom.coords])
    if geom.geom_type in ('MultiLineString', 'GeometryCollection'):
        return unary_union([_solape_a_wgs(g, lat0, lon0, k1, k2) for g in geom.geoms])
    return geom


def tramos_comunes(etapa_ref, tramo_min_km=3.0):
    """Etapas que comparten carretera con `etapa_ref`, de más a menos solape.

    Compara el track de la etapa de referencia contra el de TODAS las demás
    ediciones y devuelve, para cada una que comparte al menos `tramo_min_km` km
    de recorrido CONTINUO (para descartar simples cruces de carreteras), un
    dict {etapa, km, pct} donde km es el mayor tramo común real y pct su
    porcentaje sobre el total de la etapa de referencia. Se cachea por etapa.
    """
    cache_key = f'tramos_comunes_{etapa_ref.id}'
    cached = cache.get(cache_key)
    if cached is not None:
        return _hidratar_tramos(cached)

    linea_ref = _wkt_a_linea(etapa_ref.track_wkt)
    if linea_ref is None:
        cache.set(cache_key, [])
        return []

    # Ancla única para toda la comparación (evita reproyectar el buffer).
    lat0, lon0, k1, k2 = _ancla_proyeccion(linea_ref)
    ref_local = _proyectar(linea_ref, lat0, lon0, k1, k2)
    ref_buffer = ref_local.buffer(BUFFER_TRAMO_M)

    # Caja del buffer en grados (con margen) para descartar de un vistazo las
    # etapas que ni se acercan; así no se proyectan ~330 tracks por comparación.
    bx0, by0, bx1, by1 = ref_buffer.bounds
    lon0c = lon0 + bx0 / k2
    lon1c = lon0 + bx1 / k2
    lat0c = lat0 - by1 / k1
    lat1c = lat0 - by0 / k1
    margen = 0.15  # ~17 km extra por si los tracks se cruzan cerca del límite
    bbox_ref = (lon0c - margen, lat0c - margen, lon1c + margen, lat1c + margen)

    datos = []
    otras = (
        Etapa.objects.exclude(id=etapa_ref.id)
        .filter(track_wkt__isnull=False)
        .select_related('edicion')
    )
    for otra in otras:
        linea_otra = _wkt_a_linea(otra.track_wkt)
        if linea_otra is None:
            continue
        x0, y0, x1, y1 = linea_otra.bounds
        if x0 > bbox_ref[2] or x1 < bbox_ref[0] or y0 > bbox_ref[3] or y1 < bbox_ref[1]:
            continue
        solape, total_m = _tramo_comun_geom(
            ref_local, ref_buffer, linea_otra, BUFFER_TRAMO_M, lat0, lon0, k1, k2
        )
        tramos = _fragmentos_solape(solape)
        tramo_max_m = max((t.length for t in tramos), default=0.0)
        if tramo_max_m < tramo_min_km * 1000:
            continue
        km = tramo_max_m / 1000.0
        pct = tramo_max_m / total_m * 100.0 if total_m else 0.0
        geometria = _solape_a_wgs(solape, lat0, lon0, k1, k2)
        datos.append({
            'etapa_id': otra.id,
            'km': km,
            'pct': pct,
            'geom_wkt': geometria.wkt if not geometria.is_empty else '',
        })

    datos.sort(key=lambda r: (-r['km'], -r['pct']))
    cache.set(cache_key, datos)
    return _hidratar_tramos(datos)


def _hidratar_tramos(datos):
    """Convierte el cache (planos) a listas con objetos Etapa listos."""
    ids = [d['etapa_id'] for d in datos]
    etapas = {
        e.id: e
        for e in Etapa.objects.filter(id__in=ids).select_related('edicion')
    }
    res = []
    for d in datos:
        e = etapas.get(d['etapa_id'])
        if e is None:
            continue
        geom = None
        if d.get('geom_wkt'):
            try:
                geom = loads(d['geom_wkt'])
            except (ValueError, TypeError):
                geom = None
        res.append({'etapa': e, 'km': d['km'], 'pct': d['pct'], 'geom': geom})
    return res


def build_mapa_tramos_comunes(etapa_ref, resultados, color_track='#E3152B',
                              color_comun='#F5A623'):
    """Mapa con el track de la etapa de referencia y los tramos en común.

    El recorrido completo de la etapa de referencia se dibuja en `color_track`;
    los tramos que comparte con otras etapas (cualquiera de las del listado) se
    resaltan encima en `color_comun`.
    """
    linea_ref = _wkt_a_linea(etapa_ref.track_wkt)
    if linea_ref is None:
        return None

    coords = [(round(y, 5), round(x, 5)) for x, y in linea_ref.coords]
    if not coords:
        return None
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]

    mapa = folium.Map(
        location=[sum(lats) / len(lats), sum(lons) / len(lons)],
        zoom_start=7,
        tiles=capa_base(),
    )
    _estilos_popup_dark(mapa)
    folium.PolyLine(coords, color=color_track, weight=4, opacity=0.85).add_to(mapa)

    # Tramos en común: las geometrías ya vienen como WGS84 en cada resultado
    # (las calcula tramos_comunes). Se unen y se engordan ligeramente para que
    # se vean como una banda sobre el recorrido original.
    lineas_comunes = []
    for r in resultados:
        g = r.get('geom')
        if g is None or g.is_empty:
            continue
        if g.geom_type == 'LineString':
            lineas_comunes.append(g)
        elif g.geom_type in ('MultiLineString', 'GeometryCollection'):
            for p in (g.geoms if hasattr(g, 'geoms') else []):
                if p.geom_type in ('LineString', 'MultiLineString'):
                    lineas_comunes.append(p)

    if lineas_comunes:
        lat0, lon0, k1, k2 = _ancla_proyeccion(linea_ref)
        union_local = unary_union([
            _proyectar(g, lat0, lon0, k1, k2).buffer(10) for g in lineas_comunes
        ])
        contorno = union_local.boundary
        if contorno.geom_type == 'LineString':
            lineas_final = [contorno]
        elif contorno.geom_type == 'MultiLineString':
            lineas_final = list(contorno.geoms)
        else:
            lineas_final = []
        for linea in lineas_final:
            c = [
                (round(lat0 - y / k1, 5), round(lon0 + x / k2, 5))
                for x, y in linea.coords
            ]
            folium.PolyLine(c, color=color_comun, weight=4, opacity=0.9).add_to(mapa)

    mapa.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(25, 25))
    return capa_base_negra(mapa)


def _contorno_tramos_wgs(geom_wgs, lat0, lon0, k1, k2, grosor_m=10):
    """Líneas de contorno (WGS84) de los tramos en común, engordados."""
    partes = []
    if geom_wgs is None or geom_wgs.is_empty:
        return partes
    if geom_wgs.geom_type == 'LineString':
        geoms = [geom_wgs]
    elif geom_wgs.geom_type == 'MultiLineString':
        geoms = list(geom_wgs.geoms)
    else:
        geoms = []
    for g in geoms:
        local = _proyectar(g, lat0, lon0, k1, k2)
        contorno = local.buffer(grosor_m).boundary
        if contorno.geom_type == 'LineString':
            lineas = [contorno]
        elif contorno.geom_type == 'MultiLineString':
            lineas = list(contorno.geoms)
        else:
            lineas = []
        for lo in lineas:
            partes.append([
                (round(lat0 - y / k1, 5), round(lon0 + x / k2, 5))
                for x, y in lo.coords
            ])
    return partes


def build_mapa_par_tramos(etapa_ref, otra, geom_comun, color_ref='#E3152B',
                          color_otra='#6FA8DC', color_comun='#F5A623'):
    """Mapa cara a cara: track de referencia + track de otra + tramos en común.

    Dibuja el recorrido completo de `etapa_ref` en `color_ref`, el de `otra` en
    `color_otra`, y sobre ambos resalta en `color_comun` las carreteras que
    comparten (geom_comun, en WGS84). Devuelve el folium.Map o None.
    """
    linea_ref = _wkt_a_linea(etapa_ref.track_wkt)
    linea_otra = _wkt_a_linea(otra.track_wkt)
    if linea_ref is None or linea_otra is None:
        return None

    coords_ref = [(round(y, 5), round(x, 5)) for x, y in linea_ref.coords]
    coords_otra = [(round(y, 5), round(x, 5)) for x, y in linea_otra.coords]
    if not coords_ref or not coords_otra:
        return None

    mapa = folium.Map(location=coords_ref[len(coords_ref) // 2], zoom_start=7,
                      tiles=capa_base())
    _estilos_popup_dark(mapa)
    folium.PolyLine(coords_ref, color=color_ref, weight=4, opacity=0.9).add_to(mapa)
    folium.PolyLine(coords_otra, color=color_otra, weight=3.5, opacity=0.8).add_to(mapa)

    lat0, lon0, k1, k2 = _ancla_proyeccion(linea_ref)
    for c in _contorno_tramos_wgs(geom_comun, lat0, lon0, k1, k2):
        folium.PolyLine(c, color=color_comun, weight=4, opacity=0.95).add_to(mapa)

    todos = coords_ref + coords_otra
    lats = [c[0] for c in todos]
    lons = [c[1] for c in todos]
    mapa.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]], padding=(25, 25))
    return capa_base_negra(mapa)
