from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from analytics.models import Ciclista, Equipo, Etapa, ResultadoEquipoEtapa
from analytics.services.ciclistas import invalidar_ranking_cache


ETAPAS_CRE = (
    (2011, 1),
    (2012, 1),
    (2013, 1),
    (2014, 1),
    (2015, 1),
    (2016, 1),
    (2017, 1),
    (2019, 1),
    (2022, 1),
    (2023, 1),
    (2025, 5),
)


class Command(BaseCommand):
    help = (
        'Marca las etapas CRE y convierte sus resultados individuales existentes '
        'en ResultadoEquipoEtapa'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--anio',
            type=int,
            help='Procesa solo las CRE de un año concreto',
        )
        parser.add_argument(
            '--etapa',
            type=int,
            help='Procesa solo una etapa; requiere --anio',
        )
        parser.add_argument(
            '--dry-run',
            action='store_true',
            help='Muestra lo que haría sin escribir en la base de datos',
        )

    def handle(self, *args, **options):
        anio = options['anio']
        numero = options['etapa']
        dry_run = options['dry_run']

        if numero and not anio:
            raise CommandError('--etapa requiere indicar también --anio')

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
            self.procesar(etapa, dry_run)

        falsos = Ciclista.objects.filter(
            nombre__in=Equipo.objects.values('nombre'),
            resultadoetapa__isnull=True,
            clasificaciones_generales__isnull=True,
        )
        if dry_run:
            self.stdout.write(
                f'Eliminaría {falsos.count()} "ciclistas" que son equipos '
                '(solo los que no tengan resultados tras migrar; en dry-run '
                'esta cifra aún no refleja la migración)'
            )
            return

        # Equipos que se guardaron como Ciclista en los datos antiguos de CRE.
        eliminados = falsos.count()
        falsos.delete()
        self.stdout.write(
            self.style.SUCCESS(f'Eliminados {eliminados} ciclistas que eran equipos')
        )
        invalidar_ranking_cache()

    def procesar(self, etapa, dry_run):
        resultados = list(
            etapa.resultados_db.select_related('ciclista', 'equipo').order_by(
                'posicion'
            )
        )
        equipos_previos = list(
            etapa.resultados_equipo.select_related('equipo').order_by('posicion')
        )

        if not resultados:
            if equipos_previos:
                self.stdout.write(
                    f'{etapa}: ya tenía {len(equipos_previos)} resultados de '
                    'equipo; solo se marca es_cre'
                )
            else:
                self.stdout.write(
                    self.style.WARNING(
                        f'{etapa}: no tiene resultados que migrar; se marca es_cre'
                    )
                )
            if not dry_run:
                if not etapa.es_cre:
                    etapa.es_cre = True
                    etapa.save(update_fields=['es_cre'])
            return

        preparados = []
        equipos_nuevos = []
        for resultado in resultados:
            equipo = resultado.equipo
            if equipo is None:
                equipo, creado = Equipo.objects.get_or_create(
                    nombre=resultado.ciclista.nombre
                )
                if creado:
                    equipos_nuevos.append(equipo.nombre)
            preparados.append(
                ResultadoEquipoEtapa(
                    etapa=etapa,
                    equipo=equipo,
                    posicion=resultado.posicion,
                    tiempo=resultado.tiempo,
                    diferencia=resultado.diferencia,
                )
            )

        preparados.sort(key=lambda item: item.posicion)
        ganador = preparados[0].equipo.nombre if preparados else ''

        if dry_run:
            self.stdout.write(
                f'{etapa}: migraría {len(preparados)} resultados individuales '
                f'a equipo; ganador: {ganador}'
            )
            if equipos_nuevos:
                self.stdout.write(
                    'Equipos nuevos: ' + ', '.join(sorted(set(equipos_nuevos)))
                )
            return

        with transaction.atomic():
            etapa.es_cre = True
            etapa.ganador = ganador
            etapa.save(update_fields=['es_cre', 'ganador'])
            etapa.resultados_equipo.all().delete()
            ResultadoEquipoEtapa.objects.bulk_create(preparados)
            etapa.resultados_db.all().delete()

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
