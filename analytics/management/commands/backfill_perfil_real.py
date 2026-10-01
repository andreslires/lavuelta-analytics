import json

import numpy as np
from django.core.management.base import BaseCommand

from analytics.models import Etapa
from analytics.services.gpx_processor import GPXProcessor

_MAX_PUNTOS = 600


def perfil_desde_gpx(etapa):
    """Perfil [[km, alt]] real de una etapa a partir de su archivo .gpx.

    Usa la altitud suavizada (igual que el detalle de etapa) y baja el muestreo
    a ~600 puntos conservando mínimos y máximos por franja, para que las cumbres
    y valles no se pierdan y el JSON siga siendo ligero.
    """
    proc = GPXProcessor(etapa.file_path)
    df = proc.calculate_metrics(proc._get_dataframe())
    x = df['dist_accumulated'].to_numpy(dtype=np.float64)
    z = df['elevation_smooth'].to_numpy(dtype=np.float64)

    pts = [
        (float(km), float(alt))
        for km, alt in zip(x, z)
        if np.isfinite(km) and np.isfinite(alt)
    ]
    if len(pts) < 2:
        return []

    if len(pts) > _MAX_PUNTOS:
        base = pts[0][0]
        d_total = pts[-1][0] - base
        if d_total <= 0:
            return []
        step = d_total / (_MAX_PUNTOS // 3)
        franjas = {}
        for km, alt in pts:
            b = int(min((km - base) / step, _MAX_PUNTOS // 3 - 1))
            lo, hi = franjas.setdefault(b, (None, None))
            if lo is None or alt < lo[1]:
                lo = (km, alt)
            if hi is None or alt > hi[1]:
                hi = (km, alt)
            franjas[b] = (lo, hi)
        pts = [p for lo, hi in franjas.values() for p in (lo, hi)]
        pts.sort(key=lambda p: p[0])
    return pts


class Command(BaseCommand):
    """Rellena perfil_real de etapas con GPX local (2018-2026) a partir del archivo .gpx.

    Las ediciones sin GPX (2011-2021) ya disponen de perfil real; las recientes
    usan file_path pero dejaban perfil_real vacío, y el mini-perfil de las
    tarjetas de edición depende de ese campo.
    """

    help = "Calcula perfil_real (JSON [[km, alt], ...]) de etapas con GPX desde su archivo."

    def handle(self, *args, **options):
        etapas = Etapa.objects.filter(file_path__isnull=False, perfil_real="")
        total = etapas.count()
        self.stdout.write(f"{total} etapas con GPX y sin perfil_real por procesar")

        ok = faltantes = 0
        for i, etapa in enumerate(etapas, 1):
            try:
                perfil = perfil_desde_gpx(etapa)
            except Exception as exc:  # noqa
                self.stderr.write(
                    f"  Error [{etapa.edicion.year} Et.{etapa.numero}] {etapa.file_path}: {exc}"
                )
                faltantes += 1
                continue
            if not perfil:
                faltantes += 1
                continue
            etapa.perfil_real = json.dumps(perfil, ensure_ascii=False)
            etapa.save(update_fields=["perfil_real"])
            ok += 1
            self.stdout.write(
                self.style.SUCCESS(f"[{i}/{total}] {etapa.edicion.year} Et. {etapa.numero} ({len(perfil)} pts)")
            )

        self.stdout.write(self.style.SUCCESS(
            f"Procesadas {total} etapas · {ok} con perfil guardado · {faltantes} sin datos."
        ))