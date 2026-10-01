import json

from django.core.management.base import BaseCommand

from analytics.models import Etapa
from analytics.services.gpx_processor import GPXProcessor, metrics_from_perfil


class Command(BaseCommand):
    """Recalcula `pendiente_max` de todas las etapas con la métrica robusta (P99).

    Para etapas con GPX local se reprocesa el archivo; para las que solo tienen
    perfil persistido (perfil_real) se usa metrics_from_perfil. Solo se toca el
    campo pendiente_max, el resto de métricas queda intacto.
    """

    help = "Recalcula pendiente_max (P99 de pendientes de 100 m) en todas las etapas."

    def handle(self, *args, **kwargs):
        etapas = Etapa.objects.order_by('-edicion__year', 'numero')
        total = etapas.count()
        actualizadas = 0
        omitidas = 0
        for i, etapa in enumerate(etapas, 1):
            try:
                if etapa.file_path:
                    data = GPXProcessor(etapa.file_path).process()
                    valor = data['pendiente_max']
                elif etapa.perfil_real:
                    try:
                        perfil = json.loads(etapa.perfil_real or '[]')
                    except (ValueError, TypeError):
                        perfil = []
                    valor = metrics_from_perfil(perfil)['pendiente_max']
                else:
                    omitidas += 1
                    self.stdout.write(
                        f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}: "
                        f"sin GPX ni perfil, omitida"
                    )
                    continue

                if valor is None or valor != valor or valor in (float('inf'), float('-inf')):
                    valor = 0.0
                valor = float(valor)
                if abs(valor - float(etapa.pendiente_max or 0)) > 1e-9:
                    etapa.pendiente_max = valor
                    etapa.save(update_fields=['pendiente_max'])
                    actualizadas += 1
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}: "
                        f"{etapa.pendiente_max:.1f}%"
                    )
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}: {exc}"
                    )
                )
        self.stdout.write(self.style.SUCCESS(
            f"Procesadas {total} etapas · {actualizadas} actualizadas · {omitidas} omitidas."
        ))