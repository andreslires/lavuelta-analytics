# La Vuelta Analytics

Dashboard web interativo para analizar datos históricos de La Vuelta a España (2011–2026). Construido con Django 5.2 y SQLite.

> **Este repositorio es un portafolio/demostración**: se publica para mostrar el
> código, la estructura y el resultado visual. Los datos en bruto (`data/`,
> GPX y JSON), la base de datos SQLite y las variables de entorno son locales
> y **no se publican** (ver `.gitignore`). Para ver la app real funcionando,
> consulta la sección *Ejecución local*.

---

## Ejecución local

> Aviso: para que la app funcione con datos reales hace falta la pipeline de
> datos local (`data/` + BD poblada con `import_recorridos`), que no está en
> el repo. Sin ella, el resto se puede arrancar pero con datos vacíos.

```bash
# 1. Crear entorno virtual e instalar dependencias
python -m venv venv
venv\Scripts\activate          # Windows
pip install -r requirements.txt

# 2. Configurar variables de entorno (copia .env.example a .env)

# 3. Ejecutar migraciones
python manage.py migrate

# 4. Crear superusuario (opcional, para /admin/)
python manage.py createsuperuser

# 5. Arrancar el servidor
python manage.py runserver 127.0.0.1:8123 --noreload
```

La app se abre en `http://127.0.0.1:8123/`.

---

## Qué hay dentro

### Para el usuario (lo que ve en el navegador)

| Ruta | Qué es |
|---|---|
| `/` | **Dashboard** — métricas globales (km totales, desnivel, etapas, ediciones), gráficas interactivas (Plotly), mapa general de todas las etapas, mini-tarjetas por edición con sparklines de desnivel. |
| `/edicion/<year>/` | **Detalle de edición** — KPIs de la edición, tabla de etapas con sparklines, gráficas de desnivel/distancia/tipos, top-5 del GC y maillots, perfil de cada etapa. |
| `/etapa/<year>/<numero>/` | **Detalle de etapa** — mapa con track (Folium, tiles oscuros), perfil altimétrico (Plotly), métricas de terreno (altitud máx/mín, desnivel negativo, pendiente máx/media, nº puertos), resultado de la etapa (ganador, top-3). Navegación prev/next. |
| `/comparar/` | **Comparador** — dos pestañas: "Ediciones" (compara dos años: KPIs, gráficas superpuestas, boxplot, mapa comparativo, comunidades autónomas) y "Perfiles similares" (busca etapas con perfil altimétrico parecido, las compara lado a lado). |
| `/mapa-general/` | **Mapa general** — todas las etapas de todas las ediciones en un mapa oscuro, más mapa por provincias. |
| `/admin/` | Panel de administración Django (requiere superusuario). |

**Navegación:** barra superior con enlaces directos + menú desplegable "Ediciones" con todas las temporadas. Los mapas y gráficas se cargan vía HTMX (sin recarga completa de página).

### Para el administrador (cómo se gestiona la BD)

#### Fuente de datos

Los datos de partida están en `data/` (JSON descargados externamente y GPX de etapas).
La carpeta `data/` **no se publica en el repo** (ver `.gitignore`): es solo local y necesaria
para que etapas y comparadores pinten mapas/perfiles. Sin ella, el resto de la web funciona.

```
data/
├── recorridos/
│   ├── routes.json            # Todas las etapas por año (origen, destino, ganador, km)
│   ├── editions/              # GC final y maillots de cada edición
│   │   ├── vuelta-a-espana-2011.json
│   │   └── ...
│   └── stages/                # Detalle por etapa (fecha, perfil, track, resultado)
│       ├── vuelta-a-espana-2011-1.json
│       └── ...
└── 2022..2026/                # GPX por etapa (stage-N-parcours.gpx)
```

Los ficheros JSON y GPX se generan con una herramienta de descarga externa
(`downloader.py`, fuera de este repo).

> **Datos y marcas**: este proyecto es un ejercicio de análisis y visualización.
> "La Vuelta" es una marca registrada de Unipublic/ASO y los datos de los
> recorridos pertenecen a sus propietarios. No afiliado ni patrocinado por ellos.

#### Comandos de gestión

```bash
# Importar/actualizar datos desde data/recorridos/
python manage.py import_recorridos                    # todo 2011-2026
python manage.py import_recorridos --years 2025,2026  # solo esos años
python manage.py import_recorridos --create-only      # solo crear faltantes

# Precalcular métricas GPX (altitud, pendientes, puertos) para etapas con archivo .gpx
python manage.py precompute_metrics

# Precalcular perfil normalizado (para comparación de perfiles similares)
python manage.py precompute_perfiles

# Rellenar perfil_real de etapas con GPX (para sparklines y gráficas)
python manage.py backfill_perfil_real

# Rellenar métricas de terreno de etapas sin GPX (desde perfil_real)
python manage.py backfill_perfil_metrics

# Recalcular pendiente_max con métrica robusta P99 en todas las etapas
python manage.py recalcular_pendientes

# Backfill manual de resultados 2026 (ya ejecutado, no repetir)
python manage.py backfill_resultados_2026
```

**Orden típico tras importar datos nuevos:**

```bash
python manage.py import_recorridos
python manage.py precompute_perfiles
python manage.py precompute_metrics
python manage.py backfill_perfil_real
python manage.py backfill_perfil_metrics
python manage.py recalcular_pendientes
```

#### Admin Django (`/admin/`)

- **Edición** — año, nombre, fechas, ganador, GC (JSON), maillots (JSON).
- **Etapa** — edición, número, nombre, tipo, distancia, desnivel, track (WKT), ruta al GPX, perfil, métricas precalculadas, fecha, localidades, ganador, GC líder, resultados.

---

## Arquitectura

```
proyecto-lavuelta/
├── core/                       # Configuración Django
│   ├── settings.py             # Settings (SQLite, cache en disco, django-environ)
│   ├── urls.py                 # Enrutamiento raíz → analytics
│   └── context_processors.py   # Inyecta all_ediciones en todos los templates
│
├── analytics/                  # App principal
│   ├── models.py               # Edicion, Etapa
│   ├── views.py                # 7 vistas públicas (665 líneas)
│   ├── urls.py                 # Rutas → vistas
│   ├── admin.py                # Registro en Django admin
│   │
│   ├── services/               # Lógica de negocio separada
│   │   ├── gpx_processor.py    # Procesamiento GPX (perfil, métricas, P99)
│   │   ├── charts.py           # Gráficas Plotly (colores, layout, chart_geo)
│   │   ├── geografia.py        # Mapas Folium (tiles oscuros, comunidades, provincias)
│   │   ├── perfiles_similares.py  # Comparación de perfiles (similitud, métricas)
│   │   └── sparkline.py        # SVG mini-sparklines de desnivel
│   │
│   ├── management/commands/    # Comandos de gestión
│   │   ├── import_recorridos.py
│   │   ├── precompute_metrics.py
│   │   ├── precompute_perfiles.py
│   │   ├── backfill_perfil_real.py
│   │   ├── backfill_perfil_metrics.py
│   │   ├── backfill_resultados_2026.py
│   │   ├── recalcular_pendientes.py
│   │   └── import_data.py      # Legado (sin uso)
│   │
│   ├── templates/analytics/    # Templates Django
│   │   ├── base.html           # Layout base (navbar, HTMX, Plotly)
│   │   ├── dashboard.html      # Dashboard principal
│   │   ├── edicion_detalle.html
│   │   ├── etapa_detalle.html / etapa_detalle_content.html (HTMX)
│   │   ├── comparador.html
│   │   ├── mapa_general.html
│   │   └── partials/           # Fragmentos HTMX (charts, map_preview)
│   │
│   └── static/analytics/       # CSS, JS, imágenes
│       ├── css/                # base.css, components.css, dashboard.css, ...
│       └── vendor/             # plotly.min.js
│
├── data/recorridos/            # JSON fuente (vendored, no en repo)
├── db.sqlite3                  # Base de datos
├── cache/                      # Caché en disco (mapas, gráficas)
├── .env                        # Variables de entorno
├── pyproject.toml              # Configuración ruff (linting)
└── requirements.txt            # Dependencias Python
```

### Modelos

**Edicion** — una temporada de La Vuelta:
- `year`, `nombre`, `gender`, `fecha_inicio`, `fecha_fin`
- `ganador` — nombre del ganador final
- `gc_json` — clasificación general completa (JSON lista)
- `maillots_json` — maillots finales (JSON objeto: points, kom, youth)

**Etapa** — una etapa concreta:
- `edicion` (FK → Edicion), `numero`, `nombre`, `tipo`, `distancia`, `desnivel`
- `track_wkt` — geometría de la ruta en WKT (LINESTRING)
- `file_path` — ruta al archivo .gpx original (2022–2026) o `None` (2011–2021)
- `perfil` — perfil normalizado 441 muestras en [0,1] (para comparación)
- `perfil_real` — perfil real en km (JSON [[km, alt], ...]) (para gráficas)
- Métricas precalculadas: `altitud_max`, `altitud_min`, `desnivel_negativo`, `pendiente_max`, `pendiente_media`, `n_puertos`
- Datos factuales: `fecha`, `localidad_inicio`, `localidad_fin`, `distancia_oficial`, `ganador`, `gc_leader`, `resultados`

### Cómo se generan las gráficas y mapas

- **Gráficas:** Plotly generadas en servidor (`go.Figure` → `fig.to_html()`), incrustadas como HTML. El JS de Plotly se carga una sola vez en `base.html`.
- **Mapas:** Folium con tiles oscuros (CartoDB dark_matter), generados en servidor (`mapa._repr_html_()`). Los mapas grandes (mapa general) se cachean en disco.
- **Sparklines:** SVG de desnivel generados en servidor (`sparkline.py`).
- **HTMX:** Algunas secciones (gráficas del dashboard, preview del mapa) se cargan sin recarga de página.

### Caché

Caché en disco (`cache/`) con `timeout=None` (eterna). Se limpia manualmente con `python manage.py shell` → `from django.core.cache import cache; cache.clear()`.

Cachéados: mapa general, mapa de provincias, gráficas del dashboard, gráficas por edición, mapa comparativo, datos GPX procesados.

---

## Stack técnico

- **Backend:** Django 5.2, Python 3.10+
- **Base de datos:** SQLite (file-based, `db.sqlite3`)
- **Gráficas:** Plotly (generadas en servidor)
- **Mapas:** Folium (Leaflet) con tiles CartoDB dark_matter
- **Procesamiento geoespacial:** GeoPandas, Shapely, Geopy
- **GPX:** gpxpy
- **Datos:** pandas, numpy
- **Frontend:** HTMX 1.9, CSS custom (dark theme)
- **Configuración:** django-environ (`.env`)
- **Linting:** ruff (ver `pyproject.toml`)

---

## Desarrollo

```bash
# Linting
ruff check .
ruff format --check .

# El servidor se arranca con --noreload para que los mapas cacheados
# no se regeneren en cada cambio de archivo:
python manage.py runserver 127.0.0.1:8123 --noreload
```
