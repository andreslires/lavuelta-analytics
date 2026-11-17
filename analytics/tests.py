from pathlib import Path
from tempfile import TemporaryDirectory

from io import StringIO

from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, SimpleTestCase, Client, override_settings
from django.urls import reverse
from analytics.management.commands.export_static import (
    parsear_lista,
    seleccionado,
    verificar_enlaces,
)
from analytics.management.commands.importar_cre_pcs import (
    _parsear_tabla_equipos_html,
    _tiempo_y_diferencia,
)
from analytics.models import (
    Ciclista,
    ClasificacionGeneral,
    Edicion,
    Equipo,
    Etapa,
    ResultadoEquipoEtapa,
    ResultadoEtapa,
)
from analytics.services.ciclistas import invalidar_ranking_cache, ranking
from analytics.services.gpx_processor import GPXProcessor


class GPXProcessorTests(SimpleTestCase):
    def test_resolver_ruta_con_separadores_windows(self):
        with TemporaryDirectory() as tmp:
            gpx = Path(tmp) / '2025' / 'stage-1-ruta.gpx'
            gpx.parent.mkdir()
            gpx.write_text('<gpx></gpx>', encoding='utf-8')
            processor = GPXProcessor.__new__(GPXProcessor)
            processor.file_path = str(gpx).replace('/', '\\')
            self.assertEqual(Path(processor._resolver_ruta()), gpx)


class SmokeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.edicion = Edicion.objects.create(
            year=2026,
            nombre='La Vuelta 2026',
            ganador='Enric Mas'
        )
        cls.etapa = Etapa.objects.create(
            edicion=cls.edicion,
            numero=1,
            nombre='Etapa 1',
            tipo='Llana',
            distancia=150.0,
            desnivel=1000.0,
            track_wkt='LINESTRING (0 0, 1 1)'
        )
        cls.ciclista = Ciclista.objects.create(nombre='Enric Mas')
        cls.equipo = Equipo.objects.create(nombre='Movistar Team')
        cls.gc = ClasificacionGeneral.objects.create(
            edicion=cls.edicion,
            ciclista=cls.ciclista,
            equipo=cls.equipo,
            posicion=1,
            tiempo='73:52:55'
        )
        cls.resultado = ResultadoEtapa.objects.create(
            etapa=cls.etapa,
            ciclista=cls.ciclista,
            equipo=cls.equipo,
            posicion=1,
            tiempo='3:30:00'
        )

    def setUp(self):
        self.client = Client()

    def test_dashboard(self):
        response = self.client.get(reverse('dashboard'))
        self.assertEqual(response.status_code, 200)

    def test_ciclistas(self):
        response = self.client.get(reverse('ciclistas'))
        self.assertEqual(response.status_code, 200)

    def test_ciclista_detalle(self):
        response = self.client.get(reverse('ciclista_detalle', args=[self.ciclista.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Balance en La Vuelta')
        self.assertContains(response, 'Clasificación general')
        self.assertContains(response, 'Podios en etapas')
        self.assertContains(response, 'Trayectoria por año')

    def test_edicion_detalle(self):
        response = self.client.get(reverse('edicion_detalle', args=[2026]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Enric Mas')

    def test_etapa_detalle(self):
        response = self.client.get(reverse('etapa_detalle', args=[2026, 1]))
        self.assertEqual(response.status_code, 200)

    def test_etapa_detalle_lista_etapas_parecidas(self):
        cache.clear()
        perfil = ','.join(['0.5'] * 441)
        Etapa.objects.filter(pk=self.etapa.pk).update(perfil=perfil)
        otra = Etapa.objects.create(
            edicion=self.edicion, numero=2, nombre='Etapa 2', tipo='Llana',
            distancia=152.0, desnivel=1100.0, track_wkt='LINESTRING (0 0, 1 1)',
            perfil=perfil,
        )
        response = self.client.get(reverse('etapa_detalle', args=[2026, 1]))
        self.assertContains(response, 'Etapas más parecidas')
        self.assertContains(response, reverse('etapa_detalle', args=[2026, otra.numero]))

    def test_ayuda(self):
        response = self.client.get(reverse('ayuda'))
        self.assertEqual(response.status_code, 200)


def _tabla(cabeceras, filas):
    ths = ''.join(f'<th data-code="{c}">{c}</th>' for c in cabeceras)
    trs = ''.join(
        '<tr>' + ''.join(f'<td>{c}</td>' for c in fila) + '</tr>' for fila in filas
    )
    return f'<table><thead><tr>{ths}</tr></thead><tbody>{trs}</tbody></table>'


class CreParserTests(SimpleTestCase):
    def test_ignora_tabla_general_y_resuelve_repetidos(self):
        general = _tabla(
            ['rnk', 'prev_rnk', 'team', 'classification', 'timelag'],
            [['1', '2', 'Equipo X', 'WT', '47:43:44']],
        )
        cre = _tabla(
            ['rnk', 'team', 'classification', 'timelag'],
            [
                ['1', 'Equipo A', 'WT', '17:30'],
                ['2', 'Equipo B', 'WT', ',,'],
                ['3', 'Equipo C', 'WT', '0:06'],
                ['4', 'Equipo D', 'WT', ',,'],
            ],
        )
        filas = _parsear_tabla_equipos_html(general + cre)
        self.assertEqual(
            [(f[0], f[1], f[3]) for f in filas],
            [(1, 'Equipo A', '17:30'), (2, 'Equipo B', '0:00'),
             (3, 'Equipo C', '0:06'), (4, 'Equipo D', '0:06')],
        )

    def test_tiempo_y_diferencia(self):
        self.assertEqual(_tiempo_y_diferencia(1, '17:30'), ('17:30', None))
        self.assertEqual(_tiempo_y_diferencia(2, '0:06'), (None, '+0:06'))


class CreTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.edicion = Edicion.objects.create(year=2017, nombre='La Vuelta 2017')
        cls.cre = Etapa.objects.create(
            edicion=cls.edicion, numero=1, nombre='CRE', tipo='Contrarreloj',
            distancia=13.8, desnivel=100, track_wkt='LINESTRING (0 0, 1 1)',
            es_cre=True,
        )
        cls.equipo = Equipo.objects.create(nombre='BMC Racing Team')
        ResultadoEquipoEtapa.objects.create(
            etapa=cls.cre, equipo=cls.equipo, posicion=1, tiempo='15:58'
        )
        ResultadoEquipoEtapa.objects.create(
            etapa=cls.cre,
            equipo=Equipo.objects.create(nombre='Quick-Step Floors'),
            posicion=2, diferencia='+0:06',
        )

    def test_etapa_cre_muestra_equipos(self):
        response = self.client.get(reverse('etapa_detalle', args=[2017, 1]))
        self.assertContains(response, 'Equipo ganador')
        self.assertContains(response, 'BMC Racing Team')
        self.assertContains(response, 'Contrarreloj por equipos')

    def test_edicion_marca_cre(self):
        response = self.client.get(reverse('edicion_detalle', args=[2017]))
        self.assertContains(response, 'stage-cre')

    def test_cre_no_cuenta_en_ranking_individual(self):
        invalidar_ranking_cache()
        self.assertEqual(ranking(), [])


class RankingTests(TestCase):
    def test_ranking_cuenta_victorias_y_dashboard_muestra_lider(self):
        edicion = Edicion.objects.create(year=2020, nombre='La Vuelta 2020')
        etapa = Etapa.objects.create(
            edicion=edicion, numero=1, nombre='E1', tipo='Llana',
            distancia=100, desnivel=500, track_wkt='LINESTRING (0 0, 1 1)',
        )
        ciclista = Ciclista.objects.create(nombre='Primož Roglič')
        ResultadoEtapa.objects.create(etapa=etapa, ciclista=ciclista, posicion=1)
        invalidar_ranking_cache()
        lista = ranking()
        self.assertEqual(lista[0].nombre, 'Primož Roglič')
        self.assertEqual(lista[0].victorias, 1)
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'riders-strip')
        self.assertContains(response, 'Primož Roglič')


@override_settings(STATIC_EXPORT=True)
class ComparadorEstaticoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        perfil = ','.join(['0.5'] * 441)
        for year in (2024, 2025):
            edicion = Edicion.objects.create(year=year, nombre=f'La Vuelta {year}')
            for numero in (1, 2):
                Etapa.objects.create(
                    edicion=edicion, numero=numero, nombre=f'E{numero}', tipo='Llana',
                    distancia=150.0 + numero, desnivel=1000.0, perfil=perfil,
                    track_wkt='LINESTRING (0 0, 1 1)',
                )

    def setUp(self):
        cache.clear()

    def test_menu_estatico_incluye_comparar(self):
        response = self.client.get(reverse('dashboard'))
        self.assertContains(response, 'href="/comparar/"')

    def test_comparar_tiene_pantalla_intermedia(self):
        response = self.client.get(reverse('comparar'))
        self.assertContains(response, 'Selecciona un modo')
        self.assertNotContains(response, 'id="static-similares"')

    def test_pestanas_apuntan_a_paginas_estaticas(self):
        response = self.client.get(reverse('comparar') + '?tab=ediciones')
        self.assertContains(response, 'href="/comparar/ediciones/"')
        self.assertContains(response, 'href="/comparar/similares/"')
        self.assertContains(response, 'href="/comparar/zonas/"')
        self.assertNotContains(response, '?tab=perfiles')

    def test_similares_incrusta_datos_y_no_usa_servidor(self):
        response = self.client.get(reverse('comparar') + '?tab=perfiles')
        self.assertContains(response, 'id="similares-data"')
        self.assertContains(response, 'id="static-similares"')
        self.assertNotContains(response, "fetch('/comparar/")

    def test_zonas_incrusta_datos_y_no_carga_mapas(self):
        response = self.client.get(reverse('comparar') + '?tab=zonas')
        self.assertContains(response, 'id="zonas-data"')
        self.assertContains(response, 'id="static-zonas"')
        self.assertNotContains(response, 'zona-map-load')

    def test_pareja_de_ediciones(self):
        response = self.client.get(reverse('comparar') + '?a=2024&b=2025')
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'comp-duel')
        self.assertContains(response, 'comp-ed-hint')

    def test_exportador_incluye_parejas_y_pestanas(self):
        from analytics.management.commands.export_static import Command

        destinos = {d for _, ds in Command()._paginas([]) for d in ds}
        self.assertIn('comparar/index.html', destinos)
        self.assertIn('comparar/ediciones/index.html', destinos)
        self.assertIn('comparar/similares/index.html', destinos)
        self.assertIn('comparar/zonas/index.html', destinos)
        self.assertIn('comparar/2024-2025/index.html', destinos)
        self.assertNotIn('comparar/2025-2024/index.html', destinos)


class ExportSeleccionTests(SimpleTestCase):
    def test_parsear_lista(self):
        self.assertEqual(parsear_lista(' comparar/ , etapas,, '), ['comparar', 'etapas'])
        self.assertEqual(parsear_lista(''), [])

    def test_solo_por_grupo_y_por_prefijo(self):
        self.assertTrue(seleccionado('etapa/2025/5/index.html', ['etapas'], []))
        self.assertFalse(seleccionado('comparar/index.html', ['etapas'], []))
        self.assertTrue(seleccionado('comparar/zonas/index.html', ['comparar/zonas'], []))
        self.assertFalse(seleccionado('comparar/similares/index.html', ['comparar/zonas'], []))
        # "ciclistas" incluye el listado y las fichas
        self.assertTrue(seleccionado('ciclistas/index.html', ['ciclistas'], []))
        self.assertTrue(seleccionado('ciclista/7/index.html', ['ciclistas'], []))

    def test_excluir_y_sin_filtros(self):
        self.assertTrue(seleccionado('mapa-general/index.html', [], []))
        self.assertFalse(seleccionado('mapa-general/index.html', [], ['mapa']))
        self.assertFalse(seleccionado('comparar/index.html', ['comparar'], ['comparar/index.html']))
        self.assertTrue(seleccionado('404.html', ['general'], []))


class ExportComandoTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        edicion = Edicion.objects.create(year=2025, nombre='La Vuelta 2025')
        Etapa.objects.create(
            edicion=edicion, numero=1, nombre='E1', tipo='Llana', distancia=1,
            desnivel=1, track_wkt='LINESTRING (0 0, 1 1)',
        )

    def _ejecutar(self, tmp, *args):
        salida = StringIO()
        call_command('export_static', '--out', str(Path(tmp) / 'salida'), *args, stdout=salida)
        return salida.getvalue()

    def test_dry_run_resume_y_no_escribe(self):
        with TemporaryDirectory() as tmp:
            texto = self._ejecutar(tmp, '--solo', 'etapas', '--dry-run')
            self.assertIn('Se regenerarán 1 páginas (etapas 1)', texto)
            self.assertIn('Exportación parcial', texto)
            self.assertFalse((Path(tmp) / 'salida').exists())

    def test_excluir_se_refleja_en_el_plan(self):
        with TemporaryDirectory() as tmp:
            texto = self._ejecutar(tmp, '--excluir', 'comparar,mapa', '--dry-run')
            self.assertNotIn('comparar', texto.split('\n')[0])
            self.assertIn('etapas 1', texto)

    def test_clean_no_se_combina_con_solo(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                self._ejecutar(tmp, '--solo', 'etapas', '--clean', '--dry-run')

    def test_elemento_inexistente_da_error(self):
        with TemporaryDirectory() as tmp:
            with self.assertRaises(CommandError):
                self._ejecutar(tmp, '--solo', 'etapaz', '--dry-run')


class VerificarEnlacesTests(SimpleTestCase):
    def _pagina(self, raiz, ruta, html):
        destino = Path(raiz) / ruta
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(html, encoding='utf-8')

    def test_detecta_rotos_y_enlaces_sin_prefijo(self):
        with TemporaryDirectory() as tmp:
            self._pagina(tmp, 'index.html',
                         '<a href="/web/etapa/1/">ok</a><a href="/web/falta/">roto</a>'
                         '<a href="/sin-prefijo/">x</a><a href="//cdn.ejemplo/x.js">ext</a>')
            self._pagina(tmp, 'etapa/1/index.html', '<a href="/web/">inicio</a>')
            total, problemas = verificar_enlaces(tmp, '/web')
            self.assertEqual(total, 4)
            self.assertEqual(
                {(e, m) for e, _, m in problemas},
                {('/web/falta/', 'no existe'), ('/sin-prefijo/', 'sin el prefijo /web')},
            )

    def test_sin_base_todo_ok(self):
        with TemporaryDirectory() as tmp:
            self._pagina(tmp, 'index.html', '<a href="/etapa/1/">ok</a>')
            self._pagina(tmp, 'etapa/1/index.html', '<a href="/">inicio</a>')
            total, problemas = verificar_enlaces(tmp, '')
            self.assertEqual((total, problemas), (2, []))
