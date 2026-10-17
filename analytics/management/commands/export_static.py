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
# ayuda, una página por edición y una por etapa, más los estáticos y un 404.
# Qué NO se exporta: el comparador y el filtro de ediciones del dashboard
# (necesitan servidor), y /admin/. Las plantillas los ocultan cuando
# settings.STATIC_EXPORT es True.
import re
import shutil
import time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.test import Client
from django.test.utils import override_settings

from analytics.models import Edicion, Etapa

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
        parser.add_argument('--skip-static', action='store_true',
                            help='No copia los ficheros estáticos (CSS, JS, favicon).')

    # ------------------------------------------------------------------
    def handle(self, *args, **opts):
        out = Path(opts['out']).resolve()
        if opts['clean'] and out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True, exist_ok=True)

        years = [int(y) for y in opts['years'].split(',') if y.strip()]
        paginas = self._paginas(years)
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
            resp = client.get('/__no_existe__/', secure=True)
            if resp.status_code == 404:
                self._escribir(out / '404.html', prefijar_enlaces(resp.content, base, host))

        if not opts['skip_static']:
            self._copiar_estaticos(out)

        # Ayuda para GitHub Pages (evita que procese el sitio con Jekyll).
        (out / '.nojekyll').write_text('')

        self._resumen(out, escritos, fallos, time.time() - t0)

        if fallos:
            raise CommandError(f'{len(fallos)} página(s) fallaron; el resto se exportó igualmente.')

    # ------------------------------------------------------------------
    def _paginas(self, years):
        """Lista de (url a pedir, [ficheros donde guardar la respuesta])."""
        paginas = [
            ('/', ['index.html']),
            ('/ayuda/', ['ayuda/index.html']),
            # El mapa se genera una sola vez y se guarda en dos sitios:
            # /mapa-general/ y /mapa-general/etapas/.
            ('/mapa-general/?tab=etapas',
             ['mapa-general/index.html', 'mapa-general/etapas/index.html']),
            ('/mapa-general/?tab=provincias', ['mapa-general/provincias/index.html']),
        ]

        ediciones = Edicion.objects.order_by('year')
        etapas = Etapa.objects.select_related('edicion').order_by('edicion__year', 'numero')
        if years:
            ediciones = ediciones.filter(year__in=years)
            etapas = etapas.filter(edicion__year__in=years)

        for ed in ediciones:
            paginas.append((f'/edicion/{ed.year}/', [f'edicion/{ed.year}/index.html']))
        for et in etapas:
            y, n = et.edicion.year, et.numero
            paginas.append((f'/etapa/{y}/{n}/', [f'etapa/{y}/{n}/index.html']))
        return paginas

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
        ficheros = [p for p in out.rglob('*') if p.is_file()]
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
