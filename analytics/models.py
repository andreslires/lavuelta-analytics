# Modelos ORM: Edicion (año + nombre) y Etapa (numero, distancia, desnivel,
# track en WKT y ruta al GPX original en /data para perfil y mapa).
from django.db import models

class Edicion(models.Model):
    year = models.IntegerField(unique=True)
    nombre = models.CharField(max_length=100)
    gender = models.CharField(max_length=10, default='men')
    fecha_inicio = models.DateField(null=True, blank=True)
    fecha_fin = models.DateField(null=True, blank=True)
    ganador = models.CharField(max_length=200, blank=True, default='')
    gc_json = models.TextField(blank=True, default='')
    maillots_json = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.nombre} ({self.year})"

class Etapa(models.Model):
    edicion = models.ForeignKey(Edicion, on_delete=models.CASCADE, related_name='etapas')
    numero = models.IntegerField()
    nombre = models.CharField(max_length=200)
    tipo = models.CharField(max_length=50)
    distancia = models.FloatField()
    desnivel = models.FloatField()
    track_wkt = models.TextField()
    file_path = models.CharField(max_length=500, blank=True, null=True)
    # Perfil de elevación normalizado (441 muestras en [0,1], csv) para la
    # comparación de "perfiles similares". Se calcula en import_data o con el
    # comando precompute_perfiles; se deja vacío si no se ha precalculado.
    perfil = models.TextField(blank=True, default='')

    # Perfil real en km (JSON [[km, alt], ...]) para etapas importadas sin GPX
    # local.  Se usa para dibujar el mapa/plot desde track_wkt en lugar de
    # procesar un archivo .gpx.  Si hay file_path, este campo se ignora.
    perfil_real = models.TextField(blank=True, default='')

    # Métricas GPX precalculadas (para evitar procesar el GPX en cada consulta).
    # Se rellenan con import_data o con precompute_metrics.
    altitud_max = models.FloatField(default=0)
    altitud_min = models.FloatField(default=0)
    desnivel_negativo = models.FloatField(default=0)
    pendiente_max = models.FloatField(default=0)
    pendiente_media = models.FloatField(default=0)
    n_puertos = models.IntegerField(default=0)

    # Campos factuales enriquecidos (importados por el comando de importación).
    fecha = models.DateField(null=True, blank=True)
    localidad_inicio = models.CharField(max_length=200, blank=True, default='')
    localidad_fin = models.CharField(max_length=200, blank=True, default='')
    distancia_oficial = models.FloatField(null=True, blank=True)
    ganador = models.CharField(max_length=200, blank=True, default='')
    gc_leader = models.CharField(max_length=200, blank=True, default='')
    # JSON: [{position, rider, team, nationality, time, gap}, ...]
    resultados = models.TextField(blank=True, default='')

    def __str__(self):
        return f"{self.edicion.year} - Etapa {self.numero}: {self.nombre}"
