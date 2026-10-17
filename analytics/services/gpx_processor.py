import gpxpy
import pandas as pd
import numpy as np
import os
from django.conf import settings
from geopy.distance import geodesic
from shapely.geometry import LineString
from shapely.wkt import loads
from django.core.cache import cache


def clasificar_etapa(distancia, desnivel):
    """Clasifica una etapa según distancia y desnivel positivo.

    Índice de dureza = desnivel / distancia (metros por kilómetro).
      - Recorridos cortos (< 45 km) -> Contrarreloj
      - factor < 10   -> Llana
      - factor < 18   -> Media montaña
      - factor < 25   -> Montaña
      - factor >= 25  -> Alta montaña
    """
    if distancia < 45:
        return 'Contrarreloj'
    factor = desnivel / distancia
    if factor < 10:
        return 'Llana'
    if factor < 18:
        return 'Media montaña'
    if factor < 25:
        return 'Montaña'
    return 'Alta montaña'


def metrics_from_perfil(perfil):
    """Métricas de terreno a partir de un perfil [[km, alt]].

    Es el equivalente sin GPX de GPXProcessor._extra_metrics: el perfil se
    interpola a una malla uniforme (~100 m) y se calculan la pendiente entre
    tramos, el desnivel negativo y las cotas máxima/mínima.
    """
    CERO = {
        'altitud_max': 0.0,
        'altitud_min': 0.0,
        'desnivel_negativo': 0.0,
        'pendiente_max': 0.0,
        'pendiente_media': 0.0,
        'n_puertos': 0,
    }
    pts = [p for p in (perfil or []) if p and len(p) >= 2]
    if len(pts) < 2:
        return dict(CERO)

    x = np.array([float(p[0]) for p in pts], dtype=np.float64)
    z = np.array([float(p[1]) for p in pts], dtype=np.float64)
    finitas = np.isfinite(z)
    if not finitas.any():
        return dict(CERO)
    z = np.interp(np.arange(len(z)), np.flatnonzero(finitas), z[finitas])

    if x[-1] <= x[0]:
        return dict(CERO)

    paso_km = 0.1
    n_pasos = max(1, int(round((x[-1] - x[0]) / paso_km)))
    xf = np.linspace(x[0], x[-1], n_pasos + 1)
    zf = np.interp(xf, x, z)

    grad = np.diff(zf) / np.diff(xf) / 1000.0 * 100.0   # pendiente por tramo (%)
    dz = np.diff(zf)

    climbs = []
    i = 0
    while i < n_pasos - 1:
        while i < n_pasos - 1 and zf[i + 1] <= zf[i] + 0.05:
            i += 1
        start = i
        gain = 0.0
        while i < n_pasos - 1 and zf[i + 1] > zf[i]:
            gain += zf[i + 1] - zf[i]
            i += 1
        d = (xf[i] - xf[start]) if i < n_pasos else (xf[-1] - xf[start])
        if gain >= 120 and d > 0.5:
            climbs.append({'km': float(d), 'gain': float(gain),
                           'grad': gain / (d * 1000) * 100})

    pend_media_puertos = 0.0
    if climbs:
        total_km = sum(c['km'] for c in climbs)
        if total_km > 0:
            pend_media_puertos = sum(c['grad'] * c['km'] for c in climbs) / total_km

    return {
        'altitud_max': float(zf.max()),
        'altitud_min': float(zf.min()),
        'desnivel_negativo': float(-dz[dz < 0].sum()),
        'pendiente_max': float(np.percentile(grad, 99)) if len(grad) else 0.0,
        'pendiente_media': float(pend_media_puertos),
        'n_puertos': len(climbs),
    }

class GPXProcessor:
    def __init__(self, file_path):
        self.file_path = file_path
        self.gpx = self._load_gpx()

    def _resolver_ruta(self):
        """Localiza el .gpx en disco.

        Orden de búsqueda:
          1. La ruta guardada en la BD (data/<año>/<fichero>.gpx), válida si se
             ejecuta desde la raíz del proyecto.
          2. DATA_PATH/<fichero> (ficheros sueltos directamente en data/).
          3. Cualquier subcarpeta de DATA_PATH; si hay varios con el mismo nombre
             se prefiere el que está en una carpeta con el mismo nombre (el año).
        """
        ruta_guardada = os.path.normpath(self.file_path)
        nombre_archivo = os.path.basename(ruta_guardada)
        carpeta_anyo = os.path.basename(os.path.dirname(ruta_guardada))

        for candidata in (ruta_guardada, os.path.join(settings.DATA_PATH, nombre_archivo)):
            if os.path.isfile(candidata):
                return candidata

        encontrados = []
        for raiz, _, ficheros in os.walk(settings.DATA_PATH):
            if nombre_archivo in ficheros:
                encontrados.append(os.path.join(raiz, nombre_archivo))
        for ruta in encontrados:
            if os.path.basename(os.path.dirname(ruta)) == carpeta_anyo:
                return ruta
        if encontrados:
            return encontrados[0]

        raise FileNotFoundError(
            f'No encuentro el GPX "{nombre_archivo}". Busqué en {ruta_guardada} y en '
            f'{settings.DATA_PATH} (incluidas sus subcarpetas).'
        )

    def _load_gpx(self):
        with open(self._resolver_ruta(), 'rb') as gpx_file:
            return gpxpy.parse(gpx_file.read().decode('utf-8'))

    def process(self):
        df = self._get_dataframe()
        df = self.calculate_metrics(df)
        line = LineString(zip(df.longitude, df.latitude))
        return {
            'df': df,
            'wkt': line.wkt,
            'distancia_total': df['dist_accumulated'].iloc[-1],
            'desnivel_positivo': df[df['elevation_diff'] > 0]['elevation_diff'].sum(),
            **self._extra_metrics(df),
        }

    def _extra_metrics(self, df):
        """Métricas adicionales del terreno para el detalle de etapa."""
        x = df['dist_accumulated'].values * 1000.0   # distancia acumulada en m
        z = df['elevation'].ffill().bfill().values   # altitud real, huecos rellenados

        # --- Pendientes robustas al ruido del GPS ---
        # Se agrega la altitud en tramos de distancia fija (bin_m) y se calcula
        # la pendiente entre tramos. Así los picos absurdos entre puntos
        # consecutivos del GPS (puentes, túneles, interferencias) no inflan
        # la "pendiente máxima".
        bin_m = 100.0
        max_m = x[-1] if len(x) else 0.0
        edges = np.arange(0.0, max_m + bin_m, bin_m)
        n_bins = max(1, len(edges) - 1)
        idx = np.clip(np.digitize(x, edges) - 1, 0, n_bins - 1)
        zz = np.empty(n_bins)
        for b in range(n_bins):
            zz[b] = z[idx == b].mean() if (idx == b).any() else np.nan
        grad = np.diff(zz) / bin_m * 100.0           # pendiente entre tramos en %
        grad = grad[~np.isnan(grad)]

        # Pendiente máxima: percentil 99 de las pendientes por tramo en vez del
        # máximo, para que un bin aislado ruidoso no marque el valor de la etapa.

        # Pendiente típica de los puertos: media ponderada por la longitud de
        # cada subida continua detectada (gradiente medio que afronta el ciclista).
        climbs = self._find_climbs(df)
        if climbs:
            total_km = sum(c['km'] for c in climbs)
            pend_media_puertos = sum(c['grad'] * c['km'] for c in climbs) / total_km
        else:
            pend_media_puertos = 0.0

        dz = df['elevation_diff'].values
        return {
            'altitud_max': float(z.max()),
            'altitud_min': float(z.min()),
            'desnivel_negativo': float(-df[dz < 0]['elevation_diff'].sum()),
            'pendiente_max': float(np.percentile(grad, 99)) if len(grad) else 0.0,
            'pendiente_media': float(pend_media_puertos),
            'n_puertos': len(climbs),
        }

    @staticmethod
    def _find_climbs(df, gain_min=120.0, dist_min=0.5):
        """Detecta subidas continuas (puertos) en el perfil.

        Recorre la serie de altitud suavizada y cuenta los tramos donde la
        altitud asciende de forma ininterrumpida, con un desnivel acumulado
        >= gain_min metros y cierta longitud mínima. Devuelve una lista de
        {km, gain, grad}.
        """
        x = df['dist_accumulated'].values
        z = df['elevation_smooth'].values
        n = len(x)
        climbs = []
        i = 0
        while i < n - 1:
            # Avanzar hasta que la altitud empiece a subir.
            while i < n - 1 and z[i + 1] <= z[i] + 0.05:
                i += 1
            start = i
            gain = 0.0
            while i < n - 1 and z[i + 1] > z[i]:
                gain += z[i + 1] - z[i]
                i += 1
            d = (x[i] - x[start]) if i < n else (x[-1] - x[start])
            if gain >= gain_min and d > dist_min:
                climbs.append({'km': float(d), 'gain': float(gain),
                               'grad': gain / (d * 1000) * 100})
        return climbs

    def _get_dataframe(self):
        data = []
        for track in self.gpx.tracks:
            for segment in track.segments:
                for point in segment.points:
                    data.append({
                        'latitude': point.latitude,
                        'longitude': point.longitude,
                        'elevation': point.elevation,
                    })
        return pd.DataFrame(data)

    def calculate_metrics(self, df):
        # Calculate distances
        distances = [0.0]
        for i in range(1, len(df)):
            dist = geodesic(
                (df.iloc[i-1]['latitude'], df.iloc[i-1]['longitude']),
                (df.iloc[i]['latitude'], df.iloc[i]['longitude'])
            ).kilometers
            distances.append(dist)
        df['dist_increment'] = distances
        df['dist_accumulated'] = df['dist_increment'].cumsum()
        
        # Elevation
        # La media móvil centrada deja NaN en los extremos (sin suficientes
        # vecinos). Se rellenan hacia delante y hacia atrás para que la serie
        # no tenga huecos: los NaN rompen el trazado del perfil en Plotly.
        df['elevation_smooth'] = (
            df['elevation'].rolling(window=5, center=True).mean().bfill().ffill()
        )
        df['elevation_diff'] = df['elevation_smooth'].diff().fillna(0)
        
        return df

    def spatial_join(self, gdf_ccaa):
        # Convert GPX to GeoDataFrame
        gdf_gpx = gpd.GeoDataFrame(
            geometry=gpd.points_from_xy(self._get_dataframe().longitude, self._get_dataframe().latitude),
            crs="EPSG:4326"
        )
        # Join with regions
        return gpd.sjoin(gdf_gpx, gdf_ccaa, how="inner", predicate="intersects")
