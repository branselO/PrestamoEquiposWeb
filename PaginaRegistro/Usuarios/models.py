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
    numero_cuenta = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número de Cuenta / Trabajador")

    dependencia = models.ForeignKey('Dependencia', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="Dependencia/Facultad")
    huella_template = models.BinaryField(null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = CustomUserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['nombre', 'apellidos']

    def __str__(self):
        return f"{self.nombre} {self.apellidos} <{self.email}>"

    @property
    def tiene_sancion_activa(self):
        # Busca si existe al menos una sanción con estado 'activa'
        return self.mis_sanciones.filter(estado='activa').exists()

    @property
    def sanciones_activas(self):
        # Devuelve la lista de las sanciones activas para mostrarlas
        return self.mis_sanciones.filter(estado='activa')

    @property
    def prestamos_pendientes(self):
        # Busca los préstamos (tickets) que tengan al menos un dispositivo sin devolver
        # El .distinct() evita que el ticket salga duplicado si debe 2 dispositivos del mismo ticket
        return self.prestamos_solicitados.filter(detalles__fecha_devuelto__isnull=True).distinct()

# Proxies para diferenciar tipos de usuarios en el admin de Django
class StaffUser(CustomUser):
    class Meta:
        proxy = True 
        verbose_name = 'Usuario Staff'
        verbose_name_plural = '1. Usuarios Staff' 

class NormalUser(CustomUser):
    class Meta:
        proxy = True
        verbose_name = 'Usuario Normal'
        verbose_name_plural = '2. Usuarios Normales'

class Dependencia(models.Model):
    nombre = models.CharField(max_length=150, unique=True, verbose_name="Nombre de la Dependencia/Facultad")
    clave_corta = models.CharField(max_length=20, unique=True, verbose_name="Clave Corta (Ej. FI, DGAE)")

    class Meta:
        verbose_name = "Dependencia"
        verbose_name_plural = "Dependencias"

    def __str__(self):
        return self.clave_corta