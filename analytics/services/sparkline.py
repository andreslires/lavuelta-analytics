"""Sparkline de perfil altimétrico para tarjetas de etapas.

Genera un pequeño SVG (polyline) a partir del perfil real persistido
(etapa.perfil_real, JSON [[km, alt], ...]). Sin dependencias de JavaScript:
se pinta en el servidor en el render de la vista.
"""

import json

# Lienzo del sparkline (el navegador lo estira con preserveAspectRatio="none").
_SPARK_W = 1000
_SPARK_H = 120
_TOP = 6
_BASE = 116
_N_BUCKETS = 60


def sparkline_svg(etapa, stroke='#E3152B'):
    """Devuelve el SVG del mini-perfil de una etapa ('' si no hay datos).

    El muestreo conserva el mínimo y el máximo de altitud por franja, de modo
    que las cumbres no se pierden aunque el perfil sea denso.
    """
    try:
        profile = json.loads(etapa.perfil_real or '[]')
    except (ValueError, TypeError):
        profile = []
    pts = [(float(p[0]), float(p[1])) for p in profile if p and len(p) >= 2]
    if len(pts) < 2:
        return ''

    d_total = pts[-1][0]
    if not d_total:
        return ''

    altitudes = [alt for _, alt in pts]
    z_min, z_max = min(altitudes), max(altitudes)
    span = (z_max - z_min) or 1.0

    def _x(km):
        return km / d_total * _SPARK_W

    def _y(alt):
        return _BASE - (alt - z_min) / span * (_BASE - _TOP)

    # Muestreo por franjas: se guarda el punto más bajo y el más alto de cada
    # franja para conservar los trazos del relieve (cumbres y valles).
    if len(pts) > 2 * _N_BUCKETS:
        step = d_total / _N_BUCKETS
        franjas = {}
        for km, alt in pts:
            b = int(min((km - pts[0][0]) / step, _N_BUCKETS - 1))
            lo, hi = franjas.setdefault(b, (None, None))
            if lo is None or alt < lo[1]:
                lo = (km, alt)
            if hi is None or alt > hi[1]:
                hi = (km, alt)
            franjas[b] = (lo, hi)
        pts = [p for lo, hi in franjas.values() for p in (lo, hi)]
        pts.sort(key=lambda p: p[0])

    d = 'M' + ' L'.join(f'{_x(km):.1f},{_y(alt):.1f}' for km, alt in pts)
    return (
        f'<svg viewBox="0 0 {_SPARK_W} {_SPARK_H}" preserveAspectRatio="none"'
        f' xmlns="http://www.w3.org/2000/svg" aria-hidden="true">'
        f'<path d="{d}" fill="none" stroke="{stroke}" stroke-width="2.5"'
        f' vector-effect="non-scaling-stroke" stroke-linejoin="round"'
        f' stroke-linecap="round"/>'
        f'</svg>'
    )