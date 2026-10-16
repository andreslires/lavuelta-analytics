# La Vuelta Analytics

La idea de este proyecto es **visualizar y analizar la historia de La Vuelta a España** (2011–2026) de una manera clara, práctica y visual. En lugar de quedarme con tablas, quería crear una web donde pudiera ver el recorrido de cada edición, su perfil, su dureza y comparar distintas vueltas entre sí para entender cómo ha evolucionado la carrera.

Este repositorio es un **portafolio/demostración**: muestra la estructura, el código y el resultado visual.

## ¿Qué es esta web?

Es un dashboard hecho a medida para explorar las ediciones y etapas de La Vuelta. El objetivo ha sido combinar mapas, gráficas y métricas para que, con un par de clics, se pueda entender el carácter de cada etapa y de cada edición.

| Ruta | Qué muestra |
|---|---|
| `/` | **Dashboard** — visión global del histórico: kilómetros totales, desnivel acumulado, número de etapas y ediciones. Incluye gráficas interactivas (Plotly), mapa general con todas las etapas y mini-tarjetas por edición con el perfil resumido (sparklines). |
| `/edicion/<year>/` | **Detalle de edición** — KPIs de la temporada, tabla de etapas con su perfil resumido, gráficas de desnivel, distancia y tipología, top-5 de la clasificación general, maillots y el perfil completo de cada etapa. |
| `/etapa/<year>/<numero>/` | **Detalle de etapa** — mapa del recorrido (Folium) con el track dibujado, perfil altimétrico interactivo (Plotly), métricas de terreno (altitud máx/mín, desnivel negativo, pendiente máx/media, número de puertos), resultado de la etapa (ganador y podio). Con navegación entre etapas anterior/siguiente. |
| `/comparar/` | **Comparador cara a cara** — dos pestañas: *Ediciones* (compara dos años: KPIs, gráficas superpuestas, boxplot de desnivel, mapa comparativo y zonas por CCAA) y *Perfiles similares* (busca etapas con perfil altimétrico parecido y las compara lado a lado). |
| `/mapa-general/` | **Mapa general** — vista global de todas las etapas del histórico en un mapa oscuro, con pestaña adicional para ver el recorrido por provincias. |
| `/ayuda/` | Guía breve de uso de la web. |
| `/admin/` | Panel de administración de Django (para revisar o corregir datos puntuales). |

La navegación es sencilla: barra superior con accesos directos y un desplegable con todas las ediciones. Los mapas y gráficas se cargan con **HTMX** para evitar recargas completas de página.

## Tecnologías utilizadas

| Tecnología | Uso |
|---|---|
| [Django 5.2](https://www.djangoproject.com/) | Framework backend (vistas, modelos, gestión de datos y URLs). |
| [SQLite](https://www.sqlite.org/) | Base de datos ligera para guardar ediciones, etapas, métricas y perfiles. |
| [Plotly](https://plotly.com/python/) | Gráficas interactivas (perfiles altimétricos, comparativas, boxplots) generadas en servidor e incrustadas en HTML. |
| [Folium](https://python-visualization.github.io/folium/) | Mapas interactivos (Leaflet). Usa tiles oscuros (CartoDB Dark Matter) para mantener el estilo visual. |
| [GeoPandas](https://geopandas.org/) / [Shapely](https://shapely.readthedocs.io/) | Tratamiento de geometrías (tracks, buffers y solapes para detectar tramos comunes). |
| [pandas](https://pandas.pydata.org/) / [numpy](https://numpy.org/) | Procesamiento y cálculo de perfiles, pendientes y métricas de terreno. |
| [gpxpy](https://github.com/tkrajina/gpxpy) | Lectura y procesamiento de ficheros GPX oficiales. |
| [geopy](https://geopy.readthedocs.io/) | Cálculos de distancias geodésicas entre puntos. |
| [HTMX](https://htmx.org/) | Carga parcial de contenido (gráficas/mapas) sin recargar la página completa. |
| [CSS personalizado](https://developer.mozilla.org/es/docs/Web/CSS) | Tema oscuro hecho a medida, responsive y enfocado a lectura de datos. |
| [django-environ](https://django-environ.readthedocs.io/) | Gestión de variables de entorno (`.env`). |
| [Ruff](https://docs.astral.sh/ruff/) | Linting y formateado del código. |

## Ejecución local

> Para que la app funcione con datos reales hace falta la carpeta `data/` con los GPX/JSON y la base de datos poblada. Sin esos datos, la web se puede arrancar pero aparecerá vacía.

```bash
# 1. Crear entorno virtual e instalar dependencias
python -m venv venv
venv\Scripts\activate          # Windows

pip install -r requirements.txt

# 2. Copiar variables de entorno
copy .env.example .env

# 3. Ejecutar migraciones
python manage.py migrate

# 4. Crear superusuario (opcional, para /admin/)
python manage.py createsuperuser

# 5. Arrancar el servidor
python manage.py runserver 127.0.0.1:8123 --noreload
```

La app estará disponible en [http://127.0.0.1:8123/](http://127.0.0.1:8123/).

## Arquitectura

El proyecto sigue una arquitectura limpia y separada por responsabilidades (MVC + services):

```text
proyecto-lavuelta/
├── core/                        # Configuración global de Django
│   ├── settings.py              # Configuración (SQLite, caché en disco, django-environ)
│   ├── urls.py                  # Enrutado raíz → app analytics
│   ├── context_processors.py    # Inyecta todas las ediciones en los templates
│   ├── asgi.py                  # Configuración ASGI
│   └── wsgi.py                  # Configuración WSGI
│
├── analytics/                   # App principal
│   ├── models.py                # Modelos: Edicion, Etapa
│   ├── views.py                 # Vistas públicas (dashboard, edición, etapa, comparador, mapa...)
│   ├── urls.py                  # Rutas de la app
│   ├── admin.py                 # Registro en Django Admin
│   ├── tests.py                 # Tests básicos
│   │
│   ├── management/commands/          # Comandos personalizados de Django
│   │   ├── import_recorridos.py        # Importa datos desde data/recorridos/ (JSON)
│   │   ├── import_data.py              # Importa etapas desde GPX (data/<año>/)
│   │   ├── precompute_metrics.py       # Precalcula métricas de terreno
│   │   ├── precompute_perfiles.py      # Precalcula perfiles normalizados (comparador)
│   │   ├── backfill_perfil_real.py     # Rellena perfil_real desde GPX
│   │   ├── backfill_perfil_metrics.py  # Rellena métricas desde perfil_real
│   │   └── recalcular_pendientes.py    # Recalcula pendiente máxima (P99)
│   │
│   ├── migrations/               # Migraciones de la base de datos
│   │
│   ├── services/                # Lógica de negocio separada de las vistas
│   │   ├── charts.py             # Generación de gráficas Plotly (servidor)
│   │   ├── geografia.py          # Generación de mapas Folium (tramos, provincias, comparador)
│   │   ├── gpx_processor.py      # Procesamiento de GPX (perfil, métricas, detección de puertos)
│   │   ├── perfiles_similares.py # Lógica de similitud entre perfiles altimétricos
│   │   ├── sparkline.py          # Generación de SVG sparklines (perfiles miniatura)
│   │   └── __init__.py
│   │
│   ├── templates/analytics/      # Plantillas HTML
│   │   ├── base.html                    # Layout base (navbar, meta, CSS/JS)
│   │   ├── dashboard.html               # Dashboard principal
│   │   ├── edicion_detalle.html         # Detalle de edición
│   │   ├── etapa_detalle.html           # Detalle de etapa (layout)
│   │   ├── etapa_detalle_content.html   # Fragmento HTMX
│   │   ├── comparador.html              # Comparador cara a cara
│   │   ├── mapa_general.html            # Mapa general (etapas/provincias)
│   │   ├── ayuda.html                   # Página de ayuda
│   │   ├── _icons.html                  # Sprite SVG de iconos
│   │   ├── _perfiles_resultado.html     # Partial para perfiles similares
│   │   ├── _tipo_icono.html             # Icono por tipo de etapa
│   │   └── partials/
│   │       ├── charts.html              # Fragmento HTMX para gráficas
│   │       └── map_preview.html         # Fragmento HTMX para mapa preview
│   │
│   └── static/analytics/          # Archivos estáticos
│       ├── css/                   # Estilos CSS
│       ├── favicon.svg            # Favicon
│       └── vendor/plotly.min.js   # Plotly para gráficas interactivas
│
├── data/                        # Datos locales (GPX + JSON) - Nos se publica
├── cache/                       # Caché en disco (mapas, gráficas) - No se publica
├── db.sqlite3                   # Base de datos — NO se publica
├── .env.example                 # Plantilla de variables de entorno
├── manage.py                    # CLI de Django
├── requirements.txt             # Dependencias Python
└── README.md                    # Este documento
```

