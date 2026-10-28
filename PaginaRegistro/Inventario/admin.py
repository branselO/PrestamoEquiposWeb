from django.contrib import admin
from .models import Dispositivo, Categoria

# Register your models here.

@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ('codigo_inventario', 'nombre', 'categoria', 'estado')
    list_filter = ('estado', 'categoria')
    search_fields = ('codigo_inventario', 'nombre')

class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nombre',)

admin.site.register(Categoria, CategoriaAdmin)
