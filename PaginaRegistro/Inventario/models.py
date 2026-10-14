from django.db import models

# Create your models here.

class Categoria(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    descripcion = models.TextField(blank=True, null=True)
    def __str__(self):
        return self.nombre

class Dispositivo(models.Model):
    # Estados posibles del dispositivo
    ESTADOS = [
        ('disponible', 'Disponible'),
        ('prestado', 'En Préstamo'),
        ('mantenimiento', 'En Mantenimiento'),
        ('extraviado', 'Extraviado / Baja'),
    ]

    codigo_inventario = models.CharField(max_length=50, unique=True, verbose_name="Código de Inventario UNAM")
    nombre = models.CharField(max_length=200)

    categoria = models.ForeignKey(Categoria, on_delete=models.SET_NULL, null=True, related_name='dispositivos')
    
    especificaciones = models.TextField(help_text="Ej: Marca, modelo, procesador, RAM, puertos, etc.")
    estado = models.CharField(max_length=20, choices=ESTADOS, default='disponible')

    # Adicionales        
    foto = models.ImageField(upload_to='dispositivos_fotos/', blank=True, null=True)
    comentarios = models.TextField(blank=True, null=True)
    

    def __str__(self):
        return f"[{self.codigo_inventario}] {self.nombre} - {self.get_estado_display()}"