# Rutas de la app: cada path conecta una URL con una vista de views.py.
from django.urls import path
from . import views

urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('charts/', views.dashboard_charts, name='dashboard_charts'),
    path('map-preview/', views.dashboard_map_preview, name='dashboard_map_preview'),
    path('mapa-general/', views.mapa_general, name='mapa_general'),
    path('mapa-general/etapas/', views.mapa_general, name='mapa_general_etapas'),
    path('mapa-general/provincias/', views.mapa_general, name='mapa_general_provincias'),
    path('edicion/<int:year>/', views.edicion_detalle, name='edicion_detalle'),
    path('etapa/<int:year>/<int:numero>/', views.etapa_detalle, name='etapa_detalle'),
    path('comparar/', views.comparar, name='comparar'),
    path('comparar/mapa-par/', views.mapa_par_tramos, name='mapa_par'),
    path('ayuda/', views.ayuda, name='ayuda'),
]
