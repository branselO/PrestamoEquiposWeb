"""Flujo secuencial de 3 pasos para registrar un préstamo.

Paso 1: autenticar al solicitante (contraseña o huella).
Paso 2: seleccionar dispositivos.
Paso 3: fecha de devolución y confirmación (creación transaccional).
"""
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.generic import TemplateView

from Inventario.models import Categoria, Dispositivo
from Usuarios.hardware.biometria_cache import IndiceBiometricoRAM
from Usuarios.hardware import (
    apagar_led_sensor,
    capturar_minucias_en_vivo,
    get_sensor,
    publicar_estado,
)
from .correos import confirmar_prestamo
from .models import DetallePrestamo, Prestamo
from .views import StaffRequiredMixin

SESSION_KEY = 'registro_prestamo'


def _wizard(request):
    return request.session.get(SESSION_KEY) or {}


def _reset(request):
    request.session.pop(SESSION_KEY, None)


def quiere_json(request):
    return request.headers.get('X-Requested-With') == 'fetch'


def _nombre_visible(usuario):
    nombre = ' '.join(
        parte for parte in (usuario.nombre, usuario.apellidos) if parte
    ).strip()
    return nombre or usuario.email


def autenticar_usuario(correo, metodo, contrasena):
    """Autentica con correo y contraseña o identifica mediante una captura 1:N."""
    User = get_user_model()
    if metodo == 'contrasena':
        correo = (correo or '').strip()
        if not correo:
            return None, 'Ingresa el correo electrónico para usar contraseña.'
        usuario = User.objects.filter(email__iexact=correo, is_active=True).first()
        if usuario is None:
            return None, 'No se encontró un usuario activo con ese correo.'
        if not usuario.check_password(contrasena or ''):
            return None, 'La contraseña no es correcta.'
        return usuario, None

    if metodo != 'huella':
        return None, 'Selecciona un método de autenticación.'

    sensor = uart = None
    try:
        publicar_estado('Buscando el lector USB. En cuanto esté listo, apoya el centro del dedo.')
        sensor, uart = get_sensor()
        publicar_estado('Lector listo. Apoya el centro del dedo y no lo muevas.')
        minucias = capturar_minucias_en_vivo(sensor)
        publicar_estado('Huella leída. Buscando a la persona entre las registradas...')
        usuario_id, _, _ = IndiceBiometricoRAM.identificar_1_a_N(
            minucias,
            ModeloUsuario=User,
            umbral=0.30,
        )
    except (OSError, RuntimeError) as error:
        publicar_estado('No se pudo usar el lector. Revisa el USB y vuelve a intentar.')
        return None, f'No se pudo verificar la huella: {error}'
    finally:
        if sensor:
            apagar_led_sensor(sensor)
        if uart and uart.is_open:
            uart.close()

    if usuario_id is None:
        publicar_estado('No coincide con ninguna huella. Limpia el dedo y apóyalo otra vez en el centro.')
        return None, 'No coincide con ninguna huella registrada. Limpia el dedo, apóyalo en el centro y vuelve a intentar.'
    usuario = User.objects.filter(pk=usuario_id, is_active=True).first()
    if usuario is None:
        publicar_estado('La huella coincide con una cuenta que ya no está activa.')
        return None, 'No se encontró un usuario activo con esa huella.'
    publicar_estado(f'Huella reconocida: {_nombre_visible(usuario)}.')
    return usuario, None


def devolucion_dentro_de_dos_horas():
    """Hora local, sin segundos, dos horas después de este momento."""
    ahora = timezone.localtime().replace(second=0, microsecond=0)
    return ahora + timedelta(hours=2)


def leer_fecha_devolucion(texto):
    """Lee el datetime del formulario. Si viene vacío, usa dentro de dos horas."""
    texto = (texto or '').strip()
    if not texto:
        return devolucion_dentro_de_dos_horas()
    parsed = parse_datetime(texto)
    if parsed is None:
        try:
            parsed = datetime.strptime(texto, '%Y-%m-%dT%H:%M')
        except ValueError:
            return None
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.get_current_timezone())
    return parsed


def _solicitante_valido(usuario_id):
    """Devuelve el usuario si sigue activo y sin sanciones, o (None, motivo)."""
    usuario = get_user_model().objects.filter(pk=usuario_id, is_active=True).first()
    if usuario is None:
        return None, 'El solicitante ya no está disponible. Inicia el registro de nuevo.'
    if usuario.mis_sanciones.filter(estado='activa').exists():
        return None, 'El solicitante tiene sanciones activas y no puede pedir préstamos.'
    return usuario, None


class WizardStepMixin(StaffRequiredMixin):
    paso = 0

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['paso'] = self.paso
        context['pasos'] = [(1, 'Autenticación'), (2, 'Dispositivos'), (3, 'Confirmación')]
        return context

    def solicitante_o_redirect(self, request):
        """Paso 1 es requisito de los pasos 2 y 3."""
        usuario_id = _wizard(request).get('usuario_id')
        if not usuario_id:
            messages.error(request, 'Primero autentica al solicitante.')
            return None, redirect('registrar_prestamo')
        usuario, error = _solicitante_valido(usuario_id)
        if usuario is None:
            _reset(request)
            messages.error(request, error)
            return None, redirect('registrar_prestamo')
        return usuario, None


class RegistrarPrestamoPaso1View(WizardStepMixin, TemplateView):
    template_name = 'Prestamos/registro_paso1.html'
    paso = 1

    def post(self, request):
        correo = request.POST.get('correo', '').strip()
        metodo = request.POST.get('metodo')
        solicitante, error = autenticar_usuario(
            correo,
            metodo,
            request.POST.get('contrasena', ''),
        )
        if error:
            return self._responder(request, error, correo, metodo)
        if solicitante.mis_sanciones.filter(estado='activa').exists():
            return self._responder(
                request,
                'El solicitante tiene sanciones activas y no puede pedir préstamos.',
                correo,
                metodo,
            )

        # Se reinicia el contexto para no arrastrar selecciones de otro solicitante.
        request.session[SESSION_KEY] = {'usuario_id': solicitante.pk}
        if quiere_json(request):
            return JsonResponse({
                'status': 'success',
                'message': f'Huella reconocida: {_nombre_visible(solicitante)}. Continuando con el préstamo.',
                'redirect_url': reverse('registrar_prestamo_paso2'),
            })
        return redirect('registrar_prestamo_paso2')

    def _responder(self, request, mensaje, correo, metodo):
        if quiere_json(request):
            return JsonResponse({'status': 'error', 'message': mensaje}, status=400)
        return self.error(mensaje, correo, metodo)

    def error(self, mensaje, correo, metodo):
        context = self.get_context_data(registro_error=mensaje, correo=correo, metodo=metodo)
        return self.render_to_response(context)


class RegistrarPrestamoPaso2View(WizardStepMixin, TemplateView):
    template_name = 'Prestamos/registro_paso2.html'
    paso = 2

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            self.solicitante, respuesta = self.solicitante_o_redirect(request)
            if respuesta:
                return respuesta
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        q = self.request.GET.get('q', '').strip()
        codigo = self.request.GET.get('codigo', '').strip()
        categoria = self.request.GET.get('categoria', '')
        disponibles = Dispositivo.objects.filter(
            estado='disponible'
        ).select_related('categoria').order_by('codigo_inventario')
        if q:
            disponibles = disponibles.filter(nombre__icontains=q)
        if codigo:
            disponibles = disponibles.filter(codigo_inventario__icontains=codigo)
        if categoria.isdigit():
            disponibles = disponibles.filter(categoria_id=int(categoria))
        context.update({
            'solicitante': self.solicitante,
            'dispositivos_disponibles': disponibles,
            'categorias': Categoria.objects.all(),
            'q': q,
            'codigo': codigo,
            'categoria_sel': categoria,
            'seleccionados': _wizard(self.request).get('dispositivo_ids', []),
        })
        return context

    def post(self, request):
        ids_recibidos = request.POST.getlist('dispositivos')
        if not ids_recibidos or any(not i.isdigit() for i in ids_recibidos):
            return self.error('Selecciona al menos un dispositivo disponible.')
        ids = list(dict.fromkeys(int(i) for i in ids_recibidos))
        if Dispositivo.objects.filter(pk__in=ids, estado='disponible').count() != len(ids):
            return self.error('Uno o más dispositivos ya no están disponibles. Actualiza la página.')

        wizard = _wizard(request)
        wizard['dispositivo_ids'] = ids
        request.session[SESSION_KEY] = wizard
        return redirect('registrar_prestamo_paso3')

    def error(self, mensaje):
        return self.render_to_response(self.get_context_data(registro_error=mensaje))


class RegistrarPrestamoPaso3View(WizardStepMixin, TemplateView):
    template_name = 'Prestamos/registro_paso3.html'
    paso = 3

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            self.solicitante, respuesta = self.solicitante_o_redirect(request)
            if respuesta:
                return respuesta
            ids = _wizard(request).get('dispositivo_ids')
            if not ids:
                messages.error(request, 'Selecciona al menos un dispositivo.')
                return redirect('registrar_prestamo_paso2')
            self.ids = ids
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sugerida = devolucion_dentro_de_dos_horas()
        context.update({
            'solicitante': self.solicitante,
            'dispositivos': Dispositivo.objects.filter(
                pk__in=self.ids
            ).select_related('categoria').order_by('codigo_inventario'),
            'fecha_sugerida': sugerida.strftime('%Y-%m-%dT%H:%M'),
            'fecha_minima': timezone.localtime().replace(
                second=0, microsecond=0
            ).strftime('%Y-%m-%dT%H:%M'),
        })
        return context

    def post(self, request):
        fecha_devolucion = leer_fecha_devolucion(request.POST.get('fecha_devolucion', ''))
        if fecha_devolucion is None:
            return self.error('Ingresa una fecha y hora de devolución válidas.')
        if fecha_devolucion < timezone.now():
            return self.error('La fecha de devolución no puede ser anterior a este momento.')

        User = get_user_model()
        try:
            with transaction.atomic():
                solicitante = User.objects.select_for_update().get(
                    pk=self.solicitante.pk, is_active=True
                )
                if solicitante.mis_sanciones.filter(estado='activa').exists():
                    raise ValueError(
                        'El solicitante tiene sanciones activas y no puede pedir préstamos.'
                    )
                dispositivos = list(
                    Dispositivo.objects.select_for_update().filter(
                        pk__in=self.ids, estado='disponible'
                    ).order_by('pk')
                )
                if len(dispositivos) != len(self.ids):
                    raise ValueError('Uno o más dispositivos ya no están disponibles.')

                prestamo = Prestamo.objects.create(
                    usuario_solicita=solicitante,
                    staff_autoriza=request.user,
                    fecha_devolucion_esperada=fecha_devolucion,
                )
                DetallePrestamo.objects.bulk_create([
                    DetallePrestamo(prestamo=prestamo, dispositivo=d) for d in dispositivos
                ])
                Dispositivo.objects.filter(
                    pk__in=[d.pk for d in dispositivos]
                ).update(estado='prestado')
        except (ValueError, User.DoesNotExist) as error:
            if 'dispositivos' in str(error):
                messages.error(request, str(error))
                return redirect('registrar_prestamo_paso2')
            _reset(request)
            messages.error(request, str(error))
            return redirect('registrar_prestamo')

        prestamo = Prestamo.objects.select_related(
            'usuario_solicita', 'staff_autoriza'
        ).prefetch_related('detalles__dispositivo').get(pk=prestamo.pk)
        if confirmar_prestamo(prestamo):
            messages.success(
                request,
                f'Se envió la confirmación a {prestamo.usuario_solicita.email}.',
            )
        else:
            messages.info(
                request,
                'El préstamo quedó registrado, pero no se pudo enviar el correo de confirmación.',
            )
        _reset(request)
        return redirect(reverse('registrar_prestamo_exito', args=[prestamo.pk]))

    def error(self, mensaje):
        return self.render_to_response(self.get_context_data(registro_error=mensaje))


class RegistrarPrestamoExitoView(StaffRequiredMixin, TemplateView):
    template_name = 'Prestamos/registro_exito.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['prestamo'] = get_object_or_404(
            Prestamo.objects.select_related('usuario_solicita').prefetch_related(
                'detalles__dispositivo'
            ),
            pk=self.kwargs['pk'],
        )
        return context
