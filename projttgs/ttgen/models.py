from django.db import models
from django.conf import settings
from django.utils import timezone
from django.core.validators import MinValueValidator
from django.core.exceptions import ValidationError
from django.db.models import Q
import re


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
    ("Lecture Hall", "Lecture Hall"),
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


def _normalize_single_lab_category(raw_value):
    value = (raw_value or "").strip().lower()
    aliases = {
        "lecture": "Lecture Hall",
        "lecture hall": "Lecture Hall",
        "computer": "Computer Lab",
        "computer lab": "Computer Lab",
        "electronics": "Electronics Lab",
        "electronics lab": "Electronics Lab",
        "electrical": "Electrical Lab",
        "electrical lab": "Electrical Lab",
        "mechanical": "Mechanical Workshop",
        "mechanical workshop": "Mechanical Workshop",
        "electrical workshop": "Electrical Workshop",
        "english": "English Lab",
        "english lab": "English Lab",
        "chemistry": "Chemistry Lab",
        "chemistry lab": "Chemistry Lab",
        "physics": "Physics Lab",
        "physics lab": "Physics Lab",
        "animation": "Animation Lab",
        "animation lab": "Animation Lab",
        "general": "General",
    }
    if not value:
        return ""
    return aliases.get(value, (raw_value or "").strip())


def _parse_lab_categories(raw_value):
    if not raw_value:
        return []
    categories = []
    seen = set()
    for token in re.split(r"[;\n]+", str(raw_value)):
        normalized = _normalize_single_lab_category(token)
        if not normalized:
            continue
        key = normalized.casefold()
        if key in seen:
            continue
        seen.add(key)
        categories.append(normalized)
    return categories


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
            ("Common Lecture Hall", "Common Lecture Hall"),
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
    lab_for_lecture = models.BooleanField(default=True)
    seating_capacity = models.PositiveIntegerField()

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="rooms",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["user", "department", "r_number"],
                name="unique_room_number_per_department",
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
    email = models.CharField(max_length=500)
    contact_number = models.CharField(max_length=200)
    designation = models.CharField(
        max_length=50,
        choices=DESIGNATION_CHOICES,
        default="Associate Professor",
    )
    max_workload = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        default=12,
    )
    department = models.ForeignKey(
        Department,
        on_delete=models.SET_NULL,
        related_name="instructors",
        null=True,
        blank=True,
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


class AdminTeacher(models.Model):
    DESIGNATION_CHOICES = [
        ("Professor", "Professor"),
        ("Associate Professor", "Associate Professor"),
        ("Assistant Professor", "Assistant Professor"),
    ]

    name = models.CharField(max_length=100)
    email = models.CharField(max_length=500, blank=True, default="")
    uid = models.CharField(max_length=32, blank=True, default="")
    contact_number = models.CharField(max_length=200, blank=True, default="")
    designation = models.CharField(
        max_length=50,
        choices=DESIGNATION_CHOICES,
        default="Associate Professor",
    )
    department_name = models.CharField(max_length=150, blank=True, default="")
    department_code = models.CharField(max_length=30, blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name", "uid", "id"]

    def __str__(self):
        return f"{self.name} ({self.uid})" if self.uid else self.name


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


class Subject(models.Model):
    """
    Unified model for theory + lab subjects
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="subjects",
    )
    subject_number = models.CharField(max_length=20, db_column="course_number")
    subject_name = models.CharField(max_length=100, db_column="course_name")

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="subjects",
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
    specific_rooms = models.CharField(max_length=255, blank=True, default="")
    classes_per_week = models.PositiveIntegerField(default=3)
    duration = models.PositiveIntegerField(
        default=1,
        help_text="Duration in hours (1 hour = 1 slot). e.g. 2 means 2 consecutive slots.",
    )

    instructors = models.ManyToManyField(Instructor, db_table="ttgen_course_instructors")

    class Meta:
        db_table = "ttgen_course"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "department", "subject_number"],
                name="unique_course_number_per_department",
            ),
        ]

    def __str__(self):
        return f"{self.subject_number} - {self.subject_name}"


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
    program_name = models.CharField(max_length=50, blank=True, default="")
    student_strength = models.PositiveIntegerField(default=70)

    department = models.ForeignKey(
        Department,
        on_delete=models.CASCADE,
        related_name="sections",
    )

    allowed_subjects = models.ManyToManyField(
        Subject,
        related_name="allowed_sections",
        blank=True,
        db_table="ttgen_section_allowed_courses",
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


class SectionSubjectMapping(models.Model):
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="subject_mappings",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="section_mappings",
    )
    group_count = models.PositiveIntegerField(default=1)
    elective_section_ids = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "ttgen_section_allowed_courses"
        managed = False

    def __str__(self):
        return f"{self.section.section_id} -> {self.subject.subject_name}"


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


class SectionSubjectInstructor(models.Model):
    """
    Fixed assignment: ek specific section ke ek specific subject ke liye
    ek fixed instructor. Generator is table ko use karke teacher lock karta hai.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="section_subject_instructors",
    )
    section = models.ForeignKey(
        Section,
        on_delete=models.CASCADE,
        related_name="subject_instructors",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name="section_instructors",
        db_column="course_id",
    )
    group_instructor_ids = models.JSONField(default=list, blank=True)
    group_second_instructor_ids = models.JSONField(default=list, blank=True)
    instructor = models.ForeignKey(
        Instructor,
        on_delete=models.CASCADE,
        related_name="section_subject_assignments",
    )
    second_instructor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="second_section_subject_assignments",
    )
    group_instructor_ids = models.JSONField(default=list, blank=True)
    group_second_instructor_ids = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "ttgen_sectioncourseinstructor"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "section", "subject"],
                name="unique_instructor_per_section_course",
            ),
        ]

    def __str__(self):
        return f"{self.instructor.name} → {self.subject.subject_number} ({self.section.section_id})"


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
    name = models.CharField(max_length=120, blank=True, default="")
    department = models.ForeignKey(
        "Department",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="saved_timetables",
        help_text="If set, this timetable contains only slots for this department.",
    )
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    is_published = models.BooleanField(default=False)
    publish_code = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        if self.name:
            return self.name
        dept_label = f" [{self.department.name}]" if self.department_id else ""
        return f"Timetable{dept_label} ({self.created_at.strftime('%d %b %Y %H:%M')})"


class SavedPrefill(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="saved_prefills",
    )
    name = models.CharField(max_length=120, blank=True, default="")
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        label = self.name or "Saved Prefill"
        return f"{label} ({self.updated_at.strftime('%d %b %Y %H:%M')})"


class LiveTimetable(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="live_timetables",
    )
    name = models.CharField(max_length=120, blank=True, default="")
    notes = models.TextField(blank=True, default="")
    snapshot_version = models.PositiveIntegerField(default=1)
    snapshot = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-created_at"]

    def __str__(self):
        label = self.name or "Live Timetable"
        return f"{label} ({self.updated_at.strftime('%d %b %Y %H:%M')})"


class ScheduledSlot(models.Model):
    timetable = models.ForeignKey(
        SavedTimetable,
        on_delete=models.CASCADE,
        related_name="slots",
    )

    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, db_column="course_id")
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE)
    second_instructor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="shared_lab_slots",
    )
    room = models.ForeignKey(Room, on_delete=models.CASCADE, null=True, blank=True)
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
        if not self.instructor or not self.subject:
            return

        if self.is_lab:
            if self.subject.room_required != "Lab":
                raise ValidationError({"subject": "Only lab subjects can be scheduled as labs."})

            if not self.room:
                return

            required_categories = _parse_lab_categories(self.subject.required_lab_category)
            room_category = _normalize_single_lab_category(self.room.lab_category)
            if required_categories and room_category not in required_categories:
                required_label = ", ".join(required_categories)
                raise ValidationError(
                    {
                        "room": (
                            f"{self.room.r_number} is '{room_category or 'Unspecified'}', "
                            f"but {self.subject.subject_name} requires one of '{required_label}'."
                        )
                    }
                )

            # Lab instructor must be assigned to the subject.
            if self.instructor not in self.subject.instructors.all():
                raise ValidationError(
                    {
                        "instructor": (
                            f"{self.instructor.name} is not assigned to teach "
                            f"{self.subject.subject_name}."
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


class SavedSlotRoomReservation(models.Model):
    timetable = models.ForeignKey(
        SavedTimetable,
        on_delete=models.CASCADE,
        related_name="slot_room_reservations",
    )
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    meeting_time = models.ForeignKey(MeetingTime, on_delete=models.CASCADE)
    room = models.ForeignKey(Room, on_delete=models.CASCADE)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["timetable", "section", "meeting_time"],
                name="unique_saved_slot_room_reservation",
            ),
        ]

    def __str__(self):
        return f"{self.section.section_id} {self.meeting_time.day} {self.meeting_time.time} -> {self.room.r_number}"


class SavedParkingSlot(models.Model):
    timetable = models.ForeignKey(
        SavedTimetable,
        on_delete=models.CASCADE,
        related_name="parked_slots",
    )
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, db_column="course_id")
    instructor = models.ForeignKey(Instructor, on_delete=models.CASCADE)
    second_instructor = models.ForeignKey(
        Instructor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parked_shared_lab_slots",
    )
    original_room = models.ForeignKey(Room, on_delete=models.SET_NULL, null=True, blank=True)
    original_meeting_time = models.ForeignKey(MeetingTime, on_delete=models.SET_NULL, null=True, blank=True)
    is_lab = models.BooleanField(default=False)
    slot_span = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["section__section_id", "created_at"]

    def __str__(self):
        return f"Parked {self.subject.subject_name} ({self.section.section_id})"


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


# ── Coordinator Appointment (Super Admin) ───────────────────────
class CoordinatorAppointment(models.Model):
    """
    Record of a teacher appointed by the Super Admin to a timetable
    coordination role. Persisted so the appointment can be tracked,
    listed role-wise, and reused (e.g. analytics access).
    """
    ROLE_CHOICES = [
        ("Timetable Coordinator", "Timetable Coordinator"),
        ("University Timetable Coordinator", "University Timetable Coordinator"),
    ]

    name = models.CharField(max_length=200)
    email = models.EmailField()
    role = models.CharField(max_length=80, choices=ROLE_CHOICES)
    department = models.CharField(max_length=150, blank=True, default="")
    message = models.TextField(blank=True, default="")
    appointed_by = models.CharField(max_length=200, blank=True, default="")
    analytics_access = models.BooleanField(default=False)
    email_sent = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["role", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["email", "role"],
                name="unique_appointment_email_role",
            ),
        ]

    def __str__(self):
        return f"{self.name} — {self.role}"


class UserSession(models.Model):
    """One login session for a coordinator/HOD account.

    Records when they logged in, when they were last seen active, and when
    they logged out (if they did), so the Super Admin can see login time and
    total session duration per user. Never touches the scheduling algorithm.
    """
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="login_sessions",
    )
    username = models.CharField(max_length=200, blank=True, default="")
    email = models.CharField(max_length=254, blank=True, default="")
    session_key = models.CharField(max_length=60, blank=True, default="", db_index=True)
    ip = models.CharField(max_length=60, blank=True, default="")
    user_agent = models.CharField(max_length=300, blank=True, default="")
    login_at = models.DateTimeField(default=timezone.now)
    last_seen = models.DateTimeField(default=timezone.now)
    logout_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-login_at"]

    @property
    def ended_at(self):
        return self.logout_at or self.last_seen

    @property
    def is_open(self):
        return self.logout_at is None

    @property
    def duration_seconds(self):
        return max(0, int((self.ended_at - self.login_at).total_seconds()))

    def __str__(self):
        return f"{self.username or 'user'} @ {self.login_at:%d %b %Y %H:%M}"


class ActivityLog(models.Model):
    """A single auditable action performed by a user.

    Powers the Super Admin "Recent Activity" feed: who did what, when, how
    many times, including drag-and-drop swaps, deletes, saves and exports.
    """
    ACTIONS = [
        ("login", "Logged in"),
        ("logout", "Logged out"),
        ("generate", "Generated timetable"),
        ("save", "Saved timetable"),
        ("delete", "Deleted"),
        ("export", "Exported"),
        ("move", "Moved slot (drag & drop)"),
        ("park", "Parked slot"),
        ("restore", "Restored slot"),
        ("add", "Added slot"),
        ("edit", "Edited slot"),
        ("substitute", "Substituted teacher"),
        ("publish", "Published"),
        ("unpublish", "Unpublished"),
        ("other", "Activity"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activity_logs",
    )
    username = models.CharField(max_length=200, blank=True, default="")
    email = models.CharField(max_length=254, blank=True, default="")
    action = models.CharField(max_length=20, choices=ACTIONS, default="other", db_index=True)
    summary = models.CharField(max_length=300, blank=True, default="")
    detail = models.TextField(blank=True, default="")
    path = models.CharField(max_length=300, blank=True, default="")
    method = models.CharField(max_length=8, blank=True, default="")
    session_key = models.CharField(max_length=60, blank=True, default="")
    ip = models.CharField(max_length=60, blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["action", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.username or 'user'}: {self.action} @ {self.created_at:%d %b %H:%M}"