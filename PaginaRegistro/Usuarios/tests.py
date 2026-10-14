from django.test import TestCase
from django.urls import reverse
from django.contrib.auth import get_user_model
from unittest.mock import Mock, patch


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

    @patch('Usuarios.views.verify_fingerprint_from_db', return_value=True)
    @patch('Usuarios.views.get_sensor')
    def test_fingerprint_authentication_still_works(self, get_sensor, verify_fingerprint):
        uart = Mock(is_open=True)
        get_sensor.return_value = (Mock(), uart)
        self.client.get(reverse('login'))
        self.client.post(reverse('login'), {'email': self.user.email})

        response = self.client.post(reverse('verificar_huella'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['status'], 'success')
        self.assertTrue(self.client.session.get('_auth_user_id'))
        verify_fingerprint.assert_called_once_with(
            get_sensor.return_value[0],
            self.user.huella_template,
        )
        uart.close.assert_called_once()
