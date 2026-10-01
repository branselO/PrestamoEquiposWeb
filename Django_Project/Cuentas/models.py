from django.db import models
from django.contrib.auth.models import User

# Create your models here.

class CredemcialesWeb(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=128, blank=True)

    def __str__(self):
        return f"{self.user.username}"

class Solicitante(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    nombre = models.CharField(max_length=150, blank=True)
    apellido = models.CharField(max_length=150, blank=True)
    telefono = models.CharField(max_length=15, blank=True)
    direccion = models.CharField(max_length=255, blank=True)

    def __str__(self):
        return f"{self.user.username}"

