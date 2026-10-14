from django.contrib.auth import get_user_model
from django.contrib.auth.mixins import UserPassesTestMixin
from django.db import transaction
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.generic import TemplateView, View

from Inventario.models import Categoria, Dispositivo
from Usuarios.hardware import get_sensor, verify_fingerprint_from_db
from .models import DetallePrestamo, Prestamo


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


class RegistrarPrestamoView(StaffRequiredMixin, TemplateView):
    template_name = 'Prestamos/registrar_prestamo.html'
    PENDING_LOAN_SESSION_KEY = 'prestamo_pendiente'

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
            'dispositivos_disponibles': disponibles,
            'categorias': Categoria.objects.all(),
            'q': q,
            'categoria_sel': categoria,
            'registro_step': 'seleccion',
        })

        pendiente = self.request.session.get(self.PENDING_LOAN_SESSION_KEY)
        if pendiente:
            ids_dispositivos = pendiente.get('dispositivo_ids', [])
            dispositivos = Dispositivo.objects.filter(
                pk__in=ids_dispositivos,
                estado='disponible',
            ).select_related('categoria').order_by('codigo_inventario')

            if len(ids_dispositivos) != dispositivos.count():
                self.request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
                context['registro_error'] = (
                    'Uno o más dispositivos ya no están disponibles. Inicia el registro de nuevo.'
                )
            else:
                context.update({
                    'registro_step': 'solicitante',
                    'dispositivos_seleccionados': dispositivos,
                })
                usuario_id = pendiente.get('usuario_id')
                if usuario_id:
                    usuario = get_user_model().objects.filter(
                        pk=usuario_id,
                        is_active=True,
                    ).first()
                    if (
                        usuario
                        and not usuario.mis_sanciones.filter(estado='activa').exists()
                    ):
                        context.update({
                            'registro_step': 'identidad',
                            'solicitante': usuario,
                        })
                    else:
                        self.request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
                        context['registro_step'] = 'seleccion'
                        context['registro_error'] = (
                            'El solicitante tiene sanciones activas o ya no está disponible. '
                            'Inicia el registro de nuevo.'
                        )

        return context

    def post(self, request):
        accion = request.POST.get('accion')
        if accion == 'seleccionar_dispositivos':
            return self.seleccionar_dispositivos(request)
        if accion == 'validar_solicitante':
            return self.validar_solicitante(request)
        if accion == 'cancelar':
            request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
            return self.render_page()
        if accion == 'confirmar_identidad':
            return self.confirmar_identidad(request)
        return self.render_page(registro_error='La acción solicitada no es válida.')

    def seleccionar_dispositivos(self, request):
        ids_recibidos = request.POST.getlist('dispositivos')
        if not ids_recibidos or any(not item.isdigit() for item in ids_recibidos):
            return self.render_page(
                registro_error='Selecciona al menos un dispositivo disponible.'
            )

        ids_dispositivos = list(dict.fromkeys(int(item) for item in ids_recibidos))
        dispositivos = Dispositivo.objects.filter(
            pk__in=ids_dispositivos,
            estado='disponible',
        )
        if dispositivos.count() != len(ids_dispositivos):
            return self.render_page(
                registro_error='Uno o más dispositivos ya no están disponibles. Actualiza la página.'
            )

        fecha_devolucion = parse_datetime(
            request.POST.get('fecha_devolucion_esperada', '').strip()
        )
        if fecha_devolucion is None:
            return self.render_page(
                registro_error='Ingresa una fecha de devolución válida.'
            )
        if timezone.is_naive(fecha_devolucion):
            fecha_devolucion = timezone.make_aware(fecha_devolucion)
        if fecha_devolucion <= timezone.now():
            return self.render_page(
                registro_error='La fecha de devolución debe ser posterior a la fecha actual.'
            )

        request.session[self.PENDING_LOAN_SESSION_KEY] = {
            'dispositivo_ids': ids_dispositivos,
            'fecha_devolucion_esperada': fecha_devolucion.isoformat(),
        }
        return self.render_page()

    def validar_solicitante(self, request):
        pendiente = request.session.get(self.PENDING_LOAN_SESSION_KEY)
        if not pendiente:
            return self.render_page(
                registro_error='La sesión de registro caducó. Selecciona los dispositivos de nuevo.'
            )

        User = get_user_model()
        correo = request.POST.get('correo', '').strip()
        solicitante = User.objects.filter(email__iexact=correo, is_active=True).first()
        if solicitante is None:
            return self.render_page(
                registro_error='No se encontró un usuario activo con ese correo.'
            )

        if solicitante.mis_sanciones.filter(estado='activa').exists():
            request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
            return self.render_page(
                registro_error='El solicitante tiene sanciones activas y no puede pedir préstamos.'
            )

        pendiente['usuario_id'] = solicitante.pk
        request.session[self.PENDING_LOAN_SESSION_KEY] = pendiente
        return self.render_page()

    def confirmar_identidad(self, request):
        pendiente = request.session.get(self.PENDING_LOAN_SESSION_KEY)
        if not pendiente:
            return self.render_page(
                registro_error='La sesión de registro caducó. Inicia el proceso de nuevo.'
            )

        User = get_user_model()
        solicitante = User.objects.filter(
            pk=pendiente.get('usuario_id'),
            is_active=True,
        ).first()
        if solicitante is None:
            request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
            return self.render_page(
                registro_error='No se encontró un usuario activo. Inicia el proceso de nuevo.'
            )
        if solicitante.mis_sanciones.filter(estado='activa').exists():
            request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
            return self.render_page(
                registro_error='El solicitante tiene sanciones activas y no puede pedir préstamos.'
            )

        metodo = request.POST.get('metodo_identidad')
        if metodo == 'contrasena':
            identidad_verificada = solicitante.check_password(
                request.POST.get('contrasena', '')
            )
            if not identidad_verificada:
                return self.render_page(
                    registro_error='La contraseña no es correcta.'
                )
        elif metodo == 'huella':
            if not solicitante.huella_template:
                return self.render_page(
                    registro_error='El usuario no tiene una huella registrada.'
                )

            uart = None
            try:
                sensor, uart = get_sensor()
                identidad_verificada = verify_fingerprint_from_db(
                    sensor,
                    solicitante.huella_template,
                )
            except (OSError, RuntimeError) as error:
                return self.render_page(
                    registro_error=f'No se pudo verificar la huella: {error}'
                )
            finally:
                if uart and uart.is_open:
                    uart.close()

            if not identidad_verificada:
                return self.render_page(
                    registro_error='La huella no coincide.'
                )
        else:
            return self.render_page(
                registro_error='Selecciona la contraseña o la huella para verificar la identidad.'
            )

        try:
            with transaction.atomic():
                dispositivos = list(
                    Dispositivo.objects.select_for_update().filter(
                        pk__in=pendiente['dispositivo_ids'],
                        estado='disponible',
                    ).order_by('pk')
                )
                if len(dispositivos) != len(pendiente['dispositivo_ids']):
                    raise ValueError(
                        'Uno o más dispositivos ya no están disponibles. Inicia el registro de nuevo.'
                    )

                solicitante = User.objects.select_for_update().get(
                    pk=solicitante.pk,
                    is_active=True,
                )
                if solicitante.mis_sanciones.filter(estado='activa').exists():
                    raise ValueError(
                        'El solicitante tiene sanciones activas y no puede pedir préstamos.'
                    )

                fecha_devolucion = parse_datetime(
                    pendiente['fecha_devolucion_esperada']
                )
                prestamo = Prestamo.objects.create(
                    usuario_solicita=solicitante,
                    staff_autoriza=request.user,
                    fecha_devolucion_esperada=fecha_devolucion,
                )
                DetallePrestamo.objects.bulk_create([
                    DetallePrestamo(prestamo=prestamo, dispositivo=dispositivo)
                    for dispositivo in dispositivos
                ])
                Dispositivo.objects.filter(
                    pk__in=[dispositivo.pk for dispositivo in dispositivos]
                ).update(estado='prestado')
        except (ValueError, User.DoesNotExist) as error:
            request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
            return self.render_page(registro_error=str(error))

        request.session.pop(self.PENDING_LOAN_SESSION_KEY, None)
        return self.render_page(
            registro_exito=f'Préstamo #{prestamo.pk} registrado correctamente.'
        )

    def render_page(self, **extra_context):
        context = self.get_context_data()
        context.update(extra_context)
        return self.render_to_response(context)


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

        messages.success(request, f'Se registró la devolución de {len(detalles)} dispositivo(s).')
        return redirect('prestamos')
