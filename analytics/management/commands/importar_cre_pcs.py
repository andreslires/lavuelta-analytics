import html
import os
import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.management.commands.migrar_cre import ETAPAS_CRE
from analytics.models import Equipo, Etapa, ResultadoEquipoEtapa
from analytics.services.ciclistas import invalidar_ranking_cache


def _normalizar_tiempo(valor):
    return ' '.join((valor or '').replace(',', '.').split())


def _tiempo_y_diferencia(posicion, valor):
    valor = _normalizar_tiempo(valor)
    if not valor or valor == '-':
        return None, None
    if posicion == 1:
        return valor, None
    if not valor.startswith('+'):
        valor = '+' + valor
    return None, valor


def _texto_celda(celda):
    texto = re.sub(r'<[^>]+>', '', celda)
    return ' '.join(html.unescape(texto).split())


def _parsear_tabla_equipos_html(contenido):
    for tabla in re.findall(r'<table\b[^>]*>(.*?)</table>', contenido, re.S):
        if not (
            'data-code="team"' in tabla
            and 'data-code="classification"' in tabla
            and 'data-code="timelag"' in tabla
            and 'data-code="prev_rnk"' not in tabla
        ):
            continue
        filas = []
        ultima_diferencia = '0:00'
        valida = True
        for fila in re.findall(r'<tr\b[^>]*>(.*?)</tr>', tabla, re.S):
            celdas = re.findall(r'<td\b[^>]*>(.*?)</td>', fila, re.S)
            if len(celdas) < 4:
                continue
            posicion_raw = _texto_celda(celdas[0])
            if not posicion_raw.isdigit():
                continue
            posicion = int(posicion_raw)
            if posicion != len(filas) + 1:
                valida = False
                break
            equipo = _texto_celda(celdas[1])
            valor = _texto_celda(celdas[3])
            if posicion == 1:
                # Una CRE dura menos de una hora; descarta tablas de general
                # (h:mm:ss) o de otras clasificaciones.
                if valor.count(':') != 1:
                    valida = False
                    break
                filas.append((posicion, equipo, valor, valor))
                continue
            # ",," en PCS = mismo tiempo que el equipo anterior.
            if valor not in ('', ',,', '-'):
                ultima_diferencia = valor
            filas.append((posicion, equipo, ultima_diferencia, ultima_diferencia))
        if valida and filas:
            return filas
    return None


def _parsear_tabla_equipos(lineas):
    inicio = None
    for indice, linea in enumerate(lineas):
        if (
            linea.strip() == 'TEAM'
            and indice + 2 < len(lineas)
            and lineas[indice + 1].strip() == 'TIME'
            and lineas[indice + 2].strip() == '+TIME'
        ):
            inicio = indice + 3
            break
    if inicio is None:
        return None

    filas = []
    indice = inicio
    while indice < len(lineas):
        while indice < len(lineas) and not lineas[indice].strip():
            indice += 1
        if indice >= len(lineas):
            break
        linea = lineas[indice].strip()
        if not linea.isdigit():
            break
        posicion = int(linea)
        if posicion != len(filas) + 1:
            break
        try:
            equipo = lineas[indice + 1].strip()
            tiempo = lineas[indice + 2].strip()
            diferencia = lineas[indice + 3].strip()
        except IndexError:
            break
        if not equipo:
            break
        filas.append((posicion, equipo, tiempo, diferencia))
        indice += 4
    return filas


def _parsear_resultados_individuales(lineas):
    filas = []
    vistos = set()
    for indice, linea in enumerate(lineas):
        if '](https://www.procyclingstats.com/rider/' not in linea:
            continue
        siguiente = indice + 1
        while siguiente < len(lineas) and not lineas[siguiente].strip():
            siguiente += 1
        if siguiente >= len(lineas):
            break
        linea_equipo = lineas[siguiente]
        coincide_equipo = re.search(
            r'\[([^\]]+)\]\(https://www\.procyclingstats\.com/team/', linea_equipo
        )
        if not coincide_equipo:
            continue
        equipo = coincide_equipo.group(1).strip()
        if equipo in vistos:
            continue
        vistos.add(equipo)
        sufijo = linea_equipo[coincide_equipo.end():]
        tiempos = re.findall(r'\d{1,2}:\d{2}(?:\.\d+)?', sufijo)
        tiempo = tiempos[-1] if tiempos else ''
        filas.append((len(filas) + 1, equipo, tiempo, tiempo))
    return filas


def _parsear_archivo(ruta):
    with open(ruta, 'r', encoding='utf-8') as archivo:
        contenido = archivo.read()
    if ruta.endswith('.html') or '<table' in contenido:
        filas = _parsear_tabla_equipos_html(contenido)
        if filas is not None:
            return filas
    lineas = contenido.splitlines()
    filas = _parsear_tabla_equipos(lineas)
    if filas is not None:
        return filas
    return _parsear_resultados_individuales(lineas)


class Command(BaseCommand):
    help = 'Importa resultados completos de CRE desde páginas de PCS guardadas'

    def add_arguments(self, parser):
        parser.add_argument(
            '--anio',
            type=int,
            help='Importa solo una CRE de un año concreto',
        )
        parser.add_argument(
            '--etapa',
            type=int,
            help='Número de etapa; requiere --anio',
        )
        parser.add_argument(
            '--archivo',
            help='Ruta a una página de PCS; requiere --anio y --etapa',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra lo que haría sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        anio = options['anio']
        numero = options['etapa']
        archivo = options['archivo']
        dry_run = options['dry_run']

        if numero and not anio:
            raise CommandError('--etapa requiere indicar también --anio')
        if archivo and (not anio or not numero):
            raise CommandError('--archivo requiere indicar --anio y --etapa')

        pares = [
            (year, stage)
            for year, stage in ETAPAS_CRE
            if (not anio or year == anio) and (not numero or stage == numero)
        ]
        if not pares:
            raise CommandError('No hay ninguna CRE que coincida con el filtro')

        if dry_run:
            self.stdout.write(
                self.style.WARNING('Modo dry-run: no se escribirá nada')
            )

        for year, stage in pares:
            base = os.path.join('data', 'pcs', 'cre', f'{year}-{stage}')
            ruta = archivo
            if not ruta:
                ruta = base + '.html'
                if not os.path.exists(ruta):
                    ruta = base + '.txt'
            if not os.path.exists(ruta):
                self.stdout.write(
                    self.style.WARNING(f'{ruta}: no encontrado; se omite')
                )
                continue
            try:
                etapa = Etapa.objects.select_related('edicion').get(
                    edicion__year=year, numero=stage
                )
            except Etapa.DoesNotExist:
                self.stdout.write(
                    self.style.WARNING(
                        f'CRE {year} etapa {stage}: no existe en la BD'
                    )
                )
                continue
            try:
                filas = _parsear_archivo(ruta)
            except ValueError as exc:
                raise CommandError(f'{ruta}: {exc}') from exc
            if not filas:
                raise CommandError(f'{ruta}: no se encontraron equipos')
            self.importar(etapa, filas, dry_run)

        if not dry_run:
            invalidar_ranking_cache()

    def importar(self, etapa, filas, dry_run):
        preparados = []
        equipos_nuevos = []
        for posicion, nombre_equipo, tiempo_raw, diferencia_raw in filas:
            nombre_equipo = ' '.join(nombre_equipo.split())
            equipo, creado = Equipo.objects.get_or_create(nombre=nombre_equipo)
            if creado:
                equipos_nuevos.append(equipo.nombre)
            tiempo, diferencia = _tiempo_y_diferencia(posicion, tiempo_raw)
            if posicion > 1 and not diferencia:
                _, diferencia = _tiempo_y_diferencia(posicion, diferencia_raw)
            preparados.append(
                ResultadoEquipoEtapa(
                    etapa=etapa,
                    equipo=equipo,
                    posicion=posicion,
                    tiempo=tiempo,
                    diferencia=diferencia,
                )
            )

        ganador = preparados[0].equipo.nombre if preparados else ''

        if dry_run:
            self.stdout.write(
                f'{etapa}: importaría {len(preparados)} equipos; '
                f'ganador: {ganador}'
            )
            for item in preparados[:5]:
                self.stdout.write(
                    f"  {item.posicion}. {item.equipo.nombre} "
                    f"{item.tiempo or item.diferencia or ''}"
                )
            return

        with transaction.atomic():
            etapa.es_cre = True
            etapa.ganador = ganador
            etapa.save(update_fields=['es_cre', 'ganador'])
            etapa.resultados_equipo.all().delete()
            etapa.resultados_db.all().delete()
            ResultadoEquipoEtapa.objects.bulk_create(preparados)

        self.stdout.write(
            self.style.SUCCESS(
                f'{etapa}: {len(preparados)} resultados de equipo; '
                f'ganador: {ganador}'
            )
        )
        if equipos_nuevos:
            self.stdout.write(
                'Equipos nuevos: ' + ', '.join(sorted(set(equipos_nuevos)))
            )
