import numpy as np
from django.core.management.base import BaseCommand
from analytics.models import Etapa
from analytics.services.perfiles_similares import formatear_perfil, perfil_from_elevation
from analytics.services.gpx_processor import GPXProcessor


class Command(BaseCommand):
    help = 'Precalcula y guarda el perfil normalizado de cada etapa (campo Etapa.perfil)'

    def handle(self, *args, **kwargs):
        pendientes = Etapa.objects.filter(perfil='').order_by('-edicion__year', 'numero')
        total = pendientes.count()
        self.stdout.write(f'{total} etapas sin perfil por calcular')
        for i, etapa in enumerate(pendientes, 1):
            try:
                data = GPXProcessor(etapa.file_path).process()
                arr = perfil_from_elevation(data['df']['elevation_smooth'].to_numpy())
                etapa.perfil = formatear_perfil(arr)
                etapa.save(update_fields=['perfil'])
                self.stdout.write(self.style.SUCCESS(
                    f'[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}'))
            except Exception as exc:
                self.stdout.write(self.style.ERROR(
                    f'[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}: {exc}'))
        self.stdout.write(self.style.SUCCESS('Perfiles calculados'))