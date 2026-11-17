# Exporta el sitio completo a HTML estático
#
# Hace lo mismo que haría un navegador: pide cada página a la propia app con el
# cliente de pruebas de Django y guarda la respuesta como <ruta>/index.html.
# Se ejecuta en TU máquina, donde están db.sqlite3, data/ y los geojson.
#
# Uso (desde la raíz del proyecto):
#   python manage.py export_static
#   python manage.py export_static --out site_static --host lavuelta.pages.dev
#   python manage.py export_static --years 2024,2025     # prueba rápida
#   python manage.py export_static --host usuario.github.io --base-path /mi-repo
#                                                        # GitHub Pages en subcarpeta
#
# Qué se exporta: dashboard, mapa general (pestañas Etapas y Provincias),
# ayuda, el directorio-ranking de ciclistas, una ficha por ciclista, una página
# por edición y una por etapa, más los estáticos y un 404.
# Exportación parcial: --solo y --excluir aceptan grupos (general, mapa,
# ediciones, etapas, ciclistas, comparar, estaticos) o prefijos de ruta
# (p. ej. comparar/zonas), separados por comas. --dry-run enseña qué se
# regeneraría sin escribir nada y --verificar revisa los enlaces internos del
# resultado (siempre se hace al final de una exportación completa).
#   python manage.py export_static --solo comparar,ciclistas
#   python manage.py export_static --excluir mapa,estaticos
#
# El comparador se exporta precalculado: la pantalla intermedia (comparar/),
# la pestaña de ediciones (comparar/ediciones/) con una página por pareja
# (comparar/AAAA-BBBB/, siempre de menor a mayor año) y las pestañas de
# etapas similares y recorrido común (comparar/similares/, comparar/zonas/),
# que resuelven la elección en el navegador con datos incrustados.
# Qué NO se exporta: el filtro de ediciones del dashboard, la comparación de
# dos etapas, los mapas por pareja de "recorrido común" (necesitan servidor)
# y /admin/. Las plantillas los ocultan cuando settings.STATIC_EXPORT es True.
import re
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.test import Client
from django.test.utils import override_settings

from analytics.models import Ciclista, Edicion, Etapa

# Enlaces que empiezan por "/" (href="/etapa/..", src="/static/..", action=...),
# también dentro de los mapas de folium, donde las comillas llegan escapadas
# (&quot;) porque el mapa va incrustado en un iframe srcdoc. Se excluyen los
# enlaces "//dominio" (protocolo relativo).
_RE_ENLACE_RAIZ = re.compile(r'(\b(?:href|src|action)=(?:"|\'|&quot;|&#x27;))/(?!/)')


def prefijar_enlaces(contenido, base, host):
    """Añade `base` (p. ej. /mi-repo) a todos los enlaces que empiezan por "/".

    Necesario cuando la web se publica en una subcarpeta (GitHub Pages de un
    repo normal: usuario.github.io/mi-repo/). Si `base` está vacío no hace nada.
    """
    if not base:
        return contenido
    texto = contenido.decode('utf-8')
    texto = _RE_ENLACE_RAIZ.sub(lambda m: m.group(1) + base + '/', texto)
    # og:url apunta a la raíz del dominio; hay que añadirle la subcarpeta.
    texto = texto.replace(f'content="https://{host}/', f'content="https://{host}{base}/')
    return texto.encode('utf-8')


# Grupos de páginas, por prefijo de la ruta de destino. "estaticos" no son
# páginas sino la copia de CSS/JS/favicon, y se trata aparte.
GRUPOS = {
    'general': ('index.html', 'ayuda/', '404.html'),
    'mapa': ('mapa-general/',),
    'ediciones': ('edicion/',),
    'etapas': ('etapa/',),
    'ciclistas': ('ciclista/', 'ciclistas/'),
    'comparar': ('comparar/',),
}
ESTATICOS = 'estaticos'

_RE_ENLACE_INTERNO = re.compile(r'\b(?:href|src)="(/[^"#?\s]*)')


def parsear_lista(texto):
    """'a, b/' -> ['a', 'b']: elementos de --solo / --excluir."""
    return [x.strip().strip('/') for x in (texto or '').split(',') if x.strip().strip('/')]


def prefijos_de(elemento):
    """Prefijos de ruta de un grupo o de una ruta libre (p. ej. comparar/zonas)."""
    if elemento == ESTATICOS:
        return ()
    return GRUPOS.get(elemento, (elemento,))


def coincide(destino, elementos):
    return any(destino.startswith(p) for e in elementos for p in prefijos_de(e))


def seleccionado(destino, solo, excluir):
    """¿Entra este fichero de destino en la exportación pedida?"""
    if solo and not coincide(destino, solo):
        return False
    return not (excluir and coincide(destino, excluir))


def grupo_de(destino):
    for nombre, prefijos in GRUPOS.items():
        if any(destino.startswith(p) for p in prefijos):
            return nombre
    return 'otros'


def verificar_enlaces(out, base):
    """Revisa los href/src internos de las páginas exportadas.

    Devuelve (nº de enlaces, [(enlace, página de origen, motivo), ...]).
    Con `base` (subcarpeta de publicación) todo enlace interno debe llevarlo.
    """
    out = Path(out)
    existe_cache = {}

    def existe(rel):
        if rel not in existe_cache:
            destino = out / rel
            existe_cache[rel] = (
                destino.is_file() or (destino / 'index.html').is_file()
            )
        return existe_cache[rel]

    paginas = [
        p for p in out.rglob('index.html')
        if p.relative_to(out).parts[0] not in ('static', '.git')
    ]
    if (out / '404.html').is_file():
        paginas.append(out / '404.html')

    total = 0
    problemas = []
    vistos = set()
    for pagina in paginas:
        contenido = pagina.read_text(encoding='utf-8', errors='replace')
        origen = str(pagina.relative_to(out))
        for enlace in _RE_ENLACE_INTERNO.findall(contenido):
            if enlace.startswith('//'):
                continue
            total += 1
            if base:
                if enlace != base and not enlace.startswith(base + '/'):
                    motivo, rel = 'sin el prefijo ' + base, None
                else:
                    motivo, rel = 'no existe', enlace[len(base):].lstrip('/')
            else:
                motivo, rel = 'no existe', enlace.lstrip('/')
            if rel is not None and existe(rel):
                continue
            if enlace not in vistos:
                vistos.add(enlace)
                problemas.append((enlace, origen, motivo))
    return total, problemas


class Command(BaseCommand):
    help = 'Exporta el sitio a HTML estático (sin servidor) en la carpeta --out.'

    def add_arguments(self, parser):
        parser.add_argument('--out', default='site_static',
                            help='Carpeta de salida (por defecto: site_static).')
        parser.add_argument('--host', default='localhost',
                            help='Dominio final del sitio; se usa en og:url (p. ej. lavuelta.pages.dev).')
        parser.add_argument('--base-path', default='',
                            help='Subcarpeta donde se publicará la web, si no va en la raíz '
                                 '(p. ej. /lavuelta-analytics-web para GitHub Pages de un repo normal).')
        parser.add_argument('--years', default='',
                            help='Solo estas ediciones, separadas por comas (p. ej. 2024,2025).')
        parser.add_argument('--clean', action='store_true',
                            help='Borra la carpeta de salida antes de exportar.')
        parser.add_argument('--solo', default='',
                            help='Solo estos grupos o prefijos, separados por comas. Grupos: '
                                 + ', '.join(list(GRUPOS) + [ESTATICOS])
                                 + '. Prefijos libres: p. ej. comparar/zonas. '
                                 'Sin --solo se exporta todo.')
        parser.add_argument('--excluir', default='',
                            help='Grupos o prefijos que NO se exportan (misma sintaxis que --solo).')
        parser.add_argument('--dry-run', action='store_true',
                            help='Enseña qué se regeneraría sin escribir nada.')
        parser.add_argument('--verificar', action='store_true',
                            help='Revisa los enlaces internos al terminar '
                                 '(siempre se hace en una exportación completa).')
        parser.add_argument('--skip-static', action='store_true',
                            help='No copia los ficheros estáticos (CSS, JS, favicon).')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        out = Path(opts['out']).resolve()
        years = [int(y) for y in opts['years'].split(',') if y.strip()]
        solo = parsear_lista(opts['solo'])
        excluir = parsear_lista(opts['excluir'])
        parcial = bool(solo or excluir or years)
        if opts['clean'] and (solo or excluir):
            raise CommandError(
                '--clean borra toda la carpeta de salida; no es compatible con '
                '--solo ni --excluir (se perdería lo que no se regenera).'
            )

        todas = self._paginas(years)
        destinos_posibles = [d for _, ds in todas for d in ds] + ['404.html']
        for elemento in solo + excluir:
            if elemento != ESTATICOS and not any(
                    coincide(d, [elemento]) for d in destinos_posibles):
                raise CommandError(f'{elemento!r}: ninguna página coincide')

        paginas = []
        for url, destinos in todas:
            destinos = [d for d in destinos if seleccionado(d, solo, excluir)]
            if destinos:
                paginas.append((url, destinos))
        quiere_404 = seleccionado('404.html', solo, excluir)
        copiar_estaticos = (
            not opts['skip_static']
            and ESTATICOS not in excluir
            and (not solo or ESTATICOS in solo)
        )
        if not paginas and not quiere_404 and not copiar_estaticos:
            raise CommandError('La selección no deja nada que exportar.')

        self._plan(paginas, quiere_404, copiar_estaticos, parcial)
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('Dry-run: no se ha escrito nada.'))
            return

        if opts['clean'] and out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        base = opts['base_path'].strip().strip('/')
        base = f'/{base}' if base else ''
        host = opts['host']

        t0 = time.time()
        fallos = []
        escritos = 0

        with override_settings(
            STATIC_EXPORT=True,
            DEBUG=False,
            ALLOWED_HOSTS=['*'],
        ):
            client = Client(HTTP_HOST=opts['host'])

            total = len(paginas)
            for i, (url, destinos) in enumerate(paginas, 1):
                try:
                    resp = client.get(url, secure=True)
                except Exception as exc:  # noqa: BLE001 - queremos seguir con el resto
                    fallos.append((url, repr(exc)))
                    continue
                if resp.status_code != 200:
                    fallos.append((url, f'HTTP {resp.status_code}'))
                    continue
                contenido = prefijar_enlaces(resp.content, base, host)
                for rel in destinos:
                    self._escribir(out / rel, contenido)
                    escritos += 1
                if i % 25 == 0 or i == total:
                    self.stdout.write(f'  {i}/{total} páginas  ({time.time() - t0:.0f}s)')

            # Página 404 (Cloudflare Pages y Netlify la sirven automáticamente).
            if quiere_404:
                resp = client.get('/__no_existe__/', secure=True)
                if resp.status_code == 404:
                    self._escribir(out / '404.html', prefijar_enlaces(resp.content, base, host))

        if copiar_estaticos:
            self._copiar_estaticos(out)

        # Ayuda para GitHub Pages (evita que procese el sitio con Jekyll).
        (out / '.nojekyll').write_text('')

        self._resumen(out, escritos, fallos, time.time() - t0)

        # Una exportación completa se verifica siempre; una parcial, solo si se pide.
        problemas = []
        if opts['verificar'] or not parcial:
            total, problemas = verificar_enlaces(out, base)
            if problemas:
                self.stdout.write(self.style.ERROR(
                    f'\nEnlaces con problemas: {len(problemas)} (de {total} revisados)'))
                for enlace, origen, motivo in problemas[:20]:
                    self.stdout.write(self.style.ERROR(f'  {enlace}  ({motivo})  en {origen}'))
            else:
                self.stdout.write(self.style.SUCCESS(
                    f'\nEnlaces internos: {total} revisados, ninguno roto.'))

        if fallos:
            raise CommandError(f'{len(fallos)} página(s) fallaron; el resto se exportó igualmente.')
        if problemas:
            raise CommandError(f'{len(problemas)} enlace(s) interno(s) con problemas.')

    # ------------------------------------------------------------------
    def _paginas(self, years):
        """Lista de (url a pedir, [ficheros donde guardar la respuesta])."""
        paginas = [
            ('/', ['index.html']),
            ('/ayuda/', ['ayuda/index.html']),
            ('/ciclistas/', ['ciclistas/index.html']),
            # El mapa se genera una sola vez y se guarda en dos sitios:
            # /mapa-general/ y /mapa-general/etapas/.
            ('/mapa-general/', ['mapa-general/index.html']),
            ('/mapa-general/etapas/', ['mapa-general/etapas/index.html']),
            ('/mapa-general/provincias/', ['mapa-general/provincias/index.html']),
            ('/comparar/', ['comparar/index.html']),  # pantalla intermedia, como el mapa
            ('/comparar/?tab=ediciones', ['comparar/ediciones/index.html']),
            ('/comparar/?tab=perfiles', ['comparar/similares/index.html']),
            ('/comparar/?tab=zonas', ['comparar/zonas/index.html']),
        ]

        ediciones = Edicion.objects.order_by('year')
        etapas = Etapa.objects.select_related('edicion').order_by('edicion__year', 'numero')
        # Mismo criterio que el listado /ciclistas/: resultados de etapa o general.
        ciclistas = (
            Ciclista.objects.filter(
                Q(resultadoetapa__isnull=False)
                | Q(clasificaciones_generales__isnull=False)
            )
            .distinct()
            .order_by('pk')
        )
        if years:
            ediciones = ediciones.filter(year__in=years)
            etapas = etapas.filter(edicion__year__in=years)
            ciclistas = ciclistas.filter(
                Q(resultadoetapa__etapa__edicion__year__in=years)
                | Q(clasificaciones_generales__edicion__year__in=years)
            ).distinct()

        for ed in ediciones:
            paginas.append((f'/edicion/{ed.year}/', [f'edicion/{ed.year}/index.html']))
        for et in etapas:
            y, n = et.edicion.year, et.numero
            paginas.append((f'/etapa/{y}/{n}/', [f'etapa/{y}/{n}/index.html']))
        for c in ciclistas:
            paginas.append((f'/ciclista/{c.pk}/', [f'ciclista/{c.pk}/index.html']))

        # Comparador de ediciones: una página por pareja (a < b).
        anios = [e.year for e in ediciones]
        for i, a in enumerate(anios):
            for b in anios[i + 1:]:
                paginas.append((f'/comparar/?a={a}&b={b}', [f'comparar/{a}-{b}/index.html']))
        return paginas

    def _plan(self, paginas, quiere_404, copiar_estaticos, parcial):
        """Resumen de lo que se va a regenerar, por grupos."""
        cuentas = {}
        for _, destinos in paginas:
            for d in destinos:
                cuentas[grupo_de(d)] = cuentas.get(grupo_de(d), 0) + 1
        if quiere_404:
            cuentas['general'] = cuentas.get('general', 0) + 1
        total = sum(cuentas.values())
        detalle = ', '.join(f'{g} {n}' for g, n in cuentas.items()) or 'ninguna'
        self.stdout.write(
            f'Se regenerarán {total} páginas ({detalle}); '
            f'estáticos (CSS/JS): {"sí" if copiar_estaticos else "no"}.'
        )
        if parcial:
            self.stdout.write(self.style.WARNING(
                'Exportación parcial: el resto de páginas no se toca. Si has cambiado '
                'el menú, el pie, el CSS o datos compartidos, haz una exportación completa.'
            ))

    @staticmethod
    def _escribir(destino, contenido):
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(contenido)

    def _copiar_estaticos(self, out):
        """collectstatic -> carpeta static/ de la salida (sin los estáticos del admin)."""
        call_command('collectstatic', interactive=False, verbosity=0)
        origen = Path(settings.STATIC_ROOT)
        destino = out / 'static'
        shutil.copytree(origen, destino, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('admin'))

    def _resumen(self, out, escritos, fallos, segundos):
        ficheros = [
            p for p in out.rglob('*')
            if p.is_file() and '.git' not in p.relative_to(out).parts
        ]
        total_mb = sum(p.stat().st_size for p in ficheros) / 1e6
        grandes = sorted(ficheros, key=lambda p: p.stat().st_size, reverse=True)[:5]

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(
            f'Exportado en {out}  ({escritos} páginas HTML, {len(ficheros)} ficheros, '
            f'{total_mb:.1f} MB, {segundos:.0f}s)'))
        self.stdout.write('Los 5 ficheros más pesados:')
        for p in grandes:
            self.stdout.write(f'  {p.stat().st_size / 1e6:6.1f} MB  {p.relative_to(out)}')
        if fallos:
            self.stdout.write(self.style.ERROR(f'\nFallos ({len(fallos)}):'))
            for url, motivo in fallos[:20]:
                self.stdout.write(self.style.ERROR(f'  {url}  ->  {motivo}'))
