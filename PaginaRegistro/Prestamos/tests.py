from datetime import timedelta
from unittest.mock import Mock, patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from Inventario.models import Categoria, Dispositivo
from .models import Prestamo, Sancion


class RegistrarPrestamoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User(
            email='staff@example.com',
            nombre='Personal',
            apellidos='Prueba',
            is_staff=True,
        )
        self.staff.set_password('staff-password')
        self.staff.save()

        self.solicitante = User(
            email='alumno@example.com',
            nombre='Alumno',
            apellidos='Prueba',
        )
        self.solicitante.set_password('alumno-password')
        self.solicitante.save()

        self.categoria = Categoria.objects.create(nombre='Cómputo')
        self.dispositivo = Dispositivo.objects.create(
            codigo_inventario='PC-001',
            nombre='Laptop de prueba',
            categoria=self.categoria,
            especificaciones='16 GB RAM',
        )
        self.client.force_login(self.staff)
        self.url = reverse('registrar_prestamo')

    def autenticar(self, contrasena='alumno-password'):
        return self.client.post(self.url, {
            'correo': self.solicitante.email,
            'metodo': 'contrasena',
            'contrasena': contrasena,
        })

    def seleccionar_dispositivos(self, dispositivos=None):
        if dispositivos is None:
            dispositivos = [self.dispositivo.pk]
        return self.client.post(reverse('registrar_prestamo_paso2'), {
            'dispositivos': dispositivos,
        })

    def confirmar(self, dias=5):
        fecha = timezone.localdate() + timedelta(days=dias)
        return self.client.post(reverse('registrar_prestamo_paso3'), {
            'fecha_devolucion': fecha.isoformat(),
        })

    def iniciar_registro(self, dispositivos=None):
        self.autenticar()
        return self.seleccionar_dispositivos(dispositivos)

    def confirmar_con_contrasena(self):
        self.autenticar()
        self.seleccionar_dispositivos()
        return self.confirmar()

    def test_three_step_flow_registers_loan_and_clears_session(self):
        response = self.client.get(self.url)
        self.assertContains(response, 'name="contrasena"')

        response = self.autenticar()
        self.assertRedirects(response, reverse('registrar_prestamo_paso2'))
        self.assertEqual(
            self.client.session['registro_prestamo']['usuario_id'],
            self.solicitante.pk,
        )

        response = self.client.get(reverse('registrar_prestamo_paso2'))
        self.assertContains(response, self.dispositivo.codigo_inventario)
        self.assertContains(response, 'Dispositivos disponibles')
        self.assertContains(response, 'Dispositivos seleccionados')
        self.assertContains(response, 'id="barcode-scan"')
        response = self.seleccionar_dispositivos()
        self.assertRedirects(response, reverse('registrar_prestamo_paso3'))

        response = self.client.get(reverse('registrar_prestamo_paso3'))
        self.assertContains(response, 'type="date"')
        self.assertContains(response, self.dispositivo.codigo_inventario)

        response = self.confirmar()

        prestamo = Prestamo.objects.get()
        self.assertRedirects(
            response, reverse('registrar_prestamo_exito', args=[prestamo.pk])
        )
        self.assertEqual(
            timezone.localtime(prestamo.fecha_devolucion_esperada).date(),
            timezone.localdate() + timedelta(days=5),
        )
        self.assertNotIn('registro_prestamo', self.client.session)
        prestamo = Prestamo.objects.get()
        self.assertEqual(prestamo.usuario_solicita, self.solicitante)
        self.assertEqual(prestamo.staff_autoriza, self.staff)
        self.assertEqual(
            list(prestamo.detalles.values_list('dispositivo_id', flat=True)),
            [self.dispositivo.pk],
        )
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'prestado')
        self.assertNotIn('registro_prestamo', self.client.session)

    def test_fingerprint_is_default_for_user_authentication_forms(self):
        for url in (self.url, reverse('devolucion_login')):
            with self.subTest(url=url):
                response = self.client.get(url)

                self.assertContains(response, 'value="huella" checked')
                self.assertNotContains(response, 'value="contrasena" checked')

    def test_step_two_filters_available_devices_by_inventory_code(self):
        self.autenticar()
        otro_dispositivo = Dispositivo.objects.create(
            codigo_inventario='CAM-002',
            nombre='Cámara de prueba',
            categoria=self.categoria,
            especificaciones='4K',
        )

        response = self.client.get(
            reverse('registrar_prestamo_paso2'),
            {'codigo': 'PC-001'},
        )

        self.assertContains(response, self.dispositivo.codigo_inventario)
        self.assertNotContains(response, otro_dispositivo.codigo_inventario)

    def test_active_sanction_blocks_authentication(self):
        prestamo_anterior = Prestamo.objects.create(
            usuario_solicita=self.solicitante,
            staff_autoriza=self.staff,
            fecha_devolucion_esperada=timezone.now() + timedelta(days=1),
        )
        Sancion.objects.create(
            prestamo=prestamo_anterior,
            usuario=self.solicitante,
            tipo_sancion='mal_uso',
            observaciones='Sanción de prueba',
        )

        response = self.autenticar()

        self.assertContains(response, 'tiene sanciones activas')
        self.assertNotIn('registro_prestamo', self.client.session)

    def test_wrong_password_does_not_start_flow(self):
        response = self.autenticar('incorrecta')

        self.assertContains(response, 'La contraseña no es correcta.')
        self.assertContains(response, 'value="contrasena" checked')
        self.assertNotIn('registro_prestamo', self.client.session)
        self.assertEqual(Prestamo.objects.count(), 0)

    def test_steps_require_previous_steps(self):
        for name in ('registrar_prestamo_paso2', 'registrar_prestamo_paso3'):
            self.assertRedirects(
                self.client.get(reverse(name)), self.url
            )
        self.autenticar()
        self.assertRedirects(
            self.client.get(reverse('registrar_prestamo_paso3')),
            reverse('registrar_prestamo_paso2'),
        )

    def test_past_date_is_rejected(self):
        self.iniciar_registro()

        response = self.confirmar(dias=-1)

        self.assertContains(response, 'no puede ser anterior a hoy')
        self.assertEqual(Prestamo.objects.count(), 0)
        self.assertIn('registro_prestamo', self.client.session)

    @patch('Prestamos.registro_views.IndiceBiometricoRAM.identificar_1_a_N')
    @patch(
        'Prestamos.registro_views.capturar_minucias_en_vivo',
        return_value='minucias-capturadas',
    )
    @patch('Prestamos.registro_views.get_sensor')
    def test_fingerprint_authenticates_and_closes_sensor(
        self,
        get_sensor,
        capture_minutiae,
        identify_fingerprint,
    ):
        self.solicitante.huella_template = b'huella-registrada'
        self.solicitante.save(update_fields=['huella_template'])
        uart = Mock(is_open=True)
        sensor = Mock()
        get_sensor.return_value = (sensor, uart)
        identify_fingerprint.return_value = (self.solicitante.pk, 0.8, 1.2)

        response = self.client.post(self.url, {
            'metodo': 'huella',
        })

        self.assertRedirects(response, reverse('registrar_prestamo_paso2'))
        capture_minutiae.assert_called_once_with(sensor)
        identify_fingerprint.assert_called_once_with(
            'minucias-capturadas',
            ModeloUsuario=get_user_model(),
            umbral=0.30,
        )
        uart.close.assert_called_once()

    @patch('Prestamos.registro_views.IndiceBiometricoRAM.identificar_1_a_N')
    @patch(
        'Prestamos.registro_views.capturar_minucias_en_vivo',
        return_value='minucias-capturadas',
    )
    @patch('Prestamos.registro_views.get_sensor')
    def test_fingerprint_authentication_does_not_require_email(
        self,
        get_sensor,
        capture_minutiae,
        identify_fingerprint,
    ):
        uart = Mock(is_open=True)
        sensor = Mock()
        get_sensor.return_value = (sensor, uart)
        identify_fingerprint.return_value = (self.solicitante.pk, 0.8, 1.2)

        response = self.client.post(self.url, {'metodo': 'huella'})

        self.assertRedirects(response, reverse('registrar_prestamo_paso2'))
        self.assertEqual(
            self.client.session['registro_prestamo']['usuario_id'],
            self.solicitante.pk,
        )
        uart.close.assert_called_once()

    @patch('Prestamos.registro_views.IndiceBiometricoRAM.identificar_1_a_N')
    @patch(
        'Prestamos.registro_views.capturar_minucias_en_vivo',
        return_value='minucias-capturadas',
    )
    @patch('Prestamos.registro_views.get_sensor')
    def test_unmatched_fingerprint_does_not_start_flow(
        self,
        get_sensor,
        capture_minutiae,
        identify_fingerprint,
    ):
        uart = Mock(is_open=True)
        get_sensor.return_value = (Mock(), uart)
        identify_fingerprint.return_value = (None, 0.0, 1.2)

        response = self.client.post(self.url, {'metodo': 'huella'})

        self.assertContains(response, 'No coincide con ninguna huella registrada')
        self.assertNotIn('registro_prestamo', self.client.session)
        uart.close.assert_called_once()

    @patch('Prestamos.registro_views.IndiceBiometricoRAM.identificar_1_a_N')
    @patch(
        'Prestamos.registro_views.capturar_minucias_en_vivo',
        return_value='minucias-capturadas',
    )
    @patch('Prestamos.registro_views.get_sensor')
    def test_fingerprint_search_reports_progress_in_json(
        self,
        get_sensor,
        capture_minutiae,
        identify_fingerprint,
    ):
        uart = Mock(is_open=True)
        get_sensor.return_value = (Mock(), uart)
        identify_fingerprint.return_value = (self.solicitante.pk, 0.8, 1.2)

        pagina = self.client.get(self.url)
        self.assertContains(pagina, 'apoya el centro del dedo')
        self.assertContains(pagina, 'data-auth-estado')

        response = self.client.post(
            self.url,
            {'metodo': 'huella'},
            HTTP_X_REQUESTED_WITH='fetch',
        )

        self.assertEqual(response.status_code, 200)
        cuerpo = response.json()
        self.assertEqual(cuerpo['status'], 'success')
        self.assertIn('Alumno Prueba', cuerpo['message'])
        self.assertEqual(cuerpo['redirect_url'], reverse('registrar_prestamo_paso2'))
        self.assertEqual(
            self.client.session['registro_prestamo']['usuario_id'],
            self.solicitante.pk,
        )

    def test_device_that_becomes_unavailable_cannot_be_loaned(self):
        self.iniciar_registro()
        self.dispositivo.estado = 'prestado'
        self.dispositivo.save(update_fields=['estado'])

        response = self.confirmar()

        self.assertRedirects(response, reverse('registrar_prestamo_paso2'))
        self.assertEqual(Prestamo.objects.count(), 0)

    def test_available_devices_can_be_filtered_by_name_and_category(self):
        otra = Categoria.objects.create(nombre='Audio')
        Dispositivo.objects.create(
            codigo_inventario='AU-001', nombre='Micrófono', categoria=otra,
            especificaciones='USB',
        )
        Dispositivo.objects.create(
            codigo_inventario='PC-002', nombre='Laptop prestada', categoria=self.categoria,
            especificaciones='x', estado='prestado',
        )

        self.autenticar()
        paso2 = reverse('registrar_prestamo_paso2')
        response = self.client.get(paso2, {'q': 'laptop'})
        self.assertContains(response, 'PC-001')
        self.assertNotContains(response, 'AU-001')
        self.assertNotContains(response, 'PC-002')

        response = self.client.get(paso2, {'categoria': otra.pk})
        self.assertContains(response, 'AU-001')
        self.assertNotContains(response, 'PC-001')

    def test_loans_page_links_to_register_page(self):
        response = self.client.get(reverse('prestamos'))
        self.assertContains(response, reverse('registrar_prestamo'))
        self.assertNotContains(response, 'name="dispositivos"')

    def test_follow_up_filter_shows_only_pending_loan_of_that_device(self):
        otro = Dispositivo.objects.create(
            codigo_inventario='PC-009', nombre='Otra', categoria=self.categoria,
            especificaciones='x',
        )
        self.autenticar()
        self.seleccionar_dispositivos([self.dispositivo.pk])
        self.confirmar()
        self.autenticar()
        self.seleccionar_dispositivos([otro.pk])
        self.confirmar()
        primero, segundo = Prestamo.objects.order_by('id')

        response = self.client.get(reverse('prestamos'), {'codigo_inventario': 'PC-001'})

        self.assertEqual(list(response.context['prestamos']), [primero])
        self.assertNotIn(segundo, response.context['prestamos'])

    def test_registrar_devolucion_libera_dispositivo_y_guarda_datos(self):
        prestamo = Prestamo.objects.create(
            usuario_solicita=self.solicitante,
            staff_autoriza=self.staff,
            fecha_devolucion_esperada=timezone.now() + timedelta(days=1),
        )
        detalle = prestamo.detalles.create(dispositivo=self.dispositivo)
        self.dispositivo.estado = 'prestado'
        self.dispositivo.save()

        page = self.client.get(reverse('prestamos'))
        self.assertContains(page, f'id="como-{prestamo.id}"')
        self.assertContains(page, f'id="sin-{prestamo.id}"')

        response = self.client.post(reverse('registrar_devolucion', args=[prestamo.id]), {
            'detalles': [detalle.pk],
            f'entrega_{detalle.pk}': 'Un amigo',
            'comentarios': 'Pantalla rayada',
        })

        self.assertRedirects(response, reverse('prestamos'))
        detalle.refresh_from_db()
        self.dispositivo.refresh_from_db()
        self.assertIsNotNone(detalle.fecha_devuelto)
        self.assertEqual(detalle.nombre_externo_devuelve, 'Un amigo')
        self.assertEqual(detalle.comentarios_devolucion, 'Pantalla rayada')
        self.assertEqual(self.dispositivo.estado, 'disponible')


class RegistrarDevolucionFlujoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.staff = User(email='staff@example.com', nombre='P', apellidos='S', is_staff=True)
        self.staff.set_password('staff-password')
        self.staff.save()
        self.alumno = User(email='alumno@example.com', nombre='Alumno', apellidos='Prueba')
        self.alumno.set_password('alumno-password')
        self.alumno.save()
        self.otro = User(email='otro@example.com', nombre='Otro', apellidos='Prueba')
        self.otro.set_password('otro-password')
        self.otro.save()
        categoria = Categoria.objects.create(nombre='Cómputo')
        self.dispositivo = Dispositivo.objects.create(
            codigo_inventario='PC-001', nombre='Laptop', categoria=categoria,
            especificaciones='x', estado='prestado',
        )
        self.prestamo = Prestamo.objects.create(
            usuario_solicita=self.alumno, staff_autoriza=self.staff,
            fecha_devolucion_esperada=timezone.now() + timedelta(days=1),
        )
        self.detalle = self.prestamo.detalles.create(dispositivo=self.dispositivo)
        self.client.force_login(self.staff)

    def login_alumno(self):
        return self.client.post(reverse('devolucion_login'), {
            'correo': self.alumno.email, 'metodo': 'contrasena',
            'contrasena': 'alumno-password',
        })

    def test_login_then_pending_list(self):
        response = self.login_alumno()
        self.assertRedirects(response, reverse('devolucion_pendientes'))
        self.assertEqual(self.client.session['devolucion_usuario_id'], self.alumno.pk)
        response = self.client.get(reverse('devolucion_pendientes'))
        self.assertContains(response, 'PC-001')
        self.assertContains(response, 'Devolver como usuario')
        self.assertContains(response, 'Devolver sin usuario')

    @patch('Prestamos.registro_views.IndiceBiometricoRAM.identificar_1_a_N')
    @patch(
        'Prestamos.registro_views.capturar_minucias_en_vivo',
        return_value='minucias-capturadas',
    )
    @patch('Prestamos.registro_views.get_sensor')
    def test_fingerprint_login_does_not_require_email(
        self,
        get_sensor,
        capture_minutiae,
        identify_fingerprint,
    ):
        uart = Mock(is_open=True)
        sensor = Mock()
        get_sensor.return_value = (sensor, uart)
        identify_fingerprint.return_value = (self.alumno.pk, 0.8, 1.2)

        response = self.client.post(reverse('devolucion_login'), {'metodo': 'huella'})

        self.assertRedirects(response, reverse('devolucion_pendientes'))
        self.assertEqual(self.client.session['devolucion_usuario_id'], self.alumno.pk)
        capture_minutiae.assert_called_once_with(sensor)
        uart.close.assert_called_once()

    def test_wrong_password_and_missing_session(self):
        response = self.client.post(reverse('devolucion_login'), {
            'correo': self.alumno.email, 'metodo': 'contrasena', 'contrasena': 'mal',
        })
        self.assertContains(response, 'La contraseña no es correcta.')
        self.assertRedirects(
            self.client.get(reverse('devolucion_pendientes')), reverse('devolucion_login')
        )

    def test_return_as_user_requires_valid_credentials(self):
        self.login_alumno()
        url = reverse('devolucion_como_usuario', args=[self.prestamo.pk])
        self.client.post(url, {
            'origen': 'pendientes', 'detalles': [self.detalle.pk], 'correo': self.otro.email,
            'metodo': 'contrasena', 'contrasena': 'mala',
        })
        self.detalle.refresh_from_db()
        self.assertIsNone(self.detalle.fecha_devuelto)

        response = self.client.post(url, {
            'origen': 'pendientes', 'detalles': [self.detalle.pk], 'correo': self.otro.email,
            'metodo': 'contrasena', 'contrasena': 'otro-password',
        }, follow=True)
        self.assertContains(response, 'Se registró la devolución')
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.usuario_devuelve, self.otro)
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'disponible')

    def test_return_without_user_needs_full_name(self):
        self.login_alumno()
        url = reverse('devolucion_sin_usuario', args=[self.prestamo.pk])
        self.client.post(url, {'origen': 'pendientes', 'detalles': [self.detalle.pk], 'nombre_completo': 'Juan'})
        self.detalle.refresh_from_db()
        self.assertIsNone(self.detalle.fecha_devuelto)

        response = self.client.post(url, {
            'origen': 'pendientes', 'detalles': [self.detalle.pk], 'nombre_completo': 'Juan Pérez',
        })
        self.assertRedirects(response, reverse('devolucion_pendientes'))
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.nombre_externo_devuelve, 'Juan Pérez')
        self.assertIsNone(self.detalle.usuario_devuelve)

    def test_cannot_return_loan_of_another_user(self):
        self.client.post(reverse('devolucion_login'), {
            'correo': self.otro.email, 'metodo': 'contrasena', 'contrasena': 'otro-password',
        })
        response = self.client.post(
            reverse('devolucion_sin_usuario', args=[self.prestamo.pk]),
            {'origen': 'pendientes', 'detalles': [self.detalle.pk], 'nombre_completo': 'Juan Pérez'},
        )
        self.assertEqual(response.status_code, 404)

    def test_return_comments_saved_and_admin_shows_who_returned(self):
        self.login_alumno()
        self.client.post(reverse('devolucion_como_usuario', args=[self.prestamo.pk]), {
            'origen': 'pendientes', 'detalles': [self.detalle.pk], 'correo': self.otro.email,
            'metodo': 'contrasena', 'contrasena': 'otro-password',
            'comentarios': 'Pantalla rayada',
        })
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.comentarios_devolucion, 'Pantalla rayada')
        self.prestamo.refresh_from_db()
        self.assertIn('Pantalla rayada', self.prestamo.comentarios)
        response = self.client.get(reverse('prestamos'))
        perfil = reverse('perfil_usuario', args=[self.otro.pk])
        self.assertContains(response, f'href="{perfil}"')
        self.assertContains(response, 'Devuelto por')

    def test_admin_shows_plain_name_without_link_for_external_return(self):
        self.login_alumno()
        self.client.post(reverse('devolucion_sin_usuario', args=[self.prestamo.pk]), {
            'origen': 'pendientes', 'detalles': [self.detalle.pk], 'nombre_completo': 'Juan Pérez',
            'comentarios': 'Todo bien',
        })
        self.detalle.refresh_from_db()
        self.assertEqual(self.detalle.comentarios_devolucion, 'Todo bien')
        response = self.client.get(reverse('prestamos'))
        self.assertContains(response, 'Juan Pérez')
        self.assertNotContains(response, '>Juan Pérez</a>')

    def test_pending_cards_have_all_actions_in_both_panels(self):
        self.login_alumno()
        for url in (reverse('devolucion_pendientes'), reverse('prestamos')):
            response = self.client.get(url)
            for texto in ('Registrar sanción', 'Agregar comentario',
                          'Devolver como usuario', 'Devolver sin usuario'):
                self.assertContains(response, texto)

    def test_admin_panel_return_without_session_redirects_to_admin(self):
        response = self.client.post(
            reverse('devolucion_sin_usuario', args=[self.prestamo.pk]),
            {'origen': 'prestamos', 'detalles': [self.detalle.pk],
             'nombre_completo': 'Juan Pérez'},
        )
        self.assertRedirects(response, reverse('prestamos'))
        self.detalle.refresh_from_db()
        self.assertIsNotNone(self.detalle.fecha_devuelto)