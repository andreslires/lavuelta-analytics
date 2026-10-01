import json

from django.core.management.base import BaseCommand

from analytics.models import Etapa
from analytics.services.gpx_processor import metrics_from_perfil


class Command(BaseCommand):
    """Rellena métricas de terreno (desnivel_negativo, pendiente_max) de las
    etapas sin GPX a partir de su perfil persistido (perfil_real)."""

    help = "Calcula las métricas de terreno de etapas sin GPX desde su perfil persistido."

    def handle(self, *args, **kwargs):
        etapas = Etapa.objects.filter(file_path=None).exclude(perfil_real="")
        total = etapas.count()
        self.stdout.write(f"{total} etapas sin GPX con perfil por procesar")

        actualizadas = 0
        for i, etapa in enumerate(etapas, 1):
            try:
                perfil = json.loads(etapa.perfil_real or "[]")
            except (ValueError, TypeError):
                perfil = []
            m = metrics_from_perfil(perfil)

            cambios = {}
            pendiente_media = float(etapa.pendiente_media) or 0.0
            perfil_pend = float(m["pendiente_media"]) or 0.0
            for campo in ("desnivel_negativo", "pendiente_max"):
                valor = getattr(etapa, campo)
                if valor is None or valor != valor or not valor:
                    cambios[campo] = m[campo]
            for campo in ("altitud_max", "altitud_min"):
                if not (getattr(etapa, campo)) and m[campo]:
                    cambios[campo] = m[campo]
            # Pendiente media de puertos: si el perfil detecta puertos y la
            # etapa no los tenía, se completa. El importador ya la calculaba,
            # así que solo actúa cuando quedó a 0.
            if not pendiente_media and perfil_pend:
                cambios["pendiente_media"] = perfil_pend
            if m["n_puertos"] and not etapa.n_puertos:
                cambios["n_puertos"] = m["n_puertos"]

            if cambios:
                for campo, valor in cambios.items():
                    setattr(etapa, campo, valor)
                etapa.save(update_fields=list(cambios))
                actualizadas += 1

            self.stdout.write(
                self.style.SUCCESS(f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero}")
            )

        self.stdout.write(self.style.SUCCESS(
            f"Procesadas {total} etapas · {actualizadas} actualizadas."
        ))