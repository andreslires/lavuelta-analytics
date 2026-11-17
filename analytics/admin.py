from django.contrib import admin
from .models import (
    Ciclista,
    ClasificacionGeneral,
    Edicion,
    Equipo,
    Etapa,
    ResultadoEquipoEtapa,
    ResultadoEtapa,
)


class ResultadoEtapaInline(admin.TabularInline):
    model = ResultadoEtapa
    extra = 1
    raw_id_fields = ('ciclista', 'equipo')


class ResultadoEquipoEtapaInline(admin.TabularInline):
    model = ResultadoEquipoEtapa
    extra = 0
    raw_id_fields = ('equipo',)
    ordering = ('posicion',)


class ClasificacionGeneralInline(admin.TabularInline):
    model = ClasificacionGeneral
    extra = 0
    raw_id_fields = ('ciclista', 'equipo')
    ordering = ('posicion',)


@admin.register(Edicion)
class EdicionAdmin(admin.ModelAdmin):
    list_display = ("year", "nombre", "ganador")
    search_fields = ("nombre", "ganador")
    ordering = ("year",)
    inlines = [ClasificacionGeneralInline]


@admin.register(Etapa)
class EtapaAdmin(admin.ModelAdmin):
    list_display = ("edicion", "numero", "nombre", "tipo", "es_cre", "distancia", "desnivel")
    list_filter = ("edicion", "tipo", "es_cre")
    search_fields = ("nombre",)
    ordering = ("edicion__year", "numero")
    list_select_related = ("edicion",)
    inlines = [ResultadoEtapaInline, ResultadoEquipoEtapaInline]


@admin.register(Ciclista)
class CiclistaAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    search_fields = ("nombre",)


@admin.register(ResultadoEtapa)
class ResultadoEtapaAdmin(admin.ModelAdmin):
    list_display = ("etapa", "ciclista", "posicion")
    list_filter = ("etapa__edicion",)
    search_fields = ("ciclista__nombre", "etapa__nombre")
    raw_id_fields = ("etapa", "ciclista", "equipo")


@admin.register(ClasificacionGeneral)
class ClasificacionGeneralAdmin(admin.ModelAdmin):
    list_display = ("edicion", "posicion", "ciclista", "equipo", "tiempo", "diferencia")
    list_filter = ("edicion",)
    search_fields = ("ciclista__nombre", "equipo__nombre")
    raw_id_fields = ("edicion", "ciclista", "equipo")
    ordering = ("edicion__year", "posicion")

@admin.register(ResultadoEquipoEtapa)
class ResultadoEquipoEtapaAdmin(admin.ModelAdmin):
    list_display = ("etapa", "posicion", "equipo", "tiempo", "diferencia")
    list_filter = ("etapa__edicion",)
    search_fields = ("equipo__nombre",)
    raw_id_fields = ("etapa", "equipo")
