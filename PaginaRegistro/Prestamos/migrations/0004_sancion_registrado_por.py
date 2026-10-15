from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('Prestamos', '0003_prestamo_comentarios'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='sancion',
            name='registrado_por',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='sanciones_registradas',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Staff que registró la sanción',
            ),
        ),
    ]
