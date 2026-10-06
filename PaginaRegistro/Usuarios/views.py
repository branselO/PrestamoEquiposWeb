from django.shortcuts import render, redirect
from django.urls import reverse_lazy, reverse
from django.views.generic import CreateView, TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import LoginView # FALTA IMPORTAR ESTO
from django.contrib.auth import login
from django.http import JsonResponse
import time

from .forms import StaffSignUpForm, NormalUserCreationForm, StaffAuthenticationForm
from .models import CustomUser
from . import hardware
from .hardware import verify_fingerprint_from_db, get_sensor, enroll_fingerprint_to_db

# ==========================================
# 1. VISTAS DE REGISTRO (Paso 1: Formulario)
# ==========================================

class SignUpView(CreateView):
    form_class = StaffSignUpForm
    template_name = 'Usuarios/register_Staff.html'
    # Eliminamos success_url porque lo manejaremos manualmente

    def form_valid(self, form):
        # ¡PIEZA FALTANTE! 
        # commit=False pausa el guardado en la base de datos, pero genera el hash de la contraseña
        user = form.save(commit=False) 
        
        # Guardamos los datos temporalmente en la sesión (incluyendo la contraseña ya encriptada)
        self.request.session['temp_user_data'] = {
            'email': user.email,
            'nombre': user.nombre,
            'apellidos': user.apellidos,
            'password': user.password, # Guardamos el Hash, NUNCA texto plano
            'is_staff': True # Bandera para saber que será staff
        }
        # Redirigimos al paso 2: la huella
        return redirect('registrar_huella')


class RegisterNormalUserView(UserPassesTestMixin, CreateView):
    form_class = NormalUserCreationForm
    template_name = 'Usuarios/register_Normal.html'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def form_valid(self, form):
        # ¡PIEZA FALTANTE! Hacemos lo mismo que arriba pero para usuarios normales
        user = form.save(commit=False)
        self.request.session['temp_user_data'] = {
            'email': user.email,
            'nombre': user.nombre,
            'apellidos': user.apellidos,
            'password': user.password,
            'is_staff': False # Bandera para saber que será normal
        }
        return redirect('registrar_huella')  # Esto podría cambiar a 'registrar_huella_Normal' si se crea una ruta separada para usuarios normales


# ==========================================
# 2. VISTA DE INICIO DE SESIÓN (Paso 1: Formulario)
# ==========================================

# ¡PIEZA FALTANTE CRÍTICA!
# Necesitamos interceptar el Login estándar de Django
class CustomLoginView(LoginView):
    template_name = 'Usuarios/login.html'
    authentication_form = StaffAuthenticationForm # Asegúrate de haber importado este formulario

    def form_valid(self, form):
        # Si el correo y contraseña son correctos, Django ejecuta esto.
        # En lugar de iniciar sesión de inmediato, guardamos su ID y pedimos la huella.
        user = form.get_user()
        self.request.session['pre_login_user_id'] = user.id
        return redirect('verificar_huella')


# ==========================================
# 3. VISTAS DE HARDWARE Y BIOMETRÍA (Paso 2)
# ==========================================

def api_estado_sensor(request):
    """Devuelve el texto actual del lector de huellas."""
    return JsonResponse({'mensaje': hardware.ESTADO_SENSOR})


def api_registrar_huella(request):
    if request.method == 'POST':
        temp_data = request.session.get('temp_user_data')
        
        if not temp_data:
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)

        uart = None # Inicializamos en caso de que get_sensor falle antes de asignarla
        
        try:
            # 1. Abrimos el puerto dinámico e inicializamos el hardware
            sensor, uart = get_sensor()
            
            # 2. Ejecutamos la lectura biométrica doble
            template_bytes = enroll_fingerprint_to_db(sensor) 
            
            if template_bytes:
                # 3. Instanciamos al usuario inyectando el password hasheado
                user = CustomUser(
                    email=temp_data['email'],
                    nombre=temp_data['nombre'],
                    apellidos=temp_data['apellidos'],
                    password=temp_data['password'], 
                    huella_template=template_bytes,
                    is_staff=temp_data['is_staff']
                )
                user.save() # Guardamos en la base de datos
                
                # Limpiamos la sesión
                del request.session['temp_user_data']
                
                return JsonResponse({'status': 'success', 'message': '¡Huella y usuario guardados exitosamente!'})
            else:
                return JsonResponse({'status': 'error', 'message': 'No se pudo leer la huella. Intente de nuevo.'}, status=400)
                
        except RuntimeError as e:
            # Atrapa los mensajes que programamos en hardware.py (Ej: "Las huellas no coinciden")
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            
        except Exception as e:
            # Atrapa cualquier otro error de Python
            return JsonResponse({'status': 'error', 'message': f'Error interno: {str(e)}'}, status=500)
            
        finally:
            # Liberamos el puerto del Arduino para que el 
            # siguiente usuario no reciba el error "Resource busy"
            if uart and uart.is_open:
                uart.close()

    # Manejo de la vista GET
    if request.method == 'GET':
        temp_data = request.session.get('temp_user_data', {})
        
        # Verificamos si existe la bandera is_staff en la sesión
        if 'is_staff' in temp_data:
            is_staff = temp_data['is_staff']
            if is_staff:
                return render(request, 'Usuarios/registro_huella_Staff.html')
            else:
                return render(request, 'Usuarios/registro_huella_Normal.html')
        else:
            # Fallback en caso de que intenten entrar directo por URL sin sesión
            return render(request, 'Usuarios/registro_huella_Staff.html')            
        

def api_login_huella(request):
    user_db_id = request.session.get('pre_login_user_id')
    
    if not user_db_id:
        if request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)
        return redirect('login')
        
    user = CustomUser.objects.get(id=user_db_id)
    
    if request.method == 'POST':
        uart = None  # Inicializamos la variable del puerto
        
        try:
            # 1. Abrimos el puerto y conectamos con el Arduino/Sensor
            sensor, uart = get_sensor()
            
            # 2. Descargamos los bytes de la base de datos e inyectamos al sensor
            match = verify_fingerprint_from_db(sensor, user.huella_template)
            
            if match:
                login(request, user) # Autenticamos en Django
                del request.session['pre_login_user_id'] 
                return JsonResponse({
                    'status': 'success', 
                    'message': '¡Identidad confirmada!',
                    'redirect_url': reverse('inicio')
                })
            else:
                return JsonResponse({'status': 'error', 'message': 'La huella no coincide.'}, status=401)
                
        except RuntimeError as e:
            # Atrapa errores como desconexiones físicas o fallos del sensor
            return JsonResponse({'status': 'error', 'message': str(e)}, status=500)
            
        except Exception as e:
            # Atrapa cualquier otro error de Python
            return JsonResponse({'status': 'error', 'message': f'Error interno: {str(e)}'}, status=500)
            
        finally:
            # Cerramos el puerto USB pase lo que pase
            # Esto evita el "[Errno 16] Resource busy" en el siguiente inicio de sesión
            if uart and uart.is_open:
                uart.close()
                
    return render(request, 'Usuarios/login_huella.html', {'usuario': user})


# ==========================================
# 4. OTRAS VISTAS DE NAVEGACIÓN
# ==========================================

class InicioView(UserPassesTestMixin, TemplateView):
    template_name = 'Usuarios/inicio.html'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

