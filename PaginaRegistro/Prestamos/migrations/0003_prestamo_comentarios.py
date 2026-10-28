from django.db import migrations, models


def copiar_comentarios_devolucion(apps, schema_editor):
    Prestamo = apps.get_model('Prestamos', 'Prestamo')
    for prestamo in Prestamo.objects.all():
        lineas = []
        vistos = set()
        detalles = prestamo.detalles.filter(
            fecha_devuelto__isnull=False, comentarios_devolucion__isnull=False
        ).order_by('fecha_devuelto', 'id')
        for detalle in detalles:
            texto = detalle.comentarios_devolucion.strip()
            clave = (detalle.fecha_devuelto, texto)
            if texto and clave not in vistos:
                vistos.add(clave)
                sello = detalle.fecha_devuelto.strftime('%d/%m/%Y %H:%M')
                lineas.append(f'[{sello}] (Devolución) {texto}')
        if lineas:
            prestamo.comentarios = '\n'.join(lineas)
            prestamo.save(update_fields=['comentarios'])


class Migration(migrations.Migration):

    dependencies = [
        ('Prestamos', '0002_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='prestamo',
            name='comentarios',
            field=models.TextField(blank=True, default='', verbose_name='Comentarios del préstamo'),
        ),
        migrations.RunPython(copiar_comentarios_devolucion, migrations.RunPython.noop),
    ]
