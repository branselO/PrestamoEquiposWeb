"""Flujo secuencial de 3 pasos para registrar un préstamo.

Paso 1: autenticar al solicitante (contraseña o huella).
Paso 2: seleccionar dispositivos.
Paso 3: fecha de devolución y confirmación (creación transaccional).
"""
from datetime import datetime, time

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.generic import TemplateView

from Inventario.models import Categoria, Dispositivo
from Usuarios.hardware import get_sensor, verify_fingerprint_from_db
from .models import DetallePrestamo, Prestamo
from .views import StaffRequiredMixin

SESSION_KEY = 'registro_prestamo'


def _wizard(request):
    return request.session.get(SESSION_KEY) or {}


def _reset(request):
    request.session.pop(SESSION_KEY, None)


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
        solicitante = get_user_model().objects.filter(
            email__iexact=correo, is_active=True
        ).first()
        if solicitante is None:
            return self.error('No se encontró un usuario activo con ese correo.', correo, metodo)
        if solicitante.mis_sanciones.filter(estado='activa').exists():
            return self.error(
                'El solicitante tiene sanciones activas y no puede pedir préstamos.',
                correo, metodo,
            )

        if metodo == 'huella':
            error = self.verificar_huella(solicitante)
        elif metodo == 'contrasena':
            error = (
                None if solicitante.check_password(request.POST.get('contrasena', ''))
                else 'La contraseña no es correcta.'
            )
        else:
            error = 'Selecciona un método de autenticación.'
        if error:
            return self.error(error, correo, metodo)

        # Se reinicia el contexto para no arrastrar selecciones de otro solicitante.
        request.session[SESSION_KEY] = {'usuario_id': solicitante.pk}
        return redirect('registrar_prestamo_paso2')

    @staticmethod
    def verificar_huella(solicitante):
        if not solicitante.huella_template:
            return 'El usuario no tiene una huella registrada.'
        uart = None
        try:
            sensor, uart = get_sensor()
            coincide = verify_fingerprint_from_db(sensor, solicitante.huella_template)
        except (OSError, RuntimeError) as error:
            return f'No se pudo verificar la huella: {error}'
        finally:
            if uart and uart.is_open:
                uart.close()
        return None if coincide else 'La huella no coincide.'

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
        categoria = self.request.GET.get('categoria', '')
        disponibles = Dispositivo.objects.filter(
            estado='disponible'
        ).select_related('categoria').order_by('codigo_inventario')
        if q:
            disponibles = disponibles.filter(nombre__icontains=q)
        if categoria.isdigit():
            disponibles = disponibles.filter(categoria_id=int(categoria))
        context.update({
            'solicitante': self.solicitante,
            'dispositivos_disponibles': disponibles,
            'categorias': Categoria.objects.all(),
            'q': q,
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
        hoy = timezone.localdate()
        context.update({
            'solicitante': self.solicitante,
            'dispositivos': Dispositivo.objects.filter(
                pk__in=self.ids
            ).select_related('categoria').order_by('codigo_inventario'),
            'fecha_minima': hoy.isoformat(),
        })
        return context

    def post(self, request):
        fecha = parse_date(request.POST.get('fecha_devolucion', '').strip())
        if fecha is None:
            return self.error('Ingresa una fecha de devolución válida.')
        if fecha < timezone.localdate():
            return self.error('La fecha de devolución no puede ser anterior a hoy.')
        # La fecha se interpreta como fin del día indicado.
        fecha_devolucion = timezone.make_aware(datetime.combine(fecha, time(23, 59)))

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
