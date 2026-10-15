from django.urls import path
from . import views

urlpatterns = [
    # Aquí van tus rutas de la app Prestamos
    path('Administrar_Prestamos/', views.adminPrestamoView.as_view(), name='prestamos'),
    path('Registrar_Prestamo/', views.RegistrarPrestamoView.as_view(), name='registrar_prestamo'),
    path('Registrar_Devolucion/<int:pk>/', views.RegistrarDevolucionView.as_view(), name='registrar_devolucion'),
    path('Agregar_Comentario/<int:pk>/', views.AgregarComentarioView.as_view(), name='agregar_comentario'),

    path('Administrar_Sanciones/', views.adminSancionView.as_view(), name='sanciones'),
    path('Registrar_Sancion/', views.RegistrarSancionView.as_view(), name='registrar_sancion'),
    path('Prestamo_Usuario/<int:pk>/', views.PrestamoUsuarioJsonView.as_view(), name='prestamo_usuario_json'),
    path('Modificar_Estado_Sancion/<int:pk>/', views.ModificarEstadoSancionView.as_view(), name='modificar_estado_sancion'),
]