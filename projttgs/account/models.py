from django.db import models
from django.conf import settings


class Profile(models.Model):
    ROLE_CHOICES = [
        ('hod', 'HOD'),
        ('teacher', 'Teacher'),
        ('dean', 'Dean'),
    ]
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    role = models.CharField(max_length=10, choices=ROLE_CHOICES, blank=True, default='')
    date_of_birth = models.DateField(blank=True, null=True)
    photo = models.ImageField(upload_to='users/%Y/%m/%d/', blank=True)

    def __str__(self):
        return f'Profile for user {self.user.username}'