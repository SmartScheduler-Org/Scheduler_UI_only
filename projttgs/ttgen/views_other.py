from django.views.decorators.csrf import csrf_exempt
from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from .forms import *
from .models import *
from account.models import Profile, TeacherOnboarding
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
from django.utils import timezone
import copy
import csv
import math
import re
from datetime import date
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
            "generated_parking_items": [],
            "generated_slot_room_reservations": {},
            "generated_parking_next_id": 1,
            "generated_manual_slot_next_id": 1,
            "generated_edit_index": None,
            "prefill_mode": False,
            "prefill_section_ids": [],
            "prefill_locked_classes": [],
            "prefill_locked_labs": [],
        }
    return _USER_STATE[user_id]


def _reset_generated_drag_state(state, current_index=None):
    state["generated_parking_items"] = []
    state["generated_slot_room_reservations"] = {}
    state["generated_parking_next_id"] = 1
    state["generated_manual_slot_next_id"] = 1
    state["generated_edit_index"] = current_index


def _ensure_manual_prefill_slot_uid(state, item_obj):
    uid = str(getattr(item_obj, "manual_slot_uid", "") or "").strip()
    if uid:
        return uid
    next_id = int(state.get("generated_manual_slot_next_id") or 1)
    uid = f"manual-{next_id}"
    state["generated_manual_slot_next_id"] = next_id + 1
    setattr(item_obj, "manual_slot_uid", uid)
    return uid


def ensure_manual_prefill_slot_uids(state):
    for item_obj in list(state.get("classes") or []):
        if getattr(item_obj, "manual_entry", False):
            _ensure_manual_prefill_slot_uid(state, item_obj)
    for item_obj in list(state.get("labs") or []):
        if getattr(item_obj, "manual_entry", False):
            _ensure_manual_prefill_slot_uid(state, item_obj)
    for parked in list(state.get("generated_parking_items") or []):
        item_obj = parked.get("item")
        if item_obj is not None and getattr(item_obj, "manual_entry", False):
            parked["manual_slot_uid"] = _ensure_manual_prefill_slot_uid(state, item_obj)


def _next_generated_parking_id(state):
    next_id = state.get("generated_parking_next_id", 1)
    state["generated_parking_next_id"] = next_id + 1
    return next_id


def _decorate_generated_tables_with_parking(tables, state):
    parking_by_section = defaultdict(list)
    for item in state.get("generated_parking_items", []):
        parking_by_section[item["section_id"]].append(item)

    reserved_rooms = state.get("generated_slot_room_reservations", {})
    for table in tables:
        section_id = table["section"].section_id
        table["parking_items"] = parking_by_section.get(section_id, [])
        for row in table.get("rows", []):
            for cell in row.get("cells", []):
                key = (section_id, row["day"], str(cell.get("slot_number")))
                reservation = reserved_rooms.get(key)
                cell["reserved_room"] = reservation["room"] if reservation else None
                cell["has_room_context"] = bool(reservation)
    return tables


class ManualPrefillSubject:
    def __init__(self, label, duration=1):
        clean_label = (label or "Manual Subject").strip() or "Manual Subject"
        self.pk = None
        self.id = None
        self.subject_number = clean_label
        self.subject_name = clean_label
        self.room_required = "Lecture Hall"
        self.required_lab_category = ""
        self.specific_rooms = ""
        self.classes_per_week = 0
        self.duration = max(1, min(int(duration or 1), 8))

    def __str__(self):
        return self.subject_name


def _resolve_manual_prefill_subject(section_obj, subject_text, duration):
    subject_text = (subject_text or "").strip()
    if not subject_text:
        return ManualPrefillSubject("Manual Subject", duration=duration)
    matched = section_obj.allowed_subjects.filter(subject_number__iexact=subject_text).first()
    if matched is None:
        matched = section_obj.allowed_subjects.filter(subject_name__iexact=subject_text).first()
    if matched is not None:
        return matched
    return ManualPrefillSubject(subject_text, duration=duration)


def _parse_prefill_duration(value):
    try:
        duration = int(value)
    except (TypeError, ValueError):
        duration = 1
    return max(1, min(duration, 8))


def _prefill_teacher_uid(teacher):
    if teacher is None:
        return ""
    return str(getattr(teacher, "uid", "") or getattr(teacher, "pk", "") or "")


def _prefill_room_number(room):
    if room is None:
        return ""
    return str(getattr(room, "r_number", "") or getattr(room, "pk", "") or "")


def _prefill_subject_text(subject):
    if subject is None:
        return "Manual Subject"
    return str(getattr(subject, "subject_name", "") or getattr(subject, "subject_number", "") or subject or "Manual Subject")


def _serialize_prefill_class(cls):
    meeting_times = list(getattr(cls, "meeting_times", None) or [])
    if not meeting_times and getattr(cls, "meeting_time", None):
        meeting_times = [cls.meeting_time]
    first_time = meeting_times[0] if meeting_times else None
    return {
        "type": "class",
        "section_id": str(getattr(cls, "section", "") or ""),
        "subject_text": _prefill_subject_text(getattr(cls, "subject", None)),
        "teacher_uid": _prefill_teacher_uid(getattr(cls, "instructor", None)),
        "co_teacher_uids": [_prefill_teacher_uid(teacher) for teacher in list(getattr(cls, "co_instructors", []) or []) if teacher],
        "room_number": _prefill_room_number(getattr(cls, "room", None)),
        "day": getattr(first_time, "day", "") if first_time else "",
        "start_slot": str(getattr(first_time, "time", "") if first_time else ""),
        "duration": max(1, min(int(getattr(cls, "duration", None) or len(meeting_times) or 1), 8)),
        "manual_entry": bool(getattr(cls, "manual_entry", False)),
        "manual_slot_uid": str(getattr(cls, "manual_slot_uid", "") or ""),
        "prefill_locked": bool(getattr(cls, "prefill_locked", False)),
    }


def _serialize_prefill_lab(lab):
    meeting_times = list(getattr(lab, "meeting_times", None) or [])
    first_time = meeting_times[0] if meeting_times else None
    return {
        "type": "lab",
        "section_id": str(getattr(lab, "section", "") or ""),
        "subject_text": _prefill_subject_text(getattr(lab, "subject", None)),
        "teacher_uid": _prefill_teacher_uid(getattr(lab, "instructor", None)),
        "second_teacher_uid": _prefill_teacher_uid(getattr(lab, "second_instructor", None)),
        "co_teacher_uids": [_prefill_teacher_uid(teacher) for teacher in list(getattr(lab, "co_instructors", []) or []) if teacher],
        "room_number": _prefill_room_number(getattr(lab, "room", None)),
        "day": getattr(first_time, "day", "") if first_time else "",
        "start_slot": str(getattr(first_time, "time", "") if first_time else ""),
        "duration": max(1, min(int(getattr(lab, "duration", None) or len(meeting_times) or LAB_DURATION), 8)),
        "manual_entry": bool(getattr(lab, "manual_entry", False)),
        "manual_slot_uid": str(getattr(lab, "manual_slot_uid", "") or ""),
        "prefill_locked": bool(getattr(lab, "prefill_locked", False)),
        "batch": int(getattr(lab, "batch", 1) or 1),
        "total_batches": int(getattr(lab, "total_batches", 1) or 1),
    }


def save_prefill_session_snapshot(request, state=None):
    if not request or not getattr(request, "user", None) or not request.user.is_authenticated:
        return None
    state = state or _get_user_state(request.user.id)
    if not state.get("prefill_mode"):
        return None
    ensure_manual_prefill_slot_uids(state)
    snapshot = {
        "section_ids": list(state.get("prefill_section_ids") or request.session.get("prefill_section_ids") or []),
        "classes": [_serialize_prefill_class(cls) for cls in list(state.get("classes") or [])],
        "labs": [_serialize_prefill_lab(lab) for lab in list(state.get("labs") or [])],
        "parking_items": [],
    }
    for parked in list(state.get("generated_parking_items") or []):
        item_obj = parked.get("item")
        if item_obj is None:
            continue
        entry = _serialize_prefill_lab(item_obj) if parked.get("move_type") == "lab" else _serialize_prefill_class(item_obj)
        entry.update({
            "move_type": parked.get("move_type") or entry["type"],
            "section_id": str(parked.get("section_id") or entry.get("section_id") or ""),
            "slot_span": max(1, min(int(parked.get("slot_span") or entry.get("duration") or 1), 8)),
        })
        snapshot["parking_items"].append(entry)
    request.session["prefill_saved_slots"] = snapshot
    request.session.modified = True
    return snapshot


def _activate_prefill_snapshot(request, snapshot):
    section_ids = [str(section_id) for section_id in list((snapshot or {}).get("section_ids") or []) if str(section_id or "").strip()]
    if not section_ids:
        return False
    state = _get_user_state(request.user.id)
    state["classes"] = []
    state["labs"] = []
    state["schedules"] = [{"classes": [], "labs": [], "stats": {}, "reco_block": {}}]
    state["prefill_mode"] = True
    state["prefill_section_ids"] = section_ids
    state["prefill_locked_classes"] = []
    state["prefill_locked_labs"] = []
    _reset_generated_drag_state(state, current_index=1)
    request.session["current_index"] = 1
    request.session["prefill_mode"] = True
    request.session["prefill_section_ids"] = section_ids
    request.session["prefill_saved_slots"] = snapshot
    request.session.modified = True
    restore_prefill_session_snapshot(request, state, section_ids)
    return True


def _prefill_restore_teacher(uid, user):
    uid = str(uid or "").strip()
    if not uid:
        return None
    qs = Instructor.objects.filter(user=user)
    if uid.isdigit():
        return qs.filter(Q(uid__iexact=uid) | Q(pk=int(uid))).first()
    return qs.filter(uid__iexact=uid).first()


def _prefill_restore_room(room_number, user):
    room_number = str(room_number or "").strip()
    if not room_number:
        return None
    qs = Room.objects.filter(user=user)
    if room_number.isdigit():
        return qs.filter(Q(r_number__iexact=room_number) | Q(pk=int(room_number))).first()
    return qs.filter(r_number__iexact=room_number).first()


def _prefill_restore_meeting_times(entry, user):
    day = entry.get("day")
    try:
        start_slot = int(entry.get("start_slot"))
    except (TypeError, ValueError):
        return []
    duration = _parse_prefill_duration(entry.get("duration"))
    times = []
    for offset in range(duration):
        meeting_time = get_meeting_time(day, start_slot + offset, user=user)
        if meeting_time is None:
            return []
        times.append(meeting_time)
    return times


def _prefill_restore_class(entry, user):
    ClassImpl = globals().get("Class")
    if ClassImpl is None:
        return None
    try:
        section_obj = Section.objects.get(section_id=entry.get("section_id"), user=user)
    except Section.DoesNotExist:
        return None
    teacher = _prefill_restore_teacher(entry.get("teacher_uid"), user)
    room = _prefill_restore_room(entry.get("room_number"), user)
    if teacher is None or room is None:
        return None
    duration = _parse_prefill_duration(entry.get("duration"))
    subject = _resolve_manual_prefill_subject(section_obj, entry.get("subject_text"), duration)
    cls = ClassImpl(_next_in_memory_class_id(), section_obj.department, section_obj.section_id, subject)
    cls.set_instructor(teacher)
    co_teachers = [_prefill_restore_teacher(uid, user) for uid in list(entry.get("co_teacher_uids") or [])]
    if hasattr(cls, "set_co_instructors"):
        cls.set_co_instructors([teacher_obj for teacher_obj in co_teachers if teacher_obj])
    cls.set_room(room)
    times = _prefill_restore_meeting_times(entry, user)
    if times:
        cls.set_meetingTime(times[0])
        cls.meeting_times = times
    cls.duration = duration
    cls.manual_entry = bool(entry.get("manual_entry", True))
    cls.manual_slot_uid = str(entry.get("manual_slot_uid") or "")
    cls.prefill_locked = bool(entry.get("prefill_locked", bool(times)))
    return cls


def _prefill_restore_lab(entry, user):
    LabImpl = globals().get("Lab")
    if LabImpl is None:
        return None
    try:
        section_obj = Section.objects.get(section_id=entry.get("section_id"), user=user)
    except Section.DoesNotExist:
        return None
    teacher = _prefill_restore_teacher(entry.get("teacher_uid"), user)
    room = _prefill_restore_room(entry.get("room_number"), user)
    if teacher is None or room is None:
        return None
    duration = _parse_prefill_duration(entry.get("duration"))
    subject = _resolve_manual_prefill_subject(section_obj, entry.get("subject_text"), duration)
    lab = LabImpl(_next_in_memory_class_id(), section_obj.department, section_obj.section_id, subject, entry.get("batch", 1), entry.get("total_batches", 1))
    lab.set_instructor(teacher)
    second_teacher = _prefill_restore_teacher(entry.get("second_teacher_uid"), user)
    if second_teacher and hasattr(lab, "set_second_instructor"):
        lab.set_second_instructor(second_teacher)
    co_teachers = [_prefill_restore_teacher(uid, user) for uid in list(entry.get("co_teacher_uids") or [])]
    if hasattr(lab, "set_co_instructors"):
        lab.set_co_instructors([teacher_obj for teacher_obj in co_teachers if teacher_obj])
    lab.set_room(room)
    times = _prefill_restore_meeting_times(entry, user)
    if times:
        lab.set_meetingTimes(times)
    lab.duration = duration
    lab.manual_entry = bool(entry.get("manual_entry", True))
    lab.manual_slot_uid = str(entry.get("manual_slot_uid") or "")
    lab.prefill_locked = bool(entry.get("prefill_locked", bool(times)))
    return lab


def restore_prefill_session_snapshot(request, state, section_ids):
    snapshot = request.session.get("prefill_saved_slots") or {}
    saved_sections = set(snapshot.get("section_ids") or [])
    allowed_sections = set(section_ids or [])
    if saved_sections and saved_sections != allowed_sections:
        return False
    if state.get("classes") or state.get("labs") or state.get("generated_parking_items"):
        return False
    classes = []
    labs = []
    for entry in list(snapshot.get("classes") or []):
        if entry.get("section_id") not in allowed_sections:
            continue
        restored = _prefill_restore_class(entry, request.user)
        if restored is not None:
            classes.append(restored)
    for entry in list(snapshot.get("labs") or []):
        if entry.get("section_id") not in allowed_sections:
            continue
        restored = _prefill_restore_lab(entry, request.user)
        if restored is not None:
            labs.append(restored)
    state["classes"] = classes
    state["labs"] = labs
    state["prefill_locked_classes"] = list(classes)
    state["prefill_locked_labs"] = list(labs)
    state["generated_parking_items"] = []
    state["generated_parking_next_id"] = 1
    build_parking_item = globals().get("_generated_build_parking_item")
    if build_parking_item:
        for entry in list(snapshot.get("parking_items") or []):
            if entry.get("section_id") not in allowed_sections:
                continue
            move_type = entry.get("move_type") or entry.get("type") or "class"
            restored = _prefill_restore_lab(entry, request.user) if move_type == "lab" else _prefill_restore_class(entry, request.user)
            if restored is not None:
                state["generated_parking_items"].append(build_parking_item(state, entry.get("section_id"), move_type, restored))
    return bool(classes or labs or state.get("generated_parking_items"))


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


def get_valid_start_slots(duration):
    """Return valid start slots for a given duration, avoiding lunch (slot 5)."""
    pre_lunch = [str(s) for s in range(1, 5) if s + duration - 1 <= 4]
    post_lunch = [str(s) for s in range(6, 10) if s + duration - 1 <= 9]
    return pre_lunch + post_lunch




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


def clone_section_subjects_from_similar(section):
    if section.allowed_subjects.exists():
        return None

    semester, tokens = get_section_signature(section.section_id)
    if not semester or not tokens:
        return None

    best_match = None
    best_score = None

    candidates = (
        Section.objects.filter(department=section.department, user=section.user)
        .exclude(pk=section.pk)
        .prefetch_related("allowed_subjects")
    )
    for candidate in candidates:
        if not candidate.allowed_subjects.exists():
            continue
        candidate_semester, candidate_tokens = get_section_signature(candidate.section_id)
        if candidate_semester != semester:
            continue
        overlap = len(set(tokens) & set(candidate_tokens))
        if overlap <= 0:
            continue
        score = (overlap, candidate.allowed_subjects.count(), -len(candidate.section_id))
        if best_score is None or score > best_score:
            best_score = score
            best_match = candidate

    if not best_match:
        return None

    subjects_to_copy = list(best_match.allowed_subjects.all())
    if not subjects_to_copy:
        return None

    section.allowed_subjects.add(*subjects_to_copy)
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
                return redirect('teacher_dashboard')
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
    if _get_teacher_onboarding(request.user):
        return redirect('teacher_dashboard')
    return redirect('teacher_onboarding')


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


def _get_teacher_profile_or_locked_response(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    role_value = (profile.role or "").strip().lower()
    if role_value and role_value != "teacher":
        return profile, profile.get_role_display()
    return profile, ""


def _get_active_teacher_timetable(profile):
    if not profile.active_timetable_id:
        return None
    return SavedTimetable.objects.select_related("user").filter(
        id=profile.active_timetable_id,
        is_published=True,
    ).first()


def _connect_teacher_timetable(profile, code):
    timetable = SavedTimetable.objects.select_related("user").filter(
        is_published=True,
        publish_code=code,
    ).first()
    if not timetable:
        return None, "No published timetable found with that code."

    update_fields = ["active_timetable"]
    profile.active_timetable = timetable
    if profile.linked_instructor and profile.linked_instructor.user_id != timetable.user_id:
        profile.linked_instructor = None
        update_fields.append("linked_instructor")
    profile.save(update_fields=update_fields)
    return timetable, None


def _ensure_teacher_role(profile):
    if not profile.role:
        profile.role = "teacher"
        profile.save(update_fields=["role"])


def _get_teacher_onboarding(user):
    return getattr(user, "teacher_onboarding", None)


def _teacher_onboarding_redirect_response(request):
    onboarding = _get_teacher_onboarding(request.user)
    if onboarding and not onboarding.requires_resubmission:
        return None
    return redirect("teacher_onboarding")


def _user_can_manage_teacher_onboarding(user):
    if not user.is_authenticated:
        return False
    if user.is_superuser or user.is_staff:
        return True
    profile, _ = Profile.objects.get_or_create(user=user)
    return (profile.role or "").strip().lower() == "hod"


def _teacher_nav_context():
    return {
        "hide_live_demo": True,
        "hide_nav_cta": True,
        "show_teacher_profile_icon": True,
    }


def _format_local_datetime(value, fmt):
    if not value:
        return ""
    return timezone.localtime(value).strftime(fmt)


def _resolve_teacher_dashboard_context(request, profile):
    active_timetable = _get_active_teacher_timetable(profile)
    onboarding = _get_teacher_onboarding(request.user)
    sync_fields = []

    if profile.active_timetable_id and active_timetable is None:
        profile.active_timetable = None
        sync_fields.append("active_timetable")

    if (
        profile.linked_instructor_id
        and active_timetable
        and profile.linked_instructor.user_id != active_timetable.user_id
    ):
        profile.linked_instructor = None
        sync_fields.append("linked_instructor")

    if sync_fields:
        profile.save(update_fields=sync_fields)

    linked_instructor = profile.linked_instructor
    teacher_subjects = []
    my_teacher_table = None
    teacher_workload = {"lectures": 0, "labs": 0, "total": 0}
    published_section_count = 0
    published_teacher_count = 0

    if linked_instructor:
        teacher_subjects = list(
            Subject.objects.filter(
                user=linked_instructor.user,
                instructors=linked_instructor,
            ).order_by("subject_name", "subject_number").distinct()
        )

    if active_timetable:
        classes, labs = _rebuild_classes_and_labs_from_saved(active_timetable)
        section_tables = build_section_tables(classes, labs, user=active_timetable.user)
        teacher_tables = build_teacher_tables(classes, labs, user=active_timetable.user)
        teacher_workloads = _compute_teacher_workloads(classes, labs)
        published_section_count = len(section_tables)
        published_teacher_count = len(teacher_tables)
        if linked_instructor:
            my_teacher_table = next(
                (
                    table for table in teacher_tables
                    if table["teacher"].id == linked_instructor.id
                ),
                None,
            )
            teacher_workload = teacher_workloads.get(linked_instructor, teacher_workload)

    display_name = (
        onboarding.full_name
        if onboarding
        else request.user.get_full_name().strip() or request.user.username
    )
    if linked_instructor:
        display_name = linked_instructor.name

    role_label = profile.get_role_display() or "Teacher"
    designation = (
        linked_instructor.designation
        if linked_instructor
        else onboarding.designation if onboarding else "Teacher"
    )
    profile_card_state = (
        f"Linked to {linked_instructor.uid}"
        if linked_instructor else
        "Add contact and faculty UID"
    )
    published_card_state = (
        f"Code {active_timetable.publish_code}"
        if active_timetable else
        "Connect publish code"
    )
    if my_teacher_table:
        timetable_card_state = "Teacher timetable ready"
    elif active_timetable and linked_instructor:
        timetable_card_state = "No classes assigned yet"
    elif active_timetable:
        timetable_card_state = "Link faculty UID first"
    else:
        timetable_card_state = "Connect published timetable first"

    context = {
        "teacher_profile": profile,
        "teacher_onboarding": onboarding,
        "active_timetable": active_timetable,
        "linked_instructor": linked_instructor,
        "teacher_subjects": teacher_subjects,
        "my_teacher_table": my_teacher_table,
        "teacher_workload": teacher_workload,
        "published_section_count": published_section_count,
        "published_teacher_count": published_teacher_count,
        "teacher_display_name": display_name,
        "teacher_role_label": role_label,
        "teacher_designation": designation,
        "faculty_uid_value": linked_instructor.uid if linked_instructor else "",
        "profile_email_value": request.user.email or "",
        "slot_labels": SLOT_LABELS,
        "profile_card_state": profile_card_state,
        "published_card_state": published_card_state,
        "timetable_card_state": timetable_card_state,
        "teacher_subject_count": len(teacher_subjects),
}
    context.update(_teacher_nav_context())
    return context


@login_required
def teacher_onboarding(request):
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, "role_locked.html", {"current_role": locked_response})

    _ensure_teacher_role(profile)

    existing_onboarding = _get_teacher_onboarding(request.user)
    if existing_onboarding and not existing_onboarding.requires_resubmission:
        return redirect("teacher_dashboard")

    form_values = {
        "full_name": existing_onboarding.full_name if existing_onboarding else request.user.get_full_name().strip() or request.user.username,
        "designation": existing_onboarding.designation if existing_onboarding else "",
        "joining_year": existing_onboarding.joining_year if existing_onboarding else "",
        "email": existing_onboarding.email if existing_onboarding else request.user.email or "",
        "subjects_taught": existing_onboarding.subjects_taught if existing_onboarding else "",
    }

    if request.method == "POST":
        form_values = {
            "full_name": request.POST.get("full_name", "").strip(),
            "designation": request.POST.get("designation", "").strip(),
            "joining_year": request.POST.get("joining_year", "").strip(),
            "email": request.POST.get("email", "").strip(),
            "subjects_taught": request.POST.get("subjects_taught", "").strip(),
        }

        errors = []
        if not form_values["full_name"]:
            errors.append("Please enter your full name.")
        if form_values["designation"] not in dict(TeacherOnboarding.DESIGNATION_CHOICES):
            errors.append("Please choose a valid designation.")
        if not form_values["email"] or "@" not in form_values["email"]:
            errors.append("Please enter a valid email address.")
        if not form_values["subjects_taught"]:
            errors.append("Please enter the subjects you teach.")

        joining_year = None
        if not form_values["joining_year"]:
            errors.append("Please enter your joining year.")
        else:
            try:
                joining_year = int(form_values["joining_year"])
            except ValueError:
                errors.append("Joining year must be a number.")

        current_year = date.today().year
        if joining_year is not None and not (1950 <= joining_year <= current_year + 1):
            errors.append(f"Joining year must be between 1950 and {current_year + 1}.")

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            if existing_onboarding:
                existing_onboarding.full_name = form_values["full_name"]
                existing_onboarding.designation = form_values["designation"]
                existing_onboarding.joining_year = joining_year
                existing_onboarding.email = form_values["email"]
                existing_onboarding.subjects_taught = form_values["subjects_taught"]
                existing_onboarding.requires_resubmission = False
                existing_onboarding.resubmission_requested_at = None
                existing_onboarding.save(
                    update_fields=[
                        "full_name",
                        "designation",
                        "joining_year",
                        "email",
                        "subjects_taught",
                        "requires_resubmission",
                        "resubmission_requested_at",
                        "updated_at",
                    ]
                )
            else:
                TeacherOnboarding.objects.create(
                    user=request.user,
                    full_name=form_values["full_name"],
                    designation=form_values["designation"],
                    joining_year=joining_year,
                    email=form_values["email"],
                    subjects_taught=form_values["subjects_taught"],
                )
            if request.user.email != form_values["email"]:
                request.user.email = form_values["email"]
                request.user.save(update_fields=["email"])
            if existing_onboarding:
                messages.success(request, "Your corrected teacher form has been submitted.")
            else:
                messages.success(request, "Your teacher profile form has been submitted.")
            return redirect("teacher_dashboard")

    context = {
        "designation_choices": TeacherOnboarding.DESIGNATION_CHOICES,
        "form_values": form_values,
        "show_resubmission_notice": bool(existing_onboarding and existing_onboarding.requires_resubmission),
    }
    context.update(_teacher_nav_context())
    return render(request, "teacher_onboarding.html", context)


@login_required
def teacher_dashboard(request):
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, 'role_locked.html', {'current_role': locked_response})

    _ensure_teacher_role(profile)

    redirect_response = _teacher_onboarding_redirect_response(request)
    if redirect_response:
        return redirect_response

    context = _resolve_teacher_dashboard_context(request, profile)
    return render(request, "teacher_dashboard.html", context)


@login_required
def teacher_profile_page(request):
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, 'role_locked.html', {'current_role': locked_response})

    _ensure_teacher_role(profile)

    redirect_response = _teacher_onboarding_redirect_response(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        contact_number = request.POST.get("contact_number", "").strip()
        faculty_uid = request.POST.get("faculty_uid", "").strip()
        profile.contact_number = contact_number
        update_fields = ["contact_number"]

        if faculty_uid:
            active_timetable = _get_active_teacher_timetable(profile)
            if not active_timetable:
                messages.error(request, "Connect the HOD published timetable before linking your faculty UID.")
            else:
                instructor = Instructor.objects.filter(
                    user=active_timetable.user,
                    uid__iexact=faculty_uid,
                ).first()
                if instructor is None:
                    messages.error(request, "No teacher record matched that faculty UID in the published timetable.")
                else:
                    profile.linked_instructor = instructor
                    update_fields.append("linked_instructor")
                    messages.success(request, "Your faculty profile is linked and ready for the teacher timetable page.")
        elif request.POST.get("clear_faculty_link") == "1":
            profile.linked_instructor = None
            update_fields.append("linked_instructor")
            messages.success(request, "Faculty link removed from your teacher profile.")
        else:
            messages.success(request, "Your teacher profile details were updated.")

        profile.save(update_fields=list(dict.fromkeys(update_fields)))
        return redirect("teacher_profile_page")

    context = _resolve_teacher_dashboard_context(request, profile)
    return render(request, "teacher_profile_page.html", context)


@login_required
def teacher_published_timetable(request):
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, 'role_locked.html', {'current_role': locked_response})

    _ensure_teacher_role(profile)

    redirect_response = _teacher_onboarding_redirect_response(request)
    if redirect_response:
        return redirect_response

    if request.method == "POST":
        code = request.POST.get("access_code", "").strip()
        if not code:
            messages.error(request, "Please enter the publish code shared by your HOD.")
        else:
            timetable, error_message = _connect_teacher_timetable(profile, code)
            if error_message:
                messages.error(request, error_message)
            else:
                messages.success(
                    request,
                    f"HOD published timetable connected with code {timetable.publish_code}.",
                )
        return redirect("teacher_published_timetable")

    context = _resolve_teacher_dashboard_context(request, profile)
    return render(request, "teacher_published_timetable.html", context)


@login_required
def teacher_my_timetable(request):
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, 'role_locked.html', {'current_role': locked_response})

    _ensure_teacher_role(profile)

    redirect_response = _teacher_onboarding_redirect_response(request)
    if redirect_response:
        return redirect_response

    context = _resolve_teacher_dashboard_context(request, profile)
    return render(request, "teacher_my_timetable.html", context)

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
        'teacher_onboarding_count': TeacherOnboarding.objects.count(),
    }
    return render(request, 'admindashboard.html', context)


@login_required
def teacher_onboarding_responses_page(request):
    if not _user_can_manage_teacher_onboarding(request.user):
        return HttpResponseForbidden("You do not have permission to view teacher onboarding submissions.")

    submissions = []
    for submission in TeacherOnboarding.objects.select_related("user").all():
        submissions.append({
            "id": submission.id,
            "full_name": submission.full_name,
            "username": submission.user.username,
            "designation": submission.designation,
            "joining_year": submission.joining_year,
            "email": submission.email,
            "subjects_taught": submission.subjects_taught,
            "submitted_at": _format_local_datetime(submission.submitted_at, "%d %b %Y, %I:%M %p"),
            "requires_resubmission": submission.requires_resubmission,
            "delete_url": reverse("delete_teacher_onboarding", args=[submission.id]),
            "resubmit_url": reverse("request_teacher_onboarding_resubmission", args=[submission.id]),
        })

    return render(
        request,
        "teacher_onboarding_responses.html",
        {
            "submissions_json": json.dumps(submissions),
            "total": len(submissions),
        },
    )


@login_required
def request_teacher_onboarding_resubmission(request, submission_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST request required.")
    if not _user_can_manage_teacher_onboarding(request.user):
        return HttpResponseForbidden("You do not have permission to request teacher form resubmission.")

    submission = TeacherOnboarding.objects.filter(id=submission_id).first()
    if submission is None:
        messages.error(request, "Teacher form submission was not found.")
        return redirect("teacher_onboarding_responses")

    submission.requires_resubmission = True
    submission.resubmission_requested_at = timezone.now()
    submission.save(update_fields=["requires_resubmission", "resubmission_requested_at", "updated_at"])
    messages.success(request, f"Resubmission was requested for {submission.full_name}.")
    return redirect("teacher_onboarding_responses")


@login_required
def delete_teacher_onboarding(request, submission_id):
    if request.method != "POST":
        return HttpResponseForbidden("POST request required.")
    if not _user_can_manage_teacher_onboarding(request.user):
        return HttpResponseForbidden("You do not have permission to delete teacher form submissions.")

    submission = TeacherOnboarding.objects.filter(id=submission_id).first()
    if submission is None:
        messages.error(request, "Teacher form submission was not found.")
    else:
        full_name = submission.full_name
        submission.delete()
        messages.success(request, f"Teacher form for {full_name} was deleted.")
    return redirect("teacher_onboarding_responses")


@login_required
def export_teacher_onboarding_csv(request):
    if not _user_can_manage_teacher_onboarding(request.user):
        return HttpResponseForbidden("You do not have permission to export teacher onboarding submissions.")

    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = 'attachment; filename="teacher_onboarding_submissions.csv"'
    writer = csv.writer(response)
    writer.writerow(["Username", "Full Name", "Designation", "Joining Year", "Email", "Subjects Taught", "Submitted"])
    for submission in TeacherOnboarding.objects.select_related("user").all():
        writer.writerow([
            submission.user.username,
            submission.full_name,
            submission.designation,
            submission.joining_year,
            submission.email,
            submission.subjects_taught,
            _format_local_datetime(submission.submitted_at, "%d %b %Y %H:%M"),
        ])
    return response


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
        def __init__(self, id, dept, section, subject):
            self.section_id = id
            self.department = dept
            self.subject = subject
            self.instructor = None
            self.co_instructors = []
            self.meeting_time = None
            self.meeting_times = []
            self.room = None
            self.section = section
            self.duration = getattr(subject, 'duration', 1)

        def set_instructor(self, instructor): self.instructor = instructor
        def set_co_instructors(self, instructors): self.co_instructors = list(instructors or [])
        def set_meetingTime(self, mt): self.meeting_time = mt
        def set_room(self, room): self.room = room


if "Lab" not in globals():
    class Lab:
        def __init__(self, id, dept, section, subject, batch=1, total_batches=1):
            self.section_id = id
            self.department = dept
            self.subject = subject
            self.instructor = None
            self.second_instructor = None   # shared lab: optional second teacher
            self.co_instructors = []
            self.room = None
            self.section = section
            self.duration = getattr(subject, 'duration', LAB_DURATION)
            self.meeting_times = []
            self.batch = batch
            self.total_batches = total_batches

        def set_second_instructor(self, instructor): self.second_instructor = instructor
        def set_co_instructors(self, instructors): self.co_instructors = list(instructors or [])
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
                        lab_span = max((len(lb.meeting_times) for lb in cell_data["labs"] if lb.meeting_times), default=getattr(cell_data["labs"][0], 'duration', LAB_DURATION))
                        cells.append({
                            "type": "lab",
                            "colspan": lab_span,
                            "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cls_dur = getattr(cell_data["classes"][0], 'duration', 1)
                        cells.append({
                            "type": "class",
                            "colspan": cls_dur,
                            "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                        if cls_dur > 1:
                            skip_until = s + cls_dur - 1
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
            for t in [cls.instructor] + list(getattr(cls, "co_instructors", []) or []):
                if t and t not in teacher_map:
                    teacher_map[t] = {"classes": [], "labs": []}
                if t:
                    teacher_map[t]["classes"].append(cls)
        for lab in all_labs:
            teachers = [lab.instructor, getattr(lab, "second_instructor", None)] + list(getattr(lab, "co_instructors", []) or [])
            for t in teachers:
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
                        lab_span = max((len(lb.meeting_times) for lb in cell_data["labs"] if lb.meeting_times), default=getattr(cell_data["labs"][0], 'duration', LAB_DURATION))
                        cells.append({
                            "type": "lab", "colspan": lab_span, "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cls_dur = getattr(cell_data["classes"][0], 'duration', 1)
                        cells.append({
                            "type": "class", "colspan": cls_dur, "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                        if cls_dur > 1:
                            skip_until = s + cls_dur - 1
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
                        lab_span = max((len(lb.meeting_times) for lb in cell_data["labs"] if lb.meeting_times), default=getattr(cell_data["labs"][0], 'duration', LAB_DURATION))
                        cells.append({
                            "type": "lab", "colspan": lab_span, "slot_number": s,
                            "labs": cell_data["labs"],
                        })
                        skip_until = s + lab_span - 1
                    elif cell_data["classes"]:
                        cls_dur = getattr(cell_data["classes"][0], 'duration', 1)
                        cells.append({
                            "type": "class", "colspan": cls_dur, "slot_number": s,
                            "classes": cell_data["classes"],
                        })
                        if cls_dur > 1:
                            skip_until = s + cls_dur - 1
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
        "section", "section__department", "subject", "instructor", "second_instructor", "room", "meeting_time",
    ).prefetch_related("lab_slots").all()

    classes = []
    labs = []
    lab_slots_list = []

    # Pre-fetch all meeting times grouped by day for multi-slot class reconstruction
    from ttgen.models import MeetingTime as MT
    all_mts = list(MT.objects.filter(user=saved_t.user))
    mts_by_day = {}
    slot_order = ["1","2","3","4","5","6","7","8","9"]
    for m in all_mts:
        mts_by_day.setdefault(m.day, []).append(m)
    for d in mts_by_day:
        mts_by_day[d].sort(key=lambda x: slot_order.index(x.time) if x.time in slot_order else 99)

    for slot in slots:
        if slot.is_lab:
            lab_slots_list.append(slot)
        else:
            cls = Class(
                id=0,
                dept=slot.section.department,
                section=slot.section.section_id,
                subject=slot.subject,
            )
            cls.instructor = slot.instructor
            cls.room = slot.room
            cls.meeting_time = slot.meeting_time
            # Rebuild meeting_times for multi-slot classes
            cls_dur = getattr(slot.subject, 'duration', 1)
            if cls_dur > 1:
                day_mts = mts_by_day.get(slot.meeting_time.day, [])
                start_idx = next((i for i, m in enumerate(day_mts) if m.time == slot.meeting_time.time), None)
                if start_idx is not None and start_idx + cls_dur <= len(day_mts):
                    cls.meeting_times = day_mts[start_idx:start_idx + cls_dur]
                else:
                    cls.meeting_times = [slot.meeting_time]
            else:
                cls.meeting_times = [slot.meeting_time]
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
                subject=slot.subject,
                batch=batch_num,
                total_batches=total_batches,
            )
            lab_obj.instructor = slot.instructor
            lab_obj.second_instructor = slot.second_instructor
            lab_obj.room = slot.room
            lab_obj.meeting_times = list(slot.lab_slots.all())
            labs.append(lab_obj)

    return classes, labs


def _compute_teacher_workloads(classes, labs):
    """Compute teacher workload summary from classes and labs."""
    workloads = {}

    def _ensure_teacher(teacher):
        if teacher not in workloads:
            workloads[teacher] = {
                "lectures": 0,
                "labs": 0,
                "shared_labs": 0,
                "total": 0,
                "departments": set(),
            }
        return workloads[teacher]

    def _add_department(teacher, item_obj):
        data = _ensure_teacher(teacher)
        dept = getattr(item_obj, "department", None)
        dept_name = getattr(dept, "name", "") or getattr(dept, "code", "")
        if dept_name:
            data["departments"].add(str(dept_name))

    for cls in classes:
        teacher = cls.instructor
        cls_dur = getattr(cls, 'duration', 1)
        teachers = [teacher] + list(getattr(cls, "co_instructors", []) or [])
        for assigned_teacher in teachers:
            if not assigned_teacher:
                continue
            data = _ensure_teacher(assigned_teacher)
            data["lectures"] += cls_dur
            data["total"] += cls_dur
            _add_department(assigned_teacher, cls)
    for lab in labs:
        teacher = lab.instructor
        lab_slot_count = len(lab.meeting_times) if lab.meeting_times else getattr(lab, 'duration', LAB_DURATION)
        second_teacher = getattr(lab, "second_instructor", None)
        co_teachers = list(getattr(lab, "co_instructors", []) or [])
        if second_teacher:
            shared_load = lab_slot_count / 2
            for assigned_teacher in [teacher, second_teacher] + co_teachers:
                if not assigned_teacher:
                    continue
                data = _ensure_teacher(assigned_teacher)
                data["shared_labs"] += shared_load
                data["total"] += shared_load
                _add_department(assigned_teacher, lab)
        else:
            for assigned_teacher in [teacher] + co_teachers:
                if not assigned_teacher:
                    continue
                data = _ensure_teacher(assigned_teacher)
                data["labs"] += lab_slot_count
                data["total"] += lab_slot_count
                _add_department(assigned_teacher, lab)

    for data in workloads.values():
        data["departments"] = ", ".join(sorted(data["departments"])) or "-"
        for key in ("lectures", "labs", "shared_labs", "total"):
            value = data.get(key, 0)
            if isinstance(value, float) and value.is_integer():
                data[key] = int(value)
    return workloads


def _get_program_filter_options(user):
    """Return distinct, non-empty program names for section-level filtering."""
    return sorted(
        {
            (name or "").strip()
            for name in Section.objects.filter(user=user).values_list("program_name", flat=True)
            if (name or "").strip()
        },
        key=lambda value: value.lower(),
    )


def _filter_entities_by_program(classes, labs, user, selected_program):
    """Filter in-memory timetable entities by section program name."""
    selected_program = (selected_program or "all").strip()
    if not selected_program or selected_program.lower() == "all":
        return classes, labs, "all"

    allowed_sections = set(
        Section.objects.filter(user=user, program_name__iexact=selected_program).values_list("section_id", flat=True)
    )
    filtered_classes = [cls for cls in classes if str(getattr(cls, "section", "")) in allowed_sections]
    filtered_labs = [lab for lab in labs if str(getattr(lab, "section", "")) in allowed_sections]
    return filtered_classes, filtered_labs, selected_program


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
    from django.conf import settings as _settings
    if getattr(_settings, "BYPASS_ACCESS", False):
        return {
            "can_edit_delete": True,
            "can_substitute": True,
            "can_drag_drop": True,
        }
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


@login_required
def saved_timetable_list(request):
    timetables = SavedTimetable.objects.filter(user=request.user)
    return render(request, "saved_timetable_list.html", {
        "timetables": timetables,
        "timetable_count": timetables.count(),
        "save_limit": 2,
    })


@login_required
def saved_timetable(request, tid):
    saved_t = _get_saved_timetable_or_404(tid, request.user)
    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)

    selected_program = request.GET.get("program", "all")
    classes, labs, selected_program = _filter_entities_by_program(classes, labs, request.user, selected_program)

    tables = build_section_tables(classes, labs, user=request.user)
    room_tables = build_room_tables(classes, labs, user=request.user)
    teacher_tables = build_teacher_tables(classes, labs, user=request.user)
    teacher_workloads = _compute_teacher_workloads(classes, labs)

    permissions = _get_plan_permissions(request.user)

    context = {
        "saved": saved_t,
        "tables": tables,
        "room_tables": room_tables,
        "teacher_tables": teacher_tables,
        "teacher_workloads": teacher_workloads,
        "program_options": _get_program_filter_options(request.user),
        "active_program": selected_program,
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
                    scheduled.instructor = new_teacher
                    scheduled.save(update_fields=["instructor"])
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
                    scheduled.instructor = new_teacher
                    scheduled.save(update_fields=["instructor"])
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

    if not target_day or not target_slot:
        return JsonResponse({"ok": False, "message": "Missing target day/slot."}, status=400)

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

    else:
        # Theory class move
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
    """Legacy route: connect the HOD publish code and return to the timetable page."""
    profile, locked_response = _get_teacher_profile_or_locked_response(request.user)
    if locked_response:
        return render(request, 'role_locked.html', {'current_role': locked_response})

    _ensure_teacher_role(profile)

    if request.method == "POST":
        code = request.POST.get("access_code", "").strip()
        if not code:
            messages.error(request, "Please enter the publish code shared by your HOD.")
            return redirect("teacher_published_timetable")
        timetable, error_message = _connect_teacher_timetable(profile, code)
        if error_message:
            messages.error(request, error_message)
            return redirect("teacher_published_timetable")
        messages.success(request, f"HOD published timetable connected with code {timetable.publish_code}.")
        return redirect("teacher_published_timetable")
    return redirect("teacher_published_timetable")


@login_required
def teacher_view_timetable(request, tid):
    """Read-only timetable view for teachers accessing via publish code."""
    try:
        saved_t = SavedTimetable.objects.get(id=tid, is_published=True)
    except SavedTimetable.DoesNotExist:
        messages.error(request, "This timetable is not available.")
        return redirect("teacher_published_timetable")

    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)
    owner = saved_t.user
    selected_program = request.GET.get("program", "all")
    classes, labs, selected_program = _filter_entities_by_program(classes, labs, owner, selected_program)
    tables = build_section_tables(classes, labs, user=owner)
    room_tables = build_room_tables(classes, labs, user=owner)
    teacher_tables = build_teacher_tables(classes, labs, user=owner)
    teacher_workloads = _compute_teacher_workloads(classes, labs)

    context = {
        "saved": saved_t,
        "tables": tables,
        "room_tables": room_tables,
        "teacher_tables": teacher_tables,
        "teacher_workloads": teacher_workloads,
        "program_options": _get_program_filter_options(owner),
        "active_program": selected_program,
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
def addSubjects(request):
    form = SubjectForm(request.POST or None, user=request.user)

    # ============================
    # MANUAL ADD SUBJECT
    # ============================
    if request.method == "POST" and "add_subject" in request.POST:
        if form.is_valid():
            subject = form.save(commit=False)
            subject.user = request.user
            raw_room = (subject.room_required or "").strip().lower()
            subject.room_required = {"lab": "Lab", "lecture hall": "Lecture Hall"}.get(raw_room, subject.room_required)
            subject.required_lab_category = normalize_lab_category(subject.required_lab_category)

            if subject.room_required == "Lab" and not subject.required_lab_category:
                messages.error(request, "Lab subjects must have a Required Lab Category.")
                return redirect("addSubjects")
            if subject.room_required != "Lab":
                subject.required_lab_category = ""

            # Auto-set classes per week
            if subject.room_required == "Lab":
                subject.classes_per_week = 4
            else:
                subject.classes_per_week = 3

            subject.save()
            form.save_m2m()

            reset_global_schedule_cache(request.user.id)
            messages.success(request, "Subject added successfully!")
            return redirect("addSubjects")

    # ============================
    # CSV UPLOAD SUBJECTS
    # ============================
    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file or not csv_file.name.endswith(".csv"):
            messages.error(request, "Please upload a valid CSV file.")
            return redirect("addSubjects")

        try:
            decoded_file = csv_file.read().decode("utf-8").splitlines()
            reader = csv.DictReader(decoded_file)

            required_columns = [
                "department_code",
                "subject_number",
                "subject_name",
                "room_required",
                "required_lab_category",
                "classes_per_week",
            ]

            # Header validation
            for col in required_columns:
                if col not in reader.fieldnames:
                    messages.error(request, f"Missing required column: {col}")
                    return redirect("addSubjects")

            created_count = 0

            with transaction.atomic():
                for row in reader:
                    dept_code = row["department_code"].strip().upper()
                    subject_number = row["subject_number"].strip()
                    raw_room = row["room_required"].strip()
                    room_required = {"lab": "Lab", "lecture hall": "Lecture Hall"}.get(raw_room.lower(), raw_room)
                    required_lab_category = normalize_lab_category(row["required_lab_category"])

                    try:
                        subject_department = Department.objects.get(code=dept_code, user=request.user)
                    except Department.DoesNotExist:
                        raise ValueError(f"Department with code '{dept_code}' does not exist.")

                    # Skip duplicates
                    if Subject.objects.filter(subject_number=subject_number, user=request.user).exists():
                        continue

                    if room_required == "Lab" and not required_lab_category:
                        raise ValueError(
                            f"Subject '{subject_number}' is a Lab but required_lab_category is blank."
                        )
                    if room_required != "Lab":
                        required_lab_category = ""

                    subject = Subject.objects.create(
                        user=request.user,
                        subject_number=subject_number,
                        subject_name=row["subject_name"].strip(),
                        department=subject_department,
                        room_required=room_required,
                        required_lab_category=required_lab_category,
                        classes_per_week=int(row["classes_per_week"]),
                        max_numb_students=int(row.get("max_numb_students", 70) or 70),
                        duration=int(row.get("duration", 1) or 1),
                    )

                    created_count += 1

            reset_global_schedule_cache(request.user.id)
            messages.success(
                request, f"{created_count} subjects uploaded successfully!"
            )

        except Exception as e:
            messages.error(request, f"CSV upload failed: {str(e)}")

        return redirect("addSubjects")

    return render(request, "addSubjects.html", {"form": form})




@login_required
def subject_list_view(request):
    return render(request, 'subjectslist.html', {'subjects': Subject.objects.filter(user=request.user)})


@login_required
def delete_subject(request, pk):
    if request.method == 'POST':
        Subject.objects.filter(pk=pk, user=request.user).delete()
        reset_global_schedule_cache(request.user.id)
        return redirect('editsubject')


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
            email = row[4].strip() if len(row) > 4 else ""
            contact_number = row[5].strip() if len(row) > 5 else ""
            if uid and name and email and contact_number and not Instructor.objects.filter(uid=uid, user=request.user).exists():
                resolved_designation, resolved_workload = teacher_payload(
                    name,
                    designation,
                    max_workload,
                )
                Instructor.objects.create(
                    user=request.user,
                    uid=uid,
                    name=name,
                    email=email,
                    contact_number=contact_number,
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
def map_section_subjects(request):
    sections = Section.objects.filter(user=request.user).order_by("section_id")
    subjects = Subject.objects.filter(user=request.user).order_by("subject_number")

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
        selected_subject_ids = request.POST.getlist("subjects")

        if not section_identifier or not selected_subject_ids:
            messages.error(request, "Please select a section and at least one subject.")
            return redirect("map_section_subjects")

        try:
            section = resolve_section(section_identifier)
        except Section.DoesNotExist:
            messages.error(request, f"Section not found: {section_identifier}")
            return redirect("map_section_subjects")

        valid_subjects = list(Subject.objects.filter(pk__in=selected_subject_ids, user=request.user))
        if not valid_subjects:
            messages.error(request, "No valid subjects were selected.")
            return redirect("map_section_subjects")

        for subj in valid_subjects:
            section.allowed_subjects.add(subj)

        reset_global_schedule_cache(request.user.id)
        messages.success(
            request,
            f"{len(valid_subjects)} subject mappings saved for {section.section_id}."
        )
        return redirect("map_section_subjects")

    if request.method == "POST" and "csv_upload" in request.POST:
        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "No CSV file selected.")
            return redirect("map_section_subjects")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file format. Upload CSV only.")
            return redirect("map_section_subjects")

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
            subject_number = row[1].strip()

            try:
                section = resolve_section(section_identifier)
                subj = Subject.objects.get(subject_number=subject_number, user=request.user)
            except (Section.DoesNotExist, Subject.DoesNotExist):
                skipped += 1
                continue

            if subj in section.allowed_subjects.all():
                skipped += 1
                continue

            section.allowed_subjects.add(subj)
            added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(
            request,
            f"{added} section-subject mappings added. {skipped} skipped."
        )
        return redirect("map_section_subjects")

    return render(request, "map_section_subjects.html", {
        "sections": sections,
        "subjects": subjects
    })


@login_required
def view_section_subjects(request):
    sections = (
        Section.objects.filter(user=request.user)
        .order_by("section_id")
        .prefetch_related("allowed_subjects")
    )
    section_mappings = [
        {
            "section_id": section.section_id,
            "subjects": list(section.allowed_subjects.all().order_by("subject_number")),
        }
        for section in sections
    ]
    return render(
        request,
        "view_section_subjects.html",
        {"section_mappings": section_mappings},
    )

@login_required
def map_teacher_subjects(request):
    """
    Step 7: Fixed Teacher–Subject–Section mapping (after Sections are created in Step 6).

    CSV format (3-col legacy):
        section_id,subject_number,instructor_uid
        CE-A,CS101,T001

    CSV format (5-col with shared lab):
        section_id,subject_number,instructor_uid,shared_lab,second_instructor_uid
        CE-A,CS101,T001,false,
        BSc AM 3rd Sem,CA022,T076,true,T080
    """

    # =========================
    # CSV UPLOAD HANDLER
    # =========================
    if request.method == "POST" and "csv_upload" in request.POST:

        csv_file = request.FILES.get("csv_file")

        if not csv_file:
            messages.error(request, "No CSV file selected.")
            return redirect("map_teacher_subjects")

        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file format. Upload CSV only.")
            return redirect("map_teacher_subjects")

        decoded = csv_file.read().decode("utf-8").splitlines()
        reader = csv.reader(decoded)

        added = 0
        skipped = 0
        first = True
        validation_errors = []

        def _resolve_instructor(value):
            try:
                return Instructor.objects.get(uid=value, user=request.user)
            except Instructor.DoesNotExist:
                try:
                    return Instructor.objects.get(name=value, user=request.user)
                except (Instructor.DoesNotExist, Instructor.MultipleObjectsReturned):
                    return None

        valid_bool_values = {"", "true", "false", "1", "0", "yes", "no"}
        row_number = 0

        for row in reader:
            row_number += 1
            if not row or len(row) < 3:
                continue

            if first:
                first = False
                continue

            section_id     = row[0].strip()
            subject_number = row[1].strip()
            instructor_uid = row[2].strip()

            # Optional shared-lab columns (col 3 = shared_lab bool, col 4 = second instructor uid)
            shared_lab_flag = False
            second_instructor_uid = ""
            raw_shared_value = ""
            if len(row) >= 4:
                raw_shared_value = row[3].strip().lower()
                if raw_shared_value not in valid_bool_values:
                    skipped += 1
                    validation_errors.append(
                        f"Row {row_number}: invalid shared_lab value '{row[3].strip()}'"
                    )
                    continue
                shared_lab_flag = raw_shared_value in ("true", "1", "yes")
            if len(row) >= 5:
                second_instructor_uid = row[4].strip()

            # -------------------------
            # VALIDATION
            # -------------------------
            try:
                section = Section.objects.get(section_id=section_id, user=request.user)
            except Section.DoesNotExist:
                skipped += 1
                continue

            try:
                subj = Subject.objects.get(subject_number=subject_number, user=request.user)
            except Subject.DoesNotExist:
                skipped += 1
                validation_errors.append(
                    f"Row {row_number}: subject not found '{subject_number}'"
                )
                continue

            section_group_count = 1
            section_subject_mapping = SectionSubjectMapping.objects.filter(section=section, subject=subj).only("group_count").first()
            if section_subject_mapping is not None:
                section_group_count = max(1, section_subject_mapping.group_count or 1)

            primary_tokens = _split_teacher_tokens(instructor_uid)
            secondary_tokens = _split_teacher_tokens(second_instructor_uid)
            if section_group_count > 1:
                inferred_group_count = max(
                    section_group_count,
                    len(primary_tokens) if primary_tokens else 0,
                    len(secondary_tokens) if secondary_tokens else 0,
                    1,
                )
            else:
                inferred_group_count = max(
                    len(primary_tokens) if primary_tokens else 0,
                    len(secondary_tokens) if secondary_tokens else 0,
                    1,
                )

            primary_group_instructors = _resolve_group_assignments(
                instructor_uid,
                inferred_group_count,
                "primary instructor",
                allow_empty=False,
            )
            if primary_group_instructors is None:
                skipped += 1
                validation_errors.append(
                    f"Row {row_number}: primary instructor not found '{instructor_uid}'"
                )
                continue

            # Resolve second instructor if shared lab
            second_instructor = None
            if shared_lab_flag:
                if subj.room_required != "Lab":
                    skipped += 1
                    validation_errors.append(
                        f"Row {row_number}: shared_lab=true allowed only for Lab subjects ({subject_number})"
                    )
                    continue
                if not second_instructor_uid:
                    skipped += 1
                    validation_errors.append(
                        f"Row {row_number}: shared_lab=true but second_instructor_uid missing"
                    )
                    continue
                second_instructor = _resolve_instructor(second_instructor_uid)
                if not second_instructor:
                    skipped += 1
                    validation_errors.append(
                        f"Row {row_number}: second instructor not found '{second_instructor_uid}'"
                    )
                    continue
                if second_instructor.id == instructor.id:
                    skipped += 1
                    validation_errors.append(
                        f"Row {row_number}: primary and second instructor cannot be same for shared lab"
                    )
                    continue

            # -------------------------
            # CREATE / UPDATE MAPPING
            # -------------------------
            SectionSubjectInstructor.objects.update_or_create(
                user=request.user,
                section=section,
                subject=subj,
                defaults={"instructor": instructor, "second_instructor": second_instructor},
            )
            # Also ensure instructor is in Subject.instructors (for validation)
            subj.instructors.add(instructor)
            if second_instructor:
                subj.instructors.add(second_instructor)
            added += 1

        messages.success(
            request,
            f"{added} section–subject–teacher mappings saved. {skipped} skipped."
        )
        if validation_errors:
            preview = " | ".join(validation_errors[:5])
            remaining = len(validation_errors) - 5
            if remaining > 0:
                preview += f" | ...and {remaining} more"
            messages.warning(request, f"Validation details: {preview}")
        reset_global_schedule_cache(request.user.id)
        return redirect("map_teacher_subjects")

    # =========================
    # DISPLAY EXISTING MAPPINGS
    # =========================
    mappings = SectionSubjectInstructor.objects.filter(
        user=request.user
    ).select_related(
        "section", "subject", "instructor", "second_instructor"
    ).order_by("section__section_id", "subject__subject_number")

    return render(
        request,
        "map_teacher_subjects.html",
        {"mappings": mappings},
    )


@login_required
def delete_teacher_subject_mapping(request, subject_number, instructor_id):
    if request.method == "POST":
        try:
            subj = Subject.objects.get(subject_number=subject_number, user=request.user)
            instructor = Instructor.objects.get(id=instructor_id, user=request.user)
            subj.instructors.remove(instructor)
            messages.success(request, "Mapping removed successfully.")
        except Exception as e:
            messages.error(request, f"Error removing mapping: {e}")
    return redirect("map_teacher_subjects")


@login_required
def delete_sci_mapping(request, mapping_id):
    if request.method == "POST":
        SectionSubjectInstructor.objects.filter(
            id=mapping_id, user=request.user
        ).delete()
        reset_global_schedule_cache(request.user.id)
        messages.success(request, "Mapping removed.")
    return redirect("map_teacher_subjects")




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
        updated = 0
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
        updated = 0
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
        updated = 0
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
            template_section = clone_section_subjects_from_similar(section)
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
        updated = 0
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
                program_i = index("program_name", index("program", 1))
                dept_i = index("department", index("department_code", index("department_id", 1)))
                if dept_i == 1 and program_i == 1:
                    dept_i = index("department", index("department_code", index("department_id", 2)))
                strength_i = index("student_strength", 2 if program_i is None else 3)

                # Skip header
                continue

            # Extract values
            section_id = row[section_i].strip()
            program_name = row[program_i].strip() if program_i is not None and len(row) > program_i else ""
            dept_name = row[dept_i].strip()
            student_strength = row[strength_i].strip() if len(row) > strength_i else "70"

            # Validate Department
            try:
                dept = resolve_department(dept_name)
            except Department.DoesNotExist:
                print("Invalid department:", dept_name)
                continue

            if not student_strength.isdigit():
                print("Invalid student strength:", student_strength)
                continue

            existing_section = Section.objects.filter(section_id=section_id, user=request.user).first()
            if existing_section:
                existing_section.program_name = program_name
                existing_section.department = dept
                existing_section.student_strength = int(student_strength)
                existing_section.save(update_fields=["program_name", "department", "student_strength"])
                updated += 1
                continue

            # Create the Section object
            section = Section.objects.create(
                user=request.user,
                section_id=section_id,
                program_name=program_name,
                student_strength=int(student_strength),
                department=dept,
            )
            clone_section_subjects_from_similar(section)

            added += 1

        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"{added} section(s) added and {updated} section(s) updated from CSV!")
        return redirect("addSections")

    return render(request, "addSections.html", {"form": form})


@login_required
def prefilled_timetable_setup(request):
    if request.method == "POST":
        csv_file = request.FILES.get("csv_file")
        if not csv_file:
            messages.error(request, "Please select a sections CSV file.")
            return redirect("prefilled_timetable_setup")
        if not csv_file.name.endswith(".csv"):
            messages.error(request, "Invalid file type. Upload CSV only.")
            return redirect("prefilled_timetable_setup")

        decoded = csv_file.read().decode("utf-8-sig").splitlines()
        reader = csv.reader(decoded)
        section_ids = []
        issues = []
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

        def row_value(row, index):
            if index is None or index >= len(row):
                return ""
            return row[index].strip()

        section_i = 0
        program_i = 1
        dept_i = 2
        strength_i = 3

        for row_number, row in enumerate(reader, start=1):
            if not row:
                continue
            if first:
                first = False
                header = [h.strip().lower() for h in row]

                def index(name, default=None):
                    try:
                        return header.index(name)
                    except ValueError:
                        return default

                section_i = index("section_id", 0)
                program_i = index("program_name", index("program", 1))
                dept_i = index("department", index("department_code", index("department_id", 1)))
                if dept_i == 1 and program_i == 1:
                    dept_i = index("department", index("department_code", index("department_id", 2)))
                strength_i = index("student_strength", index("section_strength", 2 if program_i is None else 3))
                continue

            section_id = row_value(row, section_i)
            program_name = row_value(row, program_i)
            dept_name = row_value(row, dept_i)
            student_strength = row_value(row, strength_i) or "70"

            if not section_id:
                _csv_issue(issues, row_number, "section_id is blank")
                continue
            if not dept_name:
                _csv_issue(issues, row_number, f"department is blank for section '{section_id}'")
                continue
            if not student_strength.isdigit():
                _csv_issue(issues, row_number, f"student_strength '{student_strength}' is not a whole number")
                continue

            try:
                dept = resolve_department(dept_name)
            except Department.DoesNotExist:
                _csv_issue(issues, row_number, f"department '{dept_name}' not found")
                continue

            section, created = Section.objects.update_or_create(
                user=request.user,
                section_id=section_id,
                defaults={
                    "program_name": program_name,
                    "department": dept,
                    "student_strength": int(student_strength),
                },
            )
            if created:
                clone_section_subjects_from_similar(section)
            section_ids.append(section.section_id)

        if not section_ids:
            messages.error(request, "No valid sections found in the CSV.")
            _emit_csv_issues(request, issues)
            return redirect("prefilled_timetable_setup")

        state = _get_user_state(request.user.id)
        state["classes"] = []
        state["labs"] = []
        state["schedules"] = [{"classes": [], "labs": [], "stats": {}, "reco_block": {}}]
        state["prefill_mode"] = True
        state["prefill_section_ids"] = section_ids
        state["prefill_locked_classes"] = []
        state["prefill_locked_labs"] = []
        _reset_generated_drag_state(state, current_index=1)
        request.session["current_index"] = 1
        request.session["prefill_mode"] = True
        request.session["prefill_section_ids"] = section_ids
        request.session.pop("prefill_saved_slots", None)
        request.session.modified = True
        reset_global_schedule_cache(request.user.id)
        messages.success(request, f"Empty prefilled timetable created for {len(section_ids)} section(s).")
        _emit_csv_issues(request, issues)
        return redirect("prefilled_timetable_view")

    return render(request, "prefilled_timetable_setup.html")


@login_required
def prefilled_timetable_view(request):
    state = _get_user_state(request.user.id)
    section_ids = list(state.get("prefill_section_ids") or request.session.get("prefill_section_ids") or [])
    if not (state.get("prefill_mode") or request.session.get("prefill_mode")) or not section_ids:
        messages.info(request, "Upload a sections CSV to create an empty prefilled timetable.")
        return redirect("prefilled_timetable_setup")

    state["prefill_mode"] = True
    state["prefill_section_ids"] = section_ids
    if state.get("classes") is None:
        state["classes"] = []
    if state.get("labs") is None:
        state["labs"] = []
    if not state.get("schedules"):
        state["schedules"] = [{"classes": [], "labs": [], "stats": {}, "reco_block": {}}]
    restore_prefill_session_snapshot(request, state, section_ids)
    ensure_manual_prefill_slot_uids(state)
    state["view_mode"] = "editing"
    request.session["current_index"] = 1

    global GLOBAL_CLASSES, GLOBAL_LABS, GLOBAL_GENERATED_SCHEDULES, CURRENT_VIEW_MODE
    GLOBAL_CLASSES = state["classes"]
    GLOBAL_LABS = state["labs"]
    GLOBAL_GENERATED_SCHEDULES = state["schedules"]
    CURRENT_VIEW_MODE = "editing"

    tables = build_section_tables(GLOBAL_CLASSES, GLOBAL_LABS, user=request.user)
    allowed_section_ids = set(section_ids)
    tables = [table for table in tables if table["section"].section_id in allowed_section_ids]
    tables = _decorate_generated_tables_with_parking(tables, state)

    departments = []
    seen_depts = set()
    for table in tables:
        section = table["section"]
        dept = section.department
        table["section_department_code"] = dept.code
        table["section_department_name"] = dept.name
        table["subject_counts"] = []
        table["missed_labs"] = []
        table["total_missing_classes"] = 0
        if dept.code not in seen_depts:
            seen_depts.add(dept.code)
            departments.append({"code": dept.code, "name": dept.name})
        section_id = section.section_id
        table["create_slot_subjects"] = []
        table["create_slot_teachers"] = []
        table["create_slot_rooms"] = []
        table["create_slot_subjects_id"] = f"create-slot-subjects-{section_id}"
        table["create_slot_teachers_id"] = f"create-slot-teachers-{section_id}"
        table["create_slot_rooms_id"] = f"create-slot-rooms-{section_id}"

    return render(request, "gentimetable.html", {
        "tables": tables,
        "teacher_tables": [],
        "room_tables": [],
        "SLOT_LABELS": SLOT_LABELS,
        "index": 1,
        "teacher_workloads": {},
        "demo_mode": False,
        "active_dept": "",
        "active_program": "all",
        "program_options": [],
        "departments": departments,
        "prefill_mode": True,
        "can_edit_delete": True,
        "can_substitute": True,
        "can_drag_drop": True,
    })


@login_required
def save_prefilled_timetable(request):
    if request.method != "POST":
        return HttpResponseForbidden("Invalid request method.")

    state = _get_user_state(request.user.id)
    snapshot = save_prefill_session_snapshot(request, state) or request.session.get("prefill_saved_slots")
    if not snapshot or not snapshot.get("section_ids"):
        messages.error(request, "Create a prefilled table before saving.")
        return redirect("prefilled_timetable_setup")

    total_slots = len(snapshot.get("classes") or []) + len(snapshot.get("labs") or []) + len(snapshot.get("parking_items") or [])
    name = (request.POST.get("name") or "").strip()
    if not name:
        section_preview = ", ".join(list(snapshot.get("section_ids") or [])[:2])
        if len(snapshot.get("section_ids") or []) > 2:
            section_preview += " + more"
        name = f"Prefill {section_preview}" if section_preview else "Saved Prefill"

    SavedPrefill.objects.create(user=request.user, name=name[:120], snapshot=snapshot)
    messages.success(request, f"Prefilled table saved with {total_slots} slot(s).")
    return redirect("saved_prefill_list")


@login_required
def saved_prefill_list(request):
    prefills = []
    for prefill in SavedPrefill.objects.filter(user=request.user):
        snapshot = prefill.snapshot or {}
        section_ids = list(snapshot.get("section_ids") or [])
        slot_count = len(snapshot.get("classes") or []) + len(snapshot.get("labs") or []) + len(snapshot.get("parking_items") or [])
        prefills.append({
            "item": prefill,
            "section_count": len(section_ids),
            "sections": ", ".join(section_ids[:4]) + (" + more" if len(section_ids) > 4 else ""),
            "slot_count": slot_count,
        })
    return render(request, "saved_prefill_list.html", {"prefills": prefills})


@login_required
def open_saved_prefill(request, prefill_id):
    try:
        prefill = SavedPrefill.objects.get(pk=prefill_id, user=request.user)
    except SavedPrefill.DoesNotExist:
        raise Http404("Saved prefill not found")
    if not _activate_prefill_snapshot(request, prefill.snapshot or {}):
        messages.error(request, "This saved prefill has no section data.")
        return redirect("saved_prefill_list")
    messages.success(request, "Saved prefill loaded for editing.")
    return redirect("prefilled_timetable_view")


@login_required
def generate_saved_prefill(request, prefill_id):
    if request.method != "POST":
        return HttpResponseForbidden("Invalid request method.")
    try:
        prefill = SavedPrefill.objects.get(pk=prefill_id, user=request.user)
    except SavedPrefill.DoesNotExist:
        raise Http404("Saved prefill not found")
    if not _activate_prefill_snapshot(request, prefill.snapshot or {}):
        messages.error(request, "This saved prefill has no section data.")
        return redirect("saved_prefill_list")
    return redirect(f"{reverse('generate_timetable_loading')}?use_pso=1&use_prefilled_slots=1")


@login_required
def delete_saved_prefill(request, prefill_id):
    if request.method != "POST":
        return HttpResponseForbidden("Invalid request method.")
    SavedPrefill.objects.filter(pk=prefill_id, user=request.user).delete()
    messages.success(request, "Saved prefill deleted.")
    return redirect("saved_prefill_list")


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

    saved_t = _get_saved_timetable_or_404(tid, request.user)

    # Rebuild in-memory classes and labs (with proper batch grouping)
    classes, labs = _rebuild_classes_and_labs_from_saved(saved_t)

    # Build tables scoped to the current user
    tables = build_section_tables(classes, labs, user=request.user)

    # Expand cells for PDF so colspan renders properly in xhtml2pdf
    for table in tables:
        for row in table["rows"]:
            for cell in row["cells"]:
                if cell["type"] == "lab":
                    cell["width"] = 85 * cell["colspan"]
                else:
                    cell["width"] = 85

    html = render_to_string("saved_timetable_pdf.html", {
        "tables": tables,
        "SLOT_LABELS": SLOT_LABELS
    })

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="timetable_{tid}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)

    if pisa_status.err:
        return HttpResponse("PDF creation crashed.<br><br>" + html)

    return response

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
                            subj = getattr(cls, "subject", None)
                            instructor = getattr(cls, "instructor", None)
                            room = getattr(cls, "room", None)

                            xl_cell.value = "\n".join([
                                str(_safe_get(subj, "subject_number", "subject_name", default="Class")),
                                str(_safe_get(instructor, "name", "uid", default="TBD")),
                                str(_safe_get(room, "r_number", default="Room TBD")),
                            ])

                    elif cell_type == "lab":
                        lab_items = cell_data.get("labs", [])
                        if lab_items:
                            lab = lab_items[0]
                            subj = getattr(lab, "subject", None)
                            instructor = getattr(lab, "instructor", None)
                            room = getattr(lab, "room", None)

                            xl_cell.value = "\n".join([
                                f"{_safe_get(subj, 'subject_number', 'subject_name', default='Lab')} (Lab)",
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
        "columns": ["uid", "name", "designation", "max_workload", "email", "contact_number"],
        "filename": "instructors.csv",
        "required": ["uid", "name", "email", "contact_number"],
        "keywords": {
            "uid": ["uid", "id", "teacher id", "teacherid", "faculty id", "code", "teacher_id"],
            "name": ["name", "teacher name", "teachername", "faculty name", "instructor", "faculty"],
            "designation": ["designation", "position", "role", "rank", "post"],
            "max_workload": ["max_workload", "workload", "max workload", "load", "hours"],
            "email": ["email", "e-mail", "mail", "email id", "email_id"],
            "contact_number": ["contact_number", "contact", "phone", "mobile", "phone number", "contact no"],
        },
    },
    "subjects": {
        "label": "Subjects",
        "columns": ["department_code", "subject_number", "subject_name", "room_required", "required_lab_category", "classes_per_week", "duration"],
        "filename": "subjects.csv",
        "required": ["subject_number", "subject_name"],
        "keywords": {
            "department_code": ["department", "dept", "department_code", "dept_code"],
            "subject_number": ["subject_number", "subject no", "subject_id", "subject id", "code", "number", "course_number", "course no", "course_id"],
            "subject_name": ["subject_name", "subject name", "name", "title", "course_name", "course name"],
            "room_required": ["room_required", "room required", "room type", "room"],
            "required_lab_category": ["lab_category", "lab category", "required_lab", "lab"],
            "classes_per_week": ["classes_per_week", "classes per week", "classes", "per week", "frequency", "weekly"],
            "duration": ["duration", "hours", "duration_hours", "slot_duration", "slots"],
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
        "columns": ["section_id", "program_name", "department", "student_strength"],
        "filename": "sections.csv",
        "required": ["section_id"],
        "keywords": {
            "section_id": ["section_id", "section id", "section", "id", "batch"],
            "program_name": ["program_name", "program", "degree", "course_type", "program type"],
            "department": ["department", "dept", "department_code", "dept_code"],
            "student_strength": ["student_strength", "student strength", "strength", "students", "size"],
        },
    },
    "section_subjects": {
        "label": "Section-Subject Mapping",
        "columns": ["section_id", "subject_number"],
        "filename": "section_subjects.csv",
        "required": ["section_id", "subject_number"],
        "keywords": {
            "section_id": ["section_id", "section id", "section", "batch"],
            "subject_number": ["subject_number", "subject no", "subject_id", "subject id", "subject", "course_number", "course no", "course"],
        },
    },
    "teacher_subjects": {
        "label": "Teacher-Subject Mapping",
        "columns": ["instructor", "subject_number"],
        "filename": "teacher_subjects.csv",
        "required": ["instructor", "subject_number"],
        "keywords": {
            "instructor": ["instructor", "teacher", "uid", "name", "faculty", "teacher name", "instructor_name"],
            "subject_number": ["subject_number", "subject no", "subject_id", "subject id", "subject", "course_number", "course no", "course"],
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
        s['submitted_at'] = _format_local_datetime(s['submitted_at'], '%d %b %Y, %I:%M %p')
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
            _format_local_datetime(s.submitted_at, '%d %b %Y %H:%M')])
    return response
