from django.urls import path
from django.contrib.auth.views import LogoutView
from . import views

urlpatterns = [

    # 1. Rutas de Autenticación Principal
    path('login/', views.CustomLoginView.as_view(), name='login'), 
    path('logout/', LogoutView.as_view(next_page='login'), name='logout'),
    
    # 2. Rutas de Registro de Usuarios
    path('register/', views.SignUpView.as_view(), name='register_Staff'),
    path('crear_usuario/', views.RegisterNormalUserView.as_view(), name='register_Normal'),
    path(
        'api/entidades-por-programa/',
        views.entidades_por_programa,
        name='entidades_por_programa',
    ),

    # 3. Rutas de la API Biométrica (Hardware AS608)
    path('api/registrar_huella/', views.api_registrar_huella, name='registrar_huella'),
    path('api/estado_sensor/', views.api_estado_sensor, name='estado_sensor'),
    
    path('login/huella/', views.api_login_huella, name='verificar_huella'),

    ###### Rutas del Panel de Control ######
    path('inicio/', views.InicioView.as_view(), name='inicio'),
    path('inicio/admin_usuarios/', views.adminUsuariosView.as_view(), name='admin_usuarios'),

    path('perfil/<int:usuario_id>/', views.perfil_usuario, name='perfil_usuario'),
    
]