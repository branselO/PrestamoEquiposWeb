import base64
import json
import zlib

from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.generic import CreateView, TemplateView
from django.contrib.auth.mixins import UserPassesTestMixin
from django.contrib.auth.views import LoginView
from django.contrib.auth import login
from django.http import JsonResponse

from .forms import EmailLoginForm, StaffSignUpForm, NormalUserCreationForm
from .models import CustomUser, EntidadAcademica, Programa
from .hardware import (
    TOMA_TOTAL,
    deserializar_template,
    comparar_minucias_fast,
    estado_sensor,
    fusionar_plantilla,
    minucias_desde_texto,
    serializar_template,
)
from .hardware.biometria_cache import IndiceBiometricoRAM
from django.shortcuts import get_object_or_404


def entidades_por_programa(request):
    if request.method != 'GET':
        return JsonResponse(
            {'error': 'Método no permitido.'},
            status=405,
        )

    program_id = request.GET.get('programa_id')
    if not program_id or not program_id.isdecimal():
        return JsonResponse(
            {'error': 'Selecciona un programa válido.'},
            status=400,
        )

    if not Programa.objects.filter(pk=program_id).exists():
        return JsonResponse(
            {'error': 'El programa seleccionado no existe.'},
            status=404,
        )

    entidades = EntidadAcademica.objects.filter(
        programas_impartidos__pk=program_id
    ).distinct().order_by('nombre').values('id', 'clave', 'nombre')
    return JsonResponse({'entidades': list(entidades)})


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

SESION_TOMAS = 'huella_tomas'


def _cuerpo_json(request):
    if not request.body:
        return {}
    try:
        datos = json.loads(request.body.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return datos if isinstance(datos, dict) else {}


def _tomas_guardadas(request):
    tomas = request.session.get(SESION_TOMAS) or []
    return list(tomas) if isinstance(tomas, list) else []


def _png_del_kiosco(texto):
    prefijo = 'data:image/png;base64,'
    if not isinstance(texto, str) or not texto.startswith(prefijo):
        return None
    try:
        png = base64.b64decode(texto[len(prefijo):], validate=True)
    except (ValueError, TypeError):
        return None
    if not png.startswith(b'\x89PNG'):
        return None
    return texto


def _guardar_usuario(temp_data, template_bytes):
    user = CustomUser(
        email=temp_data['email'],
        nombre=temp_data['nombre'],
        apellidos=temp_data['apellidos'],
        password=temp_data['password'],
        huella_template=template_bytes,
        is_staff=temp_data['is_staff'],
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
    IndiceBiometricoRAM.actualizar_usuario(user.pk, template_bytes)
    return user


# API PARA EL ESTADO DEL SENSOR Y REGISTRO DE HUELLAS
def api_estado_sensor(request):
    """Devuelve el texto actual del lector de huellas."""
    return JsonResponse({'mensaje': estado_sensor()})


# API PARA EL REGISTRO DE HUELLAS
def api_registrar_huella(request):
    if request.method == 'POST':
        temp_data = request.session.get('temp_user_data')

        if not temp_data:
            return JsonResponse({'status': 'error', 'message': 'Sesión caducada.'}, status=400)

        cuerpo = _cuerpo_json(request)
        if cuerpo.get('accion') == 'reiniciar':
            request.session[SESION_TOMAS] = []
            request.session.modified = True
            return JsonResponse({
                'status': 'reiniciado',
                'message': 'Empezamos de nuevo. Captura la toma 1.',
                'toma': 0,
                'total': TOMA_TOTAL,
                'completo': False,
            })

        if cuerpo.get('accion') != 'guardar':
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'La captura se hace en el lector de este kiosco.',
                    'toma': len(_tomas_guardadas(request)),
                    'total': TOMA_TOTAL,
                    'completo': False,
                },
                status=400,
            )

        tomas = _tomas_guardadas(request)
        if len(tomas) >= TOMA_TOTAL:
            tomas = []
        if tomas:
            try:
                deserializar_template(base64.b64decode(tomas[0]))
            except (ValueError, OSError, json.JSONDecodeError, zlib.error):
                request.session[SESION_TOMAS] = []
                request.session.modified = True
                return JsonResponse(
                    {
                        'status': 'error',
                        'message': 'Se perdieron las tomas anteriores. Empieza de nuevo.',
                        'toma': 0,
                        'total': TOMA_TOTAL,
                        'reiniciar': True,
                    },
                    status=400,
                )

        try:
            minucias = minucias_desde_texto(cuerpo.get('minucias'))
        except ValueError as error:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': str(error),
                    'toma': len(tomas),
                    'total': TOMA_TOTAL,
                    'completo': False,
                },
                status=400,
            )
        imagen = _png_del_kiosco(cuerpo.get('imagen'))
        if imagen is None:
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'La foto de la toma no llegó. Vuelve a capturar.',
                    'toma': len(tomas),
                    'total': TOMA_TOTAL,
                    'completo': False,
                },
                status=400,
            )

        numero = len(tomas) + 1
        tomas.append(base64.b64encode(serializar_template(minucias)).decode('ascii'))
        request.session[SESION_TOMAS] = tomas
        request.session.modified = True

        if numero < TOMA_TOTAL:
            return JsonResponse({
                'status': 'captura',
                'message': f'Toma {numero} lista. Revisa la foto y pulsa Continuar.',
                'imagen': imagen,
                'toma': numero,
                'total': TOMA_TOTAL,
                'completo': False,
            })

        plantilla = fusionar_plantilla(
            [deserializar_template(base64.b64decode(item)) for item in tomas]
        )
        if plantilla is None:
            request.session[SESION_TOMAS] = []
            request.session.modified = True
            return JsonResponse(
                {
                    'status': 'error',
                    'message': 'Las cuatro tomas no alcanzaron para una plantilla. Vuelve a registrar el centro del dedo.',
                    'imagen': imagen,
                    'toma': 0,
                    'total': TOMA_TOTAL,
                    'completo': False,
                    'reiniciar': True,
                },
                status=400,
            )

        template_bytes = serializar_template(plantilla)
        _guardar_usuario(temp_data, template_bytes)
        del request.session['temp_user_data']
        request.session[SESION_TOMAS] = []
        request.session.modified = True
        return JsonResponse({
            'status': 'success',
            'message': 'Huella y usuario guardados. Ya puedes entrar.',
            'imagen': imagen,
            'toma': numero,
            'total': TOMA_TOTAL,
            'completo': True,
        })

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

        if not user.huella_template:
            return JsonResponse(
                {'status': 'error', 'message': 'Esta cuenta no tiene huella. Entra con la contraseña o registra una.'},
                status=401,
            )

        try:
            minucias = minucias_desde_texto(request.POST.get('minucias', ''))
        except ValueError as error:
            return JsonResponse({'status': 'error', 'message': str(error)}, status=400)
        try:
            minucias_registradas = deserializar_template(bytes(user.huella_template))
        except (ValueError, OSError, json.JSONDecodeError, zlib.error):
            return JsonResponse(
                {'status': 'error', 'message': 'La huella guardada de esta cuenta no se pudo leer.'},
                status=500,
            )
        if comparar_minucias_fast(minucias, minucias_registradas) >= 0.30:
            login(request, user)
            request.session.pop('pre_login_user_id', None)
            return JsonResponse({
                'status': 'success',
                'message': f'Identidad confirmada, {user.nombre}. Entrando...',
                'redirect_url': reverse('inicio'),
            })
        return JsonResponse({
            'status': 'error',
            'message': 'La huella no coincide. Limpia el dedo y apóyalo otra vez en el centro.',
        }, status=401)
                
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
