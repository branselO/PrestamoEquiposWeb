from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.http import JsonResponse
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views.generic import TemplateView, View

from Inventario.models import Dispositivo
from .models import DetallePrestamo, Prestamo, Sancion


class StaffRequiredMixin(UserPassesTestMixin):
    def test_func(self):
        return self.request.user.is_authenticated and self.request.user.is_staff


class adminPrestamoView(StaffRequiredMixin, TemplateView):
    template_name = 'Prestamos/prestamos.html'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        prestamos = Prestamo.objects.select_related(
            'usuario_solicita', 'staff_autoriza'
        ).prefetch_related('detalles__dispositivo').order_by('-id')

        estado = self.request.GET.get('estado', '')
        busqueda_id = self.request.GET.get('id', '').strip()

        if busqueda_id.isdigit():
            prestamos = prestamos.filter(id=int(busqueda_id))
        elif busqueda_id:
            prestamos = prestamos.none()

        usuario_id = self.request.GET.get('usuario', '').strip()
        usuario_filtrado = None
        if usuario_id.isdigit():
            usuario_filtrado = get_object_or_404(get_user_model(), id=int(usuario_id))
            prestamos = prestamos.filter(
                usuario_solicita=usuario_filtrado,
                detalles__fecha_devuelto__isnull=True,
            ).distinct()

        codigo_inventario = self.request.GET.get('codigo_inventario', '').strip()
        dispositivo_filtrado = None
        if codigo_inventario:
            dispositivo_filtrado = Dispositivo.objects.filter(
                codigo_inventario=codigo_inventario
            ).first()
            # Una sola condición filter() para que ambos criterios apliquen al mismo detalle
            prestamos = prestamos.filter(
                detalles__dispositivo__codigo_inventario=codigo_inventario,
                detalles__fecha_devuelto__isnull=True,
            ).distinct()

        # estado_ticket es una propiedad, por lo que se filtra en Python
        if estado == 'completado':
            prestamos = [p for p in prestamos if p.estado_ticket == 'Completado']
        elif estado == 'pendiente':
            prestamos = [p for p in prestamos if p.estado_ticket != 'Completado']

        context['prestamos'] = prestamos
        context['dispositivo_filtrado'] = dispositivo_filtrado
        context['codigo_inventario'] = codigo_inventario
        context['usuario_filtrado'] = usuario_filtrado
        context['estado'] = estado
        context['busqueda_id'] = busqueda_id
        return context


class RegistrarDevolucionView(StaffRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        prestamo = get_object_or_404(Prestamo, pk=pk)
        seleccionados = request.POST.getlist('detalles')
        comentarios = request.POST.get('comentarios', '').strip()

        with transaction.atomic():
            detalles = list(
                prestamo.detalles.select_for_update()
                .select_related('dispositivo')
                .filter(pk__in=[d for d in seleccionados if d.isdigit()],
                        fecha_devuelto__isnull=True)
            )
            if not detalles:
                messages.error(request, 'Selecciona al menos un dispositivo pendiente de devolución.')
                return redirect('prestamos')

            ahora = timezone.now()
            for detalle in detalles:
                detalle.fecha_devuelto = ahora
                detalle.nombre_externo_devuelve = (
                    request.POST.get(f'entrega_{detalle.pk}', '').strip()[:150] or None
                )
                detalle.comentarios_devolucion = comentarios or None
                detalle.save(update_fields=[
                    'fecha_devuelto', 'nombre_externo_devuelve', 'comentarios_devolucion',
                ])
                if detalle.dispositivo.estado == 'prestado':
                    detalle.dispositivo.estado = 'disponible'
                    detalle.dispositivo.save(update_fields=['estado'])

            if comentarios:
                prestamo.agregar_comentario(f'(Devolución) {comentarios}', request.user)

        messages.success(request, f'Se registró la devolución de {len(detalles)} dispositivo(s).')
        return redirect('prestamos')


class AgregarComentarioView(StaffRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        prestamo = get_object_or_404(Prestamo, pk=pk)
        with transaction.atomic():
            prestamo = Prestamo.objects.select_for_update().get(pk=prestamo.pk)
            agregado = prestamo.agregar_comentario(request.POST.get('comentarios', ''), request.user)
        if agregado:
            messages.success(request, 'Comentario agregado.')
        else:
            messages.error(request, 'Escribe un comentario.')
        if request.POST.get('origen') == 'pendientes':
            return redirect('devolucion_pendientes')
        return redirect('prestamos')


####### Vistas para Sanciones
class adminSancionView(StaffRequiredMixin, TemplateView):
    template_name = "Prestamos/sansiones.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        sanciones = Sancion.objects.select_related(
            'usuario', 'prestamo', 'registrado_por'
        ).prefetch_related('prestamo__detalles__dispositivo').order_by('-id')

        estado = self.request.GET.get('estado', '')
        busqueda_prestamo = self.request.GET.get('prestamo', '').strip()
        correo = self.request.GET.get('correo', '').strip()

        if estado in dict(Sancion.ESTADO_SANCION):
            sanciones = sanciones.filter(estado=estado)
        else:
            estado = ''

        if busqueda_prestamo.isdigit():
            sanciones = sanciones.filter(prestamo_id=int(busqueda_prestamo))
        elif busqueda_prestamo:
            sanciones = sanciones.none()

        if correo:
            sanciones = sanciones.filter(usuario__email__icontains=correo)

        usuario_id = self.request.GET.get('usuario', '').strip()
        usuario_filtrado = None
        if usuario_id.isdigit():
            usuario_filtrado = get_object_or_404(get_user_model(), id=int(usuario_id))
            sanciones = sanciones.filter(usuario=usuario_filtrado)

        context.update({
            'usuario_filtrado': usuario_filtrado,
            'sanciones': sanciones,
            'estados': Sancion.ESTADO_SANCION,
            'estado': estado,
            'busqueda_prestamo': busqueda_prestamo,
            'correo': correo,
        })
        return context


class RegistrarSancionView(StaffRequiredMixin, TemplateView):
    template_name = "Prestamos/registrar_sancion.html"

    def _prestamo_desde(self, valor):
        valor = (valor or '').strip()
        if not valor.isdigit():
            return None
        return Prestamo.objects.select_related('usuario_solicita').filter(pk=int(valor)).first()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        valor = kwargs.get('prestamo_id', self.request.GET.get('prestamo', ''))
        context.update({
            'prestamo_id': valor,
            'prestamo': self._prestamo_desde(valor),
            'tipos': Sancion.TIPO_SANCION,
            'tipo': kwargs.get('tipo', ''),
            'observaciones': kwargs.get('observaciones', ''),
        })
        return context

    def post(self, request, *args, **kwargs):
        valor = request.POST.get('prestamo', '')
        tipo = request.POST.get('tipo_sancion', '')
        observaciones = request.POST.get('observaciones', '').strip()
        prestamo = self._prestamo_desde(valor)

        error = None
        if prestamo is None:
            error = 'No existe un préstamo con ese ID.'
        elif tipo not in dict(Sancion.TIPO_SANCION):
            error = 'Selecciona un tipo de sanción.'
        elif not observaciones:
            error = 'Escribe las observaciones de la sanción.'

        if error:
            messages.error(request, error)
            return self.render_to_response(self.get_context_data(
                prestamo_id=valor, tipo=tipo, observaciones=observaciones,
            ))

        sancion = Sancion.objects.create(
            prestamo=prestamo,
            usuario=prestamo.usuario_solicita,
            registrado_por=request.user,
            tipo_sancion=tipo,
            observaciones=observaciones,
        )
        messages.success(request, f'Sanción #{sancion.pk} registrada.')
        return redirect('sanciones')


class PrestamoUsuarioJsonView(StaffRequiredMixin, View):
    http_method_names = ['get']

    def get(self, request, pk):
        prestamo = Prestamo.objects.select_related('usuario_solicita').filter(pk=pk).first()
        if prestamo is None:
            return JsonResponse({'encontrado': False}, status=404)
        usuario = prestamo.usuario_solicita
        return JsonResponse({
            'encontrado': True,
            'nombre': f'{usuario.nombre} {usuario.apellidos}'.strip(),
            'email': usuario.email,
        })


class ModificarEstadoSancionView(StaffRequiredMixin, View):
    http_method_names = ['post']

    def post(self, request, pk):
        sancion = get_object_or_404(Sancion, pk=pk)
        nuevo_estado = request.POST.get('estado', '')
        if nuevo_estado not in dict(Sancion.ESTADO_SANCION):
            messages.error(request, 'Estado de sanción no válido.')
        else:
            sancion.estado = nuevo_estado
            sancion.save(update_fields=['estado'])
            messages.success(request, f'Se actualizó el estado de la sanción #{sancion.pk}.')
        return redirect('sanciones')
