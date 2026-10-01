import os
import re

from django.core.cache import cache
from django.core.management.base import BaseCommand

from analytics.models import Edicion, Etapa
from analytics.services.gpx_processor import GPXProcessor, clasificar_etapa
from analytics.services.perfiles_similares import formatear_perfil, perfil_from_elevation


class Command(BaseCommand):
    """Importa archivos GPX y métricas derivadas desde el directorio data/."""

    help = 'Imports GPX files from data directory'

    def handle(self, *args, **kwargs):
        """Importa ediciones, etapas y GPX desde data/."""
        data_dir = 'data'
        for edicion_year in sorted(os.listdir(data_dir)):
            if not os.path.isdir(os.path.join(data_dir, edicion_year)):
                continue

            edicion, _ = Edicion.objects.get_or_create(year=int(edicion_year), nombre=f"La Vuelta {edicion_year}")

            path_edicion = os.path.join(data_dir, edicion_year)
            for filename in os.listdir(path_edicion):
                if not filename.endswith('.gpx'):
                    continue

                # Extract stage number
                match = re.search(r'stage-(\d+)', filename)
                if not match:
                    continue
                stage_num = int(match.group(1))

                file_path = os.path.join(path_edicion, filename)
                processor = GPXProcessor(file_path)
                data = processor.process()

                Etapa.objects.update_or_create(
                    edicion=edicion,
                    numero=stage_num,
                    defaults={
                        'nombre': f"Etapa {stage_num}",
                        'tipo': clasificar_etapa(data['distancia_total'], data['desnivel_positivo']),
                        'distancia': data['distancia_total'],
                        'desnivel': data['desnivel_positivo'],
                        'track_wkt': data['wkt'],
                        'perfil': formatear_perfil(
                            perfil_from_elevation(data['df']['elevation_smooth'].to_numpy())
                        ),
                        'file_path': file_path,
                        'altitud_max': data['altitud_max'],
                        'altitud_min': data['altitud_min'],
                        'desnivel_negativo': data['desnivel_negativo'],
                        'pendiente_max': data['pendiente_max'],
                        'pendiente_media': data['pendiente_media'],
                        'n_puertos': data['n_puertos'],
                    }
                )
                self.stdout.write(self.style.SUCCESS(f'Imported {edicion_year} Stage {stage_num}'))

        # Los mapas, la geografía y los datos GPX se cachean sin expiración
        # (timeout=None): al reimportar hay que invalidarlos para que reflejen
        # los datos nuevos en la siguiente petición.
        cache.clear()
        self.stdout.write(self.style.SUCCESS('Cache cleared'))
