import base64
import json
import os

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch


class UserRegistrationFormTests(TestCase):
    registration_fields = {
        'numero_cuenta',
        'numero_trabajador',
        'rfc',
        'curp',
        'genero',
        'direccion',
        'telefono_celular',
        'entidad_academica',
        'programa',
    }

    def test_registration_forms_include_all_additional_user_fields(self):
        from .forms import NormalUserCreationForm, StaffSignUpForm

        for form_class in (NormalUserCreationForm, StaffSignUpForm):
            with self.subTest(form=form_class.__name__):
                self.assertTrue(
                    self.registration_fields.issubset(form_class.base_fields)
                )

    def test_registration_forms_ask_for_program_before_academic_entity(self):
        from .forms import NormalUserCreationForm, StaffSignUpForm

        for form_class in (NormalUserCreationForm, StaffSignUpForm):
            with self.subTest(form=form_class.__name__):
                field_names = list(form_class.base_fields)
                self.assertLess(
                    field_names.index('programa'),
                    field_names.index('entidad_academica'),
                )

    def test_registration_keeps_additional_fields_until_fingerprint_step(self):
        from .models import EntidadAcademica, Programa

        staff = get_user_model().objects.create_user(
            email='admin@example.com',
            nombre='Admin',
            apellidos='Prueba',
            password='correct-password',
            is_staff=True,
        )
        programa = Programa.objects.create(clave='ING', nombre='Ingeniería')
        entidad = EntidadAcademica.objects.create(clave='FI', nombre='Facultad')
        programa.entidades_academicas.add(entidad)

        self.client.force_login(staff)
        response = self.client.post(
            reverse('register_Normal'),
            {
                'email': 'alumno@example.com',
                'nombre': 'Ana',
                'apellidos': 'López',
                'numero_cuenta': '123456789',
                'numero_trabajador': 'TRAB-10',
                'rfc': 'LOPA000101ABC',
                'curp': 'LOPA000101MDFXXX00',
                'genero': 'F',
                'direccion': 'Calle Principal 123',
                'telefono_celular': '5512345678',
                'entidad_academica': entidad.pk,
                'programa': programa.pk,
                'password1': 'secure-test-password',
                'password2': 'secure-test-password',
            },
        )

        self.assertRedirects(response, reverse('registrar_huella'))
        temp_data = self.client.session['temp_user_data']
        self.assertEqual(temp_data['numero_cuenta'], '123456789')
        self.assertEqual(temp_data['numero_trabajador'], 'TRAB-10')
        self.assertEqual(temp_data['rfc'], 'LOPA000101ABC')
        self.assertEqual(temp_data['curp'], 'LOPA000101MDFXXX00')
        self.assertEqual(temp_data['genero'], 'F')
        self.assertEqual(temp_data['direccion'], 'Calle Principal 123')
        self.assertEqual(temp_data['telefono_celular'], '5512345678')
        self.assertEqual(temp_data['entidad_academica_id'], entidad.pk)
        self.assertEqual(temp_data['programa_id'], programa.pk)
        self.assertFalse(temp_data['is_staff'])

        import numpy as np

        uart = Mock(is_open=True)
        sensor = Mock()
        pixeles = bytes([180]) * (256 * 288)
        minucia = np.zeros((12, 4), dtype=np.float32)
        plantilla = np.ones((10, 4), dtype=np.float32)
        with (
            patch('Usuarios.views.get_sensor', return_value=(sensor, uart)),
            patch(
                'Usuarios.views.capturar_toma_para_pantalla',
                return_value=(pixeles, minucia),
            ) as capturar,
            patch('Usuarios.views.fusionar_plantilla', return_value=plantilla),
            patch('Usuarios.views.IndiceBiometricoRAM.actualizar_usuario') as update_index,
        ):
            for numero in range(1, 4):
                response = self.client.post(
                    reverse('registrar_huella'),
                    data=json.dumps({'accion': 'capturar'}),
                    content_type='application/json',
                )
                self.assertEqual(response.status_code, 200)
                cuerpo = response.json()
                self.assertEqual(cuerpo['status'], 'captura')
                self.assertEqual(cuerpo['toma'], numero)
                self.assertFalse(cuerpo['completo'])
                self.assertTrue(cuerpo['imagen'].startswith('data:image/png;base64,'))
                png = base64.b64decode(cuerpo['imagen'].split(',', 1)[1])
                self.assertTrue(png.startswith(b'\x89PNG'))
                self.assertFalse(
                    get_user_model().objects.filter(email='alumno@example.com').exists()
                )

            response = self.client.post(
                reverse('registrar_huella'),
                data=json.dumps({'accion': 'capturar'}),
                content_type='application/json',
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(response.json()['completo'])
        self.assertTrue(response.json()['imagen'].startswith('data:image/png;base64,'))
        usuario = get_user_model().objects.get(email='alumno@example.com')
        self.assertEqual(capturar.call_count, 4)
        update_index.assert_called_once_with(usuario.pk, bytes(usuario.huella_template))
        self.assertEqual(uart.close.call_count, 4)
        self.assertEqual(usuario.numero_cuenta, '123456789')
        self.assertEqual(usuario.numero_trabajador, 'TRAB-10')
        self.assertEqual(usuario.rfc, 'LOPA000101ABC')
        self.assertEqual(usuario.curp, 'LOPA000101MDFXXX00')
        self.assertEqual(usuario.genero, 'F')
        self.assertEqual(usuario.direccion, 'Calle Principal 123')
        self.assertEqual(usuario.telefono_celular, '5512345678')
        self.assertEqual(usuario.entidad_academica_id, entidad.pk)
        self.assertEqual(usuario.programa_id, programa.pk)

    def test_failed_capture_keeps_previous_images_and_restart_clears_them(self):
        import numpy as np

        sesion = self.client.session
        sesion['temp_user_data'] = {
            'email': 'alumno@example.com',
            'nombre': 'Ana',
            'apellidos': 'López',
            'password': 'hashed',
            'is_staff': False,
        }
        sesion.save()
        pixeles = bytes([90]) * (256 * 288)
        minucia = np.zeros((12, 4), dtype=np.float32)
        uart = Mock(is_open=True)
        with (
            patch('Usuarios.views.get_sensor', return_value=(Mock(), uart)),
            patch(
                'Usuarios.views.capturar_toma_para_pantalla',
                side_effect=[(pixeles, minucia), RuntimeError('No llegó el dedo a tiempo.')],
            ),
        ):
            primera = self.client.post(
                reverse('registrar_huella'),
                data=json.dumps({'accion': 'capturar'}),
                content_type='application/json',
            )
            segunda = self.client.post(
                reverse('registrar_huella'),
                data=json.dumps({'accion': 'capturar'}),
                content_type='application/json',
            )

        self.assertEqual(primera.json()['toma'], 1)
        self.assertEqual(segunda.status_code, 400)
        self.assertEqual(segunda.json()['toma'], 1)
        self.assertEqual(len(self.client.session['huella_tomas']), 1)

        reinicio = self.client.post(
            reverse('registrar_huella'),
            data=json.dumps({'accion': 'reiniciar'}),
            content_type='application/json',
        )
        self.assertEqual(reinicio.status_code, 200)
        self.assertEqual(reinicio.json()['toma'], 0)
        self.assertEqual(self.client.session['huella_tomas'], [])

    def test_capture_returns_as_soon_as_the_finger_is_still(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace

        import numpy as np

        from Usuarios.hardware import hardware as hw

        pixeles = bytes([120]) * (256 * 288)
        minucia = np.zeros((12, 4), dtype=np.float32)
        pausas = []

        def anotar_pausa(segundos):
            pausas.append(segundos)

        with (
            tempfile.TemporaryDirectory() as carpeta,
            patch.object(hw, '_leer_foto', return_value=(pixeles, 0)),
            patch.object(hw, 'analizar', return_value=SimpleNamespace(motivo='dedo')),
            patch.object(hw, '_minucias_de_foto', return_value=minucia),
            patch.object(hw.time, 'sleep', side_effect=anotar_pausa),
        ):
            foto, puntos = hw._capturar_toma(
                Mock(),
                1,
                None,
                hw.ESPERA_QUIETO,
                Path(carpeta),
                5,
            )

        self.assertEqual(foto, pixeles)
        self.assertEqual(len(puntos), 12)
        self.assertLess(sum(pausas), 1.0)
        self.assertNotIn(3.0, pausas)

    def test_sensor_status_follows_live_updates(self):
        from Usuarios.hardware.hardware import _estado

        _estado('Toma 2 de 4. Apoya el centro del dedo.')
        try:
            response = self.client.get(reverse('estado_sensor'))
            self.assertEqual(
                response.json()['mensaje'],
                'Toma 2 de 4. Apoya el centro del dedo.',
            )
        finally:
            _estado('Iniciando...')

    def test_entidades_endpoint_returns_only_entities_of_selected_program(self):
        from .models import EntidadAcademica, Programa

        entidad_permitida = EntidadAcademica.objects.create(clave='FI', nombre='Facultad')
        entidad_ajena = EntidadAcademica.objects.create(clave='FDER', nombre='Derecho')
        programa = Programa.objects.create(clave='ING', nombre='Ingeniería')
        programa_sin_entidad = Programa.objects.create(clave='DER', nombre='Derecho')
        programa.entidades_academicas.add(entidad_permitida)
        programa_sin_entidad.entidades_academicas.add(entidad_ajena)

        response = self.client.get(
            reverse('entidades_por_programa'),
            {'programa_id': programa.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()['entidades'],
            [{
                'id': entidad_permitida.pk,
                'clave': 'FI',
                'nombre': 'Facultad',
            }],
        )

    def test_registration_form_rejects_entity_not_associated_with_selected_program(self):
        from .forms import NormalUserCreationForm
        from .models import EntidadAcademica, Programa

        entidad = EntidadAcademica.objects.create(clave='FI', nombre='Facultad')
        otra_entidad = EntidadAcademica.objects.create(clave='FDER', nombre='Derecho')
        programa = Programa.objects.create(clave='DER', nombre='Derecho')
        programa.entidades_academicas.add(otra_entidad)

        form = NormalUserCreationForm(data={
            'email': 'alumno@example.com',
            'nombre': 'Ana',
            'apellidos': 'López',
            'entidad_academica': entidad.pk,
            'programa': programa.pk,
            'password1': 'secure-test-password',
            'password2': 'secure-test-password',
        })

        self.assertFalse(form.is_valid())
        self.assertIn('entidad_academica', form.errors)

    def test_user_profile_displays_all_registration_fields(self):
        from .models import EntidadAcademica, Programa

        entidad = EntidadAcademica.objects.create(clave='FI', nombre='Facultad de Ingeniería')
        programa = Programa.objects.create(
            clave='ING',
            nombre='Ingeniería en Computación',
        )
        programa.entidades_academicas.add(entidad)
        usuario = get_user_model().objects.create(
            email='ana@example.com',
            nombre='Ana',
            apellidos='López',
            numero_cuenta='123456789',
            numero_trabajador='TRAB-10',
            rfc='LOPA000101ABC',
            curp='LOPA000101MDFXXX00',
            genero='F',
            direccion='Calle Principal 123',
            telefono_celular='5512345678',
            entidad_academica=entidad,
            programa=programa,
        )

        response = self.client.get(
            reverse('perfil_usuario', args=[usuario.pk])
        )

        self.assertEqual(response.status_code, 200)
        for value in (
            'Número de cuenta',
            '123456789',
            'Número de trabajador',
            'TRAB-10',
            'RFC',
            'LOPA000101ABC',
            'CURP',
            'LOPA000101MDFXXX00',
            'Femenino',
            'Calle Principal 123',
            '5512345678',
            'Facultad de Ingeniería',
            'Ingeniería en Computación',
            'Fecha de registro',
        ):
            with self.subTest(value=value):
                self.assertContains(response, value)


class LoginFlowTests(TestCase):
    def setUp(self):
        self.user = get_user_model()(
            email='staff@example.com',
            nombre='Prueba',
            apellidos='Pérez',
            is_staff=True,
        )
        self.user.set_password('correct-password')
        self.user.save()

    def test_login_requests_email_only_then_opens_authentication_options(self):
        response = self.client.get(reverse('login'))

        self.assertContains(response, 'Correo electrónico')
        self.assertNotContains(response, 'name="password"')

        response = self.client.post(
            reverse('login'),
            {'email': self.user.email},
        )

        self.assertRedirects(response, reverse('verificar_huella'))
        self.assertEqual(
            self.client.session['pre_login_user_id'],
            self.user.id,
        )

        response = self.client.get(reverse('verificar_huella'))
        self.assertContains(response, 'Usar contraseña en su lugar')
        self.assertContains(response, 'apoya el centro del dedo')

    def test_password_alternative_authenticates_without_using_fingerprint_sensor(self):
        self.client.get(reverse('login'))
        self.client.post(reverse('login'), {'email': self.user.email})

        with patch('Usuarios.views.get_sensor') as get_sensor:
            response = self.client.post(
                reverse('verificar_huella'),
                {'auth_method': 'password', 'password': 'correct-password'},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(self.client.session.get('_auth_user_id'))
        self.assertNotIn('pre_login_user_id', self.client.session)
        get_sensor.assert_not_called()

    def test_incorrect_password_does_not_authenticate(self):
        self.client.get(reverse('login'))
        self.client.post(reverse('login'), {'email': self.user.email})

        response = self.client.post(
            reverse('verificar_huella'),
            {'auth_method': 'password', 'password': 'incorrect-password'},
        )

        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json()['status'], 'error')
        self.assertNotIn('_auth_user_id', self.client.session)
        self.assertEqual(
            self.client.session['pre_login_user_id'],
            self.user.id,
        )

    @patch('Usuarios.views.comparar_minucias_fast', return_value=0.8)
    @patch('Usuarios.views.capturar_minucias_en_vivo', return_value='minucias-capturadas')
    @patch('Usuarios.views.deserializar_template', return_value='minucias-registradas')
    @patch('Usuarios.views.get_sensor')
    def test_fingerprint_authentication_still_works(
        self,
        get_sensor,
        deserialize_template,
        capture_minutiae,
        compare_minutiae,
    ):
        self.user.huella_template = b'template-registrado'
        self.user.save(update_fields=['huella_template'])
        uart = Mock(is_open=True)
        sensor = Mock()
        get_sensor.return_value = (sensor, uart)
        self.client.get(reverse('login'))
        self.client.post(reverse('login'), {'email': self.user.email})

        response = self.client.post(reverse('verificar_huella'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(self.client.session.get('_auth_user_id'))
        deserialize_template.assert_called_once_with(bytes(self.user.huella_template))
        capture_minutiae.assert_called_once_with(sensor)
        compare_minutiae.assert_called_once()
        uart.close.assert_called_once()


class _Puerto:
    def __init__(self, device, description="", manufacturer="", product="", hwid=""):
        self.device = device
        self.description = description
        self.manufacturer = manufacturer
        self.product = product
        self.hwid = hwid


class DeteccionPuertoTests(SimpleTestCase):
    def test_elige_el_cp210_aunque_el_numero_com_cambie(self):
        from Usuarios.hardware.verificar_as608 import elegir_puerto

        puertos = [
            _Puerto("COM3", description="USB Serial Device"),
            _Puerto(
                "COM12",
                description="Silicon Labs CP210x USB to UART Bridge (COM12)",
                manufacturer="Silicon Labs",
                product="CP210x USB to UART Bridge",
            ),
        ]
        self.assertEqual(elegir_puerto(puertos), "COM12")

    def test_el_puerto_forzado_y_el_ultimo_baud_tienen_prioridad(self):
        from Usuarios.hardware import hardware as lector

        anterior = lector._baud_detectado
        lector._baud_detectado = 9600
        try:
            entorno = os.environ.copy()
            entorno.pop("HUELLA_BAUD", None)
            entorno["HUELLA_PUERTO"] = "COM5"
            with patch.dict(os.environ, entorno, clear=True):
                self.assertEqual(lector.encontrar_puerto_arduino(), "COM5")
                self.assertEqual(lector._baud_pedido(), 9600)
            with patch.dict(os.environ, {"HUELLA_BAUD": "57600"}, clear=False):
                self.assertEqual(lector._baud_pedido(), 57600)
        finally:
            lector._baud_detectado = anterior
