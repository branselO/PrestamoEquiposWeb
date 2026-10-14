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

    def test_staff_can_edit_device_attributes(self):
        response = self.client.post(self.url, {
            'codigo_inventario': 'INV-002',
            'nombre': 'Laptop actualizada',
            'categoria': self.categoria.pk,
            'especificaciones': '16 GB RAM',
            'estado': 'prestado',
            'comentarios': 'Asignada para prueba',
        })

        self.assertRedirects(response, reverse('inventario'))
        self.dispositivo.refresh_from_db()
        self.assertEqual(self.dispositivo.codigo_inventario, 'INV-002')
        self.assertEqual(self.dispositivo.nombre, 'Laptop actualizada')
        self.assertEqual(self.dispositivo.especificaciones, '16 GB RAM')
        self.assertEqual(self.dispositivo.estado, 'prestado')
        self.assertEqual(self.dispositivo.comentarios, 'Asignada para prueba')

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
