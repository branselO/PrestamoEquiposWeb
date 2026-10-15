from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic import CreateView, TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import login
from django.http import JsonResponse

from .forms import EmailLoginForm, StaffSignUpForm, NormalUserCreationForm
from .models import CustomUser, EntidadAcademica, Programa
from . import hardware
from .hardware import verify_fingerprint_from_db, get_sensor, enroll_fingerprint_to_db
from django.shortcuts import get_object_or_404


def programas_por_entidad(request):
    if request.method != 'GET':
        return JsonResponse(
            {'error': 'Método no permitido.'},
            status=405,
        )

    entity_id = request.GET.get('entidad_id')
    if not entity_id or not entity_id.isdecimal():
        return JsonResponse(
            {'error': 'Selecciona una entidad académica válida.'},
            status=400,
        )

    if not EntidadAcademica.objects.filter(pk=entity_id).exists():
        return JsonResponse(
            {'error': 'La entidad académica seleccionada no existe.'},
            status=404,
        )

    programas = Programa.objects.filter(
        entidades__pk=entity_id
    ).distinct().order_by('nombre').values('id', 'clave', 'nombre')
    return JsonResponse({'programas': list(programas)})


def _get_registration_session_data(form, is_staff):
    user = form.save(commit=False)
    data = {
        'email': user.email,
        'nombre': user.nombre,
        'apellidos': user.apellidos,
        'password': user.password,
        'is_staff': is_staff,
    }

    for field_name in form.Meta.fields:
        if field_name in {'email', 'nombre', 'apellidos'}:
            continue

        model_field = CustomUser._meta.get_field(field_name)
        if model_field.is_relation:
            data[f'{field_name}_id'] = getattr(user, f'{field_name}_id')
        else:
            data[field_name] = getattr(user, field_name)

    return data


# 1. VISTAS DE REGISTRO 

# VIEW PARA EL REGISTRO DE STAFF
class SignUpView(CreateView):
    form_class = StaffSignUpForm
    template_name = 'Usuarios/register_Staff.html'

    def form_valid(self, form):
        self.request.session['temp_user_data'] = _get_registration_session_data(
            form,
            is_staff=True,
        )
        return redirect('registrar_huella')

# VIEW PARA EL REGISTRO DE USUARIOS NORMALES
class RegisterNormalUserView(UserPassesTestMixin, CreateView):
    form_class = NormalUserCreationForm
    template_name = 'Usuarios/register_Normal.html'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

    def form_valid(self, form):
        self.request.session['temp_user_data'] = _get_registration_session_data(
            form,
            is_staff=False,
        )
        return redirect('registrar_huella')  


# 2. VISTA DE INICIO DE SESIÓN 

class CustomLoginView(LoginView):
    template_name = 'Usuarios/login.html'
    authentication_form = EmailLoginForm

    def form_valid(self, form):
        user = CustomUser.objects.filter(
            email=form.cleaned_data['email'],
            is_active=True,
            is_staff=True,
        ).first()
        if user is None:
            form.add_error(None, 'No se pudo iniciar sesión con ese correo.')
            return self.form_invalid(form)

        self.request.session['pre_login_user_id'] = user.id
        return redirect('verificar_huella')


# 3. VISTAS DE HARDWARE Y BIOMETRÍA 

# API PARA EL ESTADO DEL SENSOR Y REGISTRO DE HUELLAS
def api_estado_sensor(request):
    """Devuelve el texto actual del lector de huellas."""
    return JsonResponse({'mensaje': hardware.ESTADO_SENSOR})

# API PARA EL REGISTRO DE HUELLAS
def api_registrar_huella(request):
    if request.method == 'POST':
        temp_data = request.session.get('temp_user_data')
        
        if not temp_data:
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)

        uart = None # Inicializamos en caso de que get_sensor falle antes de asignarla
        
        try:
            # 1. Abrimos el puerto dinámico e inicializamos el hardware
            #sensor, uart = get_sensor()
            
            # 2. Ejecutamos la lectura biométrica doble
            #template_bytes = enroll_fingerprint_to_db(sensor) 

            template_bytes = b'simulacion_huella'  # Simulación de la plantilla de huella en bytes
            
            if template_bytes:
                user = CustomUser(
                    email=temp_data['email'],
                    nombre=temp_data['nombre'],
                    apellidos=temp_data['apellidos'],
                    password=temp_data['password'], 
                    huella_template=template_bytes,
                    is_staff=temp_data['is_staff']
                )
                for field_name, value in temp_data.items():
                    if field_name not in {
                        'email',
                        'nombre',
                        'apellidos',
                        'password',
                        'is_staff',
                    }:
                        setattr(user, field_name, value)

                user.save()
                
                del request.session['temp_user_data']
                
                return JsonResponse({'status': 'success', 'message': '¡Huella y usuario guardados exitosamente!'})
            else:
                return JsonResponse({'status': 'error', 'message': 'No se pudo leer la huella. Intente de nuevo.'}, status=400)
                
        except RuntimeError as e:
            return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
            
        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Error interno: {str(e)}'}, status=500)
            
        finally:
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
        
# API PARA EL LOGIN CON HUELLA
def api_login_huella(request):
    user_db_id = request.session.get('pre_login_user_id')
    
    if not user_db_id:
        if request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)
        return redirect('login')
        
    user = CustomUser.objects.filter(
        id=user_db_id,
        is_active=True,
        is_staff=True,
    ).first()
    if user is None:
        request.session.pop('pre_login_user_id', None)
        if request.method == 'POST':
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)
        return redirect('login')
    
    if request.method == 'POST':
        if request.POST.get('auth_method') == 'password':
            password = request.POST.get('password', '')
            if not password or not user.check_password(password):
                return JsonResponse(
                    {'status': 'error', 'message': 'La contraseña no es correcta.'},
                    status=401,
                )

            login(request, user)
            request.session.pop('pre_login_user_id', None)
            return JsonResponse({
                'status': 'success',
                'message': '¡Identidad confirmada!',
                'redirect_url': reverse('inicio'),
            })

        uart = None  # Inicializamos la variable del puerto
        
        try:
            # 1. Abrimos el puerto y conectamos con el Arduino/Sensor
            sensor, uart = get_sensor()
            
            # 2. Descargamos los bytes de la base de datos e inyectamos al sensor
            match = verify_fingerprint_from_db(sensor, user.huella_template)
            
            if match:
                login(request, user) # Autenticamos en Django
                request.session.pop('pre_login_user_id', None)
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

# 4.  VISTAS DEL PANEL DE CONTROL

class InicioView(UserPassesTestMixin, TemplateView):
    template_name = 'Usuarios/inicio.html'

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

class adminUsuariosView(UserPassesTestMixin, TemplateView):
    template_name = 'Usuarios/admin_usuarios.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        nombre = self.request.GET.get('nombre', '').strip() 
        email = self.request.GET.get('email', '').strip() 

        if nombre or email:
            usuario = CustomUser.objects.filter(nombre__icontains=nombre, email__icontains=email)
        else:
            usuario = CustomUser.objects.all()
        context['usuarios_normales'] = usuario.filter(is_staff=False)
        context['usuarios_staff'] = usuario.filter(is_staff=True, is_superuser=False)
        return context

    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff

def perfil_usuario(request, usuario_id):
    # Buscamos al usuario en la BD
    usuario = get_object_or_404(CustomUser, id=usuario_id)
    return render(request, 'Usuarios/ver_perfil.html', {'perfil': usuario})
