from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('audio', '0007_rejilla_manual'),
    ]

    operations = [
        migrations.AddField(
            model_name='track',
            name='genre',
            field=models.CharField(blank=True, help_text='Genero de la pista (merengue, bachata, salsa...), en minusculas; lo pone el DJ y da contexto al estilo.', max_length=40),
        ),
    ]
