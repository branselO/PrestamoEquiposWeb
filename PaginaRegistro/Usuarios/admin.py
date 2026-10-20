from django.contrib import admin
from .models import CustomUser, StaffUser, NormalUser, EntidadAcademica, Programa


class BaseUserAdmin(admin.ModelAdmin):
    list_display = ('email', 'nombre', 'apellidos', 'numero_cuenta', 'is_staff')
    list_filter = ('is_staff', 'fecha_registro', 'programa')
    search_fields = ('email', 'numero_cuenta', 'nombre')
    readonly_fields = ('fecha_registro',)

    # Esta regla asegura que solo un Superusuario pueda ver esta sección en el menú
    def has_module_permission(self, request):
        return request.user.is_superuser

    # Esta regla asegura que nadie más pueda entrar ni siquiera con la URL directa
    def has_view_permission(self, request, obj=None):
        return request.user.is_superuser

# 2. Registramos el modelo virtual de Staff
@admin.register(StaffUser)
class StaffUserAdmin(BaseUserAdmin):
    def get_queryset(self, request):
        # Trae a todos los que son Staff, pero excluye a los Superusuarios
        return super().get_queryset(request).filter(is_staff=True, is_superuser=False)

# 3. Registramos el modelo virtual de Usuarios Normales
@admin.register(NormalUser)
class NormalUserAdmin(BaseUserAdmin):
    def get_queryset(self, request):
        # Trae a todos los que no son ni Staff ni Superusuarios
        return super().get_queryset(request).filter(is_staff=False, is_superuser=False)

# 4. (Opcional) Puedes registrar el modelo original si quieres una tabla maestra 
# que incluya a absolutamente todos, incluidos los Superusuarios.
@admin.register(CustomUser)
class MasterUserAdmin(BaseUserAdmin):
    def get_queryset(self, request):
        return super().get_queryset(request)

@admin.register(Programa)
class ProgramaAdmin(admin.ModelAdmin):
    list_display = ('clave', 'nombre')
    search_fields = ('clave', 'nombre')

    # ESTA LÍNEA CAMBIA TODA LA INTERFAZ:
    filter_horizontal = ('entidades_academicas',)

# 2. Registramos la Entidad Académica con la MAGIA de filter_horizontal
@admin.register(EntidadAcademica)
class EntidadAcademicaAdmin(admin.ModelAdmin):
    list_display = ('clave', 'nombre')
    search_fields = ('clave', 'nombre')
    
