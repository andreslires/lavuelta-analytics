"""Similitud entre etapas: análisis multi-métrica.

Compara etapas por un vector completo de características:
  - Distancia total (km)
  - Desnivel positivo acumulado (m)
  - Nº de puertos de montaña
  - Pendiente media de los puertos (%)
  - Altitud máxima alcanzada (m)
  - Forma del perfil normalizado (441 muestras)

Cada métrica se normaliza como diferencia relativa [0, 1] y se pondera para
obtener un índice de similitud único (1.0 = idénticas, 0.0 = nada parecidas).

No se excluye ningún tipo de etapa: una contrareloj se parecerá naturalmente
a otras contrarrelojes porque TODAS las métricas serán similares entre sí y
muy distintas de una etapa de montaña.
"""

import numpy as np
from django.core.cache import cache

from analytics.models import Etapa

from .gpx_processor import GPXProcessor

# Nº de muestras del perfil normalizado (441 = trama de alta fidelidad).
N_MUESTRAS = 441


# ---------------------------------------------------------------------------
# Pesos de cada métrica en el índice compuesto (suman 1.0)
# ---------------------------------------------------------------------------
PESOS = {
    'distancia': 0.15,
    'desnivel': 0.20,
    'n_puertos': 0.20,
    'pend_media': 0.15,
    'alt_max': 0.10,
    'forma': 0.20,
}


# ---------------------------------------------------------------------------
# Helpers de datos GPX (cacheados)
# ---------------------------------------------------------------------------
def _gpx_data(etapa):
    """Datos GPX procesados de una etapa (cacheados por archivo)."""
    key = f'gpx_data_{etapa.file_path}'
    data = cache.get(key)
    if data is None:
        data = GPXProcessor(etapa.file_path).process()
        cache.set(key, data, timeout=None)
    return data


def _elevacion_suavizada(etapa):
    return _gpx_data(etapa)['df']['elevation_smooth'].to_numpy()


def formatear_perfil(arr):
    """Serializa el perfil normalizado como CSV compacto para el campo Etapa.perfil."""
    return ','.join(f'{v:.6f}' for v in arr)


def perfil_from_elevation(z):
    """Perfil normalizado [0,1] por esfuerzo vertical, a partir de alturas crudas.

    Reparametrización por arco vertical: el eje X destino (0..1) acumula |ΔT|,
    de modo que los tramos con más pendiente ocupan proporcionalmente más eje.
    """
    z = np.asarray(z, dtype=np.float64)
    n = len(z)
    if n < 2:
        return np.zeros(N_MUESTRAS)
    rango = float(z.max() - z.min())
    if rango < 1e-6:
        return np.zeros(N_MUESTRAS)
    t = (z - z.min()) / rango
    d = np.abs(np.diff(t))
    total = float(d.sum())
    if total < 1e-12:
        return np.full(N_MUESTRAS, t[0])
    cum = np.cumsum(d)
    pos = (np.arange(N_MUESTRAS) + 0.5) / N_MUESTRAS
    return np.interp(pos * cum[-1], np.concatenate(([0.0], cum)), t[:n])


def perfil_forma(etapa):
    """Perfil normalizado [0,1] por esfuerzo vertical de una etapa.

    Prioriza el valor persistido en BD (etapa.perfil); si falta, lo calcula y
    lo guarda (autocuración) para no repetir el coste de procesar el GPX.
    """
    if etapa.perfil:
        arr = np.array(etapa.perfil.split(','), dtype=np.float64)
        if arr.size == N_MUESTRAS:
            return arr
    arr = perfil_from_elevation(_elevacion_suavizada(etapa))
    etapa.perfil = formatear_perfil(arr)
    etapa.save(update_fields=['perfil'])
    return arr


# ---------------------------------------------------------------------------
# Vector de características de una etapa (directo de la BD, sin procesar GPX)
# ---------------------------------------------------------------------------
def _feature_vector(etapa):
    """Devuelve las 6 métricas clave de una etapa leyendo de la BD.

    Usa los campos precalculados (altitud_max, n_puertos, etc.) y el perfil
    normalizado ya persistido. No procesa archivos GPX.
    """
    return {
        'distancia': etapa.distancia,
        'desnivel': etapa.desnivel,
        'n_puertos': etapa.n_puertos,
        'pend_media': etapa.pendiente_media,
        'alt_max': etapa.altitud_max,
        'forma': perfil_forma(etapa),
    }


# ---------------------------------------------------------------------------
# Índice de similitud compuesto
# ---------------------------------------------------------------------------
def _diff_rel(a, b):
    """Diferencia relativa entre dos valores: 0 si son iguales, 1 si uno es 0."""
    mx = max(a, b)
    if mx < 1e-9:
        return 0.0
    return abs(a - b) / mx


def indice_similitud(e_a, e_b):
    """Índice de similitud entre dos etapas. 1.0 = idénticas, 0.0 = nada.

    Compara 6 métricas con pesos calibrados:
      - Distancia (0.15):  etapas de longitud similar
      - Desnivel (0.20):   misma carga de subida
      - Nº puertos (0.20): misma cantidad de puertos
      - Pend. media (0.15): puertos de dureza similar
      - Altitud máx (0.10): cumbres de altura comparable
      - Forma perfil (0.20): mismo "dibujo" del perfil
    """
    if e_a.id == e_b.id:
        return 1.0

    fa = _feature_vector(e_a)
    fb = _feature_vector(e_b)

    # Diferencia de cada métrica normalizada [0, 1]
    d_dist = _diff_rel(fa['distancia'], fb['distancia'])
    d_desn = _diff_rel(fa['desnivel'], fb['desnivel'])
    d_puer = _diff_rel(fa['n_puertos'], fb['n_puertos'])
    d_pend = _diff_rel(fa['pend_media'], fb['pend_media'])
    d_altm = _diff_rel(fa['alt_max'], fb['alt_max'])

    # MSE del perfil normalizado → diferencia [0, 1]
    # Un MSE de ~0.15 equivale a difference = 1.0 (muy distintos)
    mse = float(np.mean((fa['forma'] - fb['forma']) ** 2))
    d_forma = min(1.0, mse / 0.15)

    # Índice compuesto: media ponderada de las diferencias
    penalizacion = (
        PESOS['distancia'] * d_dist
        + PESOS['desnivel'] * d_desn
        + PESOS['n_puertos'] * d_puer
        + PESOS['pend_media'] * d_pend
        + PESOS['alt_max'] * d_altm
        + PESOS['forma'] * d_forma
    )

    return round(max(0.0, 1.0 - penalizacion), 3)


def etapas_similares(referencia, limite=6):
    """Las N etapas más parecidas a `referencia`, excluyéndola a ella misma.

    Compara contra todas las demás etapas sin filtrar por tipo: la lógica
    multi-métrica hace que cada tipo se agrupe naturalmente con los suyos.
    Solo carga los campos necesarios para la comparación (no track_wkt).
    """
    campos = [
        "id", "edicion_id", "numero", "nombre", "tipo",
        "distancia", "desnivel", "perfil",
        "altitud_max", "pendiente_media", "n_puertos",
    ]
    otros = (
        Etapa.objects.exclude(id=referencia.id)
        .select_related("edicion")
        .only(*campos)
    )
    pares = [(indice_similitud(referencia, e), e) for e in otros]
    pares.sort(key=lambda p: -p[0])
    return pares[:limite]


# ---------------------------------------------------------------------------
# Métricas detalladas (para la tabla de comparación lado a lado)
# ---------------------------------------------------------------------------
def metricas(etapa):
    """Métricas clave de una etapa para la comparación profunda.

    Lee directamente de los campos precalculados en BD.
    """
    return {
        'edicion': etapa.edicion.year,
        'numero': etapa.numero,
        'nombre': etapa.nombre,
        'tipo': etapa.tipo,
        'distancia': etapa.distancia,
        'desnivel': etapa.desnivel,
        'pendiente_max': etapa.pendiente_max,
        'pendiente_media': etapa.pendiente_media,
        'n_puertos': etapa.n_puertos,
        'altitud_max': etapa.altitud_max,
    }


# ---------------------------------------------------------------------------
# Gráfico de perfil para el comparador
# ---------------------------------------------------------------------------
def perfil_etapa_html(etapa):
    """Perfil altimétrico real de una etapa (sin normalizar; km reales).

    Cada perfil se dibuja en su propio chart para que puedan colocarse uno al
    lado del otro sin solaparse, conservando la longitud y las alturas reales.

    Usa escalado adaptativo según la categoría del recorrido (mismo criterio
    que etapa_detalle): contrarelojes compactas, llanas panorámicas, montaña
    con techo alto.
    """
    import json

    import plotly.graph_objects as go

    from .charts import COLOR_GRID, COLOR_ROJO, COLOR_TEXTO, chart_layout

    if etapa.file_path:
        df = _gpx_data(etapa)['df']
        x = df['dist_accumulated'].to_numpy()
        y = df['elevation_smooth'].to_numpy()
    else:
        # Etapa importada sin GPX: se usa el perfil real persistido.
        try:
            profile = json.loads(etapa.perfil_real or '[]')
        except (ValueError, TypeError):
            profile = []
        perfil_filtrado = [p for p in profile if p and len(p) >= 2]
        x = [float(p[0]) for p in perfil_filtrado]
        y = [float(p[1]) for p in perfil_filtrado]
        if not x:
            return ''
    color = COLOR_ROJO  # perfil de una sola etapa: rojo Vuelta

    D = float(x[-1]) if len(x) else 0.0
    a_max = float(max(y)) if len(y) else 0.0

    SUELO = -10

    if D < 45:
        techo = a_max + 150
        alto = 330
    elif a_max <= 800:
        techo = 800
        alto = 250
    else:
        techo = max(2500, a_max + 200)
        alto = 250

    fig = go.Figure(go.Scatter(
        x=x, y=y, mode='lines', line=dict(color=color, width=2.2),
        fill='tozeroy', fillcolor='rgba(227, 21, 43, 0.22)', cliponaxis=False,
        hovertemplate='%{x:.1f} km · %{y:.0f} m<extra></extra>'))
    chart_layout(fig)
    fig.update_layout(
        height=alto,
        margin=dict(l=0, r=0, t=10, b=20),
    )
    fig.update_xaxes(
        title_text='Distancia (km)', range=[0, D],
        showgrid=False, tickfont=dict(color=COLOR_TEXTO))
    fig.update_yaxes(
        title_text='Altitud (m)',
        range=[SUELO, techo],
        gridcolor=COLOR_GRID, zeroline=False, tickfont=dict(color=COLOR_TEXTO))
    return fig.to_html(full_html=False, include_plotlyjs=False, config={'displayModeBar': False})

