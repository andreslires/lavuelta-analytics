# La Vuelta Analytics

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.2-092E20?style=flat&logo=django&logoColor=white)](https://www.djangoproject.com/)
[![Plotly](https://img.shields.io/badge/Plotly-Interactive-3F4F75?style=flat&logo=plotly&logoColor=white)](https://plotly.com/)
[![Folium](https://img.shields.io/badge/Folium-Leaflet-77B829?style=flat&logo=leaflet&logoColor=white)](https://python-visualization.github.io/folium/)
[![HTMX](https://img.shields.io/badge/HTMX-Dynamic_UI-3366CC?style=flat&logo=htmx&logoColor=white)](https://htmx.org/)

Plataforma analítica y geoespacial para **visualizar, procesar y comparar el histórico de La Vuelta a España (2011–2026)**. Transforma ficheros GPX brutos y clasificaciones en mapas interactivos, métricas avanzadas de terreno y herramientas de análisis comparativo.

> 🌐 **Demo online:** [https://andreslires.github.io/lavuelta-analytics-web/](https://andreslires.github.io/lavuelta-analytics-web/)  
> *Nota: Esta demo es una exportación a sitio estático alojada en GitHub Pages para explorar el diseño, los mapas y las vistas principales. Al no contar con un backend Python activo, las funciones que requieren cómputo en vivo (el comparador en sus 3 modalidades, los filtros dinámicos del dashboard con URL compartible y el panel de administración) no están disponibles en la versión web estática.*

---

## 💡 La idea detrás del proyecto

El ciclismo es un deporte con una cantidad tremenda de datos, pero casi siempre están atrapados en PDFs oficiales que caducan de un año para otro, tablas estáticas o rutómetros difíciles de consultar a posteriori. La idea de construir **La Vuelta Analytics** nació de una inquietud personal: quería una herramienta que resolviera de verdad las preguntas y debates típicos que siempre surgen viendo la carrera o hablando de ciclismo:

* **El mítico debate del reparto geográfico:** *"Es que La Vuelta siempre va a los mismos sitios"* o *"este año se han olvidado por completo de esta zona"*. En lugar de guiarnos por sensaciones, la web permite analizar la cobertura real: consultar las comunidades visitadas, las etapas que salieron fuera de España y, en el mapa de provincias, ver exactamente cuándo fue la última vez que la carrera pasó por un territorio concreto.
* **El recuerdo histórico y los tramos compartidos:** *"¿Cuándo fue la última vez que se subió por este puerto o se pasó por esta carretera?"*. Para esto desarrollé el detector de Zonas comunes: seleccionas una etapa de referencia y el sistema calcula intersecciones espaciales para encontrar qué otras etapas de la historia compartieron al menos 3 kilómetros continuos de asfalto con ella.
* **El clásico déjà vu de los perfiles:** *"Bua, juraría que hace unos años hubo una etapa clavadita a esta"*. Diseñé un comparador de perfiles altimétricos que permite buscar similitudes automáticas por correlación o enfrentar manualmente dos etapas cualesquiera para ver sus pendientes y métricas cara a cara.
* **El cara a cara entre ediciones:** *"La Vuelta de este año es mucho más dura que la del anterior"* o *"antes se metía más contrarreloj y menos finales en alto"*. El comparador enfrenta dos años al detalle: superpone sus gráficas de kilometraje y desnivel, analiza la distribución de dureza y dibuja el mapa conjunto de ambas ediciones.

Al final, el objetivo no era solo hacer una web con números, sino crear una plataforma donde cualquier aficionado que quiera recordar ediciones pasadas, un comentarista en plena retransmisión buscando contexto rápido, o un analista que necesite medir la exigencia real del trazado puedan resolver estas dudas en un par de clics. 

Para lograrlo, procesé los tracks oficiales en `.gpx` con Python, calculé las pendientes reales, identifiqué puertos y tramos de carretera con librerías SIG (GeoPandas/Shapely) y parametricé los perfiles para permitir comparaciones directas entre etapas separadas por más de una década.

---

## 🧭 Módulos y Navegación

| Ruta | Módulo | Descripción |
|---|---|---|
| `/` | **Dashboard Global** | Métricas acumuladas del histórico (km totales, desnivel, etapas y ediciones). Incluye mapa previo interactivo, métricas geográficas (comunidades y etapas internacionales), filtro dinámico de ediciones con URL compartible (`?years=...`) y tarjetas con *sparklines* altimétricos en SVG. |
| `/mapa-general/` | **Mapa General** | Visor completo con dos pestañas directas: `?tab=etapas` (todas las rutas históricas clicables con acceso a su perfil) y `?tab=provincias` (provincias atravesadas con detalle de la última etapa que pasó por cada una). |
| `/edicion/<year>/` | **Detalle de Edición** | KPIs de la temporada (dureza media, etapa más dura/larga/corta), clasificación general final, maillots oficiales, gráficas de desnivel/distancia/tipología y tarjetas individuales por etapa. |
| `/etapa/<year>/<numero>/` | **Detalle de Etapa** | Mapa interactivo del recorrido (Folium), altimetría dinámica (Plotly), métricas de terreno (altitud máx/mín, pendiente máxima P99, pendiente media de puertos, total de puertos), podio del día y navegación anterior/siguiente. |
| `/comparar/` *(Backend)* | **Comparador Multimodal** | Tres herramientas avanzadas:<br>• `?tab=ediciones`: Cara a cara entre dos años (KPIs, gráficas superpuestas, tipologías y mapa conjunto).<br>• `?tab=perfiles`: Búsqueda automática de etapas con perfil idéntico o enfrentamiento manual 1v1.<br>• `?tab=zonas`: Detección geoespacial de etapas que compartieron trazado (mínimo ~3 km continuos). |
| `/ayuda/` | **Guía de uso** | Documentación integrada en la aplicación con el funcionamiento de cada vista y glosario. |
| `/admin/` | **Administración** | Panel de control Django para mantenimiento y verificación de datos. |

---

## 🛠️ Tecnologías utilizadas

* **Backend:** [Django 5.2](https://www.djangoproject.com/) con arquitectura modular separada en modelos, vistas y servicios de dominio.
* **Interactividad frontend:** [HTMX](https://htmx.org/) para actualización dinámica de gráficas y mapas en servidor sin recargar la página.
* **Análisis geoespacial y GPX:** [GeoPandas](https://geopandas.org/), [Shapely](https://shapely.readthedocs.io/), [gpxpy](https://github.com/tkrajina/gpxpy) y [geopy](https://geopy.readthedocs.io/) para buffers de ruta, solapes de tramos e importación de tracks.
* **Ciencia de datos:** [pandas](https://pandas.pydata.org/) y [NumPy](https://numpy.org/) para cálculo de desniveles, normalización de altimetrías y limpieza de pendientes por percentiles.
* **Visualización:** [Plotly Python](https://plotly.com/python/) (gráficas interactivas incrustadas) y [Folium](https://python-visualization.github.io/folium/) con mapa base oscuro (*CartoDB Dark Matter*).
* **Calidad y configuración:** [django-environ](https://django-environ.readthedocs.io/) y [Ruff](https://docs.astral.sh/ruff/) para linting y formateo.

---

## 🚀 Puesta en marcha en local

> **Nota sobre los datos:** La aplicación requiere los archivos GPX/JSON de las etapas y la base de datos poblada para reflejar los recorridos reales. Por motivos de derechos sobre los tracks oficiales de carrera, la carpeta `data/` y la base de datos SQLite no forman parte del repositorio público.

```bash
# 1. Clonar el repositorio y acceder a la carpeta
git clone https://github.com/andreslires/lavuelta-analytics.git
cd lavuelta-analytics

# 2. Crear y activar entorno virtual
python -m venv venv

# En Windows:
venv\Scripts\activate
# En Linux/macOS:
source venv/bin/activate

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
copy .env.example .env    # En Linux/macOS: cp .env.example .env

# 5. Ejecutar migraciones
python manage.py migrate

# 6. Crear superusuario (opcional, para acceder a /admin/)
python manage.py createsuperuser

# 7. Iniciar el servidor de desarrollo
python manage.py runserver 127.0.0.1:8123 --noreload

```

La aplicación estará lista en [http://127.0.0.1:8123/](http://127.0.0.1:8123/).

---

## 🏗️ Arquitectura del proyecto

El código mantiene una estricta separación de responsabilidades, aislando los cálculos matemáticos y espaciales dentro de una capa de **servicios**:

```text
proyecto-lavuelta/
├── core/                         # Configuración Django (settings, urls, WSGI/ASGI, context processors)
├── analytics/                    # Aplicación analítica
│   ├── models.py                 # Modelos: Edicion, Etapa
│   ├── views.py                  # Controladores de vistas y respuestas HTMX
│   ├── services/                 # Lógica de negocio desacoplada de las vistas
│   │   ├── charts.py             # Renderizado de figuras Plotly (perfiles y comparativas)
│   │   ├── geografia.py          # Renderizado de mapas Folium y cálculo de tramos/zonas
│   │   ├── gpx_processor.py      # Parseo GPX, cálculo de pendientes (P99) y detección de puertos
│   │   ├── perfiles_similares.py # Algoritmo de correlación altimétrica entre etapas
│   │   └── sparkline.py          # Generador de perfiles SVG en miniatura
│   ├── management/commands/      # Comandos de importación, backfill y precomputación
│   ├── templates/analytics/      # Templates HTML y partials HTMX
│   └── static/analytics/         # CSS a medida (tema oscuro) y scripts vendor
├── requirements.txt              # Dependencias de Python
└── manage.py                     # CLI de Django

```
