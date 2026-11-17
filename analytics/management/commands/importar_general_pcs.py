import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.management.commands.importar_general_csv import (
    GENERAL_DESCALIFICADA,
    TIEMPOS_CORREGIDOS,
    ResolverNombres,
    construir_diccionario,
    nombre_natural,
    normalizar,
)
from analytics.models import Ciclista, ClasificacionGeneral, Edicion, Equipo
from analytics.services.ciclistas import invalidar_ranking_cache


ANIOS_PCS = (2023, 2024, 2025, 2026)

ALIASES_PCS = {
    'dunbar eddie': 'Edward Dunbar',
    'sweeny harry': 'Harrison Sweeny',
    'koerdt bjorn': 'Bjoern Koerdt',
}


def _parsear_texto(lineas):
    filas = []
    inicio = None
    for indice, linea in enumerate(lineas):
        if linea.startswith('Rnk\tPrev.'):
            inicio = indice + 1
            break
    if inicio is None:
        raise ValueError('No se encontró la tabla de clasificación general')

    indice = inicio
    while indice < len(lineas):
        linea = lineas[indice]
        if not linea.strip():
            indice += 1
            continue
        partes = linea.split('\t')
        if not partes[0].strip().isdigit():
            break
        posicion = int(partes[0].strip())
        rider = partes[-1].strip()
        siguiente = indice + 1
        while siguiente < len(lineas) and not lineas[siguiente].strip():
            siguiente += 1
        if siguiente >= len(lineas):
            break
        partes_equipo = lineas[siguiente].split('\t')
        equipo = next((p.strip() for p in partes_equipo if p.strip()), '')
        tiempo = next((p.strip() for p in reversed(partes_equipo) if p.strip()), '')
        if rider:
            filas.append((posicion, rider, equipo, tiempo))
        indice = siguiente + 1
    return filas


def _parsear_markdown(lineas):
    filas = []
    inicio = None
    for indice, linea in enumerate(lineas):
        if linea.strip() == '#### General classification':
            inicio = indice + 1
            break
    if inicio is None:
        raise ValueError('No se encontró la tabla de clasificación general')

    for linea in lineas[inicio:]:
        if linea.startswith('####'):
            break
        if not linea.startswith('|'):
            continue
        coincide_posicion = re.match(r'\|\s*(\d+)\s*\|', linea)
        if not coincide_posicion:
            continue
        coincide_rider = re.search(
            r'\[([^\]]+)\]\(https://www\.procyclingstats\.com/rider/', linea
        )
        if not coincide_rider:
            continue
        coincide_equipo = re.search(
            r'\[([^\]]+)\]\(https://www\.procyclingstats\.com/team/', linea
        )
        coincide_tiempo = re.search(r'\|\s*([^|]+?)\s*\|\s*\[\.\.\]', linea)
        filas.append(
            (
                int(coincide_posicion.group(1)),
                coincide_rider.group(1).strip(),
                coincide_equipo.group(1).strip() if coincide_equipo else '',
                coincide_tiempo.group(1).strip() if coincide_tiempo else '',
            )
        )
    return filas


def _parsear_archivo(archivo):
    with open(archivo, 'r', encoding='utf-8') as f:
        lineas = f.read().splitlines()
    if any(linea.strip() == '#### General classification' for linea in lineas):
        return _parsear_markdown(lineas)
    return _parsear_texto(lineas)


def _tiempo_y_diferencia(posicion, valor):
    valor = (valor or '').strip()
    if not valor or valor == '-':
        return None, None
    if posicion == 1:
        return valor, None
    if not valor.startswith('+'):
        valor = '+' + valor
    return None, valor


class Command(BaseCommand):
    help = 'Importa la general final desde las páginas de PCS guardadas en data/pcs'

    def add_arguments(self, parser):
        parser.add_argument(
            '--anio',
            type=int,
            choices=ANIOS_PCS,
            help='Importa solo un año concreto (por defecto, 2023–2026)',
        )
        parser.add_argument(
            '--archivo',
            help='Ruta a una página de PCS ya guardada; requiere --anio',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra lo que haría sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        anio = options['anio']
        archivo = options['archivo']
        dry_run = options['dry_run']

        if archivo and not anio:
            raise CommandError('--archivo requiere indicar también --anio')

        anios = [anio] if anio else list(ANIOS_PCS)
        ediciones_db = {edicion.year: edicion for edicion in Edicion.objects.all()}
        faltantes = [year for year in anios if year not in ediciones_db]
        if faltantes:
            raise CommandError(
                'No existen en la BD las ediciones: '
                + ', '.join(str(year) for year in faltantes)
            )

        filas_por_anio = {}
        nombres_pcs = []
        for year in anios:
            ruta = archivo or os.path.join('data', 'pcs', f'{year}-gc.txt')
            if not os.path.exists(ruta):
                raise CommandError(f'Archivo {ruta} no encontrado')
            try:
                filas = _parsear_archivo(ruta)
            except ValueError as exc:
                raise CommandError(f'{ruta}: {exc}') from exc
            if not filas:
                raise CommandError(f'{ruta}: no se encontraron clasificados')
            filas_por_anio[year] = filas
            nombres_pcs.extend(rider for _, rider, _, _ in filas)

        nombres, apellidos = construir_diccionario(
            Ciclista.objects.all(), nombres_pcs
        )
        normalizador = lambda nombre: nombre_natural(nombre, nombres, apellidos)

        if dry_run:
            self.stdout.write(
                self.style.WARNING('Modo dry-run: no se escribirá nada')
            )

        resumen = []
        for year in sorted(filas_por_anio):
            resumen.append(
                self.importar_anio(
                    year,
                    ediciones_db[year],
                    filas_por_anio[year],
                    dry_run,
                    normalizador,
                )
            )

        self.stdout.write('')
        for item in resumen:
            self.stdout.write(
                f"{item['year']}: {item['importadas']} clasificados "
                f"({item['descalificados']} descalificados, "
                f"{item['duplicados']} duplicados)"
            )
        total = sum(item['importadas'] for item in resumen)
        self.stdout.write(
            self.style.SUCCESS(f'Total clasificados a importar: {total}')
        )
        if not dry_run:
            invalidar_ranking_cache()

    def importar_anio(self, year, edicion, filas, dry_run, normalizador):
        descalificados = GENERAL_DESCALIFICADA.get(year, set())
        vistos = set()
        limpias = []
        n_descalificados = 0
        n_duplicados = 0

        for posicion, rider, equipo, tiempo in sorted(
            filas, key=lambda item: item[0]
        ):
            rider = ' '.join(rider.split())
            if not rider:
                continue
            clave_rider = normalizar(rider)
            if clave_rider in descalificados:
                n_descalificados += 1
                continue
            if clave_rider in vistos:
                n_duplicados += 1
                continue
            vistos.add(clave_rider)
            limpias.append((posicion, rider, equipo, tiempo))

        ciclistas = ResolverNombres(
            Ciclista, crear=not dry_run, normalizador=normalizador
        )
        equipos = ResolverNombres(Equipo, crear=not dry_run)
        nuevos_ciclistas = {}
        nuevos_equipos = {}
        preparadas = []

        for posicion, (_, rider, equipo_nombre, tiempo_raw) in enumerate(
            limpias, start=1
        ):
            rider_resolver = ALIASES_PCS.get(normalizar(rider), rider)
            ciclista, nuevo_c = ciclistas.resolver(rider_resolver)
            if nuevo_c:
                nuevos_ciclistas[
                    ciclista.nombre
                    if ciclista
                    else normalizador(rider_resolver)
                ] = True

            equipo_nombre = ' '.join(equipo_nombre.split())
            equipo = None
            if equipo_nombre:
                equipo, nuevo_e = equipos.resolver(equipo_nombre)
                if nuevo_e:
                    nuevos_equipos[
                        equipo.nombre if equipo else equipo_nombre
                    ] = True

            tiempo, diferencia = _tiempo_y_diferencia(posicion, tiempo_raw)
            if posicion == 1:
                tiempo = TIEMPOS_CORREGIDOS.get(
                    (year, normalizar(rider)), tiempo
                )

            preparadas.append(
                {
                    'edicion': edicion,
                    'ciclista': ciclista,
                    'equipo': equipo,
                    'posicion': posicion,
                    'tiempo': tiempo,
                    'diferencia': diferencia,
                }
            )

        if not dry_run:
            with transaction.atomic():
                ClasificacionGeneral.objects.filter(edicion=edicion).delete()
                ClasificacionGeneral.objects.bulk_create(
                    [ClasificacionGeneral(**datos) for datos in preparadas]
                )

        if nuevos_ciclistas:
            self.stdout.write(
                f'{year}: {len(nuevos_ciclistas)} ciclistas nuevos: '
                + ', '.join(sorted(nuevos_ciclistas)[:15])
            )
        if nuevos_equipos:
            self.stdout.write(
                f'{year}: {len(nuevos_equipos)} equipos nuevos: '
                + ', '.join(sorted(nuevos_equipos)[:15])
            )
        for nombre_pcs, natural, candidatos in ciclistas.ambiguos:
            self.stdout.write(
                self.style.WARNING(
                    f'{year}: nombre ambiguo {nombre_pcs!r} -> {natural!r}; '
                    'candidatos: ' + ', '.join(candidatos)
                )
            )

        return {
            'year': year,
            'importadas': len(preparadas),
            'descalificados': n_descalificados,
            'duplicados': n_duplicados,
        }
