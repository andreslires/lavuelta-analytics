import json

from django.core.management.base import BaseCommand

from analytics.models import Edicion, Etapa

# Datos factuales de la edición 2026 aportados manualmente (CG final, maillots
# y ganadores de etapa) porque la fuente de datos aún no los publicó. Formato
# idéntico al que importa `import_recorridos` (gc_json, maillots_json,
# resultados). La vista corta gc[:5] para el top-5, por eso gc_json lleva la
# lista completa.
GC_2026 = [
    {"position": 1, "rider": "Enric Mas", "team": "Movistar Team", "nationality": None, "time": "74:52:55", "gap": None},
    {"position": 2, "rider": "Primož Roglič", "team": "Red Bull - BORA - hansgrohe", "nationality": None, "time": None, "gap": "+2:15"},
    {"position": 3, "rider": "Felix Gall", "team": "Decathlon CMA CGM Team", "nationality": None, "time": None, "gap": "+2:44"},
    {"position": 4, "rider": "Richard Carapaz", "team": "EF Education - EasyPost", "nationality": None, "time": None, "gap": "+6:54"},
    {"position": 5, "rider": "Sepp Kuss", "team": "Team Visma | Lease a Bike", "nationality": None, "time": None, "gap": "+8:45"},
    {"position": 6, "rider": "Oscar Onley", "team": "Netcompany INEOS", "nationality": None, "time": None, "gap": "+9:28"},
    {"position": 7, "rider": "Jakob Omrzel", "team": "Bahrain - Victorious", "nationality": None, "time": None, "gap": "+10:38"},
    {"position": 8, "rider": "Clément Berthet", "team": "Groupama - FDJ United", "nationality": None, "time": None, "gap": "+11:41"},
    {"position": 9, "rider": "Cristián Rodríguez", "team": "XDS Astana Team", "nationality": None, "time": None, "gap": "+11:59"},
    {"position": 10, "rider": "Harold Tejada", "team": "XDS Astana Team", "nationality": None, "time": None, "gap": "+12:51"},
    {"position": 11, "rider": "Guillaume Martin-Guyonnet", "team": "Groupama - FDJ United", "nationality": None, "time": None, "gap": "+20:14"},
    {"position": 12, "rider": "Léo Bisiaux", "team": "Decathlon CMA CGM Team", "nationality": None, "time": None, "gap": "+25:03"},
    {"position": 13, "rider": "Mattias Skjelmose", "team": "Lidl - Trek", "nationality": None, "time": None, "gap": "+25:43"},
    {"position": 14, "rider": "Mario Aparicio", "team": "Burgos-Burpellet-BH", "nationality": None, "time": None, "gap": "+42:17"},
    {"position": 15, "rider": "Jan Hirt", "team": "NSN Cycling Team", "nationality": None, "time": None, "gap": "+43:20"},
    {"position": 16, "rider": "Juan Felipe Rodríguez", "team": "EF Education - EasyPost", "nationality": None, "time": None, "gap": "+47:56"},
    {"position": 17, "rider": "Santiago Buitrago", "team": "Bahrain - Victorious", "nationality": None, "time": None, "gap": "+50:56"},
    {"position": 18, "rider": "Filippo Zana", "team": "Soudal Quick-Step", "nationality": None, "time": None, "gap": "+58:44"},
    {"position": 19, "rider": "Urko Berrade", "team": "Equipo Kern Pharma", "nationality": None, "time": None, "gap": "+1:01:09"},
    {"position": 20, "rider": "Embret Svestad-Bårdseng", "team": "Netcompany INEOS", "nationality": None, "time": None, "gap": "+1:10:46"},
]

MAILLOTS_2026 = {
    "points": {"position": 1, "rider": "Wout van Aert", "team": "Team Visma | Lease a Bike", "nationality": None, "time": None, "gap": None},
    "kom": {"position": 1, "rider": "Santiago Buitrago", "team": "Bahrain - Victorious", "nationality": None, "time": None, "gap": None},
    "youth": {"position": 1, "rider": "Oscar Onley", "team": "Netcompany INEOS", "nationality": None, "time": None, "gap": None},
}

# Ganadores de etapa que la fuente dejó vacíos y se rellenan manualmente.
# resultados = lista de entradas del resultado parcial (mínimo el ganador).
ETAPAS_2026 = {
    19: {
        "ganador": "Edward Dunbar",
        "resultados": [
            {"position": 1, "rider": "Edward Dunbar", "team": "Pinarello Q36.5 Pro Cycling Team", "nationality": None, "time": None, "gap": None},
        ],
    },
    20: {
        "ganador": "Mikel Landa",
        "resultados": [
            {"position": 1, "rider": "Mikel Landa", "team": "Soudal Quick-Step", "nationality": None, "time": None, "gap": None},
        ],
    },
    21: {
        "ganador": "Tobias Halland Johannessen",
        "resultados": [
            {"position": 1, "rider": "Tobias Halland Johannessen", "team": "Uno-X Mobility", "nationality": None, "time": None, "gap": None},
        ],
    },
}


class Command(BaseCommand):
    """Backfill manual de resultados 2026 (CG final, maillots y ganadores de etapa).

    La fuente de datos no publicó los resultados de la edición 2026; se rellenan
    a mano los campos factuales que el resto de ediciones ya tienen importados.
    Solo toca Edicion 2026 y las etapas 19-21; no modifica métricas ni perfiles.
    """

    help = "Rellena ganador, gc_json, maillots_json de la edición 2026 y los ganadores de las etapas 19-21."

    def handle(self, *args, **kwargs):
        edicion = Edicion.objects.get(year=2026)
        cambios = []

        if edicion.ganador != "Enric Mas":
            edicion.ganador = "Enric Mas"
            cambios.append("Edicion.ganador")
        if edicion.gc_json != json.dumps(GC_2026, ensure_ascii=False):
            edicion.gc_json = json.dumps(GC_2026, ensure_ascii=False)
            cambios.append("Edicion.gc_json")
        if edicion.maillots_json != json.dumps(MAILLOTS_2026, ensure_ascii=False):
            edicion.maillots_json = json.dumps(MAILLOTS_2026, ensure_ascii=False)
            cambios.append("Edicion.maillots_json")
        if cambios:
            edicion.save(update_fields=['ganador', 'gc_json', 'maillots_json'])
        self.stdout.write(self.style.SUCCESS(f"Edicion 2026: {', '.join(cambios) if cambios else 'sin cambios'}"))

        for numero, datos in ETAPAS_2026.items():
            etapa = Etapa.objects.filter(edicion=edicion, numero=numero).first()
            if not etapa:
                self.stderr.write(f"Etapa {numero} no encontrada; omitida.")
                continue
            resultados_json = json.dumps(datos['resultados'], ensure_ascii=False)
            ups = []
            if etapa.ganador != datos['ganador']:
                etapa.ganador = datos['ganador']
                ups.append('ganador')
            if etapa.resultados != resultados_json:
                etapa.resultados = resultados_json
                ups.append('resultados')
            if ups:
                etapa.save(update_fields=ups)
                self.stdout.write(self.style.SUCCESS(f"Etapa {numero}: {', '.join(ups)}"))
            else:
                self.stdout.write(f"Etapa {numero}: sin cambios")

        self.stdout.write(self.style.SUCCESS("Backfill 2026 completado."))