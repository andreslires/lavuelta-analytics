import csv
import os
from django.core.management.base import BaseCommand, CommandError
from analytics.models import Etapa, Ciclista, Equipo, ResultadoEtapa

class Command(BaseCommand):
    help = 'Importa resultados de múltiples etapas desde un archivo CSV maestro'

    def add_arguments(self, parser):
        parser.add_argument('csv_file', type=str, help='Ruta al archivo CSV maestro')
        parser.add_argument('year', type=int, help='Año de la edición')

    def handle(self, *args, **options):
        csv_file = options['csv_file']
        year = options['year']

        if not os.path.exists(csv_file):
            raise CommandError(f'Archivo {csv_file} no encontrado')

        # 1. Leer todo el CSV y agrupar los datos por etapa
        data_by_stage = {}
        with open(csv_file, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                etapa_num = int(row.get('etapa', 0))
                if etapa_num not in data_by_stage:
                    data_by_stage[etapa_num] = []
                data_by_stage[etapa_num].append(row)

        # 2. Procesar cada etapa encontrada en el CSV
        for etapa_num, rows in data_by_stage.items():
            try:
                etapa = Etapa.objects.get(edicion__year=year, numero=etapa_num)
            except Etapa.DoesNotExist:
                self.stdout.write(self.style.WARNING(f'Etapa {etapa_num} de {year} no encontrada, saltando...'))
                continue

            # Limpiamos resultados anteriores SOLO para esta etapa específica
            ResultadoEtapa.objects.filter(etapa=etapa).delete()

            # 3. Importar filas
            count = 0
            for r in rows:
                ciclista_nombre = r.get('ciclista', '').strip()
                equipo_nombre = r.get('equipo', '').strip()
                posicion = int(r.get('posicion', 0))
                tiempo = r.get('tiempo', '').strip()
                diferencia = r.get('diferencia', '').strip()

                if not ciclista_nombre:
                    continue

                ciclista, _ = Ciclista.objects.get_or_create(nombre=ciclista_nombre)
                
                equipo = None
                if equipo_nombre:
                    equipo, _ = Equipo.objects.get_or_create(nombre=equipo_nombre)

                ResultadoEtapa.objects.create(
                    etapa=etapa,
                    ciclista=ciclista,
                    equipo=equipo,
                    posicion=posicion,
                    tiempo=tiempo or None,
                    diferencia=diferencia or None
                )
                count += 1
            self.stdout.write(self.style.SUCCESS(f'Importados {count} resultados para {etapa}'))
