# Consultas y agregados de ciclistas (directorio, ranking y ficha).
# Se apoyan en la tabla relacional ResultadoEtapa y ClasificacionGeneral.
from collections import defaultdict
from django.core.cache import cache
from django.db.models import Count, Q

from analytics.models import Ciclista, ClasificacionGeneral, Etapa, ResultadoEtapa


RANKING_CACHE_KEY = 'ciclistas_ranking_all_v3'


def invalidar_ranking_cache():
    """Elimina el ranking cacheado; llamar tras cualquier importación de datos."""
    cache.delete(RANKING_CACHE_KEY)


class CiclistaResumen:
    def __init__(self, pk, nombre, victorias, victorias_gc, podios, podios_gc, top10, top10_gc, participaciones, y0, y1, equipo):
        self.pk = pk
        self.nombre = nombre
        self.victorias = victorias
        self.victorias_gc = victorias_gc
        self.podios = podios
        self.podios_gc = podios_gc
        self.top10 = top10
        self.top10_gc = top10_gc
        self.participaciones = participaciones
        self.y0 = y0
        self.y1 = y1
        self.equipo = equipo


def ranking():
    """Ciclistas ordenados por victorias (incluye a todos los participantes en GC o etapas)."""
    cached = cache.get(RANKING_CACHE_KEY)
    if cached is not None:
        return cached

    ciclistas = list(
        Ciclista.objects.filter(
            Q(resultadoetapa__isnull=False) | Q(clasificaciones_generales__isnull=False)
        )
        .distinct()
        .values('pk', 'nombre')
    )

    victorias = dict(
        ResultadoEtapa.objects.filter(posicion=1)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )
    victorias_gc = dict(
        ClasificacionGeneral.objects.filter(posicion=1)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )
    podios = dict(
        ResultadoEtapa.objects.filter(posicion__lte=3)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )
    podios_gc = dict(
        ClasificacionGeneral.objects.filter(posicion__lte=3)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )
    top10 = dict(
        ResultadoEtapa.objects.filter(posicion__lte=10)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )
    top10_gc = dict(
        ClasificacionGeneral.objects.filter(posicion__lte=10)
        .values('ciclista_id')
        .annotate(c=Count('id'))
        .values_list('ciclista_id', 'c')
    )

    etapa_anos = dict(Etapa.objects.values_list('id', 'edicion__year'))
    anos = defaultdict(set)
    for cid, etapa_id in ResultadoEtapa.objects.values_list('ciclista_id', 'etapa_id'):
        y = etapa_anos.get(etapa_id)
        if y:
            anos[cid].add(y)
    for cid, y in ClasificacionGeneral.objects.values_list('ciclista_id', 'edicion__year'):
        if y:
            anos[cid].add(y)

    equipos = {}
    for cid, eq in ResultadoEtapa.objects.filter(equipo__isnull=False).order_by('-etapa__edicion__year', '-etapa__numero').values_list('ciclista_id', 'equipo__nombre'):
        if cid not in equipos:
            equipos[cid] = eq
    for cid, eq in ClasificacionGeneral.objects.filter(equipo__isnull=False).order_by('-edicion__year').values_list('ciclista_id', 'equipo__nombre'):
        if cid not in equipos:
            equipos[cid] = eq

    res = []
    for c in ciclistas:
        cid = c['pk']
        y_set = anos[cid]
        res.append(
            CiclistaResumen(
                pk=cid,
                nombre=c['nombre'],
                victorias=victorias.get(cid, 0),
                victorias_gc=victorias_gc.get(cid, 0),
                podios=podios.get(cid, 0),
                podios_gc=podios_gc.get(cid, 0),
                top10=top10.get(cid, 0),
                top10_gc=top10_gc.get(cid, 0),
                participaciones=len(y_set),
                y0=min(y_set) if y_set else None,
                y1=max(y_set) if y_set else None,
                equipo=equipos.get(cid, ''),
            )
        )

    res.sort(key=lambda x: (-x.victorias, -x.podios, -x.top10, x.nombre))
    cache.set(RANKING_CACHE_KEY, res, timeout=86400)
    return res


def ficha(ciclista):
    """Resumen completo de un ciclista para su página de detalle."""
    resultados = list(
        ResultadoEtapa.objects.filter(ciclista=ciclista)
        .select_related('etapa', 'etapa__edicion', 'equipo')
        .order_by('-etapa__edicion__year', 'etapa__numero')
    )
    generales = list(
        ClasificacionGeneral.objects.filter(ciclista=ciclista)
        .select_related('edicion', 'equipo')
        .order_by('-edicion__year')
    )
    victorias = [r for r in resultados if r.posicion == 1]
    podios = [r for r in resultados if 2 <= r.posicion <= 3]
    years = sorted(
        {r.etapa.edicion.year for r in resultados}
        | {g.edicion.year for g in generales}
    )

    por_anio = {}
    equipos = {}

    def fila_anio(year):
        return por_anio.setdefault(
            year,
            {
                'year': year,
                'victorias': 0,
                'podios': 0,
                'top10': 0,
                'equipos': [],
                'general_posicion': None,
                'general_tiempo': '',
                'general_diferencia': '',
                'general_equipo': '',
            },
        )

    def registrar_equipo(nombre, year, fila):
        if not nombre:
            return
        if nombre not in fila['equipos']:
            fila['equipos'].append(nombre)
        equipo = equipos.setdefault(
            nombre,
            {'nombre': nombre, 'y0': year, 'y1': year, 'n': 0},
        )
        equipo['y0'] = min(equipo['y0'], year)
        equipo['y1'] = max(equipo['y1'], year)
        equipo['n'] += 1

    for r in resultados:
        year = r.etapa.edicion.year
        fila = fila_anio(year)
        if r.posicion == 1:
            fila['victorias'] += 1
        if r.posicion <= 3:
            fila['podios'] += 1
        if r.posicion <= 10:
            fila['top10'] += 1
        if r.equipo:
            registrar_equipo(r.equipo.nombre, year, fila)

    for g in generales:
        year = g.edicion.year
        fila = fila_anio(year)
        fila['general_posicion'] = g.posicion
        fila['general_tiempo'] = g.tiempo or ''
        fila['general_diferencia'] = g.diferencia or ''
        if g.equipo:
            fila['general_equipo'] = g.equipo.nombre
            registrar_equipo(g.equipo.nombre, year, fila)

    por_anio_lista = [por_anio[y] for y in sorted(por_anio, reverse=True)]
    for fila in por_anio_lista:
        fila['equipos_txt'] = ' / '.join(fila['equipos'])

    equipos_lista = sorted(equipos.values(), key=lambda e: (-e['y1'], e['nombre']))
    mejor_general_obj = min(generales, key=lambda g: g.posicion) if generales else None

    return {
        'resultados': resultados,
        'generales': generales,
        'victorias': victorias,
        'podios': podios,
        'podios_todos': [r for r in resultados if r.posicion <= 3],
        'top10': sum(1 for r in resultados if r.posicion <= 10),
        'podios_total': sum(1 for r in resultados if r.posicion <= 3),
        'victorias_general': sum(1 for g in generales if g.posicion == 1),
        'podios_general': sum(1 for g in generales if g.posicion <= 3),
        'participaciones': len(years),
        'y0': years[0] if years else None,
        'y1': years[-1] if years else None,
        'por_anio': por_anio_lista,
        'equipos': equipos_lista,
        'equipo_actual': equipos_lista[0]['nombre'] if equipos_lista else '',
        'mejor_resultado': min(
            (r.posicion for r in resultados if r.posicion), default=None
        ),
        'mejor_general': mejor_general_obj.posicion if mejor_general_obj else None,
        'mejor_general_anio': mejor_general_obj.edicion.year if mejor_general_obj else None,
        'top10_general': sum(1 for g in generales if g.posicion <= 10),
        'ediciones_terminadas': len(generales),
    }
