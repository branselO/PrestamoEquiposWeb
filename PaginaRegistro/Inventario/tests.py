from django.test import TestCase
from django.urls import reverse

from Usuarios.models import CustomUser
from .models import Categoria, Dispositivo


class DispositivoUpdateViewTests(TestCase):
    def setUp(self):
        self.staff_user = CustomUser.objects.create_user(
            email='staff@example.com',
            nombre='Personal',
            apellidos='Inventario',
            password='test-password',
            is_staff=True,
        )
        self.categoria = Categoria.objects.create(nombre='Computadoras')
        self.dispositivo = Dispositivo.objects.create(
            codigo_inventario='INV-001',
            nombre='Laptop',
            categoria=self.categoria,
            especificaciones='8 GB RAM',
            estado='disponible',
            comentarios='Equipo de prueba',
        )
        self.client.force_login(self.staff_user)
        self.url = reverse('dispositivo_editar', args=[self.dispositivo.pk])

    def test_staff_can_edit_device_attributes_without_setting_loaned_state(self):
        response = self.client.post(self.url, {
            'codigo_inventario': 'INV-002',
            'nombre': 'Laptop actualizada',
            'categoria': self.categoria.pk,
            'especificaciones': '16 GB RAM',
            'estado': 'mantenimiento',
            'comentarios': 'Asignada para prueba',
        })

        self.assertRedirects(response, reverse('inventario'))
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.codigo_inventario, 'INV-002')
        self.assertEqual(self.dispositivo.nombre, 'Laptop actualizada')
        self.assertEqual(self.dispositivo.especificaciones, '16 GB RAM')
        self.assertEqual(self.dispositivo.estado, 'mantenimiento')
        self.assertEqual(self.dispositivo.comentarios, 'Asignada para prueba')

    def test_loaned_state_is_not_available_or_accepted_when_editing(self):
        response = self.client.get(self.url)

        estado_choices = response.context['form'].fields['estado'].choices
        self.assertNotIn('prestado', [value for value, _label in estado_choices])

        response = self.client.post(self.url, {
            'codigo_inventario': 'INV-001',
            'nombre': 'Laptop',
            'categoria': self.categoria.pk,
            'especificaciones': '8 GB RAM',
            'estado': 'prestado',
            'comentarios': 'Equipo de prueba',
        })

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Seleccione una opción válida')
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.estado, 'disponible')

    def test_edit_link_and_loan_follow_up_button_are_shown_only_for_loaned_devices(self):
        response = self.client.get(reverse('inventario'))

        self.assertContains(
            response,
            reverse('dispositivo_editar', args=[self.dispositivo.pk]),
        )
        self.assertNotContains(response, 'Dar seguimiento al préstamo')

        self.dispositivo.estado = 'prestado'
        self.dispositivo.save(update_fields=['estado'])
        response = self.client.get(reverse('inventario'))

        self.assertContains(response, 'Dar seguimiento al préstamo')
