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
    contact_number = models.CharField(max_length=20, blank=True, default='')
    linked_instructor = models.OneToOneField(
        'ttgen.Instructor',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teacher_account_profile',
    )
    active_timetable = models.ForeignKey(
        'ttgen.SavedTimetable',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='teacher_account_profiles',
    )

    def __str__(self):
        return f'Profile for user {self.user.username}'


class TeacherOnboarding(models.Model):
    DESIGNATION_CHOICES = [
        ("Professor", "Professor"),
        ("Associate Professor", "Associate Professor"),
        ("Assistant Professor", "Assistant Professor"),
        ("Lab Worker", "Lab Worker"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="teacher_onboarding",
    )
    full_name = models.CharField(max_length=150)
    designation = models.CharField(max_length=50, choices=DESIGNATION_CHOICES)
    joining_year = models.PositiveIntegerField()
    email = models.EmailField()
    subjects_taught = models.TextField()
    requires_resubmission = models.BooleanField(default=False)
    resubmission_requested_at = models.DateTimeField(blank=True, null=True)
    submitted_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-submitted_at"]

    def __str__(self):
        return f"{self.full_name} ({self.user.username})"
