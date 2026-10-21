from django.test import TestCase
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

        uart = Mock(is_open=True)
        sensor = Mock()
        with (
            patch('Usuarios.views.get_sensor', return_value=(sensor, uart)),
            patch(
                'Usuarios.views.enroll_fingerprint_to_db',
                return_value=b'template-biometrico',
            ) as enroll,
            patch('Usuarios.views.IndiceBiometricoRAM.actualizar_usuario') as update_index,
        ):
            response = self.client.post(reverse('registrar_huella'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        usuario = get_user_model().objects.get(email='alumno@example.com')
        enroll.assert_called_once_with(sensor)
        update_index.assert_called_once_with(usuario.pk, b'template-biometrico')
        uart.close.assert_called_once()
        self.assertEqual(usuario.numero_cuenta, '123456789')
        self.assertEqual(usuario.numero_trabajador, 'TRAB-10')
        self.assertEqual(usuario.rfc, 'LOPA000101ABC')
        self.assertEqual(usuario.curp, 'LOPA000101MDFXXX00')
        self.assertEqual(usuario.genero, 'F')
        self.assertEqual(usuario.direccion, 'Calle Principal 123')
        self.assertEqual(usuario.telefono_celular, '5512345678')
        self.assertEqual(usuario.entidad_academica_id, entidad.pk)
        self.assertEqual(usuario.programa_id, programa.pk)

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
