from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ttgen", "0008_savedtimetable_name_snapshot"),
    ]

    operations = [
        migrations.RemoveConstraint(
            model_name="room",
            name="unique_room_number_per_user",
        ),
        migrations.AddConstraint(
            model_name="room",
            constraint=models.UniqueConstraint(
                fields=("user", "department", "r_number"),
                name="unique_room_number_per_department",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="subject",
            name="unique_course_number_per_user",
        ),
        migrations.AddConstraint(
            model_name="subject",
            constraint=models.UniqueConstraint(
                fields=("user", "department", "subject_number"),
                name="unique_course_number_per_department",
            ),
        ),
    ]
