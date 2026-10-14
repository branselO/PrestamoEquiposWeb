from django.contrib import admin
from .models import Sancion, Prestamo, DetallePrestamo

class SancionAdmin(admin.ModelAdmin):
    list_display = ('id', 'prestamo', 'usuario', 'tipo_sancion', 'estado', 'fecha_reporte')
    search_fields = ('prestamo__id', 'usuario__email', 'tipo_sancion', 'estado')
    list_filter = ('tipo_sancion', 'estado', 'fecha_reporte')
# Register your models here.


# Esto permite agregar equipos directamente dentro de la pantalla del Préstamo
class DetallePrestamoInline(admin.TabularInline):
    model = DetallePrestamo
    extra = 1 # Muestra 1 fila vacía por defecto para agregar equipos
    autocomplete_fields = ['dispositivo'] # Opcional: Hace que buscar dispositivos sea un buscador con lupa

@admin.register(Prestamo)
class PrestamoAdmin(admin.ModelAdmin):
    list_display = ('id', 'usuario_solicita', 'staff_autoriza', 'fecha_salida', 'fecha_devolucion_esperada', 'estado_ticket')
    
    # Inyectamos el Inline aquí
    inlines = [DetallePrestamoInline]


admin.site.register(Sancion, SancionAdmin)

