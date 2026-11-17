import csv
import os
import re
import unicodedata
from collections import defaultdict

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.models import Ciclista, ClasificacionGeneral, Edicion, Equipo
from analytics.services.ciclistas import invalidar_ranking_cache


PARTICULAS = {
    'af', 'av', 'da', 'das', 'de', 'del', 'den', 'der', 'des', 'di', 'do',
    'dos', 'du', 'e', 'el', 'i', 'la', 'las', 'le', 'los', 'ter', 'ten',
    'van', 'von', 'y', 'zu',
}

NOMBRES_COMPUESTOS = {
    'ALBERTO', 'ALEJANDRO', 'ALVARO', 'ANDRES', 'ANGEL', 'ANTONIO',
    'CARLOS', 'DANIEL', 'DAVID', 'DIEGO', 'EDUARDO', 'ENRIQUE', 'ESTEBAN',
    'FELIX', 'FERNANDO', 'FRANCISCO', 'IGNACIO', 'IVAN', 'JAVIER', 'JEAN',
    'JESUS', 'JHOAN', 'JHON', 'JOAQUIN', 'JOSE', 'JUAN', 'LUIS', 'MANUEL',
    'MARIA', 'MATEO', 'MIGUEL', 'NICOLAS', 'OSCAR', 'PABLO', 'PEDRO',
    'PIERRE', 'RAMIRO', 'RAUL', 'RICARDO', 'ROBERTO', 'RUBEN', 'SEBASTIAN',
    'SERGIO', 'VICENTE',
}

NOMBRES_EXTRA = {
    'ADAM', 'ADOLFO', 'ALEX', 'ALEXANDRE', 'ALEXANDRO', 'ANDREA', 'ANTHONY',
    'BEKIM', 'BEN', 'BENJAMIN', 'BRAM', 'BRANDON', 'CARL', 'CASPER', 'CESAR',
    'CHRIS', 'CHRISTOPHE', 'DAN', 'DANAIL', 'DANILO', 'DARIO', 'DUNCAN',
    'DYLAN', 'ERIC', 'FABIO', 'FELIPE', 'FLORIAN', 'FREDERIC', 'GABRIEL', 'GIAN',
    'GUILLAUME', 'GUSTAV', 'GUSTAVO', 'HEBERTH', 'HERNAN', 'HUGO', 'JAIME',
    'JAY', 'JEFFERSON', 'JESSE', 'JOAO', 'JONAS', 'JONATHAN', 'JORGE',
    'JULIO', 'JULIEN', 'LASSE', 'LARS', 'LEIF', 'LEO', 'LEON', 'LEONARDO',
    'LUCAS', 'LUCA', 'MAARTEN', 'MADS', 'MAGNUS', 'MARCOS', 'MARIO', 'MARTIN',
    'MATHIEU', 'MATTEO', 'MAX', 'MICKAEL', 'MURILO', 'NELSON', 'NICO', 'ODD',
    'OLIVIER', 'PABLO', 'PEDRO', 'PREBEN', 'RAFAEL', 'RAMIRO', 'REMI',
    'RODOLFO', 'ROMAN', 'RUBEN', 'RUI', 'SAM', 'SEBASTIEN', 'SERGIO', 'SIMON',
    'SVEN', 'TIM', 'TOBIAS', 'TOM', 'TOMAS', 'VALENTIN', 'VEGARD', 'VICENTE',
    'VICTOR', 'WALTER', 'WILLIAM', 'WIM', 'XABIER', 'XAVIER', 'YVES',
}

GENERAL_DESCALIFICADA = {
    2011: {'cobo juan jose'},
    2022: {'lopez miguel angel'},
}

TIEMPOS_CORREGIDOS = {
    (2011, 'froome chris'): '84:59:44',
}


def normalizar(texto):
    texto = unicodedata.normalize('NFKD', texto)
    texto = texto.encode('ascii', 'ignore').decode('ascii').lower()
    texto = re.sub(r'[^a-z0-9 ]', ' ', texto)
    return ' '.join(texto.split())


def clave(texto):
    return tuple(sorted(normalizar(texto).split()))


def titular(token):
    if token.startswith("MC") and len(token) > 2:
        return 'Mc' + token[2:].title()
    return token.title()


def construir_diccionario(ciclistas, nombres_csv):
    nombres = set()
    apellidos = set()
    for ciclista in ciclistas:
        tokens = normalizar(ciclista.nombre).split()
        if tokens:
            nombres.add(tokens[0].upper())
            apellidos.add(tokens[-1].upper())
    for nombre in nombres_csv:
        tokens = nombre.split()
        if tokens:
            apellidos.add(normalizar(tokens[0]).upper())
        if len(tokens) == 2:
            nombres.add(normalizar(tokens[1]).upper())
    return nombres | NOMBRES_COMPUESTOS | NOMBRES_EXTRA, apellidos


def nombre_natural(nombre_csv, nombres, apellidos):
    tokens = nombre_csv.split()
    if not tokens:
        return nombre_csv

    inicio_nombre = len(tokens) - 1
    tras_particula = normalizar(tokens[0]) in PARTICULAS
    for indice in range(1, len(tokens)):
        token = normalizar(tokens[indice])
        token_upper = token.upper()
        if token in PARTICULAS:
            tras_particula = True
            continue
        if tras_particula:
            tras_particula = False
            continue
        if token_upper in nombres:
            inicio_nombre = indice
            break
        if token_upper in apellidos:
            continue
        if (
            indice + 1 < len(tokens)
            and normalizar(tokens[indice + 1]).upper() in nombres
        ):
            continue
        inicio_nombre = indice
        break

    apellidos_csv = tokens[:inicio_nombre]
    nombres_csv = tokens[inicio_nombre:]

    apellidos_txt = []
    for token in apellidos_csv:
        minuscula = normalizar(token)
        apellidos_txt.append(minuscula if minuscula in PARTICULAS else titular(token))

    nombres_txt = [titular(token) for token in nombres_csv]
    return ' '.join(nombres_txt + apellidos_txt)


class ResolverNombres:
    def __init__(self, modelo, crear=False, normalizador=None):
        self.modelo = modelo
        self.crear = crear
        self.normalizador = normalizador or (lambda nombre: nombre)
        self.exactos = {obj.nombre: obj for obj in modelo.objects.all()}
        self.por_clave = defaultdict(list)
        self.por_token = defaultdict(list)
        for obj in self.exactos.values():
            self.por_clave[clave(obj.nombre)].append(obj)
            for token in set(normalizar(obj.nombre).split()):
                self.por_token[token].append(obj)
        self.nuevos = {}
        self.ambiguos = []

    def _indexar(self, obj):
        self.exactos[obj.nombre] = obj
        self.por_clave[clave(obj.nombre)].append(obj)
        for token in set(normalizar(obj.nombre).split()):
            self.por_token[token].append(obj)

    def _natural(self, nombre):
        if self.modelo is Ciclista:
            return self.normalizador(nombre)
        return nombre

    def _elegir(self, candidatos):
        return sorted(candidatos, key=lambda obj: obj.pk)[0]

    def resolver(self, nombre):
        nombre = ' '.join(nombre.split())
        if nombre in self.exactos:
            return self.exactos[nombre], False

        candidatos = self.por_clave.get(clave(nombre), [])
        if candidatos:
            return self._elegir(candidatos), False

        natural = self._natural(nombre)
        if natural in self.exactos:
            return self.exactos[natural], False

        candidatos = self.por_clave.get(clave(natural), [])
        if candidatos:
            return self._elegir(candidatos), False

        if self.modelo is Ciclista:
            tokens = normalizar(nombre).split()
            if tokens:
                clave_natural = set(normalizar(natural).split())
                candidatos = []
                for obj in self.por_token.get(tokens[0], []):
                    clave_obj = set(normalizar(obj.nombre).split())
                    if clave_natural <= clave_obj or clave_obj <= clave_natural:
                        candidatos.append(obj)
                if len(candidatos) == 1:
                    return candidatos[0], False
                if len(candidatos) > 1:
                    candidatos.sort(
                        key=lambda obj: (
                            -len(set(normalizar(obj.nombre).split()) & clave_natural),
                            len(normalizar(obj.nombre).split()),
                            obj.pk,
                        )
                    )
                    self.ambiguos.append(
                        (nombre, natural, [obj.nombre for obj in candidatos])
                    )
                    return candidatos[0], False

        if not self.crear:
            self.nuevos.setdefault(natural, None)
            return None, True

        obj = self.modelo.objects.create(nombre=natural)
        self._indexar(obj)
        self.nuevos[natural] = obj
        return obj, True


class Command(BaseCommand):
    help = 'Importa la clasificación general final desde data/gc.csv'

    def add_arguments(self, parser):
        parser.add_argument(
            '--archivo',
            default='data/gc.csv',
            help='Ruta al CSV de clasificación general (por defecto data/gc.csv)',
        )
        parser.add_argument(
            '--anio',
            type=int,
            help='Importa solo un año concreto (para pruebas)',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra lo que haría sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        archivo = options['archivo']
        anio = options['anio']
        dry_run = options['dry_run']

        if not os.path.exists(archivo):
            raise CommandError(f'Archivo {archivo} no encontrado')

        ediciones_db = {ed.year: ed for ed in Edicion.objects.all()}
        ediciones = ediciones_db
        if anio:
            if anio not in ediciones_db:
                raise CommandError(f'La edición {anio} no existe en la base de datos')
            ediciones = {anio: ediciones_db[anio]}

        filas_por_anio = defaultdict(list)
        nombres_csv = []
        años_saltados = set()
        total = 0
        with open(archivo, 'r', encoding='utf-8-sig', newline='') as f:
            for fila in csv.DictReader(f):
                try:
                    year = int(fila['year'])
                    rnk = int(fila['Rnk'])
                except (KeyError, TypeError, ValueError):
                    continue
                total += 1
                if year not in ediciones_db:
                    años_saltados.add(year)
                    continue
                if year not in ediciones:
                    continue
                filas_por_anio[year].append((rnk, fila))
                rider = ' '.join(fila.get('Rider', '').split())
                if rider:
                    nombres_csv.append(rider)

        nombres, apellidos = construir_diccionario(Ciclista.objects.all(), nombres_csv)
        normalizador = lambda nombre: nombre_natural(nombre, nombres, apellidos)

        if dry_run:
            self.stdout.write(self.style.WARNING('Modo dry-run: no se escribirá nada'))

        resumen = []
        for year in sorted(filas_por_anio):
            resumen.append(
                self.importar_anio(
                    year,
                    ediciones[year],
                    filas_por_anio[year],
                    dry_run,
                    normalizador,
                )
            )

        self.stdout.write('')
        self.stdout.write(f'Filas leídas: {total}')
        if años_saltados:
            self.stdout.write(
                'Años ignorados por no existir en la BD: '
                + ', '.join(str(a) for a in sorted(años_saltados))
            )
        for item in resumen:
            self.stdout.write(
                f"{item['year']}: {item['importadas']} clasificados "
                f"({item['descalificados']} descalificados, {item['duplicados']} duplicados)"
            )
        total_importado = sum(item['importadas'] for item in resumen)
        self.stdout.write(self.style.SUCCESS(f'Total clasificados a importar: {total_importado}'))
        if not dry_run:
            invalidar_ranking_cache()

    def importar_anio(self, year, edicion, filas, dry_run, normalizador):
        descalificados = GENERAL_DESCALIFICADA.get(year, set())
        vistos = set()
        limpias = []
        n_descalificados = 0
        n_duplicados = 0

        for rnk, fila in sorted(filas, key=lambda item: item[0]):
            rider = ' '.join(fila.get('Rider', '').split())
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
            limpias.append((rnk, rider, fila))

        ciclistas = ResolverNombres(
            Ciclista, crear=not dry_run, normalizador=normalizador
        )
        equipos = ResolverNombres(Equipo, crear=not dry_run)
        nuevos_ciclistas = {}
        nuevos_equipos = {}
        preparadas = []

        for posicion, (_, rider, fila) in enumerate(limpias, start=1):
            ciclista, nuevo_c = ciclistas.resolver(rider)
            if nuevo_c:
                nuevos_ciclistas[ciclista.nombre if ciclista else normalizador(rider)] = True
            equipo_nombre = ' '.join(fila.get('Team', '').split())
            equipo = None
            if equipo_nombre:
                equipo, nuevo_e = equipos.resolver(equipo_nombre)
                if nuevo_e:
                    nuevos_equipos[equipo.nombre if equipo else equipo_nombre] = True

            tiempo_raw = (fila.get('Time') or '').strip()
            if tiempo_raw in ('', '-'):
                tiempo_raw = None

            clave_rider = normalizar(rider)
            if posicion == 1:
                tiempo = TIEMPOS_CORREGIDOS.get((year, clave_rider), tiempo_raw)
                diferencia = None
            else:
                tiempo = None
                diferencia = tiempo_raw

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
        for nombre_csv, natural, candidatos in ciclistas.ambiguos:
            self.stdout.write(
                self.style.WARNING(
                    f'{year}: nombre ambiguo {nombre_csv!r} -> {natural!r}; '
                    'candidatos: ' + ', '.join(candidatos)
                )
            )

        return {
            'year': year,
            'importadas': len(preparadas),
            'descalificados': n_descalificados,
            'duplicados': n_duplicados,
        }
