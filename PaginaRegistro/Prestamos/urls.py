from django.urls import path
from . import views

urlpatterns = [
    # Aquí van tus rutas de la app Prestamos
    path('Administrar_Prestamos/', views.adminPrestamoView.as_view(), name='prestamos'),
    path('Registrar_Prestamo/', views.RegistrarPrestamoView.as_view(), name='registrar_prestamo'),
    path('Registrar_Devolucion/<int:pk>/', views.RegistrarDevolucionView.as_view(), name='registrar_devolucion'),
]