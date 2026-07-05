from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ttgen", "0007_adminteacher"),
    ]

    operations = [
        migrations.AddField(
            model_name="savedtimetable",
            name="name",
            field=models.CharField(blank=True, default="", max_length=120),
        ),
        migrations.AddField(
            model_name="savedtimetable",
            name="snapshot",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
