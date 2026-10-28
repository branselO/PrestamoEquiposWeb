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
    OPCIONES_GENERO = [
        ('M', 'Masculino'),
        ('F', 'Femenino'),
        ('O', 'Otro'),
        ('N', 'Prefiero no decirlo'),
    ]

    email = models.EmailField(unique=True, verbose_name="Correo Electrónico")
    nombre = models.CharField(max_length=100)
    apellidos = models.CharField(max_length=100)
    numero_cuenta = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número de Cuenta (Alumnos)")
    
    # --- LOS NUEVOS CAMPOS ADMINISTRATIVOS ---
    numero_trabajador = models.CharField(max_length=20, blank=True, null=True, verbose_name="Número de Trabajador")
    rfc = models.CharField(max_length=13, blank=True, null=True, verbose_name="RFC")
    curp = models.CharField(max_length=18, blank=True, null=True, verbose_name="CURP")
    genero = models.CharField(max_length=1, choices=OPCIONES_GENERO, blank=True, null=True, verbose_name="Género")
    direccion = models.TextField(blank=True, null=True, verbose_name="Dirección Completa")
    telefono_celular = models.CharField(max_length=15, blank=True, null=True, verbose_name="Teléfono Celular")
    
    # auto_now_add=True hace que el sistema llene este campo automáticamente cuando se crea el registro
    fecha_registro = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de Registro en el Sistema")
    # ----------------------------------------

    # Llaves foráneas (De la explicación anterior)
    entidad_academica = models.ForeignKey(
        'EntidadAcademica', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='usuarios'
    )
    
    programa = models.ForeignKey(
        'Programa', 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True, 
        related_name='alumnos'
    )
    #Huella digital del usuario
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

##### MODELOS ACADÉMICOS (PROGRAMAS Y ENTIDADES ACADÉMICAS) #####

class EntidadAcademica(models.Model):
    clave = models.CharField(max_length=20, unique=True, verbose_name="Clave (Ej. FI, IIMAS)")
    nombre = models.CharField(max_length=150, verbose_name="Nombre de la Entidad")
    director = models.CharField(max_length=150, blank=True, null=True, verbose_name="Director de la Entidad")

    class Meta:
        verbose_name = "Entidad Académica"
        verbose_name_plural = "Entidades Académicas"

    def __str__(self):
        return self.nombre

class Programa(models.Model):
    clave = models.CharField(max_length=20, unique=True, verbose_name="Clave del Programa")
    nombre = models.CharField(max_length=150, verbose_name="Nombre del Programa")
    nombre_corto = models.CharField(max_length=50, blank=True, null=True)

    entidades_academicas = models.ManyToManyField(
        EntidadAcademica,
        related_name='programas_impartidos',
        blank=True,
        verbose_name="Entidades Académicas que imparten este Programa"
    )

    class Meta:
        verbose_name = "Programa Académico"
        verbose_name_plural = "Programas Académicos"

    def __str__(self):
        return f"{self.clave} - {self.nombre}"