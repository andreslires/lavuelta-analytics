from django.contrib import admin
from .models import Edicion, Etapa, Ciclista, Equipo, ResultadoEtapa


class ResultadoEtapaInline(admin.TabularInline):
    model = ResultadoEtapa
    extra = 1
    raw_id_fields = ('ciclista', 'equipo')


@admin.register(Edicion)
class EdicionAdmin(admin.ModelAdmin):
    list_display = ("year", "nombre")
    search_fields = ("nombre",)
    ordering = ("year",)


@admin.register(Etapa)
class EtapaAdmin(admin.ModelAdmin):
    list_display = ("edicion", "numero", "nombre", "tipo", "distancia", "desnivel")
    list_filter = ("edicion", "tipo")
    search_fields = ("nombre",)
    ordering = ("edicion__year", "numero")
    list_select_related = ("edicion",)
    inlines = [ResultadoEtapaInline]


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