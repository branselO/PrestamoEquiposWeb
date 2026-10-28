"""Flujo de devoluciones.

Paso 1: login del usuario (contraseña o huella).
Paso 2: panel de préstamos pendientes con acciones de devolución por préstamo.
"""
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from .models import Prestamo
from .registro_views import autenticar_usuario
from .views import StaffRequiredMixin

SESSION_KEY = 'devolucion_usuario_id'


class DevolucionLoginView(StaffRequiredMixin, TemplateView):
    template_name = 'Prestamos/devolucion_login.html'

    def post(self, request):
        correo = request.POST.get('correo', '')
        metodo = request.POST.get('metodo')
        usuario, error = autenticar_usuario(
            correo,
            metodo,
            request.POST.get('contrasena'),
        )
        if error:
            context = self.get_context_data(registro_error=error, correo=correo, metodo=metodo)
            return self.render_to_response(context)
        request.session[SESSION_KEY] = usuario.pk
        return redirect('devolucion_pendientes')


class DevolucionPendientesView(StaffRequiredMixin, TemplateView):
    template_name = 'Prestamos/devolucion_pendientes.html'

    def dispatch(self, request, *args, **kwargs):
        if request.user.is_authenticated and request.user.is_staff:
            self.usuario = get_user_model().objects.filter(
                pk=request.session.get(SESSION_KEY), is_active=True
            ).first()
            if self.usuario is None:
                request.session.pop(SESSION_KEY, None)
                messages.error(request, 'Primero autentica al usuario.')
                return redirect('devolucion_login')
        return super().dispatch(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prestamos = Prestamo.objects.filter(
            usuario_solicita=self.usuario,
            detalles__fecha_devuelto__isnull=True,
        ).distinct().order_by('-id').prefetch_related('detalles__dispositivo')
        context['usuario'] = self.usuario
        context['prestamos'] = prestamos
        return context


class DevolucionSalirView(StaffRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request):
        request.session.pop(SESSION_KEY, None)
        return redirect('devolucion_login')


class DevolucionBaseView(StaffRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        origen = request.POST.get('origen')
        destino = 'devolucion_pendientes' if origen == 'pendientes' else 'prestamos'
        if origen == 'pendientes':
            usuario_id = request.session.get(SESSION_KEY)
            if not usuario_id:
                messages.error(request, 'Primero autentica al usuario.')
                return redirect('devolucion_login')
            prestamo = get_object_or_404(Prestamo, pk=pk, usuario_solicita_id=usuario_id)
        else:
            prestamo = get_object_or_404(Prestamo, pk=pk)
        datos, error = self.identificar_quien_devuelve(request)
        if error:
            messages.error(request, error)
            return redirect(destino)

        seleccionados = [d for d in request.POST.getlist('detalles') if d.isdigit()]
        comentarios = request.POST.get('comentarios', '').strip()
        with transaction.atomic():
            detalles = list(
                prestamo.detalles.select_for_update().select_related('dispositivo').filter(
                    pk__in=seleccionados, fecha_devuelto__isnull=True
                )
            )
            if not detalles:
                messages.error(request, 'Selecciona al menos un dispositivo pendiente de devolución.')
                return redirect(destino)
            ahora = timezone.now()
            for detalle in detalles:
                detalle.fecha_devuelto = ahora
                detalle.usuario_devuelve = datos.get('usuario')
                detalle.nombre_externo_devuelve = datos.get('nombre')
                detalle.comentarios_devolucion = comentarios or None
                detalle.save(update_fields=[
                    'fecha_devuelto', 'usuario_devuelve', 'nombre_externo_devuelve',
                    'comentarios_devolucion',
                ])
                if detalle.dispositivo.estado == 'prestado':
                    detalle.dispositivo.estado = 'disponible'
                    detalle.dispositivo.save(update_fields=['estado'])
            if comentarios:
                prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
                prestamo.agregar_comentario(f'(Devolución) {comentarios}', request.user)

        messages.success(
            request,
            f'Se registró la devolución de {len(detalles)} dispositivo(s) del préstamo #{prestamo.pk}.',
        )
        return redirect(destino)

    def identificar_quien_devuelve(self, request):
        raise NotImplementedError


class DevolverComoUsuarioView(DevolucionBaseView):
    def identificar_quien_devuelve(self, request):
        usuario, error = autenticar_usuario(
            request.POST.get('correo'),
            request.POST.get('metodo'),
            request.POST.get('contrasena'),
        )
        return ({'usuario': usuario}, None) if usuario else (None, error)


class DevolverSinUsuarioView(DevolucionBaseView):
    def identificar_quien_devuelve(self, request):
        nombre = ' '.join(request.POST.get('nombre_completo', '').split())
        if len(nombre.split()) < 2:
            return None, 'Ingresa el nombre completo de quien devuelve.'
        return {'nombre': nombre[:150]}, None
