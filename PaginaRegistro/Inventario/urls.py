from django.urls import path
from . import views

urlpatterns = [
    path('Administrar_Inventario/', views.adminInventarioView.as_view(), name='inventario'),
    path('Dispositivos/Nuevo/', views.DispositivoCreateView.as_view(), name='dispositivo_nuevo'),
    path('Dispositivos/<int:pk>/Editar/', views.DispositivoUpdateView.as_view(), name='dispositivo_editar'),
    path('Categorias/Nueva/', views.CategoriaCreateView.as_view(), name='categoria_nueva'),
]
