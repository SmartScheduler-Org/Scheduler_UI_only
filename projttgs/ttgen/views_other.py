from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from .forms import *
from .models import *
from account.models import Profile
from django.core.mail import send_mail, EmailMessage
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.views.generic import View
import logging
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
from smtplib import SMTPAuthenticationError
from itertools import combinations
from .models import MeetingTime
from .models import DAYS_OF_WEEK, TIME_SLOTS
from .forms import DepartmentForm
from ttgen.utils import section_sort_key


import random as rnd

logger = logging.getLogger(__name__)


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
def live_demo(request): return render(request, 'live_demo.html')
def services(request): return render(request, 'services.html')
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
                return redirect('teacher_enter_code')
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
    return redirect('teacher_enter_code')


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
        name    = request.POST.get('name', '').strip()
        email   = request.POST.get('email', '').strip()
        subject = request.POST.get('subject', 'No subject').strip()
        message = request.POST.get('message', '').strip()

        body = (
            f"New contact form submission from SmartScheduler\n"
            f"{'-' * 44}\n"
            f"Name    : {name}\n"
            f"Email   : {email}\n"
            f"Subject : {subject}\n"
            f"{'-' * 44}\n\n"
            f"{message}\n"
        )
        try:
            msg = EmailMessage(
                subject=f"[SmartScheduler] {subject} — from {name}",
                body=body,
                from_email=settings.EMAIL_HOST_USER,   # Gmail forces this to be your account
                to=['smartschedulertech@gmail.com'],
                reply_to=[f"{name} <{email}>"],         # Reply goes to the visitor
            )
            msg.send(fail_silently=False)
            messages.success(request, "Message sent! We'll get back to you soon.")
        except Exception:
            messages.error(request, "Couldn't send your message right now. Please try again later.")
        return redirect('contact')
    return render(request, 'contact.html')


def institute_application(request):
    if request.method == "POST":
        institute_type = request.POST.get("institute_type", "").strip()
        other_type = request.POST.get("other_type", "").strip()
        contact_name = request.POST.get("contact_name", "").strip()
        official_email = request.POST.get("official_email", "").strip()
        contact_number = request.POST.get("contact_number", "").strip()
        note = request.POST.get("note", "").strip()

        selected_type = other_type if institute_type == "Other" and other_type else institute_type

        if not settings.EMAIL_HOST_USER or not settings.EMAIL_HOST_PASSWORD:
            messages.error(
                request,
                "Email is not configured yet. Add EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in your .env file, then restart the server.",
            )
            return render(request, "institute_application.html")

        body = (
            "New institute customization application\n"
            "--------------------------------------\n"
            f"Institute type : {selected_type}\n"
            f"Contact person : {contact_name}\n"
            f"Official email : {official_email}\n"
            f"Contact number : {contact_number}\n"
            "--------------------------------------\n\n"
            f"Additional note:\n{note or 'No note added.'}\n"
        )

        try:
            msg = EmailMessage(
                subject=f"[SmartScheduler] Institute application - {selected_type or 'New request'}",
                body=body,
                from_email=settings.EMAIL_HOST_USER,
                to=["smartschedulertech@gmail.com"],
                reply_to=[f"{contact_name} <{official_email}>"] if official_email else None,
            )
            msg.send(fail_silently=False)
            return redirect("institute_application_thanks")
        except SMTPAuthenticationError:
            logger.exception("Institute application email authentication failed")
            messages.error(
                request,
                "Gmail rejected the sender email/password. Use the exact Gmail address in EMAIL_HOST_USER and a valid 16-character Gmail App Password in EMAIL_HOST_PASSWORD.",
            )
        except Exception as exc:
            logger.exception("Institute application email failed")
            error_message = "Could not send your application right now. Please check the SMTP settings and try again."
            if settings.DEBUG:
                error_message = f"{error_message} Server said: {exc}"
            messages.error(request, error_message)

    return render(request, "institute_application.html")


def institute_application_thanks(request):
    return render(request, "institute_application_thanks.html")


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
    def build_section_tables(all_classes, all_labs, user=None):
        from collections import defaultdict, OrderedDict
        section_map = OrderedDict()
        for cls in all_classes:
            sec_key = cls.section
            if sec_key not in section_map:
                section_map[sec_key] = {"classes": [], "labs": [], "dept": cls.department}
            section_map[sec_key]["classes"].append(cls)
        for lab in all_labs:
            sec_key = lab.section
            if sec_key not in section_map:
                section_map[sec_key] = {"classes": [], "labs": [], "dept": lab.department}
            section_map[sec_key]["labs"].append(lab)

        tables = []
        for sec_id, data in section_map.items():
            grid = {}
            for day in DAYS:
                grid[day] = {}
            for cls in data["classes"]:
                if cls.meeting_time:
                    day = cls.meeting_time.day
                    slot = int(cls.meeting_time.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["classes"].append(cls)
            for lab in data["labs"]:
                if lab.meeting_times:
                    first_mt = lab.meeting_times[0]
                    day = first_mt.day
                    slot = int(first_mt.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["labs"].append(lab)

            rows = []
            for day in DAYS:
                cells = []
                skip_until = 0
                for s in range(1, 10):
                    if s <= skip_until:
                        continue
                    if s == 5:
                        cells.append({"type": "lunch", "colspan": 1, "slot_number": s})
                        continue
                    cell_data = grid[day].get(s, {"classes": [], "labs": []})
                    if cell_data["labs"]:
                        lab_span = len(cell_data["labs"][0].meeting_times) if cell_data["labs"][0].meeting_times else LAB_DURATION
                        cells.append({
                            "type": "lab",
                            "colspan": lab_span,
                            "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cells.append({
                            "type": "class",
                            "colspan": 1,
                            "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                    else:
                        cells.append({"type": "empty", "colspan": 1, "slot_number": s})
                rows.append({"day": day, "cells": cells})

            class _SectionProxy:
                def __init__(self, sid, dept):
                    self.section_id = sid
                    self.department = dept
            tables.append({
                "section": _SectionProxy(sec_id, data["dept"]),
                "rows": rows,
                "subject_counts": [],
                "total_missing_classes": 0,
            })
        return tables


if "build_teacher_tables" not in globals():
    def build_teacher_tables(all_classes, all_labs, user=None):
        from collections import OrderedDict
        teacher_map = OrderedDict()
        for cls in all_classes:
            t = cls.instructor
            if t and t not in teacher_map:
                teacher_map[t] = {"classes": [], "labs": []}
            if t:
                teacher_map[t]["classes"].append(cls)
        for lab in all_labs:
            t = lab.instructor
            if t and t not in teacher_map:
                teacher_map[t] = {"classes": [], "labs": []}
            if t:
                teacher_map[t]["labs"].append(lab)

        tables = []
        for teacher, data in teacher_map.items():
            grid = {}
            for day in DAYS:
                grid[day] = {}
            for cls in data["classes"]:
                if cls.meeting_time:
                    day = cls.meeting_time.day
                    slot = int(cls.meeting_time.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["classes"].append(cls)
            for lab in data["labs"]:
                if lab.meeting_times:
                    first_mt = lab.meeting_times[0]
                    day = first_mt.day
                    slot = int(first_mt.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["labs"].append(lab)

            rows = []
            for day in DAYS:
                cells = []
                skip_until = 0
                for s in range(1, 10):
                    if s <= skip_until:
                        continue
                    if s == 5:
                        cells.append({"type": "lunch", "colspan": 1, "slot_number": s})
                        continue
                    cell_data = grid[day].get(s, {"classes": [], "labs": []})
                    if cell_data["labs"]:
                        lab_span = len(cell_data["labs"][0].meeting_times) if cell_data["labs"][0].meeting_times else LAB_DURATION
                        cells.append({
                            "type": "lab", "colspan": lab_span, "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cells.append({
                            "type": "class", "colspan": 1, "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                    else:
                        cells.append({"type": "empty", "colspan": 1, "slot_number": s})
                rows.append({"day": day, "cells": cells})

            tables.append({"teacher": teacher, "rows": rows})
        return tables


if "build_room_tables" not in globals():
    def build_room_tables(all_classes, all_labs, user=None):
        from collections import OrderedDict
        room_map = OrderedDict()
        for cls in all_classes:
            r = cls.room
            if r and r not in room_map:
                room_map[r] = {"classes": [], "labs": []}
            if r:
                room_map[r]["classes"].append(cls)
        for lab in all_labs:
            r = lab.room
            if r and r not in room_map:
                room_map[r] = {"classes": [], "labs": []}
            if r:
                room_map[r]["labs"].append(lab)

        tables = []
        for room, data in room_map.items():
            grid = {}
            for day in DAYS:
                grid[day] = {}
            for cls in data["classes"]:
                if cls.meeting_time:
                    day = cls.meeting_time.day
                    slot = int(cls.meeting_time.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["classes"].append(cls)
            for lab in data["labs"]:
                if lab.meeting_times:
                    first_mt = lab.meeting_times[0]
                    day = first_mt.day
                    slot = int(first_mt.time)
                    if day in grid:
                        grid[day].setdefault(slot, {"classes": [], "labs": []})
                        grid[day][slot]["labs"].append(lab)

            total_slots = sum(1 for d in grid.values() for s, v in d.items() if v["classes"] or v["labs"])
            max_slots = len(DAYS) * 8
            optimization = round(total_slots / max_slots * 100) if max_slots else 0

            rows = []
            for day in DAYS:
                cells = []
                skip_until = 0
                for s in range(1, 10):
                    if s <= skip_until:
                        continue
                    if s == 5:
                        cells.append({"type": "lunch", "colspan": 1, "slot_number": s})
                        continue
                    cell_data = grid[day].get(s, {"classes": [], "labs": []})
                    if cell_data["labs"]:
                        lab_span = len(cell_data["labs"][0].meeting_times) if cell_data["labs"][0].meeting_times else LAB_DURATION
                        cells.append({
                            "type": "lab", "colspan": lab_span, "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cells.append({
                            "type": "class", "colspan": 1, "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                    else:
                        cells.append({"type": "empty", "colspan": 1, "slot_number": s})
                rows.append({"day": day, "cells": cells})

            tables.append({"room": room, "rows": rows, "optimization": optimization})
        return tables


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


if "normalize_lab_category" not in globals():
    def normalize_lab_category(value):
        """Fallback: normalize a lab category string to match LAB_CATEGORY_CHOICES."""
        if not value:
            return ""
        value = value.strip()
        from ttgen.models import LAB_CATEGORY_CHOICES
        valid = {v.lower(): v for v, _ in LAB_CATEGORY_CHOICES}
        lower = value.lower()
        if lower in valid:
            return valid[lower]
        for key, canonical in valid.items():
            if lower in key or key in lower:
                return canonical
        return value


if "teacher_payload" not in globals():
    def teacher_payload(name, designation="", max_workload=""):
        """Fallback: return sensible defaults for teacher designation & workload."""
        resolved_designation = designation.strip() if designation else "Assistant Professor"
        try:
            resolved_workload = int(max_workload)
        except (TypeError, ValueError):
            resolved_workload = 12
        return resolved_designation, resolved_workload


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


# ================================================================
# SAVED TIMETABLE VIEWS (overrides private runtime stubs)
# ================================================================

def _rebuild_classes_and_labs_from_saved(saved_t):
    """Rebuild in-memory Class and Lab objects from ScheduledSlot records."""
    slots = saved_t.slots.select_related(
        "section", "section__department", "course", "instructor", "room", "meeting_time",
    ).prefetch_related("lab_slots").all()

    classes = []
    labs = []
    lab_slots_list = []

    for slot in slots:
        if slot.is_lab:
            lab_slots_list.append(slot)
        else:
            cls = Class(
                id=0,
                dept=slot.section.department,
                section=slot.section.section_id,
                course=slot.course,
            )
            cls.instructor = slot.instructor
            cls.room = slot.room
            cls.meeting_time = slot.meeting_time
            classes.append(cls)

    # Group labs by (section, starting day/time) to compute batch numbers
    from collections import defaultdict
    lab_groups = defaultdict(list)
    for slot in lab_slots_list:
        key = (slot.section.section_id, slot.meeting_time.day, slot.meeting_time.time)
        lab_groups[key].append(slot)

    for key, group in lab_groups.items():
        total_batches = len(group)
        for batch_num, slot in enumerate(group, start=1):
            lab_obj = Lab(
                id=0,
                dept=slot.section.department,
                section=slot.section.section_id,
                course=slot.course,
                batch=batch_num,
                total_batches=total_batches,
            )
            lab_obj.instructor = slot.instructor
            lab_obj.room = slot.room
            lab_obj.meeting_times = list(slot.lab_slots.all())
            labs.append(lab_obj)

    return classes, labs


def _compute_teacher_workloads(classes, labs):
    """Compute teacher workload summary from classes and labs."""
    workloads = {}
    for cls in classes:
        teacher = cls.instructor
        if teacher not in workloads:
            workloads[teacher] = {"lectures": 0, "labs": 0, "total": 0}
        workloads[teacher]["lectures"] += 1
        workloads[teacher]["total"] += 1
    for lab in labs:
        teacher = lab.instructor
        if teacher not in workloads:
            workloads[teacher] = {"lectures": 0, "labs": 0, "total": 0}
        lab_slot_count = len(lab.meeting_times) if lab.meeting_times else LAB_DURATION
        workloads[teacher]["labs"] += lab_slot_count
        workloads[teacher]["total"] += lab_slot_count
    return workloads


def _get_saved_timetable_or_404(tid, user):
    """Fetch a saved timetable ensuring it belongs to the user."""
    try:
        saved_t = SavedTimetable.objects.get(id=tid)
    except SavedTimetable.DoesNotExist:
        raise Http404("Timetable does not exist")
    if saved_t.user != user:
        raise Http404("Timetable does not exist")
    return saved_t


def _get_plan_permissions(user):
    """Return plan permission flags for a user."""
    try:
        plan = UserAccessPlan.objects.get(user=user)
        if plan.is_active:
            return {
                "can_edit_delete": plan.can_edit_delete,
                "can_substitute": plan.can_substitute,
                "can_drag_drop": plan.can_drag_drop,
            }
    except UserAccessPlan.DoesNotExist:
        pass
    return {
        "can_edit_delete": False,
        "can_substitute": False,
        "can_drag_drop": False,
    }


def _normalize_reason(raw_reason):
    return (raw_reason or "").strip()


def _meeting_time_payload(mt):
    if not mt:
        return {}
    return {
        "day": getattr(mt, "day", ""),
        "slot": str(getattr(mt, "time", "")),
        "slot_label": SLOT_LABELS.get(str(getattr(mt, "time", "")), ""),
    }


def _saved_slot_snapshot(slot):
    if not slot:
        return {}
    return {
        "type": "lab" if slot.is_lab else "class",
        "section": slot.section.section_id if slot.section else "",
        "course": slot.course.course_name if slot.course else "",
        "teacher": slot.instructor.name if slot.instructor else "",
        "room": slot.room.r_number if slot.room else "",
        **_meeting_time_payload(slot.meeting_time),
        "lab_slots": [_meeting_time_payload(mt) for mt in list(slot.lab_slots.all())] if slot.is_lab else [],
    }


def _create_saved_change_log(
    timetable,
    request,
    action_type,
    reason,
    section="",
    day="",
    slot="",
    before_snapshot=None,
    after_snapshot=None,
    source="saved",
):
    TimetableChangeLog.objects.create(
        timetable=timetable,
        changed_by=request.user if request.user.is_authenticated else None,
        action_type=action_type,
        reason=reason,
        section=str(section or ""),
        day=str(day or ""),
        slot=str(slot or ""),
        before_snapshot=before_snapshot or {},
        after_snapshot=after_snapshot or {},
        source=source,
    )


@login_required
def saved_timetable_list(request):
    timetables = SavedTimetable.objects.filter(user=request.user)
    return render(request, "saved_timetable_list.html", {"timetables": timetables})


@login_required
def saved_timetable(request, tid):
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)

    tables = build_section_tables(classes, labs, user=request.user)
    room_tables = build_room_tables(classes, labs, user=request.user)
    teacher_tables = build_teacher_tables(classes, labs, user=request.user)
    teacher_workloads = _compute_teacher_workloads(classes, labs)
    change_logs = saved_t.change_logs.select_related("changed_by")[:40]

    permissions = _get_plan_permissions(request.user)

    context = {
        "saved": saved_t,
        "tables": tables,
        "room_tables": room_tables,
        "teacher_tables": teacher_tables,
        "teacher_workloads": teacher_workloads,
        "change_logs": change_logs,
        "SLOT_LABELS": SLOT_LABELS,
        "can_edit_delete": permissions["can_edit_delete"],
        "can_substitute": permissions["can_substitute"],
        "can_drag_drop": permissions["can_drag_drop"],
    }
    return render(request, "saved_timetable.html", context)


@login_required
def saved_substitute_teacher(request, tid, section, day, slot):
    """Substitute a theory class instructor in a saved timetable."""
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    mt = get_meeting_time(day, slot, user=request.user)
    if mt is None:
        messages.error(request, "Invalid time slot.")
        return redirect("saved_timetable", tid=tid)

    try:
        sec = Section.objects.get(section_id=section, user=request.user)
    except Section.DoesNotExist:
        messages.error(request, "Section not found.")
        return redirect("saved_timetable", tid=tid)

    scheduled = saved_t.slots.filter(section=sec, meeting_time=mt, is_lab=False).first()
    if not scheduled:
        messages.error(request, "No theory class found at this slot.")
        return redirect("saved_timetable", tid=tid)

    available_teachers = Instructor.objects.filter(user=request.user).exclude(id=scheduled.instructor.id)

    if request.method == "POST":
        reason = _normalize_reason(request.POST.get("reason"))
        if not reason:
            messages.error(request, "Reason is required for substitution.")
            return redirect("saved_substitute_teacher", tid=tid, section=section, day=day, slot=slot)

        teacher_id = request.POST.get("teacher")
        if teacher_id:
            try:
                new_teacher = Instructor.objects.get(id=teacher_id, user=request.user)
                # Check for conflict: new teacher already has a slot at this time
                conflict = saved_t.slots.filter(
                    instructor=new_teacher, meeting_time=mt,
                ).exclude(id=scheduled.id).exists()
                if conflict:
                    messages.error(request, f"{new_teacher.name} already has a class at this time.")
                else:
                    before_snapshot = _saved_slot_snapshot(scheduled)
                    scheduled.instructor = new_teacher
                    scheduled.save(update_fields=["instructor"])
                    _create_saved_change_log(
                        timetable=saved_t,
                        request=request,
                        action_type=TimetableChangeLog.ACTION_SUBSTITUTE,
                        reason=reason,
                        section=section,
                        day=day,
                        slot=slot,
                        before_snapshot=before_snapshot,
                        after_snapshot=_saved_slot_snapshot(scheduled),
                        source="saved",
                    )
                    messages.success(request, f"Teacher substituted to {new_teacher.name}.")
                    return redirect("saved_timetable", tid=tid)
            except Instructor.DoesNotExist:
                messages.error(request, "Selected teacher not found.")

    return render(request, "saved_substitute_teacher.html", {
        "saved": saved_t,
        "scheduled": scheduled,
        "section": sec,
        "day": day,
        "slot": slot,
        "available_teachers": available_teachers,
        "SLOT_LABELS": SLOT_LABELS,
    })


@login_required
def saved_substitute_lab_teacher(request, tid, section, day, slot):
    """Substitute a lab instructor in a saved timetable."""
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    mt = get_meeting_time(day, slot, user=request.user)
    if mt is None:
        messages.error(request, "Invalid time slot.")
        return redirect("saved_timetable", tid=tid)

    try:
        sec = Section.objects.get(section_id=section, user=request.user)
    except Section.DoesNotExist:
        messages.error(request, "Section not found.")
        return redirect("saved_timetable", tid=tid)

    scheduled = saved_t.slots.filter(section=sec, meeting_time=mt, is_lab=True).first()
    if not scheduled:
        messages.error(request, "No lab found at this slot.")
        return redirect("saved_timetable", tid=tid)

    available_teachers = Instructor.objects.filter(user=request.user).exclude(id=scheduled.instructor.id)

    if request.method == "POST":
        reason = _normalize_reason(request.POST.get("reason"))
        if not reason:
            messages.error(request, "Reason is required for lab substitution.")
            return redirect("saved_substitute_lab_teacher", tid=tid, section=section, day=day, slot=slot)

        teacher_id = request.POST.get("teacher")
        if teacher_id:
            try:
                new_teacher = Instructor.objects.get(id=teacher_id, user=request.user)
                lab_times = list(scheduled.lab_slots.all())
                conflict = saved_t.slots.filter(
                    instructor=new_teacher, meeting_time__in=lab_times,
                ).exclude(id=scheduled.id).exists()
                if conflict:
                    messages.error(request, f"{new_teacher.name} already has a class during this lab.")
                else:
                    before_snapshot = _saved_slot_snapshot(scheduled)
                    scheduled.instructor = new_teacher
                    scheduled.save(update_fields=["instructor"])
                    _create_saved_change_log(
                        timetable=saved_t,
                        request=request,
                        action_type=TimetableChangeLog.ACTION_SUBSTITUTE_LAB,
                        reason=reason,
                        section=section,
                        day=day,
                        slot=slot,
                        before_snapshot=before_snapshot,
                        after_snapshot=_saved_slot_snapshot(scheduled),
                        source="saved",
                    )
                    messages.success(request, f"Lab teacher substituted to {new_teacher.name}.")
                    return redirect("saved_timetable", tid=tid)
            except Instructor.DoesNotExist:
                messages.error(request, "Selected teacher not found.")

    return render(request, "saved_substitute_teacher.html", {
        "saved": saved_t,
        "scheduled": scheduled,
        "section": sec,
        "day": day,
        "slot": slot,
        "available_teachers": available_teachers,
        "SLOT_LABELS": SLOT_LABELS,
        "is_lab": True,
    })


@login_required
def saved_move_slot_dragdrop(request, tid, section, day, slot):
    """Drag-and-drop move a slot in a saved timetable."""
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "POST required."}, status=405)

    saved_t = _get_saved_timetable_or_404(tid, request.user)

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "message": "Invalid payload."}, status=400)

    target_day = payload.get("target_day")
    target_slot = payload.get("target_slot")
    move_type = payload.get("move_type", "class")
    reason = _normalize_reason(payload.get("reason"))

    if not target_day or not target_slot:
        return JsonResponse({"ok": False, "message": "Missing target day/slot."}, status=400)
    if not reason:
        return JsonResponse({"ok": False, "message": "Reason is required to move a slot."}, status=400)

    source_mt = get_meeting_time(day, slot, user=request.user)
    target_mt = get_meeting_time(target_day, target_slot, user=request.user)

    if not source_mt or not target_mt:
        return JsonResponse({"ok": False, "message": "Invalid time slot."}, status=400)

    try:
        sec = Section.objects.get(section_id=section, user=request.user)
    except Section.DoesNotExist:
        return JsonResponse({"ok": False, "message": "Section not found."}, status=404)

    if move_type == "lab":
        scheduled = saved_t.slots.filter(section=sec, meeting_time=source_mt, is_lab=True).first()
    else:
        scheduled = saved_t.slots.filter(section=sec, meeting_time=source_mt, is_lab=False).first()

    if not scheduled:
        return JsonResponse({"ok": False, "message": "No slot found at source."}, status=404)

    if move_type == "lab":
        before_snapshot = _saved_slot_snapshot(scheduled)
        source_lab_times = list(scheduled.lab_slots.all().order_by("time"))
        if not source_lab_times:
            return JsonResponse({"ok": False, "message": "Lab has no time slots."}, status=400)

        # Calculate offset
        source_start_slot = int(source_lab_times[0].time)
        target_start_slot = int(target_mt.time)
        offset = target_start_slot - source_start_slot

        new_lab_times = []
        for lt in source_lab_times:
            new_slot_num = int(lt.time) + offset
            new_lt = get_meeting_time(target_day, new_slot_num, user=request.user)
            if not new_lt:
                return JsonResponse({"ok": False, "message": f"Target slot {new_slot_num} on {target_day} does not exist."}, status=400)
            new_lab_times.append(new_lt)

        # Check conflicts for all new lab times
        for nlt in new_lab_times:
            # Section conflict
            sec_conflict = saved_t.slots.filter(section=sec, meeting_time=nlt).exclude(id=scheduled.id).exists()
            if sec_conflict:
                return JsonResponse({"ok": False, "message": f"Section conflict at {target_day} slot {nlt.time}."}, status=409)
            # Teacher conflict
            teacher_conflict = saved_t.slots.filter(instructor=scheduled.instructor, meeting_time=nlt).exclude(id=scheduled.id).exists()
            if teacher_conflict:
                return JsonResponse({"ok": False, "message": f"Teacher conflict at {target_day} slot {nlt.time}."}, status=409)
            # Room conflict
            room_conflict = saved_t.slots.filter(room=scheduled.room, meeting_time=nlt).exclude(id=scheduled.id).exists()
            if room_conflict:
                return JsonResponse({"ok": False, "message": f"Room conflict at {target_day} slot {nlt.time}."}, status=409)

        # Apply move
        scheduled.meeting_time = new_lab_times[0]
        scheduled.save(update_fields=["meeting_time"])
        scheduled.lab_slots.set(new_lab_times)
        _create_saved_change_log(
            timetable=saved_t,
            request=request,
            action_type=TimetableChangeLog.ACTION_MOVE,
            reason=reason,
            section=section,
            day=target_day,
            slot=target_slot,
            before_snapshot=before_snapshot,
            after_snapshot=_saved_slot_snapshot(scheduled),
            source="saved",
        )

    else:
        # Theory class move
        before_snapshot = _saved_slot_snapshot(scheduled)
        # Check section conflict
        sec_conflict = saved_t.slots.filter(section=sec, meeting_time=target_mt).exclude(id=scheduled.id).exists()
        if sec_conflict:
            return JsonResponse({"ok": False, "message": "Section already has a class at target slot."}, status=409)
        # Teacher conflict
        teacher_conflict = saved_t.slots.filter(instructor=scheduled.instructor, meeting_time=target_mt).exclude(id=scheduled.id).exists()
        if teacher_conflict:
            return JsonResponse({"ok": False, "message": "Teacher already has a class at target slot."}, status=409)
        # Room conflict
        room_conflict = saved_t.slots.filter(room=scheduled.room, meeting_time=target_mt).exclude(id=scheduled.id).exists()
        if room_conflict:
            return JsonResponse({"ok": False, "message": "Room already occupied at target slot."}, status=409)

        scheduled.meeting_time = target_mt
        scheduled.save(update_fields=["meeting_time"])
        _create_saved_change_log(
            timetable=saved_t,
            request=request,
            action_type=TimetableChangeLog.ACTION_MOVE,
            reason=reason,
            section=section,
            day=target_day,
            slot=target_slot,
            before_snapshot=before_snapshot,
            after_snapshot=_saved_slot_snapshot(scheduled),
            source="saved",
        )

    return JsonResponse({"ok": True, "message": "Slot moved successfully."})


# ================================================================
# PUBLISH / TEACHER READ-ONLY VIEWS
# ================================================================

@login_required
def publish_timetable(request, tid):
    """HOD publishes a saved timetable with a custom code."""
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    if request.method == "POST":
        code = request.POST.get("publish_code", "").strip()
        if not code:
            messages.error(request, "Please enter a publish code.")
            return redirect("saved_timetable", tid=tid)
        conflict = SavedTimetable.objects.filter(
            user=request.user, publish_code=code, is_published=True
        ).exclude(id=tid).exists()
        if conflict:
            messages.error(request, "This code is already used for another timetable.")
            return redirect("saved_timetable", tid=tid)
        saved_t.is_published = True
        saved_t.publish_code = code
        saved_t.save(update_fields=["is_published", "publish_code"])
        messages.success(request, f"Timetable published with code: {code}")
    return redirect("saved_timetable", tid=tid)


@login_required
def unpublish_timetable(request, tid):
    """HOD unpublishes a timetable."""
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    if request.method == "POST":
        saved_t.is_published = False
        saved_t.publish_code = ""
        saved_t.save(update_fields=["is_published", "publish_code"])
        messages.success(request, "Timetable unpublished.")
    return redirect("saved_timetable", tid=tid)


@login_required
def teacher_enter_code(request):
    """Teacher enters a publish code to view a timetable."""
    if request.method == "POST":
        code = request.POST.get("access_code", "").strip()
        if not code:
            messages.error(request, "Please enter a code.")
            return render(request, "teacher_enter_code.html")
        timetable = SavedTimetable.objects.filter(
            is_published=True, publish_code=code
        ).first()
        if not timetable:
            messages.error(request, "No published timetable found with that code.")
            return render(request, "teacher_enter_code.html")
        return redirect("teacher_view_timetable", tid=timetable.id)
    return render(request, "teacher_enter_code.html")


@login_required
def teacher_view_timetable(request, tid):
    """Read-only timetable view for teachers accessing via publish code."""
    try:
        saved_t = SavedTimetable.objects.get(id=tid, is_published=True)
    except SavedTimetable.DoesNotExist:
        messages.error(request, "This timetable is not available.")
        return redirect("teacher_enter_code")

    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)
    owner = saved_t.user
    tables = build_section_tables(classes, labs, user=owner)
    room_tables = build_room_tables(classes, labs, user=owner)
    teacher_tables = build_teacher_tables(classes, labs, user=owner)
    teacher_workloads = _compute_teacher_workloads(classes, labs)
    change_logs = saved_t.change_logs.select_related("changed_by")[:40]

    context = {
        "saved": saved_t,
        "tables": tables,
        "room_tables": room_tables,
        "teacher_tables": teacher_tables,
        "teacher_workloads": teacher_workloads,
        "change_logs": change_logs,
        "SLOT_LABELS": SLOT_LABELS,
        "can_edit_delete": False,
        "can_substitute": False,
        "can_drag_drop": False,
        "is_readonly": True,
    }
    return render(request, "saved_timetable.html", context)


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
def dashboard_inst_list_view(request):
    return render(
        request,
        'dashboard_inslist.html',
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
def dashboard_department_list(request):
    return render(request, 'dashboard_deptlist.html', {'departments': Department.objects.filter(user=request.user)})


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
def dashboard_section_list(request):
    return render(request, 'dashboard_seclist.html', {'sections': Section.objects.filter(user=request.user)})


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


def _safe_get(obj, *attrs, default=""):
    for attr in attrs:
        value = getattr(obj, attr, None)
        if value not in (None, ""):
            return value
    return default


def _pick_slot_cell(table_rows, day, slot_number):
    for table_row in table_rows:
        if table_row.get("day") != day:
            continue
        for cell_data in table_row.get("cells", []):
            if str(cell_data.get("slot_number")) == str(slot_number):
                return cell_data
    return None


def _build_timetable_excel_response(classes, labs, user, filename, view_type='section'):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    except ImportError:
        return HttpResponse("Excel dependency missing", status=503)

    allowed_views = {"section", "room", "teacher", "workload", "all"}
    if view_type not in allowed_views:
        view_type = "section"

    classes = list(classes or [])
    labs = list(labs or [])

    section_tables = build_section_tables(classes, labs, user=user)
    room_tables = build_room_tables(classes, labs, user=user)
    teacher_tables = build_teacher_tables(classes, labs, user=user)
    teacher_workloads = _compute_teacher_workloads(classes, labs)

    wb = Workbook()
    wb.remove(wb.active)

    # ---- STYLES ----
    day_fill = PatternFill(start_color="D9E1F2", end_color="D9E1F2", fill_type="solid")
    day_font = Font(bold=True, size=10)

    lunch_fill = PatternFill(start_color="FFF2CC", end_color="FFF2CC", fill_type="solid")
    lunch_font = Font(bold=True, size=9)

    center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )

    # =====================================================
    # COMMON WRITER (DAYS → ROWS, SLOTS → COLUMNS)
    # =====================================================
    def write_timetable(ws, tables, title_func):
        row = 1

        for table in tables:
            # ---- TITLE ----
            ws[f"A{row}"] = title_func(table)
            ws[f"A{row}"].font = Font(bold=True, size=12, color="1F4E78")
            row += 1

            # ---- HEADER ----
            ws[f"A{row}"] = "Day"

            for slot in range(1, 10):
                cell = ws.cell(row=row, column=slot + 1,
                               value=SLOT_LABELS.get(str(slot), f"Slot {slot}"))
                cell.fill = day_fill
                cell.font = day_font
                cell.alignment = center_align

            row += 1

            # ---- DATA ----
            for day in DAYS:
                ws[f"A{row}"] = day
                ws[f"A{row}"].fill = day_fill
                ws[f"A{row}"].font = day_font

                for slot in range(1, 10):
                    xl_cell = ws.cell(row=row, column=slot + 1)
                    xl_cell.border = border
                    xl_cell.alignment = center_align

                    cell_data = _pick_slot_cell(table.get("rows", []), day, slot)

                    if not cell_data:
                        continue

                    cell_type = cell_data.get("type")

                    if cell_type == "lunch":
                        xl_cell.value = "LUNCH"
                        xl_cell.fill = lunch_fill
                        xl_cell.font = lunch_font

                    elif cell_type == "class":
                        class_items = cell_data.get("classes", [])
                        if class_items:
                            cls = class_items[0]
                            course = getattr(cls, "course", None)
                            instructor = getattr(cls, "instructor", None)
                            room = getattr(cls, "room", None)

                            xl_cell.value = "\n".join([
                                str(_safe_get(course, "course_number", "course_name", default="Class")),
                                str(_safe_get(instructor, "name", "uid", default="TBD")),
                                str(_safe_get(room, "r_number", default="Room TBD")),
                            ])

                    elif cell_type == "lab":
                        lab_items = cell_data.get("labs", [])
                        if lab_items:
                            lab = lab_items[0]
                            course = getattr(lab, "course", None)
                            instructor = getattr(lab, "instructor", None)
                            room = getattr(lab, "room", None)

                            xl_cell.value = "\n".join([
                                f"{_safe_get(course, 'course_number', 'course_name', default='Lab')} (Lab)",
                                str(_safe_get(instructor, "name", "uid", default="TBD")),
                                str(_safe_get(room, "r_number", default="Room TBD")),
                            ])

                row += 1

            row += 2

        # ---- WIDTH ----
        ws.column_dimensions["A"].width = 18
        for col in range(2, 11):
            ws.column_dimensions[chr(64 + col)].width = 25

    # =====================================================
    # SECTION
    # =====================================================
    if view_type in {"section", "all"}:
        ws = wb.create_sheet("Section Timetable")

        def section_title(table):
            section = table.get("section")
            dept = getattr(section, "department", None)
            return f"{_safe_get(section, 'section_id')} ({_safe_get(dept, 'name', default='Dept')})"

        write_timetable(ws, section_tables, section_title)

    # =====================================================
    # ROOM
    # =====================================================
    if view_type in {"room", "all"}:
        ws = wb.create_sheet("Room Timetable")

        def room_title(table):
            room = table.get("room")
            return f"Room: {_safe_get(room, 'r_number', default='Room')}"

        write_timetable(ws, room_tables, room_title)

    # =====================================================
    # TEACHER
    # =====================================================
    if view_type in {"teacher", "all"}:
        ws = wb.create_sheet("Teacher Timetable")

        def teacher_title(table):
            teacher = table.get("teacher")
            return f"Teacher: {_safe_get(teacher, 'name', 'uid', default='Teacher')}"

        write_timetable(ws, teacher_tables, teacher_title)

    # =====================================================
    # WORKLOAD
    # =====================================================
    if view_type in {"workload", "all"}:
        ws = wb.create_sheet("Teacher Workload")

        ws["A1"] = "Teacher Workload Summary"
        ws["A1"].font = Font(bold=True, size=12)

        headers = ["Teacher Name", "Classes", "Labs", "Total Hours"]
        for col, h in enumerate(headers, start=1):
            ws.cell(row=2, column=col, value=h)

        row = 3
        for teacher, workload in teacher_workloads.items():
            lectures = workload.get("lectures", workload.get("classes", 0))
            labs_count = workload.get("labs", 0)
            total_hours = workload.get("total", lectures + labs_count)

            ws.cell(row=row, column=1, value=_safe_get(teacher, "name", "uid"))
            ws.cell(row=row, column=2, value=lectures)
            ws.cell(row=row, column=3, value=labs_count)
            ws.cell(row=row, column=4, value=total_hours)

            row += 1

    # ---- RESPONSE ----
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    wb.save(response)

    return response


# =====================================================
# DOWNLOAD FUNCTIONS (UNCHANGED)
# =====================================================
@login_required
def download_timetable_excel(request, tid, view_type='section'):
    try:
        saved_t = SavedTimetable.objects.get(id=tid)
    except SavedTimetable.DoesNotExist:
        raise Http404("Timetable does not exist")

    if saved_t.user != request.user:
        return HttpResponseForbidden("You do not have permission")

    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)

    return _build_timetable_excel_response(
        classes=classes,
        labs=labs,
        user=request.user,
        filename=f"timetable_{tid}.xlsx",
        view_type=view_type,
    )


@login_required
def download_generated_timetable_excel(request, index, view_type='section'):
    try:
        idx = int(index)
    except:
        raise Http404("Invalid index")

    state = _get_user_state(request.user.id)
    schedules = state.get("schedules") or GLOBAL_GENERATED_SCHEDULES or []

    if not schedules or idx < 1 or idx > len(schedules):
        raise Http404("Invalid timetable")

    selected = schedules[idx - 1]
    classes = list(selected.get("classes", []))
    labs = list(selected.get("labs", []))

    return _build_timetable_excel_response(
        classes=classes,
        labs=labs,
        user=request.user,
        filename=f"generated_timetable_{idx}.xlsx",
        view_type=view_type,
    )

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


# ═══════════════════════════════════════════════════════════════
# TEACHER PREFERENCE VIEWS
# ═══════════════════════════════════════════════════════════════
import csv as _csv, io as _io, re as _re, json as _json
from django.http import HttpResponse as _HR
from django.core.mail import send_mail as _sm
from django.conf import settings as _cfg

_ERE = _re.compile(r'[\w\.\+\-]+@[\w\.\-]+\.[a-zA-Z]{2,}')

def teacher_pref_form(request):
    return render(request, 'teacher_pref_form.html')

def send_preferences_page(request):
    return render(request, 'send_preferences.html')

def teacher_responses_page(request):
    from .models import TeacherPreference
    subs = list(TeacherPreference.objects.all().values(
        'id','name','email','designation','subjects','classes','years','submitted_at'))
    for s in subs:
        s['submitted_at'] = s['submitted_at'].strftime('%d %b %Y, %I:%M %p')
    return render(request, 'teacher_responses.html', {
        'submissions_json': _json.dumps(subs), 'total': len(subs)})

@csrf_exempt
def teacher_pref_submit(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        from .models import TeacherPreference
        d = _json.loads(request.body)
        name=d.get('name','').strip(); email=d.get('email','').strip()
        desg=d.get('designation','').strip()
        subj=d.get('subjects',[]); cls=d.get('classes',[]); yrs=d.get('years',[])
        err = []
        if not name: err.append('Name required.')
        if not email or '@' not in email: err.append('Valid email required.')
        if not desg: err.append('Designation required.')
        if not subj: err.append('Select at least one subject.')
        if len(subj) > 3: err.append('Max 3 subjects.')
        if not cls: err.append('Select at least one class.')
        if not yrs: err.append('Select at least one year.')
        if err: return JsonResponse({'ok': False, 'errors': err}, status=400)
        sub = TeacherPreference.objects.create(
            name=name, email=email, designation=desg,
            subjects=subj, classes=cls, years=yrs)
        try:
            _sm(subject=f'SmartScheduler — Preferences Received: {name}',
                message=f'Name: {name}\nEmail: {email}\nDesignation: {desg}\nSubjects: {", ".join(subj)}\nClasses: {", ".join(cls)}\nYears: {", ".join(yrs)}',
                from_email=_cfg.EMAIL_HOST_USER,
                recipient_list=[email, _cfg.EMAIL_HOST_USER], fail_silently=True)
        except: pass
        return JsonResponse({'ok': True, 'id': sub.id})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

@csrf_exempt
def send_pref_links_smtp(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        d = _json.loads(request.body); emails = d.get('emails', [])
        base = request.build_absolute_uri('/teacher-pref-form/')
        sent, failed = [], []
        for email in emails:
            email = email.strip().lower()
            if not _ERE.match(email): failed.append(email); continue
            try:
                _sm(subject='SmartScheduler — Fill Your Teaching Preferences',
                    message=f'Dear Teacher,\n\nFill your preferences:\n{base}?email={email}\n\nThank you,\nSmartScheduler Team',
                    from_email=_cfg.EMAIL_HOST_USER,
                    recipient_list=[email], fail_silently=False)
                sent.append(email)
            except: failed.append(email)
        return JsonResponse({'ok': True, 'sent': sent, 'failed': failed})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

@csrf_exempt
def parse_emails_view(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        f = request.FILES.get('file')
        if not f: return JsonResponse({'ok': False, 'error': 'No file.'}, status=400)
        n = f.name.lower(); raw = ''
        if n.endswith('.csv'):
            content = f.read()
            try: t = content.decode('utf-8')
            except: t = content.decode('latin-1', errors='replace')
            raw = ' '.join(cell for row in _csv.reader(_io.StringIO(t)) for cell in row)
        elif n.endswith('.txt'):
            content = f.read()
            try: raw = content.decode('utf-8')
            except: raw = content.decode('latin-1', errors='replace')
        elif n.endswith('.pdf'):
            try:
                from pypdf import PdfReader
                raw = '\n'.join(p.extract_text() or '' for p in PdfReader(_io.BytesIO(f.read())).pages)
            except Exception as e:
                return JsonResponse({'ok': False, 'error': f'PDF error: {e}'}, status=400)
        else:
            return JsonResponse({'ok': False, 'error': 'Upload CSV, TXT, or PDF.'}, status=400)
        found = _ERE.findall(raw); seen = set(); emails = []
        for e in found:
            e = e.lower().strip('.')
            if e not in seen: seen.add(e); emails.append(e)
        if not emails:
            return JsonResponse({'ok': False, 'error': 'No emails found.'}, status=400)
        return JsonResponse({'ok': True, 'emails': emails, 'count': len(emails)})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)

def export_preferences_csv(request):
    from .models import TeacherPreference
    response = _HR(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="teacher_preferences.csv"'
    w = _csv.writer(response)
    w.writerow(['Name','Email','Designation','Subjects','Classes','Years','Submitted'])
    for s in TeacherPreference.objects.all():
        w.writerow([s.name, s.email, s.designation,
            ', '.join(s.subjects), ', '.join(s.classes), ', '.join(s.years),
            s.submitted_at.strftime('%d %b %Y %H:%M')])
    return response
