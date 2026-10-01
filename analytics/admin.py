from django.contrib import admin
from .models import Edicion, Etapa


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
