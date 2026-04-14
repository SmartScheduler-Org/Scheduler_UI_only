from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ttgen', '0002_useraccessplan'),
    ]

    operations = [
        migrations.CreateModel(
            name='TeacherPreference',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=200)),
                ('email', models.EmailField(max_length=254)),
                ('designation', models.CharField(choices=[('Professor', 'Professor'), ('Associate Professor', 'Associate Professor'), ('Assistant Professor', 'Assistant Professor')], max_length=50)),
                ('subjects', models.JSONField(default=list)),
                ('classes', models.JSONField(default=list)),
                ('years', models.JSONField(default=list)),
                ('submitted_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'ordering': ['-submitted_at'],
            },
        ),
    ]
