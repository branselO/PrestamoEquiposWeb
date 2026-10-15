from django.db import models
from django.conf import settings
from Inventario.models import Dispositivo 

# Create your models here.

class Prestamo(models.Model):
    # El ALUMNO que pone su huella para llevarse los equipos
    usuario_solicita = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.CASCADE, 
        related_name='prestamos_solicitados',
        verbose_name="Usuario que solicita"
    )
    
    # (Opcional pero recomendado) El STAFF que está en ventanilla y autoriza en el sistema
    staff_autoriza = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        related_name='prestamos_autorizados',
        verbose_name="Staff en ventanilla (Salida)"
    )

    fecha_salida = models.DateTimeField(auto_now_add=True, verbose_name="Fecha y hora de salida")
    fecha_devolucion_esperada = models.DateTimeField(verbose_name="Devolución esperada")

    @property
    def estado_ticket(self):
        total_equipos = self.detalles.count()
        equipos_devueltos = self.detalles.filter(fecha_devuelto__isnull=False).count()

        if total_equipos == 0:
            return "Vacío"
        elif equipos_devueltos == 0:
            return "Pendiente (Ningún equipo devuelto)"
        elif equipos_devueltos < total_equipos:
            return f"Parcial ({equipos_devueltos}/{total_equipos} devueltos)"
        else:
            return "Completado"
        
    @property
    def comentarios_devolucion(self):
        comentarios = []
        vistos = set()
        detalles = self.detalles.filter(
            fecha_devuelto__isnull=False, comentarios_devolucion__isnull=False
        ).order_by('fecha_devuelto', 'id')
        for detalle in detalles:
            texto = detalle.comentarios_devolucion.strip()
            clave = (detalle.fecha_devuelto, texto)
            if texto and clave not in vistos:
                vistos.add(clave)
                comentarios.append(texto)
        return "\n".join(comentarios)

    class Meta:
        verbose_name = "Préstamo (Ticket)"
        verbose_name_plural = "Préstamos (Tickets)"

    def __str__(self):
        return f"Ticket #{self.id} | Solicitó: {self.usuario_solicita.email}"


class DetallePrestamo(models.Model):
    prestamo = models.ForeignKey(Prestamo, on_delete=models.CASCADE, related_name='detalles')
    dispositivo = models.ForeignKey(Dispositivo, on_delete=models.PROTECT, related_name='historial_prestamos')
    
    # --- DATOS DE DEVOLUCIÓN ---
    fecha_devuelto = models.DateTimeField(null=True, blank=True, verbose_name="Fecha devuelto real")
    
    # El USUARIO que físicamente entrega el equipo de regreso en ventanilla
    usuario_devuelve = models.ForeignKey(
        settings.AUTH_USER_MODEL, 
        on_delete=models.SET_NULL, 
        null=True, 
        blank=True,
        related_name='equipos_devueltos',
        verbose_name="Usuario que devuelve"
    )

    # (Opcional) Si un amigo que NO está registrado en el sistema lo devuelve, puedes usar este campo de respaldo
    nombre_externo_devuelve = models.CharField(
        max_length=150, 
        blank=True, 
        null=True, 
        help_text="Llenar solo si quien devuelve no es un usuario registrado."
    )

    comentarios_devolucion = models.TextField(blank=True, null=True, help_text="Ej: Pantalla rayada.")

    class Meta:
        verbose_name = "Detalle de Préstamo"
        verbose_name_plural = "Detalles de Préstamos"

    def __str__(self):
        estado = "DEVUELTO" if self.fecha_devuelto else "NO DEVUELTO"
        return f"{self.dispositivo.codigo_inventario} - {estado}"


class Sancion(models.Model):
    TIPO_SANCION = [
        ('retraso_entrega', 'Retraso en la Devolución'),
        ('equipo_danado', 'Equipo Devuelto con Daños'),
        ('extravio', 'Extravío del Equipo'),
        ('mal_uso', 'Mal Uso de Instalaciones/Equipo'),
    ]

    ESTADO_SANCION = [
        ('activa', 'Sanción Activa (Bloqueado)'),
        ('resuelta', 'Sanción Resuelta / Pagada'),
    ]

    # CASCADE: Si por alguna razón se borra el préstamo o el usuario, la sanción desaparece
    prestamo = models.ForeignKey(Prestamo, on_delete=models.CASCADE, related_name='sanciones')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='mis_sanciones')

    tipo_sancion = models.CharField(max_length=50, choices=TIPO_SANCION)
    estado = models.CharField(max_length=20, choices=ESTADO_SANCION, default='activa')
    
    observaciones = models.TextField(help_text="Describe la multa económica, penalización de días o daños específicos.")
    fecha_reporte = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Sanción"
        verbose_name_plural = "Sanciones"

    def __str__(self):
        return f"Sanción: {self.get_tipo_sancion_display()} a {self.usuario.numero_cuenta} - {self.get_estado_display()}"