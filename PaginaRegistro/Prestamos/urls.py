from django.urls import path
from . import devolucion_views, registro_views, views

urlpatterns = [
    # Aquí van tus rutas de la app Prestamos
    path('Administrar_Prestamos/', views.adminPrestamoView.as_view(), name='prestamos'),
    path('Registrar_Prestamo/', registro_views.RegistrarPrestamoPaso1View.as_view(), name='registrar_prestamo'),
    path('Registrar_Prestamo/Dispositivos/', registro_views.RegistrarPrestamoPaso2View.as_view(), name='registrar_prestamo_paso2'),
    path('Registrar_Prestamo/Confirmar/', registro_views.RegistrarPrestamoPaso3View.as_view(), name='registrar_prestamo_paso3'),
    path('Registrar_Prestamo/Exito/<int:pk>/', registro_views.RegistrarPrestamoExitoView.as_view(), name='registrar_prestamo_exito'),
    path('Registrar_Devolucion/', devolucion_views.DevolucionLoginView.as_view(), name='devolucion_login'),
    path('Registrar_Devolucion/Pendientes/', devolucion_views.DevolucionPendientesView.as_view(), name='devolucion_pendientes'),
    path('Registrar_Devolucion/Salir/', devolucion_views.DevolucionSalirView.as_view(), name='devolucion_salir'),
    path('Registrar_Devolucion/<int:pk>/como-usuario/', devolucion_views.DevolverComoUsuarioView.as_view(), name='devolucion_como_usuario'),
    path('Registrar_Devolucion/<int:pk>/sin-usuario/', devolucion_views.DevolverSinUsuarioView.as_view(), name='devolucion_sin_usuario'),
    path('Registrar_Devolucion/<int:pk>/', views.RegistrarDevolucionView.as_view(), name='registrar_devolucion'),
    path('Agregar_Comentario/<int:pk>/', views.AgregarComentarioView.as_view(), name='agregar_comentario'),

    path('Administrar_Sanciones/', views.adminSancionView.as_view(), name='sanciones'),
    path('Registrar_Sancion/', views.RegistrarSancionView.as_view(), name='registrar_sancion'),
    path('Prestamo_Usuario/<int:pk>/', views.PrestamoUsuarioJsonView.as_view(), name='prestamo_usuario_json'),
    path('Modificar_Estado_Sancion/<int:pk>/', views.ModificarEstadoSancionView.as_view(), name='modificar_estado_sancion'),
]