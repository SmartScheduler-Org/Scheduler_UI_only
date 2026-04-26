from django.db import models
from django.conf import settings
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Q


# ==============================
# CONSTANTS
# ==============================

TIME_SLOTS = [(str(i), str(i)) for i in range(1, 10)]

DAYS_OF_WEEK = (
    ("Monday", "Monday"),
    ("Tuesday", "Tuesday"),
    ("Wednesday", "Wednesday"),
    ("Thursday", "Thursday"),
    ("Friday", "Friday"),
)

LAB_CATEGORY_CHOICES = (
    ("General", "General"),
    ("Electronics Lab", "Electronics Lab"),
    ("Electrical Lab", "Electrical Lab"),
    ("Mechanical Workshop", "Mechanical Workshop"),
    ("Electrical Workshop", "Electrical Workshop"),
    ("English Lab", "English Lab"),
    ("Chemistry Lab", "Chemistry Lab"),
    ("Physics Lab", "Physics Lab"),
    ("Animation Lab", "Animation Lab"),
)


# ==============================
# CORE MASTER TABLES
# ==============================

class Department(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="departments",
    )
    name = models.CharField(max_length=100, default="Computer Science")
    code = models.CharField(max_length=10, default="CS")

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "code"],
                name="unique_dept_code_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.name} ({self.code})"


class Room(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="rooms",
    )
    r_number = models.CharField(max_length=50)
    room_type = models.CharField(
        max_length=20,
        choices=[
            ("Lecture Hall", "Lecture Hall"),
            ("Lab", "Lab"),
            ("Seminar Room", "Seminar Room"),
        ],
    )
    lab_category = models.CharField(
        max_length=50,
        choices=LAB_CATEGORY_CHOICES,
        blank=True,
        default="",
    )
    seating_capacity = models.PositiveIntegerField()

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="rooms",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "r_number"],
                name="unique_room_number_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.r_number} - {self.room_type}"


class Instructor(models.Model):
    DESIGNATION_CHOICES = [
        ("Professor", "Professor"),
        ("Associate Professor", "Associate Professor"),
        ("Assistant Professor", "Assistant Professor"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="instructors",
    )
    uid = models.CharField(max_length=6)
    name = models.CharField(max_length=100)
    designation = models.CharField(
        max_length=50,
        choices=DESIGNATION_CHOICES,
        default="Associate Professor",
    )
    max_workload = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        default=12,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "uid"],
                name="unique_instructor_uid_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.uid} - {self.name}"


class MeetingTime(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="meeting_times",
    )
    pid = models.CharField(max_length=5)
    day = models.CharField(max_length=15, choices=DAYS_OF_WEEK)
    time = models.CharField(max_length=2, choices=TIME_SLOTS)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "pid"],
                name="unique_meetingtime_pid_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.day} - Slot {self.time}"


class Course(models.Model):
    """
    Unified model for theory + lab courses
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="courses",
    )
    course_number = models.CharField(max_length=20)
    course_name = models.CharField(max_length=100)

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="courses",
    )

    max_numb_students = models.PositiveIntegerField()
    room_required = models.CharField(
        max_length=20,
        choices=[
            ("Lecture Hall", "Lecture Hall"),
            ("Lab", "Lab"),
        ],
    )
    required_lab_category = models.CharField(
        max_length=50,
        choices=LAB_CATEGORY_CHOICES,
        blank=True,
        default="",
    )
    classes_per_week = models.PositiveIntegerField(default=3)

    instructors = models.ManyToManyField(Instructor)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "course_number"],
                name="unique_course_number_per_user",
            ),
        ]

    def __str__(self):
        return f"{self.course_number} - {self.course_name}"


class Section(models.Model):
    """
    Example: CE21 2nd Sem, IT 6th Sem, BCA 4th
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sections",
    )
    section_id = models.CharField(max_length=50)
    student_strength = models.PositiveIntegerField(default=70)

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="sections",
    )

    allowed_courses = models.ManyToManyField(
        Course,
        related_name="allowed_sections",
        blank=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "section_id"],
                name="unique_section_id_per_user",
            ),
        ]

    def __str__(self):
        return self.section_id


class TeacherSection(models.Model):
    instructor = models.ForeignKey(
        Instructor,
        on_delete=models.CASCADE,
        related_name="section_mappings",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="teacher_mappings",
    )

    class Meta:
        unique_together = ("instructor", "section")

    def __str__(self):
        return f"{self.instructor.name} -> {self.section.section_id}"


# ==============================
# TIMETABLE STORAGE
# ==============================

class SavedTimetable(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
    )
    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saved_timetables",
        help_text="If set, this timetable contains only slots for this department.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False)
    publish_code = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        dept_label = f" [{self.department.name}]" if self.department_id else ""
        return f"Timetable{dept_label} ({self.created_at.strftime('%d %b %Y %H:%M')})"


class ScheduledSlot(models.Model):
    timetable = models.ForeignKey(
        SavedTimetable,
        on_delete=models.CASCADE,
        related_name="slots",
    )

    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    course = models.ForeignKey(Course, on_delete=models.CASCADE)
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)
    meeting_time = models.ForeignKey(MeetingTime, on_delete=models.CASCADE)

    is_lab = models.BooleanField(default=False)

    lab_slots = models.ManyToManyField(
        MeetingTime,
        related_name="lab_extra_slots",
        blank=True,
    )

    class Meta:
        constraints = [
            # Keep theory slots unique per section and start slot.
            models.UniqueConstraint(
                fields=["timetable", "section", "meeting_time"],
                condition=Q(is_lab=False),
                name="unique_theory_per_section_slot",
            ),
        ]

    def clean(self):
        """
        HARD VALIDATIONS (THEORY vs LAB AWARE)
        """

        # COMMON: instructor must exist
        if not self.instructor or not self.course:
            return

        if self.is_lab:
            if self.course.room_required != "Lab":
                raise ValidationError({"course": "Only lab courses can be scheduled as labs."})

            required_category = (self.course.required_lab_category or "").strip()
            room_category = (self.room.lab_category or "").strip()
            if required_category and required_category != room_category:
                raise ValidationError(
                    {
                        "room": (
                            f"{self.room.r_number} is '{room_category or 'Unspecified'}', "
                            f"but {self.course.course_name} requires '{required_category}'."
                        )
                    }
                )

            # Lab instructor must be assigned to the course.
            if self.instructor not in self.course.instructors.all():
                raise ValidationError(
                    {
                        "instructor": (
                            f"{self.instructor.name} is not assigned to teach "
                            f"{self.course.course_name}."
                        )
                    }
                )

            # Do not enforce section mapping for labs.
            return

        # Theory instructor must be assigned to section.
        if not TeacherSection.objects.filter(
            instructor=self.instructor,
            section=self.section,
        ).exists():
            raise ValidationError(
                {
                    "instructor": (
                        f"{self.instructor.name} is not assigned to "
                        f"{self.section.section_id}."
                    )
                }
            )


class TimetableChangeLog(models.Model):
    ACTION_ADD = "ADD"
    ACTION_UPDATE = "UPDATE"
    ACTION_DELETE = "DELETE"
    ACTION_MOVE = "MOVE"
    ACTION_SUBSTITUTE = "SUBSTITUTE"
    ACTION_SUBSTITUTE_LAB = "SUBSTITUTE_LAB"

    ACTION_CHOICES = [
        (ACTION_ADD, "Add"),
        (ACTION_UPDATE, "Update"),
        (ACTION_DELETE, "Delete"),
        (ACTION_MOVE, "Move"),
        (ACTION_SUBSTITUTE, "Substitute"),
        (ACTION_SUBSTITUTE_LAB, "Substitute Lab"),
    ]

    timetable = models.ForeignKey(
        SavedTimetable,
        on_delete=models.CASCADE,
        related_name="change_logs",
        null=True,
        blank=True,
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="timetable_change_logs",
    )
    action_type = models.CharField(max_length=32, choices=ACTION_CHOICES)
    reason = models.TextField()
    section = models.CharField(max_length=120, blank=True, default="")
    day = models.CharField(max_length=20, blank=True, default="")
    slot = models.CharField(max_length=20, blank=True, default="")
    before_snapshot = models.JSONField(default=dict, blank=True)
    after_snapshot = models.JSONField(default=dict, blank=True)
    source = models.CharField(max_length=24, blank=True, default="saved")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        when = self.created_at.strftime("%d %b %Y %H:%M")
        return f"{self.action_type} | {self.section} {self.day} {self.slot} | {when}"


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="ttgen_profile",
    )
    role = models.CharField(max_length=50, default="User")
    avatar = models.ImageField(upload_to="avatars/", default="default-avatar.png")

    def __str__(self):
        return self.user.username


class UserAccessPlan(models.Model):
    PLAN_BASIC = "basic"
    PLAN_PRO = "pro"
    PLAN_CHOICES = [
        (PLAN_BASIC, "Basic"),
        (PLAN_PRO, "Pro"),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="access_plan",
    )
    plan_code = models.CharField(max_length=20, choices=PLAN_CHOICES, blank=True, default="")
    plan_name = models.CharField(max_length=100, blank=True, default="")
    amount_paid = models.PositiveIntegerField(default=0)
    generations_total = models.PositiveIntegerField(default=0)
    generations_used = models.PositiveIntegerField(default=0)
    can_edit_delete = models.BooleanField(default=False)
    can_substitute = models.BooleanField(default=False)
    can_drag_drop = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    razorpay_order_id = models.CharField(max_length=100, blank=True, default="")
    razorpay_payment_id = models.CharField(max_length=100, blank=True, default="")
    purchased_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "User access plan"
        verbose_name_plural = "User access plans"

    @property
    def generations_remaining(self):
        return max(self.generations_total - self.generations_used, 0)

    def __str__(self):
        if self.plan_name:
            return f"{self.user.username} - {self.plan_name}"
        return self.user.username


# ── Teacher Preference ──────────────────────────────────────────
class TeacherPreference(models.Model):
    DESIGNATION_CHOICES = [
        ('Professor', 'Professor'),
        ('Associate Professor', 'Associate Professor'),
        ('Assistant Professor', 'Assistant Professor'),
    ]
    name         = models.CharField(max_length=200)
    email        = models.EmailField()
    designation  = models.CharField(max_length=50, choices=DESIGNATION_CHOICES)
    subjects     = models.JSONField(default=list)
    classes      = models.JSONField(default=list)
    years        = models.JSONField(default=list)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.name} ({self.email})"
