from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from .forms import *
from .models import *
from account.models import Profile
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.generic import View
import random as rnd
from django.contrib import messages
import os
import json
import requests
from django.http import HttpResponseForbidden, Http404
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.conf import settings
import copy
import csv
import math
import re
from itertools import combinations
from .models import MeetingTime
from .models import DAYS_OF_WEEK, TIME_SLOTS
from .forms import DepartmentForm
from ttgen.utils import section_sort_key


import random as rnd


# ---------------- PER-USER STATE ----------------
_USER_STATE = {}  # {user_id: {"classes": ..., "labs": ..., "schedules": [...], "view_mode": ..., "data": ...}}


def _get_user_state(user_id):
    """Get or create per-user in-memory state."""
    if user_id not in _USER_STATE:
        _USER_STATE[user_id] = {
            "classes": None,
            "labs": None,
            "schedules": [],
            "view_mode": None,
            "data": None,
        }
    return _USER_STATE[user_id]


# Legacy aliases so private modules loaded via exec() can reference them.
# These are updated by show_timetable / generate to point at the current user's data.
GLOBAL_CLASSES = None
GLOBAL_LABS = None
GLOBAL_GENERATED_SCHEDULES = []
CURRENT_VIEW_MODE = None

POPULATION_SIZE = 3
USE_PSO_REFINEMENT = True
NUMB_OF_ELITE_SCHEDULES = 1
TOURNAMENT_SELECTION_SIZE = 2
MUTATION_RATE = 0.05

LAB_DURATION = 4
VALID_LAB_START_SLOTS = ["1", "6"]
LUNCH_SLOT = "5"




# placeholder for private generation algorithm loaded outside this repo
data = None
GENERATOR_RULES_AVAILABLE = False
GENERATOR_ALGO_AVAILABLE = False
GENERATOR_RUNTIME_AVAILABLE = False


def _private_file_path(env_var, filename):
    configured_path = os.environ.get(env_var)
    if configured_path:
        return os.path.expanduser(configured_path)
    configured_dir = os.environ.get("TTGEN_PRIVATE_DIR")
    if configured_dir:
        return os.path.join(os.path.expanduser(configured_dir), filename)
    return os.path.join(os.path.expanduser("~"), ".ttgen_private", filename)


def _load_private_generator_rules():
    global GENERATOR_RULES_AVAILABLE

    rules_path = _private_file_path("TTGEN_RULES_PATH", "views_other_rules.py")
    if not os.path.exists(rules_path):
        return

    with open(rules_path, "r", encoding="utf-8") as rules_file:
        code = compile(rules_file.read(), rules_path, "exec")

    exec(code, globals())
    GENERATOR_RULES_AVAILABLE = True


def _load_private_generator_algo():
    global GENERATOR_ALGO_AVAILABLE

    algo_path = _private_file_path("TTGEN_ALGO_PATH", "views_other_algorithm.py")
    if not os.path.exists(algo_path):
        return

    with open(algo_path, "r", encoding="utf-8") as algo_file:
        code = compile(algo_file.read(), algo_path, "exec")

    exec(code, globals())
    GENERATOR_ALGO_AVAILABLE = True


def _load_private_generator_runtime():
    global GENERATOR_RUNTIME_AVAILABLE

    runtime_path = _private_file_path("TTGEN_RUNTIME_PATH", "views_other_runtime.py")
    if not os.path.exists(runtime_path):
        return

    with open(runtime_path, "r", encoding="utf-8") as runtime_file:
        code = compile(runtime_file.read(), runtime_path, "exec")

    exec(code, globals())
    GENERATOR_RUNTIME_AVAILABLE = True


_load_private_generator_rules()
_load_private_generator_algo()
_load_private_generator_runtime()

def ensure_cs_department(user=None):
    if user:
        department, _ = Department.objects.get_or_create(
            user=user,
            code="CS",
            defaults={"name": "Computer Science"},
        )
    else:
        department, _ = Department.objects.get_or_create(
            code="CS",
            defaults={"name": "Computer Science"},
        )
    return department




SECTION_SEMESTER_PATTERN = re.compile(r"(\d+(?:st|nd|rd|th)\s+sem)", re.IGNORECASE)


def get_section_signature(section_id):
    raw = (section_id or "").strip().lower()
    match = SECTION_SEMESTER_PATTERN.search(raw)
    semester = match.group(1).lower() if match else ""
    prefix = raw[:match.start()] if match else raw
    tokens = []
    for token in prefix.split():
        normalized = re.sub(r"[^a-z]+", "", token)
        if normalized:
            tokens.append(normalized)
    return semester, tuple(tokens)


def clone_section_courses_from_similar(section):
    if section.allowed_courses.exists():
        return None

    semester, tokens = get_section_signature(section.section_id)
    if not semester or not tokens:
        return None

    best_match = None
    best_score = None

    candidates = (
        Section.objects.filter(department=section.department, user=section.user)
        .exclude(pk=section.pk)
        .prefetch_related("allowed_courses")
    )
    for candidate in candidates:
        if not candidate.allowed_courses.exists():
            continue
        candidate_semester, candidate_tokens = get_section_signature(candidate.section_id)
        if candidate_semester != semester:
            continue
        overlap = len(set(tokens) & set(candidate_tokens))
        if overlap <= 0:
            continue
        score = (overlap, candidate.allowed_courses.count(), -len(candidate.section_id))
        if best_score is None or score > best_score:
            best_score = score
            best_match = candidate

    if not best_match:
        return None

    courses_to_copy = list(best_match.allowed_courses.all())
    if not courses_to_copy:
        return None

    section.allowed_courses.add(*courses_to_copy)
    return best_match





# BASIC NAVIGATION VIEWS
def index(request): return render(request, 'index.html')
def about(request): return render(request, 'aboutus.html')
def help(request): return render(request, 'help.html')
def terms(request): return render(request, 'terms.html')
def privacy(request): return render(request, 'privacy.html')
def role(request):
    if request.user.is_authenticated:
        profile, _ = Profile.objects.get_or_create(user=request.user)
        role_value = (profile.role or "").strip().lower()
        if role_value:
            # Already has a role and should be sent to that role's page.
            if role_value == 'hod':
                return redirect('admindash')
            elif role_value == 'teacher':
                return redirect('teachertimetable_list')
            elif role_value == 'dean':
                return redirect('teachertimetable')
    return render(request, 'role.html')

@login_required
def admindash_role_set(request):
    """Set role to HOD and redirect to dashboard."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if profile.role and profile.role != 'hod':
        return render(request, 'role_locked.html', {'current_role': profile.get_role_display()})
    profile.role = 'hod'
    profile.save()
    return redirect('admindash')


@login_required
def teacher_role_set(request):
    """Set role to Teacher and redirect."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if profile.role and profile.role != 'teacher':
        return render(request, 'role_locked.html', {'current_role': profile.get_role_display()})
    profile.role = 'teacher'
    profile.save()
    return redirect('teachertimetable_list')


@login_required
def dean_role_set(request):
    """Set role to Dean and redirect."""
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if profile.role and profile.role != 'dean':
        return render(request, 'role_locked.html', {'current_role': profile.get_role_display()})
    profile.role = 'dean'
    profile.save()
    return redirect('teachertimetable')


def teacherlogin(request): return render(request, 'teacherlogin.html')
def deanlogin(request): return render(request, 'deanlogin.html')
def teachertimetable(request): return render(request, 'teachertimetable.html')

# CONTACT FORM
def contact(request):
    if request.method == 'POST':
        message = request.POST['message']
        send_mail(
            'Contact',
            message,
            settings.EMAIL_HOST_USER,
            ['studyyou40@gmail.com'],
            fail_silently=False
        )
    return render(request, 'contact.html')


# ADMIN DASHBOARD
@login_required
def admindash(request):
    context = {
        'teacher_count': Instructor.objects.filter(user=request.user).count(),
        'department_count': Department.objects.filter(user=request.user).count(),
        'class_count': Section.objects.filter(user=request.user).count(),
    }
    return render(request, 'admindashboard.html', context)


# Helper to reset GA cache when admin modifies models
def reset_global_schedule_cache(user_id=None):
    global data, GLOBAL_GENERATED_SCHEDULES, GLOBAL_CLASSES, GLOBAL_LABS
    if user_id is not None:
        state = _get_user_state(user_id)
        state["data"] = None
        state["schedules"] = []
        state["classes"] = None
        state["labs"] = None
    # Also clear legacy globals
    data = None
    GLOBAL_GENERATED_SCHEDULES = []
    GLOBAL_CLASSES = None
    GLOBAL_LABS = None
    # Clear the algorithm data cache for this user
    if "reset_user_data_cache" in globals() and user_id is not None:
        reset_user_data_cache(user_id)


def _runtime_unavailable_response(request):
    messages.error(request, "You are not able to access this feature right now. Please contact your administrator.")
    return redirect("generate")


if "SLOT_LABELS" not in globals():
    SLOT_LABELS = {
        "1": "8:30 - 9:30",
        "2": "9:30 - 10:30",
        "3": "10:30 - 11:30",
        "4": "11:30 - 12:30",
        "5": "12:30 - 1:30",
        "6": "1:30 - 2:30",
        "7": "2:30 - 3:30",
        "8": "3:30 - 4:30",
        "9": "4:30 - 5:30",
    }


if "DAYS" not in globals():
    DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]


if "Class" not in globals():
    class Class:
        def __init__(self, id, dept, section, course):
            self.section_id = id
            self.department = dept
            self.course = course
            self.instructor = None
            self.meeting_time = None
            self.room = None
            self.section = section

        def set_instructor(self, instructor): self.instructor = instructor
        def set_meetingTime(self, mt): self.meeting_time = mt
        def set_room(self, room): self.room = room


if "Lab" not in globals():
    class Lab:
        def __init__(self, id, dept, section, course, batch=1, total_batches=1):
            self.section_id = id
            self.department = dept
            self.course = course
            self.instructor = None
            self.room = None
            self.section = section
            self.duration = LAB_DURATION
            self.meeting_times = []
            self.batch = batch
            self.total_batches = total_batches

        def set_instructor(self, instructor): self.instructor = instructor
        def set_meetingTimes(self, mts): self.meeting_times = mts
        def set_room(self, room): self.room = room


if "build_section_tables" not in globals():
    def build_section_tables(all_classes, all_labs):
        return []


if "build_teacher_tables" not in globals():
    def build_teacher_tables(all_classes, all_labs):
        return []


if "build_room_tables" not in globals():
    def build_room_tables(all_classes, all_labs):
        return []


if "timetable" not in globals():
    def timetable(request):
        return _runtime_unavailable_response(request)


if "get_meeting_time" not in globals():
    def get_meeting_time(day, slot, user=None):
        if slot is None:
            return None
        try:
            slot_str = str(int(slot))
        except (TypeError, ValueError):
            return None
        qs = MeetingTime.objects.filter(day=day, time=slot_str)
        if user:
            qs = qs.filter(user=user)
        return qs.first()


for _runtime_view_name in (
    "delete_slot",
    "add_slot",
    "update_slot",
    "move_slot_dragdrop",
    "substitute_teacher",
    "substitute_lab_teacher",
    "save_timetable",
    "saved_timetable",
    "saved_timetable_list",
    "teachertimetable_list",
    "saved_teacher_timetable",
    "saved_delete_slot",
    "saved_add_slot",
    "saved_update_slot",
):
    if _runtime_view_name not in globals():
        def _fallback_runtime_view(request, *args, **kwargs):
            return _runtime_unavailable_response(request)
        globals()[_runtime_view_name] = _fallback_runtime_view


# ---------------- CRUD VIEWS ----------------
import csv
from django.contrib import messages
from django.shortcuts import redirect, render
from django.db import transaction

@login_required
def addCourses(request):
    form = CourseForm(request.POST or None, user=request.user)

    # ============================
    # MANUAL ADD COURSE
    # ============================
    if request.method == "POST" and "add_course" in request.POST:
        if form.is_valid():
            course = form.save(commit=False)
            course.user = request.user
            course.room_required = (course.room_required or "").strip()
            course.required_lab_category = normalize_lab_category(course.required_lab_category)

            if course.room_required == "Lab" and not course.required_lab_category:
                messages.error(request, "Lab courses must have a Required Lab Category.")
                return redirect("addCourses")
            if course.room_required != "Lab":
                course.required_lab_category = ""

            # Auto-set classes per week
            if course.room_required == "Lab":
                course.classes_per_week = 4
            else:
                course.classes_per_week = 3

            course.save()
            form.save_m2m()

            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Course added successfully!")
            return redirect("addCourses")

    # ============================
    # CSV UPLOAD COURSES (FIXED)
    # ============================
    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file or not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a valid CSV file.")
            return redirect("addCourses")

        try:
            decoded_file = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded_file)

            # ✅ REQUIRED columns (MATCH YOUR CSV)
            required_columns = [
                "department_code",
                "course_number",
                "course_name",
                "room_required",
                "required_lab_category",
                "classes_per_week",
            ]

            # Header validation
            for col in required_columns:
                if col not in reader.fieldnames:
                    messages.error(request, f"Missing required column: {col}")
                    return redirect("addCourses")

            created_count = 0

            with transaction.atomic():
                for row in reader:
                    dept_code = row["department_code"].strip().upper()
                    course_number = row["course_number"].strip()
                    room_required = row["room_required"].strip()
                    required_lab_category = normalize_lab_category(row["required_lab_category"])

                    try:
                        course_department = Department.objects.get(code=dept_code, user=request.user)
                    except Department.DoesNotExist:
                        raise ValueError(f"Department with code '{dept_code}' does not exist.")

                    # Skip duplicates
                    if Course.objects.filter(course_number=course_number, user=request.user).exists():
                        continue

                    if room_required == "Lab" and not required_lab_category:
                        raise ValueError(
                            f"Course '{course_number}' is a Lab but required_lab_category is blank."
                        )
                    if room_required != "Lab":
                        required_lab_category = ""

                    course = Course.objects.create(
                        user=request.user,
                        course_number=course_number,
                        course_name=row["course_name"].strip(),
                        department=course_department,
                        room_required=room_required,
                        required_lab_category=required_lab_category,
                        classes_per_week=int(row["classes_per_week"]),
                        max_numb_students=int(row.get("max_numb_students", 70) or 70),
                    )

                    created_count += 1

            reset_global_schedule_cache(request.user.id)
            messages.success(
                request, f"{created_count} courses uploaded successfully!"
            )

        except Exception as e:
            messages.error(request, f"CSV upload failed: {str(e)}")

        return redirect("addCourses")

    return render(request, "addCourses.html", {"form": form})




@login_required
def course_list_view(request):
    return render(request, 'courseslist.html', {'courses': Course.objects.filter(user=request.user)})


@login_required
def delete_course(request, pk):
    if request.method == 'POST':
        Course.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editcourse')


@login_required
def addInstructor(request):
    form = InstructorForm(request.POST or None)

    # ================================
    # FETCH FROM ERP API
    # ================================
    if request.method == "POST" and "fetch_api" in request.POST:
        url = "http://localhost:1000/api/teachers/"
        try:
            response = requests.get(url)
            response.raise_for_status()
            request.session["api_teachers"] = response.json()
            messages.success(request, "Teachers fetched successfully!")
        except Exception as e:
            print("API ERROR:", e)
            messages.error(request, "Failed to fetch teachers from API.")
        return redirect("addInstructors")

    # ================================
    # CONFIRM ADD FROM API
    # ================================
    if request.method == "POST" and "confirm_add_api" in request.POST:
        data = request.session.get("api_teachers", [])
        added = 0

        for t in data:
            uid = t.get("teacherId")
            name = t.get("teacherName")

            if uid and name and not Instructor.objects.filter(uid=uid, user=request.user).exists():
                designation, workload = teacher_payload(name)
                Instructor.objects.create(
                    user=request.user,
                    uid=uid,
                    name=name,
                    designation=designation,
                    max_workload=workload,
                )
                added += 1

        request.session["api_teachers"] = []
        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} teachers added successfully!")
        return redirect("addInstructors")

    # ================================
    # MANUAL ADD TEACHER
    # ================================
    if request.method == "POST" and "add_teacher" in request.POST:
        if form.is_valid():
            instructor = form.save(commit=False)
            instructor.user = request.user
            instructor.save()
            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Teacher added successfully!")
        else:
            messages.error(request, "Invalid input.")
        return redirect("addInstructors")

    # ================================
    # CSV UPLOAD
    # ================================
    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file or not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a valid CSV file.")
            return redirect("addInstructors")

        import csv
        reader = csv.reader(csv_file.read().decode("utf-8").splitlines())

        first = True

        added = 0
        for row in reader:
            if not row or len(row) < 2:
                continue

            if first:
                first = False
                continue

            uid, name = row[0].strip(), row[1].strip()
            designation = row[2].strip() if len(row) > 2 else ""
            max_workload = row[3].strip() if len(row) > 3 else ""
            if uid and name and not Instructor.objects.filter(uid=uid, user=request.user).exists():
                resolved_designation, resolved_workload = teacher_payload(
                    name,
                    designation,
                    max_workload,
                )
                Instructor.objects.create(
                    user=request.user,
                    uid=uid,
                    name=name,
                    designation=resolved_designation,
                    max_workload=resolved_workload,
                )
                added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} teachers imported successfully!")
        return redirect("addInstructors")

    popup_data = request.session.get("api_teachers", [])
    return render(request, "addInstructors.html", {
        "form": form,
        "popup_data": popup_data,
    })

@login_required
def map_section_courses(request):
    sections = Section.objects.filter(user=request.user).order_by("section_id")
    courses = Course.objects.filter(user=request.user).order_by("course_number")

    def resolve_section(section_identifier):
        section_identifier = (section_identifier or "").strip()
        if not section_identifier:
            raise Section.DoesNotExist

        try:
            return Section.objects.get(section_id=section_identifier, user=request.user)
        except Section.DoesNotExist:
            if section_identifier.isdigit():
                return Section.objects.get(pk=int(section_identifier), user=request.user)
            raise

    if request.method == "POST" and "manual_add" in request.POST:
        section_identifier = request.POST.get("section_id", "").strip()
        selected_course_ids = request.POST.getlist("courses")

        if not section_identifier or not selected_course_ids:
            messages.error(request, "Please select a section and at least one subject.")
            return redirect("map_section_courses")

        try:
            section = resolve_section(section_identifier)
        except Section.DoesNotExist:
            messages.error(request, f"Section not found: {section_identifier}")
            return redirect("map_section_courses")

        valid_courses = list(Course.objects.filter(pk__in=selected_course_ids, user=request.user))
        if not valid_courses:
            messages.error(request, "No valid subjects were selected.")
            return redirect("map_section_courses")

        for course in valid_courses:
            section.allowed_courses.add(course)

        reset_global_schedule_cache(request.user.id)
        messages.success(
            request,
            f"{len(valid_courses)} subject mappings saved for {section.section_id}."
        )
        return redirect("map_section_courses")

    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "No CSV file selected.")
            return redirect("map_section_courses")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file format. Upload CSV only.")
            return redirect("map_section_courses")

        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        skipped = 0
        first = True

        for row in reader:
            if not row or len(row) < 2:
                continue

            if first:
                first = False
                continue

            section_identifier = row[0].strip()
            course_number = row[1].strip()

            try:
                section = resolve_section(section_identifier)
                course = Course.objects.get(course_number=course_number, user=request.user)
            except (Section.DoesNotExist, Course.DoesNotExist):
                skipped += 1
                continue

            if course in section.allowed_courses.all():
                skipped += 1
                continue

            section.allowed_courses.add(course)
            added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(
            request,
            f"{added} section-subject mappings added. {skipped} skipped."
        )
        return redirect("map_section_courses")

    return render(request, "map_section_courses.html", {
        "sections": sections,
        "courses": courses
    })


@login_required
def view_section_courses(request):
    sections = (
        Section.objects.filter(user=request.user)
        .order_by("section_id")
        .prefetch_related("allowed_courses")
    )
    section_mappings = [
        {
            "section_id": section.section_id,
            "courses": list(section.allowed_courses.all().order_by("course_number")),
        }
        for section in sections
    ]
    return render(
        request,
        "view_section_courses.html",
        {"section_mappings": section_mappings},
    )

@login_required
def map_teacher_courses(request):
    """
    CSV Upload:
    instructor_name,course_number
    """

    # =========================
    # CSV UPLOAD HANDLER
    # =========================
    if request.method == "POST" and "csv_upload" in request.POST:

        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "No CSV file selected.")
            return redirect("map_teacher_courses")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file format. Upload CSV only.")
            return redirect("map_teacher_courses")

        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        skipped = 0
        first = True

        for row in reader:
            # Skip empty rows
            if not row or len(row) < 2:
                continue

            # Skip header row
            if first:
                first = False
                continue

            instructor_name = row[0].strip()
            course_number = row[1].strip()

            # -------------------------
            # VALIDATION
            # -------------------------
            try:
                instructor = Instructor.objects.get(name=instructor_name, user=request.user)
            except Instructor.DoesNotExist:
                try:
                    instructor = Instructor.objects.get(uid=instructor_name, user=request.user)
                except Instructor.DoesNotExist:
                    skipped += 1
                    continue
            except Instructor.MultipleObjectsReturned:
                skipped += 1
                continue

            try:
                course = Course.objects.get(course_number=course_number, user=request.user)
            except Course.DoesNotExist:
                skipped += 1
                continue

            # -------------------------
            # ADD MAPPING (SAFE)
            # -------------------------
            if instructor not in course.instructors.all():
                course.instructors.add(instructor)
                added += 1
            else:
                skipped += 1

        messages.success(
            request,
            f"{added} teacher–subject mappings added. {skipped} skipped."
        )

        return redirect("map_teacher_courses")

    # =========================
    # DISPLAY EXISTING MAPPINGS
    # =========================
    mappings = Course.instructors.through.objects.filter(
        course__user=request.user
    ).select_related(
        "instructor",
        "course"
    ).order_by("course__course_number", "instructor__uid")

    return render(
        request,
        "map_teacher_courses.html",
        {"mappings": mappings}
    )


@login_required
def delete_teacher_course_mapping(request, course_number, instructor_id):
    if request.method == "POST":
        try:
            course = Course.objects.get(course_number=course_number, user=request.user)
            instructor = Instructor.objects.get(id=instructor_id, user=request.user)
            course.instructors.remove(instructor)
            messages.success(request, "Mapping removed successfully.")
        except Exception as e:
            messages.error(request, f"Error removing mapping: {e}")

    return redirect("map_teacher_courses")




@login_required
def inst_list_view(request):
    return render(
        request,
        'inslist.html',
        {'instructors': Instructor.objects.filter(user=request.user)}
    )


@login_required
def delete_instructor(request, pk):
    if request.method == 'POST':
        Instructor.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editinstructor')




@login_required
def addRooms(request):
    form = RoomForm(request.POST or None, user=request.user)
    from ttgen.models import Department, Room

    def resolve_department(dept_identifier):
        dept_identifier = (dept_identifier or "").strip()
        if not dept_identifier:
            raise Department.DoesNotExist
        if dept_identifier.isdigit():
            return Department.objects.get(pk=int(dept_identifier), user=request.user)
        try:
            return Department.objects.get(code=dept_identifier.upper(), user=request.user)
        except Department.DoesNotExist:
            return Department.objects.get(name=dept_identifier, user=request.user)

    # ---------------------------
    # 1) MANUAL ADD ROOM
    # ---------------------------
    if request.method == "POST" and "add_room" in request.POST:
        if form.is_valid():
            room = form.save(commit=False)
            room.user = request.user
            room.save()

            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Room added successfully!")
            return redirect("addRooms")
        else:
            messages.error(request, "Please fill out all required fields.")
            return redirect("addRooms")

    # ---------------------------
    # 2) CSV UPLOAD ROOMS
    # ---------------------------
    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file or not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a valid CSV file.")
            return redirect("addRooms")

        import csv
        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        first = True

        for row in reader:
            if not row or len(row) < 5:
                continue

            if first:
                first = False
                header = [h.strip().lower() for h in row]

                rid_index = header.index("r_number") if "r_number" in header else 0
                dept_index = header.index("department") if "department" in header else (
                    header.index("department_code") if "department_code" in header else (
                        header.index("department_id") if "department_id" in header else 1
                    )
                )
                cap_index = header.index("seating_capacity") if "seating_capacity" in header else 2
                type_index = header.index("room_type") if "room_type" in header else 3
                if "lab_category" not in header:
                    messages.error(request, "Missing required column: lab_category")
                    return redirect("addRooms")
                category_index = header.index("lab_category")
                continue

            r_number = row[rid_index].strip()
            department_value = row[dept_index].strip()
            seating_capacity = row[cap_index].strip()
            room_type = row[type_index].strip()
            lab_category = normalize_lab_category(row[category_index].strip()) if category_index < len(row) else ""

            room_map = {
                "lecture hall": "Lecture Hall",
                "lab": "Lab",
                "seminar room": "Seminar Room",
            }
            room_type = room_map.get(room_type.lower(), room_type)
            if room_type != "Lab":
                lab_category = ""
            elif not lab_category:
                # Lab rooms must have a category in CSV.
                continue

            if not seating_capacity.isdigit():
                continue

            seating_capacity = int(seating_capacity)
            try:
                department = resolve_department(department_value)
            except Department.DoesNotExist:
                continue

            if not Room.objects.filter(r_number=r_number, user=request.user).exists():
                Room.objects.create(
                    user=request.user,
                    r_number=r_number,
                    seating_capacity=seating_capacity,
                    room_type=room_type,
                    lab_category=lab_category,
                    department=department
                )
                added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} room(s) added from CSV!")
        return redirect("addRooms")

    return render(request, "addRooms.html", {"form": form})


@login_required
def room_list(request):
    return render(request, 'roomslist.html', {'rooms': Room.objects.filter(user=request.user)})


@login_required
def delete_room(request, pk):
    if request.method == 'POST':
        Room.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editrooms')


@login_required
def addTimings(request):
    form = MeetingTimeForm(request.POST or None)

    # -------------------------
    # 1. MANUAL ADD TIMING
    # -------------------------
    if request.method == "POST" and "add_timing" in request.POST:
        if form.is_valid():
            mt = form.save(commit=False)
            mt.user = request.user
            mt.save()
            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Timing added successfully!")
            return redirect("addTimings")
        else:
            messages.error(request, "Please fill all fields.")
            return redirect("addTimings")

    # -------------------------
    # 2. CSV UPLOAD TIMINGS
    # -------------------------
    if request.method == "POST" and "csv_upload" in request.POST:

        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("addTimings")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file type. Upload CSV only.")
            return redirect("addTimings")

        import csv
        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        first = True

        for row in reader:

            # Skip empty or incomplete rows
            if not row or len(row) < 3:
                continue

            # Skip header row
            if first:
                first = False
                if row[0].strip().lower() == "pid":
                    continue

            pid = row[0].strip()
            time = row[1].strip()
            day_raw = row[2].strip()

            # --------------------------
            # FIXED DAY PARSING
            # --------------------------
            # Normalize capitalization
            day_value = day_raw.capitalize()

            # Map numeric day → weekday
            day_map = {
                '1': 'Monday',
                '2': 'Tuesday',
                '3': 'Wednesday',
                '4': 'Thursday',
                '5': 'Friday',
                '6': 'Saturday',
                '7': 'Sunday',
            }

            # If the value is numeric, map it
            day = day_map.get(day_value.lower(), day_value.capitalize())

            # Validate day
            valid_days = [d[0] for d in DAYS_OF_WEEK]  # ['Monday', 'Tuesday',...]
            if day not in valid_days:
                print("Invalid mapped day:", day)
                continue

            # Validate time slot
            valid_times = [t[0] for t in TIME_SLOTS]  # ['1','2','3','4',...]
            if time not in valid_times:
                print("Invalid time:", time)
                continue

            # Avoid duplicates
            if not MeetingTime.objects.filter(pid=pid, user=request.user).exists():
                MeetingTime.objects.create(user=request.user, pid=pid, day=day, time=time)
                added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} timing(s) added from CSV!")
        return redirect("addTimings")



    return render(request, "addTimings.html", {"form": form})


@login_required
def meeting_list_view(request):
    return render(request, 'mtlist.html', {'meeting_times': MeetingTime.objects.filter(user=request.user)})


@login_required
def delete_meeting_time(request, pk):
    if request.method == 'POST':
        MeetingTime.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editmeetingtime')


@login_required
def addDepts(request):
    form = DepartmentForm(request.POST or None)

    # ------------------------------------
    # 1) MANUAL ADD DEPARTMENT
    # ------------------------------------
    if request.method == "POST" and "add_department" in request.POST:
        if form.is_valid():
            dept = form.save(commit=False)
            dept.user = request.user
            dept.save()
            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Department added successfully!")
            return redirect("addDepts")
        else:
            messages.error(request, "Please fill all required fields.")
            return redirect("addDepts")

    # ------------------------------------
    # 2) CSV UPLOAD DEPARTMENTS
    # ------------------------------------
    if request.method == "POST" and "csv_upload" in request.POST:

        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("addDepts")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file type. Upload CSV only.")
            return redirect("addDepts")

        import csv
        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        first = True
        skipped = 0

        for row in reader:

            # Skip blank rows
            if not row or len(row) < 2:
                continue

            # Handle header row
            if first:
                first = False
                header = [h.strip().lower() for h in row]
                
                # Detect column positions
                try:
                    # Try both 'name' and 'dept_name'
                    if 'name' in header:
                        name_i = header.index('name')
                    elif 'dept_name' in header:
                        name_i = header.index('dept_name')
                    else:
                        name_i = 0  # Default first column
                    
                    # Try both 'code' and 'dept_code'
                    if 'code' in header:
                        code_i = header.index('code')
                    elif 'dept_code' in header:
                        code_i = header.index('dept_code')
                    else:
                        code_i = 1  # Default second column
                        
                except ValueError as e:
                    messages.error(request, f"CSV format error: {e}")
                    return redirect("addDepts")
                
                continue

            # Extract values
            dept_name = row[name_i].strip()
            dept_code = row[code_i].strip().upper()

            # Skip if department already exists (check both name and code)
            if Department.objects.filter(code=dept_code, user=request.user).exists():
                skipped += 1
                continue

            if Department.objects.filter(name=dept_name, user=request.user).exists():
                skipped += 1
                continue

            # Create Department
            try:
                Department.objects.create(
                    user=request.user,
                    name=dept_name,
                    code=dept_code
                )
                added += 1
            except Exception as e:
                print(f"Error creating department {dept_name}: {e}")
                skipped += 1
                continue

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} department(s) added from CSV! {skipped} skipped.")
        return redirect("addDepts")

    return render(request, 'addDepts.html', {'form': form})


@login_required
def department_list(request):
    return render(request, 'deptlist.html', {'departments': Department.objects.filter(user=request.user)})


@login_required
def delete_department(request, pk):
    if request.method == 'POST':
        Department.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editdepartment')


@login_required
def addSections(request):
    form = SectionForm(request.POST or None, user=request.user)

    # -------------------------------------------
    # 1) MANUAL ADDING OF SECTION
    # -------------------------------------------
    if request.method == "POST" and "add_section" in request.POST:
        if form.is_valid():
            section = form.save(commit=False)
            section.user = request.user
            section.save()
            template_section = clone_section_courses_from_similar(section)
            reset_global_schedule_cache(request.user.id)
            if template_section:
                messages.success(
                    request,
                    f"Section added successfully! Subjects copied from {template_section.section_id}.",
                )
            else:
                messages.success(request, "Section added successfully!")
            return redirect("addSections")
        else:
            messages.error(request, "Please fill all required fields.")
            return redirect("addSections")

    # -------------------------------------------
    # 2) CSV UPLOAD SECTION DATA
    # -------------------------------------------
    if request.method == "POST" and "csv_upload" in request.POST:

        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "Please select a CSV file.")
            return redirect("addSections")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file type. Upload CSV only.")
            return redirect("addSections")

        import csv
        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        first = True

        def resolve_department(dept_identifier):
            dept_identifier = (dept_identifier or "").strip()
            if not dept_identifier:
                raise Department.DoesNotExist
            if dept_identifier.isdigit():
                return Department.objects.get(pk=int(dept_identifier), user=request.user)
            try:
                return Department.objects.get(code=dept_identifier.upper(), user=request.user)
            except Department.DoesNotExist:
                return Department.objects.get(name=dept_identifier, user=request.user)

        for row in reader:

            # Skip empty or insufficient rows
            if not row or len(row) < 2:
                continue

            # Auto-detect column positions using header row
            if first:
                first = False
                header = [h.strip().lower() for h in row]

                def index(name, default=None):
                    try:
                        return header.index(name)
                    except:
                        return default

                section_i = index("section_id", 0)
                dept_i = index("department", index("department_code", index("department_id", 1)))
                strength_i = index("student_strength", 2)

                # Skip header
                continue

            # Extract values
            section_id = row[section_i].strip()
            dept_name = row[dept_i].strip()
            student_strength = row[strength_i].strip() if len(row) > strength_i else "70"

            # Skip duplicates
            if Section.objects.filter(section_id=section_id, user=request.user).exists():
                continue

            # Validate Department
            try:
                dept = resolve_department(dept_name)
            except Department.DoesNotExist:
                print("Invalid department:", dept_name)
                continue

            if not student_strength.isdigit():
                print("Invalid student strength:", student_strength)
                continue

            # Create the Section object
            section = Section.objects.create(
                user=request.user,
                section_id=section_id,
                student_strength=int(student_strength),
                department=dept,
            )
            clone_section_courses_from_similar(section)

            added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} section(s) added from CSV!")
        return redirect("addSections")

    return render(request, "addSections.html", {"form": form})


@login_required
def section_list(request):
    return render(request, 'seclist.html', {'sections': Section.objects.filter(user=request.user)})


@login_required
def delete_section(request, pk):
    if request.method == 'POST':
        Section.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editsection')


@login_required
def generate(request):
    return render(request, 'generate.html')


def generate(request):
    return render(request, 'generate.html')




def delete_saved_timetable(request, tid):
    SavedTimetable.objects.filter(id=tid, user=request.user).delete()
    messages.success(request, "Saved timetable deleted.")
    return redirect('saved_timetable_list')

def expand_labs_for_pdf(rows):
    new_rows = []

    for row in rows:
        expanded = []
        for cell in row["cells"]:
            if cell.get("type") == "lab":
                span = cell.get("colspan", 1)
                for _ in range(span):
                    expanded.append(cell)
            else:
                expanded.append(cell)

        row_copy = row.copy()
        row_copy["cells"] = expanded
        new_rows.append(row_copy)

    return new_rows




from django.template.loader import render_to_string
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.http import HttpResponse, Http404, HttpResponseForbidden

def download_saved_timetable_pdf(request, tid):
    try:
        from xhtml2pdf import pisa
    except ImportError:
        return HttpResponse(
            "PDF generation dependencies are not installed on this machine yet.",
            status=503,
        )

    # 1. Fetch saved timetable securely
    try:
        saved_t = SavedTimetable.objects.get(id=tid)
    except SavedTimetable.DoesNotExist:
        raise Http404("Timetable does not exist")

    if saved_t.user != request.user:
        return HttpResponseForbidden("You do not have permission to download this PDF.")

    # 2. Rebuild in-memory classes and labs
    slots = saved_t.slots.all()

    classes = []
    labs = []

    for slot in slots:
        if slot.is_lab:
            lab_obj = Lab(
                id=0,
                dept=slot.section.department,
                section=slot.section.section_id,
                course=slot.course
            )
            lab_obj.instructor = slot.instructor
            lab_obj.room = slot.room
            lab_obj.meeting_times = list(slot.lab_slots.all())
            labs.append(lab_obj)
        else:
            cls = Class(
                id=0,
                dept=slot.section.department,
                section=slot.section.section_id,
                course=slot.course
            )
            cls.instructor = slot.instructor
            cls.room = slot.room
            cls.meeting_time = slot.meeting_time
            classes.append(cls)

    # 3. Build tables (using your existing function)
    tables = build_section_tables(classes, labs)

    # 4. Expand cells for PDF so colspan renders properly
    for table in tables:
        for row in table["rows"]:
            for cell in row["cells"]:
                if cell["type"] == "lab":
                    cell["width"] = 85 * cell["colspan"]
                else:
                    cell["width"] = 85

    # 5. Render HTML template
    html = render_to_string("saved_timetable_pdf.html", {
        "tables": tables,
        "SLOT_LABELS": SLOT_LABELS
    })

    # 6. Prepare response object
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="timetable_{tid}.pdf"'

    # 7. Create PDF
    pisa_status = pisa.CreatePDF(html, dest=response)

    # 8. If PDF fails, return HTML for debugging instead of crashing
    if pisa_status.err:
        return HttpResponse("PDF creation crashed.<br><br>" + html)

    # 9. Always return a response
    return response



    # ------------------------------------------------------------------
    # Build tables (returns list of dictionaries)
    # ------------------------------------------------------------------
    tables = build_section_tables(classes, labs)

    # ------------------------------------------------------------------
    # ⭐ FIX A: Add width to each cell for xhtml2pdf (dict-safe) ⭐
    # ------------------------------------------------------------------
    for table in tables:
        for row in table["rows"]:            # dict access
            for cell in row["cells"]:        # dict access
                if cell["type"] == "lab":
                    cell["width"] = 85 * cell["colspan"]
                else:
                    cell["width"] = 85
    # ------------------------------------------------------------------

    # Render HTML
    html = render_to_string("saved_timetable_pdf.html", {
        "tables": tables
    })

    # Generate PDF
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = 'attachment; filename="saved_timetable.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    # If PDF fails, return HTML to debug
    if pisa_status.err:
        return HttpResponse("PDF creation crashed.<br><br>" + html)

    return response


# UNIFIED CSV CONVERTER (PDF/Excel → CSV) — All Entity Types
# ============================================================
ENTITY_CONFIGS = {
    "instructors": {
        "label": "Instructors",
        "columns": ["uid", "name", "designation", "max_workload"],
        "filename": "instructors.csv",
        "required": ["uid", "name"],
        "keywords": {
            "uid": ["uid", "id", "teacher id", "teacherid", "faculty id", "code", "teacher_id"],
            "name": ["name", "teacher name", "teachername", "faculty name", "instructor", "faculty"],
            "designation": ["designation", "position", "role", "rank", "post"],
            "max_workload": ["max_workload", "workload", "max workload", "load", "hours"],
        },
    },
    "courses": {
        "label": "Courses",
        "columns": ["department_code", "course_number", "course_name", "room_required", "required_lab_category", "classes_per_week"],
        "filename": "courses.csv",
        "required": ["course_number", "course_name"],
        "keywords": {
            "department_code": ["department", "dept", "department_code", "dept_code"],
            "course_number": ["course_number", "course no", "course_id", "course id", "code", "number"],
            "course_name": ["course_name", "course name", "name", "title", "subject"],
            "room_required": ["room_required", "room required", "room type", "room"],
            "required_lab_category": ["lab_category", "lab category", "required_lab", "lab"],
            "classes_per_week": ["classes_per_week", "classes per week", "classes", "per week", "frequency", "weekly"],
        },
    },
    "rooms": {
        "label": "Rooms",
        "columns": ["r_number", "department", "seating_capacity", "room_type", "lab_category"],
        "filename": "rooms.csv",
        "required": ["r_number"],
        "keywords": {
            "r_number": ["r_number", "room number", "room_number", "room no", "room id", "room_id", "number"],
            "department": ["department", "dept", "department_code", "dept_code"],
            "seating_capacity": ["seating_capacity", "seating capacity", "capacity", "seats"],
            "room_type": ["room_type", "room type", "type"],
            "lab_category": ["lab_category", "lab category", "lab", "category"],
        },
    },
    "timings": {
        "label": "Timings",
        "columns": ["pid", "time", "day"],
        "filename": "timings.csv",
        "required": ["pid"],
        "keywords": {
            "pid": ["pid", "period id", "period_id", "period", "slot id"],
            "time": ["time", "slot", "period number", "slot number"],
            "day": ["day", "weekday", "day_number"],
        },
    },
    "departments": {
        "label": "Departments",
        "columns": ["name", "code"],
        "filename": "departments.csv",
        "required": ["name", "code"],
        "keywords": {
            "name": ["name", "dept_name", "department_name", "department name", "department"],
            "code": ["code", "dept_code", "department_code", "department code"],
        },
    },
    "sections": {
        "label": "Sections",
        "columns": ["section_id", "department", "student_strength"],
        "filename": "sections.csv",
        "required": ["section_id"],
        "keywords": {
            "section_id": ["section_id", "section id", "section", "id", "batch"],
            "department": ["department", "dept", "department_code", "dept_code"],
            "student_strength": ["student_strength", "student strength", "strength", "students", "size"],
        },
    },
    "section_courses": {
        "label": "Section-Course Mapping",
        "columns": ["section_id", "course_number"],
        "filename": "section_courses.csv",
        "required": ["section_id", "course_number"],
        "keywords": {
            "section_id": ["section_id", "section id", "section", "batch"],
            "course_number": ["course_number", "course no", "course_id", "course id", "course", "subject"],
        },
    },
    "teacher_courses": {
        "label": "Teacher-Course Mapping",
        "columns": ["instructor", "course_number"],
        "filename": "teacher_courses.csv",
        "required": ["instructor", "course_number"],
        "keywords": {
            "instructor": ["instructor", "teacher", "uid", "name", "faculty", "teacher name", "instructor_name"],
            "course_number": ["course_number", "course no", "course_id", "course id", "course", "subject"],
        },
    },
}


def _extract_rows_from_file(uploaded_file):
    """Extract rows from PDF or Excel file. Returns (rows, error_msg)."""
    filename = uploaded_file.name.lower()
    rows = []

    if filename.endswith((".xlsx", ".xls")):
        import openpyxl
        wb = openpyxl.load_workbook(uploaded_file, read_only=True)
        ws = wb.active
        for row in ws.iter_rows(values_only=True):
            cells = [str(c).strip() if c is not None else "" for c in row]
            if any(cells):
                rows.append(cells)

    elif filename.endswith(".pdf"):
        import pdfplumber
        import tempfile
        import re as _re
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            for chunk in uploaded_file.chunks():
                tmp.write(chunk)
            tmp_path = tmp.name

        with pdfplumber.open(tmp_path) as pdf:
            for page in pdf.pages:
                table = page.extract_table()
                if table and len(table) > 1 and len(table[0]) >= 2:
                    for row in table:
                        cells = [str(c).strip() if c else "" for c in row]
                        if any(cells):
                            rows.append(cells)
                    continue

                table = page.extract_table({
                    "vertical_strategy": "text",
                    "horizontal_strategy": "text",
                })
                if table and len(table) > 1 and len(table[0]) >= 2:
                    for row in table:
                        cells = [str(c).strip() if c else "" for c in row]
                        if any(cells):
                            rows.append(cells)
                    continue

                text = page.extract_text(layout=True)
                if text:
                    for line in text.split("\n"):
                        line = line.strip()
                        if not line:
                            continue
                        parts = _re.split(r'\s{2,}', line)
                        if len(parts) >= 2:
                            rows.append(parts)
                    if rows:
                        continue

                words = page.extract_words(x_tolerance=3, y_tolerance=3, keep_blank_chars=True)
                if words:
                    y_groups = {}
                    for w in words:
                        y_key = round(w["top"] / 5) * 5
                        y_groups.setdefault(y_key, []).append(w)
                    for y_key in sorted(y_groups.keys()):
                        line_words = sorted(y_groups[y_key], key=lambda w: w["x0"])
                        cells = []
                        current = line_words[0]["text"]
                        prev_x1 = line_words[0]["x1"]
                        for w in line_words[1:]:
                            gap = w["x0"] - prev_x1
                            if gap > 15:
                                cells.append(current.strip())
                                current = w["text"]
                            else:
                                current += " " + w["text"]
                            prev_x1 = w["x1"]
                        cells.append(current.strip())
                        if len(cells) >= 2:
                            rows.append(cells)

        os.unlink(tmp_path)
    else:
        return [], "Unsupported file type. Please upload PDF or Excel (.xlsx/.xls)."

    return rows, None


@login_required(login_url='/accounts/login/')
def convert_csv(request):
    import json as _json
    entity_configs_json = _json.dumps({
        k: {"label": v["label"], "columns": v["columns"]}
        for k, v in ENTITY_CONFIGS.items()
    })

    if request.method == "POST":
        entity_type = request.POST.get("entity_type", "instructors")
        config = ENTITY_CONFIGS.get(entity_type)
        if not config:
            messages.error(request, "Invalid entity type.")
            return redirect("convert_csv")

        uploaded_file = request.FILES.get("file")
        if not uploaded_file:
            messages.error(request, "Please upload a file.")
            return redirect("convert_csv")

        try:
            rows, err = _extract_rows_from_file(uploaded_file)
        except Exception as e:
            messages.error(request, f"Error reading file: {e}")
            return redirect("convert_csv")

        if err:
            messages.error(request, err)
            return redirect("convert_csv")

        rows = [r for r in rows if len(r) >= 2]
        if not rows:
            messages.error(request, "No data found in the uploaded file.")
            return redirect("convert_csv")

        columns = config["columns"]
        keywords = config["keywords"]

        col_map = {}
        data_start = 0
        for row_idx in range(min(5, len(rows))):
            row_lower = [c.lower() for c in rows[row_idx]]
            temp_map = {}
            for field, kws in keywords.items():
                for i, cell in enumerate(row_lower):
                    if any(kw in cell for kw in kws):
                        temp_map[field] = i
                        break
            if len(temp_map) >= 2:
                col_map = temp_map
                data_start = row_idx + 1
                break

        if not col_map:
            for i, col in enumerate(columns):
                if i < len(rows[0]):
                    col_map[col] = i

        import io
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(columns)

        required = config["required"]
        for row in rows[data_start:]:
            vals = {}
            for col in columns:
                vals[col] = row[col_map[col]] if col in col_map and col_map[col] < len(row) else ""
            if all(vals.get(r) for r in required):
                writer.writerow([vals[col] for col in columns])

        response = HttpResponse(output.getvalue(), content_type="text/csv")
        response["Content-Disposition"] = f'attachment; filename="{config["filename"]}"'
        return response

    return render(request, "convert_csv.html", {
        "entity_configs_json": entity_configs_json,
    })
