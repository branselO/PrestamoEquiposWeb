from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [

    # Rutas de Autenticación Principal
    path('', views.CustomLoginView.as_view(), name='login'), 
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    
    # Rutas de Registro de Usuarios
    path('register/', views.SignUpView.as_view(), name='register_Staff'),
    path('crear_usuario/', views.RegisterNormalUserView.as_view(), name='register_Normal'),
    path('api/entidades-por-programa/', views.entidades_por_programa, name='entidades_por_programa'),

    # Rutas de la API Biométrica (Hardware AS608)
    path('api/registrar_huella/', views.api_registrar_huella, name='registrar_huella'),
    path('api/estado_sensor/', views.api_estado_sensor, name='estado_sensor'),
    
    path('login/huella/', views.api_login_huella, name='verificar_huella'),

    # Rutas del Panel de Control
    path('inicio/', views.InicioView.as_view(), name='inicio'),
    path('inicio/admin_usuarios/', views.adminUsuariosView.as_view(), name='admin_usuarios'),

    path('perfil/<int:usuario_id>/', views.perfil_usuario, name='perfil_usuario'),
    path('perfil/<int:usuario_id>/enviar_correo/', views.enviar_correo_perfil_usuario, name='enviar_correo_perfil'),
    path('editar_usuario/<int:pk>/', views.UsuarioUpdateView.as_view(), name='editar_usuario'),
]