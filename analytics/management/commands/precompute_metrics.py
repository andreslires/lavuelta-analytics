from django.core.management.base import BaseCommand

from analytics.models import Etapa
from analytics.services.gpx_processor import GPXProcessor


class Command(BaseCommand):
    """Precalcula y guarda las métricas GPX de cada etapa (altitud, puertos, pendientes)."""

    help = "Precalcula y guarda las métricas GPX de cada etapa (altitud, puertos, pendientes)."

    def handle(self, *args, **kwargs):
        pendientes = Etapa.objects.filter(n_puertos=0, altitud_max=0).order_by(
            "-edicion__year", "numero"
        )
        total = pendientes.count()
        self.stdout.write(f"{total} etapas sin métricas por calcular")
        for i, etapa in enumerate(pendientes, 1):
            try:
                data = GPXProcessor(etapa.file_path).process()
                etapa.altitud_max = data["altitud_max"]
                etapa.altitud_min = data["altitud_min"]
                etapa.desnivel_negativo = data["desnivel_negativo"]
                etapa.pendiente_max = data["pendiente_max"]
                etapa.pendiente_media = data["pendiente_media"]
                etapa.n_puertos = data["n_puertos"]
                # Guarda contra NaN: SQLite guarda NaN como NULL y rompe los
                # campos NOT NULL. Si alguna métrica sigue con valor no finito,
                # se deja en 0.
                for campo in (
                    "altitud_max",
                    "altitud_min",
                    "desnivel_negativo",
                    "pendiente_max",
                    "pendiente_media",
                ):
                    valor = getattr(etapa, campo)
                    if valor is None or valor != valor or valor in (float("inf"), float("-inf")):
                        setattr(etapa, campo, 0)
                etapa.save(
                    update_fields=[
                        "altitud_max",
                        "altitud_min",
                        "desnivel_negativo",
                        "pendiente_max",
                        "pendiente_media",
                        "n_puertos",
                    ]
                )
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero} "
                        f"— {etapa.n_puertos} puertos, {etapa.altitud_max:.0f}m"
                    )
                )
            except Exception as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}: {exc}"
                    )
                )
        self.stdout.write(self.style.SUCCESS("Métricas calculadas"))
