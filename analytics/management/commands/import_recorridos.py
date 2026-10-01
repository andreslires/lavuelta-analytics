# Importa datos factuales de La Vuelta a España desde los ficheros locales de
# data/recorridos/. No hace llamadas de red; los ficheros los genera la
# herramienta de descarga externa (downloader.py, fuera del repo).
#
# Uso:
#   python manage.py import_recorridos                  # todo 2011-2026
#   python manage.py import_recorridos --years 2011,2012
#   python manage.py import_recorridos --create-only    # no actualiza existentes
import json
import os
import sys

import numpy as np
from django.conf import settings
from django.core.cache import cache
from django.core.management.base import BaseCommand

from analytics.models import Edicion, Etapa
from analytics.services.gpx_processor import clasificar_etapa, metrics_from_perfil
from analytics.services.perfiles_similares import formatear_perfil, perfil_from_elevation


def _read_json(path):
    with open(path, 'r', encoding='utf-8') as fh:
        return json.load(fh)


def _wkt_from_points(points):
    """WKT 'LINESTRING(lon lat, ...)' a partir de [[lon, lat], ...]."""
    if not points:
        return ''
    coords = ', '.join(f'{lon:.6f} {lat:.6f}' for lon, lat in points)
    return f'LINESTRING ({coords})'


def _climbs_from_profile(profile):
    """Detecta puertos (subidas continuas) sobre un perfil [km, alt]."""
    profile = [p for p in profile if p and len(p) >= 2]
    if len(profile) < 3:
        return []
    x = np.array([p[0] for p in profile], dtype=np.float64)
    z = np.array([p[1] for p in profile], dtype=np.float64)
    if z.std() < 1e-6:
        return []
    # Suavizado ligero (equivalente al rolling window de los GPX)
    kernel = np.ones(3) / 3.0
    zs = np.convolve(z, kernel, mode='same')
    n = len(x)
    climbs = []
    i = 0
    while i < n - 1:
        while i < n - 1 and zs[i + 1] <= zs[i] + 0.05:
            i += 1
        start = i
        gain = 0.0
        while i < n - 1 and zs[i + 1] > zs[i]:
            gain += zs[i + 1] - zs[i]
            i += 1
        d = (x[i] - x[start]) if i < n else (x[-1] - x[start])
        if gain >= 120 and d > 0.5:
            climbs.append({'km': float(d), 'gain': float(gain),
                           'grad': gain / (d * 1000) * 100})
    return climbs


def _pendiente_media_puertos(climbs):
    if not climbs:
        return 0.0
    total_km = sum(c['km'] for c in climbs)
    if total_km <= 0:
        return 0.0
    return sum(c['grad'] * c['km'] for c in climbs) / total_km


class Command(BaseCommand):
    help = 'Importa datos factuales de la Vuelta a España masculina desde ficheros locales.'

    def add_arguments(self, parser):
        parser.add_argument('--years', default='',
                            help='Años a importar, separados por coma (ej. 2011,2012). Por defecto todos.')
        parser.add_argument('--data-dir', default='')
        parser.add_argument('--create-only', action='store_true',
                            help='Solo crea ediciones/etapas faltantes, no actualiza las existentes.')

    def handle(self, *args, **options):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
        self.create_only = options['create_only']
        self.data_dir = options['data_dir'] or str(settings.BASE_DIR / 'data' / 'recorridos')
        years_seleccionados = {int(y) for y in options['years'].split(',') if y.strip()} or None

        routes_path = os.path.join(self.data_dir, 'routes.json')
        if not os.path.exists(routes_path):
            self.stderr.write(f'No se encuentra {routes_path}. Ejecuta primero el descargador externo.')
            return
        vueltas = _read_json(routes_path)
        if not vueltas:
            self.stderr.write('No hay etapas en routes.json.')
            return

        por_anio = {}
        for f in vueltas:
            anio = int(f['properties']['year'])
            if years_seleccionados and anio not in years_seleccionados:
                continue
            por_anio.setdefault(anio, []).append(f)
        por_anio = dict(sorted(por_anio.items()))

        total = sum(len(v) for v in por_anio.values())
        self.stdout.write(f'Etapas a procesar: {total} en {len(por_anio)} ediciones.')

        contador = {'creadas': 0, 'actualizadas': 0, 'ediciones': 0}
        for anio, features in por_anio.items():
            self._importar_edicion(anio, features, contador)

        cache.clear()
        self.stdout.write(self.style.SUCCESS(
            f'Importación terminada: {contador["ediciones"]} ediciones, '
            f'{contador["creadas"]} etapas creadas, {contador["actualizadas"]} etapas actualizadas.'
        ))

    # ------------------------------------------------------------------
    def _edition_path(self, slug):
        return os.path.join(self.data_dir, 'editions', f'{slug}.json')

    def _stage_path(self, rid):
        return os.path.join(self.data_dir, 'stages', f'{rid}.json')

    def _importar_edicion(self, anio, features, contador):
        features = sorted(features, key=lambda f: int(f['properties']['stage']))
        slug = features[0]['properties']['rid'].rsplit('-', 1)[0]
        edicion, created = Edicion.objects.get_or_create(
            year=anio,
            defaults={'nombre': f'La Vuelta {anio}'},
        )
        if created:
            contador['ediciones'] += 1

        # Datos de la edición: GC final y maillots (factuales).
        detail = {}
        ed_path = self._edition_path(slug)
        if os.path.exists(ed_path):
            try:
                detail = _read_json(ed_path)
            except (ValueError, OSError) as exc:  # noqa
                self.stderr.write(f'  Aviso: edición {slug} ilegible ({exc})')
                detail = {}

        gc = detail.get('gc') or []
        maillots = detail.get('jerseys') or {}
        if gc and gc[0].get('rider'):
            edicion.ganador = gc[0]['rider']
        if gc:
            edicion.gc_json = json.dumps(gc, ensure_ascii=False)
        if maillots:
            edicion.maillots_json = json.dumps(maillots, ensure_ascii=False)

        fechas = []
        for f in features:
            numero = int(f['properties']['stage'])
            self._importar_etapa(edicion, f, contador, fechas)
        if fechas:
            edicion.fecha_inicio = min(fechas)
            edicion.fecha_fin = max(fechas)
        edicion.save(update_fields=[
            'ganador', 'gc_json', 'maillots_json', 'fecha_inicio', 'fecha_fin',
        ] if not created else None)
        self.stdout.write(self.style.SUCCESS(
            f'[{anio}] {len(features)} etapas · ganador: {edicion.ganador or "—"}'
        ))

    def _importar_etapa(self, edicion, feature, contador, fechas):
        props = feature['properties']
        numero = int(props['stage'])
        rid = props['rid']
        etapa = Etapa.objects.filter(edicion=edicion, numero=numero).first()

        # Datos que siempre se pueden leer desde routes.json.
        localidad_inicio = props.get('from', '')
        localidad_fin = props.get('to', '')
        ganador = props.get('winner', '')
        distancia_oficial = props.get('km')

        if etapa is not None and self.create_only:
            contador['actualizadas'] += 1
            return

        # Fecha y detalles del track/perfil/resultado (fichero por etapa).
        detail = {}
        st_path = self._stage_path(rid)
        if os.path.exists(st_path):
            try:
                detail = _read_json(st_path)
            except (ValueError, OSError) as exc:  # noqa
                self.stderr.write(f'  Aviso: detalle {rid} ilegible ({exc})')
                detail = {}

        stage = detail.get('stage') or {}
        if stage.get('date'):
            fechas.append(stage['date'][:10])
        if not localidad_inicio:
            localidad_inicio = stage.get('fromTown') or ''
        if not localidad_fin:
            localidad_fin = stage.get('toTown') or ''
        if not ganador:
            ganador = stage.get('winner') or ''

        gc_leader = ''
        gc_leader_obj = detail.get('gcLeader') or {}
        if gc_leader_obj.get('rider'):
            gc_leader = gc_leader_obj['rider']
        resultados = json.dumps(detail.get('stageResult') or [], ensure_ascii=False)

        points = detail.get('points') or []
        profile = detail.get('profile') or []

        if etapa is None:
            # Etapa nueva: se construye desde el track/perfil local.
            distancia = distancia_oficial or 0
            desnivel = stage.get('elevGainM') or 0
            if distancia <= 0:
                distancia = stage.get('distanceKm') or 0
            track_wkt = _wkt_from_points(points)
            perfil_real = json.dumps(profile, ensure_ascii=False)

            if profile:
                alts = [p[1] for p in profile if len(p) >= 2]
                perfil = formatear_perfil(perfil_from_elevation(np.array(alts, dtype=np.float64)))
            else:
                perfil = ''

            climbs = _climbs_from_profile(profile)
            perfil_metrics = metrics_from_perfil(profile)
            Etapa.objects.create(
                edicion=edicion,
                numero=numero,
                nombre=f'Etapa {numero}',
                tipo=clasificar_etapa(distancia, desnivel),
                distancia=distancia,
                desnivel=desnivel,
                track_wkt=track_wkt,
                file_path=None,
                perfil=perfil,
                perfil_real=perfil_real,
                altitud_max=stage.get('elevMaxM') or perfil_metrics['altitud_max'] or 0,
                altitud_min=stage.get('elevMinM') or perfil_metrics['altitud_min'] or 0,
                desnivel_negativo=perfil_metrics['desnivel_negativo'],
                pendiente_max=perfil_metrics['pendiente_max'],
                pendiente_media=_pendiente_media_puertos(climbs),
                n_puertos=len(climbs),
                fecha=stage.get('date')[:10] if stage.get('date') else None,
                localidad_inicio=localidad_inicio,
                localidad_fin=localidad_fin,
                distancia_oficial=distancia_oficial or None,
                ganador=ganador,
                gc_leader=gc_leader,
                resultados=resultados,
            )
            contador['creadas'] += 1
        else:
            # Etapa existente: solo enriquecer campos factuales (sin tocar GPX).
            etapa.fecha = stage.get('date')[:10] if stage.get('date') else etapa.fecha
            etapa.localidad_inicio = localidad_inicio
            etapa.localidad_fin = localidad_fin
            etapa.distancia_oficial = distancia_oficial or etapa.distancia_oficial
            etapa.ganador = ganador
            etapa.gc_leader = gc_leader
            etapa.resultados = resultados
            etapa.save(update_fields=[
                'fecha', 'localidad_inicio', 'localidad_fin',
                'distancia_oficial', 'ganador', 'gc_leader', 'resultados',
            ])
            contador['actualizadas'] += 1