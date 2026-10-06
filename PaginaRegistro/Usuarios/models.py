from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models

class CustomUserManager(BaseUserManager):
    def create_user(self, email, nombre, apellidos, password=None, **extra_fields):
        if not email:
            raise ValueError('El email es obligatorio')
        email = self.normalize_email(email)
        user = self.model(email=email, nombre=nombre, apellidos=apellidos, **extra_fields)
        user.set_password(password) # Encripta la contraseña usando PBKDF2 por defecto
        user.save(using=self._db)
        return user

    def create_superuser(self, email, nombre, apellidos, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        return self.create_user(email, nombre, apellidos, password, **extra_fields)

class CustomUser(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(unique=True)
    nombre = models.CharField(max_length=50)
    apellidos = models.CharField(max_length=50)

    huella_template = models.BinaryField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre', 'apellidos']

    def __str__(self):
        return f"{self.nombre} {self.apellidos} <{self.email}>"

    # Añade esto al final de tu archivo users/models.py

class StaffUser(CustomUser):
    class Meta:
        proxy = True # ¡Crucial! Evita que se cree una tabla en la BD
        verbose_name = 'Usuario Staff'
        verbose_name_plural = '1. Usuarios Staff' # El "1." es un truco para ordenar la lista en el panel

class NormalUser(CustomUser):
    class Meta:
        proxy = True
        verbose_name = 'Usuario Normal'
        verbose_name_plural = '2. Usuarios Normales'