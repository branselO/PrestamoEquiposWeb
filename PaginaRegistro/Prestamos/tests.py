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

    def seleccionar_dispositivos(self, dispositivos=None):
        if dispositivos is None:
            dispositivos = [self.dispositivo.pk]
        return self.client.post(self.url, {
            'accion': 'seleccionar_dispositivos',
            'dispositivos': dispositivos,
            'fecha_devolucion_esperada': (
                timezone.localtime(timezone.now() + timedelta(days=5))
                .strftime('%Y-%m-%dT%H:%M')
            ),
        })

    def iniciar_registro(self, dispositivos=None):
        self.seleccionar_dispositivos(dispositivos)
        return self.client.post(self.url, {
            'accion': 'validar_solicitante',
            'correo': self.solicitante.email,
        })

    def confirmar_con_contrasena(self, contrasena='alumno-password'):
        return self.client.post(self.url, {
            'accion': 'confirmar_identidad',
            'metodo_identidad': 'contrasena',
            'contrasena': contrasena,
        })

    def test_available_device_is_listed_then_password_registers_loan(self):
        response = self.client.get(self.url)
        self.assertContains(response, self.dispositivo.codigo_inventario)
        self.assertContains(response, 'name="dispositivos"')

        response = self.seleccionar_dispositivos()
        self.assertContains(response, 'Correo del solicitante')
        self.assertNotContains(response, 'name="contrasena"')

        response = self.client.post(self.url, {
            'accion': 'validar_solicitante',
            'correo': self.solicitante.email,
        })
        self.assertContains(response, 'Verificar con contraseña')
        self.assertEqual(
            self.client.session['prestamo_pendiente']['usuario_id'],
            self.solicitante.pk,
        )

        response = self.confirmar_con_contrasena()

        self.assertContains(response, 'registrado correctamente')
        self.assertEqual(Prestamo.objects.count(), 1)
        prestamo = Prestamo.objects.get()
        self.assertEqual(prestamo.usuario_solicita, self.solicitante)
        self.assertEqual(prestamo.staff_autoriza, self.staff)
        self.assertEqual(
            list(prestamo.detalles.values_list('dispositivo_id', flat=True)),
            [self.dispositivo.pk],
        )
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'prestado')
        self.assertNotIn('prestamo_pendiente', self.client.session)

    def test_active_sanction_blocks_registration_before_identity_check(self):
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

        response = self.iniciar_registro()

        self.assertContains(response, 'tiene sanciones activas')
        self.assertNotIn('prestamo_pendiente', self.client.session)
        self.assertEqual(Prestamo.objects.count(), 1)
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'disponible')

    def test_wrong_password_does_not_create_loan_or_change_device(self):
        self.iniciar_registro()

        response = self.confirmar_con_contrasena('incorrecta')

        self.assertContains(response, 'La contraseña no es correcta.')
        self.assertEqual(Prestamo.objects.count(), 0)
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'disponible')
        self.assertIn('prestamo_pendiente', self.client.session)

    @patch('Prestamos.views.verify_fingerprint_from_db', return_value=True)
    @patch('Prestamos.views.get_sensor')
    def test_fingerprint_confirms_identity_and_closes_sensor(
        self,
        get_sensor,
        verify_fingerprint,
    ):
        self.solicitante.huella_template = b'huella-registrada'
        self.solicitante.save(update_fields=['huella_template'])
        uart = Mock(is_open=True)
        sensor = Mock()
        get_sensor.return_value = (sensor, uart)
        self.iniciar_registro()

        response = self.client.post(self.url, {
            'accion': 'confirmar_identidad',
            'metodo_identidad': 'huella',
        })

        self.assertContains(response, 'registrado correctamente')
        verify_fingerprint.assert_called_once()
        self.assertEqual(
            bytes(verify_fingerprint.call_args.args[1]),
            b'huella-registrada',
        )
        uart.close.assert_called_once()
        self.assertEqual(Prestamo.objects.count(), 1)
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'prestado')

    def test_device_that_becomes_unavailable_cannot_be_loaned(self):
        self.iniciar_registro()
        self.dispositivo.estado = 'prestado'
        self.dispositivo.save(update_fields=['estado'])

        response = self.confirmar_con_contrasena()

        self.assertContains(response, 'ya no están disponibles')
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

        response = self.client.get(self.url, {'q': 'laptop'})
        self.assertContains(response, 'PC-001')
        self.assertNotContains(response, 'AU-001')
        self.assertNotContains(response, 'PC-002')

        response = self.client.get(self.url, {'categoria': otra.pk})
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
        self.seleccionar_dispositivos([self.dispositivo.pk])
        self.client.post(self.url, {'accion': 'validar_solicitante', 'correo': self.solicitante.email})
        self.confirmar_con_contrasena()
        self.seleccionar_dispositivos([otro.pk])
        self.client.post(self.url, {'accion': 'validar_solicitante', 'correo': self.solicitante.email})
        self.confirmar_con_contrasena()
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
        self.assertContains(page, f'id="return-{prestamo.id}"')

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
