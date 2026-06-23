"""Super Admin module.

Self-contained feature:
  * Inbuilt login validated against credentials stored in .env
    (``SUPERADMIN_USERS`` parsed by settings into ``settings.SUPERADMIN_USERS``).
    There is no self sign-up for super admins.
  * A dedicated, real-data analytics dashboard on its own URL.

IMPORTANT: This module never touches the scheduling / generation algorithm.
It only *reads* timetable data that already exists in the database and turns
it into university-wide analytics. Every number below is computed live from
real records (no hardcoded analytics values).
"""

from __future__ import annotations

import hmac
import io
import logging
import re
from collections import defaultdict
from datetime import datetime
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.http import HttpResponse, JsonResponse, Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from django.db.models import Max

from .models import (
    CoordinatorAppointment,
    Department,
    Instructor,
    MeetingTime,
    Room,
    ScheduledSlot,
    SavedTimetable,
    Section,
    TeacherSection,
)

logger = logging.getLogger(__name__)

SESSION_FLAG = "is_superadmin"
SESSION_EMAIL = "superadmin_email"
SA_IMPERSONATE = "sa_impersonate_uid"

WORKING_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]
_DAY_ORDER = {d: i for i, d in enumerate(WORKING_DAYS)}
_SEM_RE = re.compile(r"(\d+)\s*(?:st|nd|rd|th)?\s*sem", re.IGNORECASE)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------
def _superadmin_users():
    return getattr(settings, "SUPERADMIN_USERS", {}) or {}


def _check_credentials(email, password):
    """Constant-time validation against the .env credential list."""
    email = (email or "").strip().lower()
    password = password or ""
    expected = _superadmin_users().get(email)
    if not expected:
        # Still burn a comparison to reduce timing signal.
        hmac.compare_digest(password, password)
        return False
    return hmac.compare_digest(password, expected)


def superadmin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not request.session.get(SESSION_FLAG):
            messages.info(request, "Please sign in as Super Admin to continue.")
            return redirect("superadmin_login")
        return view_func(request, *args, **kwargs)

    return _wrapped


def superadmin_login(request):
    if request.session.get(SESSION_FLAG):
        return redirect("superadmin_dashboard")

    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        if not _superadmin_users():
            messages.error(
                request,
                "Super Admin login is not configured. Set SUPERADMIN_USERS in .env.",
            )
        elif _check_credentials(email, password):
            request.session[SESSION_FLAG] = True
            request.session[SESSION_EMAIL] = email.strip().lower()
            request.session.modified = True
            return redirect("superadmin_dashboard")
        else:
            messages.error(request, "Invalid email or password.")

    return render(request, "superadmin_login.html")


def superadmin_logout(request):
    request.session.pop(SESSION_FLAG, None)
    request.session.pop(SESSION_EMAIL, None)
    request.session.pop(SA_IMPERSONATE, None)
    request.session.modified = True
    messages.success(request, "Signed out of Super Admin.")
    return redirect("superadmin_login")


# ---------------------------------------------------------------------------
# Analytics helpers (all read-only, real DB data)
# ---------------------------------------------------------------------------
def _semester_of(section_id):
    match = _SEM_RE.search(section_id or "")
    if not match:
        return ""
    number = match.group(1)
    if number in {"11", "12", "13"}:
        suffix = "th"
    else:
        suffix = {"1": "st", "2": "nd", "3": "rd"}.get(number[-1], "th")
    return f"{number}{suffix} Sem"


def _slot_universe():
    """Distinct (day, time) cells that the institution actually uses."""
    pairs = set(MeetingTime.objects.values_list("day", "time").distinct())
    universe = {(d, str(t)) for d, t in pairs if d}
    if not universe:
        universe = {(d, str(t)) for d in WORKING_DAYS for t in range(1, 9)}
    return universe


def _active_timetable_ids():
    """Latest saved timetable per (user, department) = current live picture."""
    rows = SavedTimetable.objects.values("user", "department").annotate(mx=Max("id"))
    return [row["mx"] for row in rows if row["mx"]]


def _active_owner_ids():
    """User IDs that own at least one *non-empty* saved timetable.

    Master data (departments, teachers, rooms, sections) is stored per user.
    The same institution can exist under multiple accounts (seeded twice),
    which would double every count. Scoping analytics to the accounts that
    actually own scheduled timetables removes that duplication. Falls back to
    "all users" when nothing is scheduled yet, preserving the empty-DB view.
    """
    return set(
        SavedTimetable.objects.filter(slots__isnull=False)
        .values_list("user_id", flat=True)
        .distinct()
    )


def _scope_to_owners(qs, owners):
    """Restrict a user-scoped queryset to the active owners (no-op if none)."""
    return qs.filter(user_id__in=owners) if owners else qs


def _pct(used, total):
    if not total:
        return 0.0
    return round((used / total) * 100.0, 1)


def _active_slots():
    ids = _active_timetable_ids()
    if not ids:
        return ScheduledSlot.objects.none()
    return (
        ScheduledSlot.objects.filter(timetable_id__in=ids)
        .select_related(
            "section",
            "section__department",
            "subject",
            "instructor",
            "second_instructor",
            "room",
            "room__department",
            "meeting_time",
        )
        .prefetch_related("lab_slots")
    )


def _build_analytics(request):
    """Compute the full analytics context from real timetable records."""
    dept_filter = (request.GET.get("dept") or "all").strip()
    sem_filter = (request.GET.get("sem") or "all").strip()
    search = (request.GET.get("q") or "").strip()

    universe = _slot_universe()
    universe_count = len(universe) or 1

    # Accounts that actually own scheduled timetables. Master data is per-user
    # and may be duplicated across accounts, so scope everything to these owners
    # to avoid double-counting departments / teachers / rooms / sections.
    owners = _active_owner_ids()

    # Master counts (whole institution, independent of current filter).
    total_departments = _scope_to_owners(Department.objects, owners).count()
    total_teachers = _scope_to_owners(Instructor.objects, owners).count()
    total_rooms = _scope_to_owners(Room.objects, owners).count()
    total_labs = _scope_to_owners(Room.objects.filter(room_type="Lab"), owners).count()
    total_sections = _scope_to_owners(Section.objects, owners).count()

    # Filter dropdown sources (dynamic, from real data).
    departments = list(
        _scope_to_owners(Department.objects, owners)
        .order_by("name")
        .values("id", "name", "code")
    )
    semesters = sorted(
        {
            _semester_of(sid)
            for sid in _scope_to_owners(Section.objects, owners).values_list(
                "section_id", flat=True
            )
            if _semester_of(sid)
        },
        key=lambda s: int(re.match(r"(\d+)", s).group(1)),
    )

    slots = _active_slots()

    # Accumulators.
    room_cells = defaultdict(set)            # room_id -> {(day,time)}
    dept_room_cells = defaultdict(set)       # dept_id -> {(room_id,day,time)}
    heat = defaultdict(int)                  # (day,time) -> occupancy
    teacher_load = defaultdict(int)          # instructor_id -> cells taught
    teacher_name = {}
    room_meta = {}                           # room_id -> {number,dept,is_lab}
    dept_meta = {}                           # dept_id -> {name,code}
    section_scheduled = set()
    dept_scheduled = set()
    teacher_scheduled = set()

    room_slot_sections = defaultdict(set)    # (room_id,day,time) -> {section_id}
    teacher_slot_sections = defaultdict(set)  # (instr_id,day,time) -> {section_id}
    section_slot_subjects = defaultdict(set)  # (section_id,day,time) -> {subject_id}

    preview_rows = []

    for slot in slots:
        section = slot.section
        if not section:
            continue
        sec_id = section.section_id
        dept = section.department
        dept_id = dept.id if dept else None
        sem = _semester_of(sec_id)

        # Apply filters.
        if dept_filter != "all" and str(dept_id) != dept_filter:
            continue
        if sem_filter != "all" and sem != sem_filter:
            continue
        if search:
            blob = " ".join(
                str(x).lower()
                for x in (
                    sec_id,
                    getattr(slot.subject, "subject_name", ""),
                    getattr(slot.instructor, "name", ""),
                    getattr(slot.room, "r_number", ""),
                )
            )
            if search.lower() not in blob:
                continue

        room = slot.room
        room_id = room.id if room else None
        if room_id is not None and room_id not in room_meta:
            room_meta[room_id] = {
                "number": room.r_number,
                "dept": room.department.name if room.department_id else "—",
                "dept_id": room.department_id,
                "is_lab": room.room_type == "Lab",
            }
        if dept_id is not None and dept_id not in dept_meta:
            dept_meta[dept_id] = {"name": dept.name, "code": dept.code}

        instr = slot.instructor
        instr_id = instr.id if instr else None
        if instr_id is not None:
            teacher_name[instr_id] = instr.name
            teacher_scheduled.add(instr_id)
        second = slot.second_instructor
        second_id = second.id if second else None
        if second_id is not None:
            teacher_name[second_id] = second.name

        section_scheduled.add(sec_id)
        if dept_id is not None:
            dept_scheduled.add(dept_id)

        # All cells occupied by this slot (main + lab continuation slots).
        cells = [(slot.meeting_time.day, str(slot.meeting_time.time))]
        if slot.is_lab:
            cells += [(mt.day, str(mt.time)) for mt in slot.lab_slots.all()]
        cells = list({c for c in cells if c[0]})

        for day, time in cells:
            if room_id is not None:
                room_cells[room_id].add((day, time))
                room_slot_sections[(room_id, day, time)].add(sec_id)
                if room.department_id:
                    dept_room_cells[room.department_id].add((room_id, day, time))
            heat[(day, time)] += 1
            if instr_id is not None:
                teacher_load[instr_id] += 1
                teacher_slot_sections[(instr_id, day, time)].add(sec_id)
            if second_id is not None:
                teacher_load[second_id] += 1
            section_slot_subjects[(sec_id, day, time)].add(slot.subject_id)

        preview_rows.append(
            {
                "section": sec_id,
                "subject": getattr(slot.subject, "subject_name", "—"),
                "teacher": getattr(instr, "name", "—"),
                "room": getattr(room, "r_number", "—"),
                "day": slot.meeting_time.day,
                "slot": str(slot.meeting_time.time),
                "type": "Lab" if slot.is_lab else "Theory",
                "dept": dept.name if dept else "—",
            }
        )

    # Scope room set for utilization denominators.
    scope_rooms = _scope_to_owners(Room.objects, owners)
    if dept_filter != "all":
        scope_rooms = scope_rooms.filter(department_id=dept_filter)
    scope_room_list = list(scope_rooms.values("id", "r_number", "room_type", "department__name"))
    scope_room_count = len(scope_room_list) or 1

    # Overall utilization.
    used_cells = sum(len(v) for v in room_cells.values())
    available_cells = scope_room_count * universe_count
    overall_util = _pct(used_cells, available_cells)

    # Conflicts.
    room_conflicts = sum(1 for v in room_slot_sections.values() if len(v) > 1)
    teacher_conflicts = sum(1 for v in teacher_slot_sections.values() if len(v) > 1)
    section_conflicts = sum(1 for v in section_slot_subjects.values() if len(v) > 1)
    total_conflicts = room_conflicts + teacher_conflicts + section_conflicts

    # Department-wise utilization.
    dept_util = []
    dept_qs = _scope_to_owners(Department.objects, owners)
    if dept_filter != "all":
        dept_qs = dept_qs.filter(id=dept_filter)
    for dept in dept_qs.order_by("name"):
        d_rooms = _scope_to_owners(Room.objects.filter(department=dept), owners).count()
        used = len(dept_room_cells.get(dept.id, set()))
        denom = d_rooms * universe_count
        dept_util.append(
            {
                "id": dept.id,
                "name": dept.name,
                "code": dept.code,
                "util": _pct(used, denom),
                "used": used,
                "rooms": d_rooms,
                "scheduled": dept.id in dept_scheduled,
            }
        )
    dept_util.sort(key=lambda d: d["util"], reverse=True)

    # Room utilization list (includes idle rooms with 0%).
    room_util = []
    for room in scope_room_list:
        used = len(room_cells.get(room["id"], set()))
        room_util.append(
            {
                "id": room["id"],
                "number": room["r_number"],
                "type": room["room_type"],
                "dept": room["department__name"] or "—",
                "used": used,
                "capacity": universe_count,
                "util": _pct(used, universe_count),
            }
        )
    room_util.sort(key=lambda r: r["util"], reverse=True)
    top_rooms = room_util[:10]
    least_rooms = sorted(room_util, key=lambda r: r["util"])[:5]
    idle_rooms = [r for r in room_util if r["used"] == 0]

    # Teacher workload (all in-scope teachers; 0 for unscheduled).
    teacher_qs = _scope_to_owners(Instructor.objects, owners)
    if dept_filter != "all":
        # Teachers who teach at least one in-scope section.
        teacher_qs = teacher_qs.filter(id__in=list(teacher_load.keys()) or [0])
    teacher_workload = []
    for instr in teacher_qs:
        load = teacher_load.get(instr.id, 0)
        teacher_workload.append(
            {
                "id": instr.id,
                "name": instr.name,
                "designation": instr.designation,
                "load": load,
                "max": instr.max_workload,
                "util": _pct(load, instr.max_workload),
            }
        )
    teacher_workload.sort(key=lambda t: t["load"], reverse=True)
    top_teachers = teacher_workload[:5]

    # Workload distribution buckets.
    buckets = {"0-10": 0, "10-15": 0, "15-20": 0, "20+": 0}
    for t in teacher_workload:
        load = t["load"]
        if load < 10:
            buckets["0-10"] += 1
        elif load < 15:
            buckets["10-15"] += 1
        elif load < 20:
            buckets["15-20"] += 1
        else:
            buckets["20+"] += 1

    # Resource utilisation overview (rooms vs labs vs all).
    lab_used = sum(
        len(room_cells.get(r["id"], set()))
        for r in scope_room_list
        if r["room_type"] == "Lab"
    )
    lab_count_scope = sum(1 for r in scope_room_list if r["room_type"] == "Lab") or 1
    lecture_rooms = [r for r in scope_room_list if r["room_type"] != "Lab"]
    lecture_used = sum(len(room_cells.get(r["id"], set())) for r in lecture_rooms)
    lecture_count_scope = len(lecture_rooms) or 1
    resource_overview = {
        "all": {"used": used_cells, "total": available_cells, "util": overall_util},
        "labs": {
            "used": lab_used,
            "total": lab_count_scope * universe_count,
            "util": _pct(lab_used, lab_count_scope * universe_count),
        },
        "rooms": {
            "used": lecture_used,
            "total": lecture_count_scope * universe_count,
            "util": _pct(lecture_used, lecture_count_scope * universe_count),
        },
    }

    # Heatmap matrix (days x sorted time slots).
    times = sorted({t for _, t in universe}, key=lambda x: int(x) if x.isdigit() else x)
    days = sorted({d for d, _ in universe}, key=lambda d: _DAY_ORDER.get(d, 99))
    max_heat = max(heat.values()) if heat else 0
    heatmap = {
        "days": days,
        "times": times,
        "max": max_heat,
        "rows": [
            {"day": d, "cells": [heat.get((d, t), 0) for t in times]} for d in days
        ],
    }

    # AI insights (dynamic, derived from the numbers above).
    insights = []
    if dept_util:
        best = dept_util[0]
        insights.append(
            f"{best['name']} has the highest resource utilisation at {best['util']}%."
        )
        worst = min((d for d in dept_util if d["rooms"]), key=lambda d: d["util"], default=None)
        if worst and worst["util"] < 40:
            insights.append(
                f"{worst['name']} is under-utilised ({worst['util']}%) — capacity to absorb more classes."
            )
    if idle_rooms:
        insights.append(
            f"{len(idle_rooms)} room(s) are completely idle in the current schedule."
        )
    if total_conflicts:
        insights.append(
            f"{total_conflicts} scheduling conflict(s) detected — review room/teacher overlaps."
        )
    else:
        insights.append("No hard conflicts detected in the active timetables.")
    if top_teachers and top_teachers[0]["load"]:
        busiest = top_teachers[0]
        insights.append(
            f"{busiest['name']} carries the heaviest load ({busiest['load']} hrs / {busiest['max']} max)."
        )
    if heatmap["max"]:
        peak_idx = max(
            range(len(times)),
            key=lambda i: max((heat.get((d, times[i]), 0) for d in days), default=0),
        )
        insights.append(f"Slot {times[peak_idx]} is the busiest time across the campus.")

    # Recent activity from real saved timetables.
    recent = []
    for st in SavedTimetable.objects.select_related("department").order_by("-created_at")[:8]:
        recent.append(
            {
                "label": st.department.name if st.department_id else "All Departments",
                "published": st.is_published,
                "when": timezone.localtime(st.created_at).strftime("%d %b %Y, %H:%M")
                if st.created_at
                else "",
            }
        )

    # Quick timetable preview ordering.
    preview_rows.sort(key=lambda r: (r["section"], _DAY_ORDER.get(r["day"], 99), r["slot"]))

    avg_workload = round(
        sum(t["load"] for t in teacher_workload) / len(teacher_workload), 1
    ) if teacher_workload else 0

    kpis = {
        "departments_active": len(dept_scheduled) or total_departments,
        "teachers_active": len(teacher_scheduled) or total_teachers,
        "sections_scheduled": len(section_scheduled),
        "rooms_total": total_rooms,
        "labs_total": total_labs,
        "classes_scheduled": len(preview_rows),
        "overall_util": overall_util,
        "conflicts": total_conflicts,
    }

    return {
        "kpis": kpis,
        "totals": {
            "departments": total_departments,
            "teachers": total_teachers,
            "rooms": total_rooms,
            "labs": total_labs,
            "sections": total_sections,
        },
        "departments": departments,
        "semesters": semesters,
        "dept_filter": dept_filter,
        "sem_filter": sem_filter,
        "search": search,
        "dept_util": dept_util,
        "room_util": room_util,
        "top_rooms": top_rooms,
        "least_rooms": least_rooms,
        "idle_rooms_count": len(idle_rooms),
        "teacher_workload": teacher_workload,
        "top_teachers": top_teachers,
        "workload_buckets": buckets,
        "resource_overview": resource_overview,
        "heatmap": heatmap,
        "insights": insights,
        "recent": recent,
        "preview": preview_rows,
        "avg_workload": avg_workload,
        "conflict_breakdown": {
            "room": room_conflicts,
            "teacher": teacher_conflicts,
            "section": section_conflicts,
        },
    }


# ---------------------------------------------------------------------------
# Dashboard + drilldown + exports
# ---------------------------------------------------------------------------
def _chart_data(ctx):
    """Chart-ready payloads shared by every super-admin page."""
    return {
        "deptUtil": {
            "labels": [d["name"] for d in ctx["dept_util"]],
            "values": [d["util"] for d in ctx["dept_util"]],
        },
        "workload": {
            "labels": list(ctx["workload_buckets"].keys()),
            "values": list(ctx["workload_buckets"].values()),
        },
        "resource": ctx["resource_overview"],
        "heatmap": ctx["heatmap"],
        "topRooms": {
            "labels": [r["number"] for r in ctx["top_rooms"]],
            "values": [r["util"] for r in ctx["top_rooms"]],
        },
        "leastRooms": {
            "labels": [r["number"] for r in ctx["least_rooms"]],
            "values": [r["util"] for r in ctx["least_rooms"]],
        },
        "topTeachers": {
            "labels": [t["name"] for t in ctx["top_teachers"]],
            "values": [t["load"] for t in ctx["top_teachers"]],
        },
    }


def _page_ctx(request, page):
    """Build the full analytics context for any super-admin page."""
    ctx = _build_analytics(request)
    ctx["superadmin_email"] = request.session.get(SESSION_EMAIL, "")
    ctx["page"] = page
    ctx["chart_data"] = _chart_data(ctx)
    return ctx


@superadmin_required
def superadmin_dashboard(request):
    return render(request, "superadmin_dashboard.html", _page_ctx(request, "overview"))


@superadmin_required
def superadmin_resource(request):
    return render(request, "superadmin_resource.html", _page_ctx(request, "resource"))


@superadmin_required
def superadmin_teachers(request):
    return render(request, "superadmin_teachers.html", _page_ctx(request, "teachers"))


@superadmin_required
def superadmin_depts(request):
    return render(request, "superadmin_depts.html", _page_ctx(request, "depts"))


@superadmin_required
def superadmin_slots(request):
    return render(request, "superadmin_slots.html", _page_ctx(request, "slots"))


@superadmin_required
def superadmin_explorer(request):
    return render(request, "superadmin_explorer.html", _page_ctx(request, "explorer"))


@superadmin_required
def superadmin_saved_page(request):
    return render(request, "superadmin_saved.html", _page_ctx(request, "saved"))


@superadmin_required
def superadmin_preview(request):
    return render(request, "superadmin_preview.html", _page_ctx(request, "preview"))


@superadmin_required
def superadmin_activity(request):
    return render(request, "superadmin_activity.html", _page_ctx(request, "activity"))


# ---------------------------------------------------------------------------
# Appoint coordinators (search/add a teacher, assign a role, email them)
# ---------------------------------------------------------------------------

APPOINT_ROLES = [
    "Timetable Coordinator",
    "University Timetable Coordinator",
]

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Logo embedded inline in emails (referenced as ``cid:smartscheduler_logo``).
LOGO_CID = "smartscheduler_logo"


def _attach_logo(msg):
    """Embed the real SmartScheduler logo into an email as an inline image.

    Uses a Content-ID attachment so the HTML can reference ``cid:...`` — this
    renders reliably in Gmail/Outlook (unlike SVG, which they strip). Silently
    skips if the logo file can't be read so email sending never breaks.
    """
    from email.mime.image import MIMEImage
    from pathlib import Path

    for base in settings.STATICFILES_DIRS or []:
        for fname in ("logo_email.png", "logo.jpeg"):
            logo_path = Path(base) / "img" / fname
            if logo_path.exists():
                try:
                    img = MIMEImage(logo_path.read_bytes())
                    img.add_header("Content-ID", f"<{LOGO_CID}>")
                    img.add_header("Content-Disposition", "inline", filename=fname)
                    msg.attach(img)
                except Exception:
                    logger.warning("Could not attach email logo", exc_info=True)
                return

# Role that is allowed to view university-wide statistics (super-admin analytics).
ANALYTICS_ROLE = "University Timetable Coordinator"


def _viewer_credential():
    """Pick a super-admin credential to share with a University Timetable
    Coordinator so they can sign in and view university-wide statistics.

    Prefers a ``dean`` account if one exists in ``SUPERADMIN_USERS`` (a
    secondary analytics login), otherwise falls back to the first configured
    account. Returns ``(email, password)`` or ``None`` if none configured.
    """
    users = getattr(settings, "SUPERADMIN_USERS", {}) or {}
    if not users:
        return None
    for email, pwd in users.items():
        if "dean" in email.lower():
            return email, pwd
    email = next(iter(users))
    return email, users[email]


def _appoint_email(*, name, role, dept_name, message, appointer, creds=None, login_url=""):
    """Return (subject, text_body, html_body) for an appointment email.

    The HTML uses inline styles only (best compatibility across mail clients)
    and the new brand mark/gradient used on the app's loading screen.

    ``creds`` is an optional ``(email, password)`` tuple. When provided (for a
    University Timetable Coordinator) the super-admin analytics login details
    are included so the coordinator can view university-wide statistics.
    """
    safe_name = name or "Faculty Member"
    dept_line = f" for <strong>{dept_name}</strong>" if dept_name else ""
    note_html = ""
    if message:
        note_html = f"""
            <tr><td style="padding:18px 28px 0;">
              <div style="background:#0f1a2c;border:1px solid rgba(148,163,184,.18);
                          border-radius:12px;padding:16px 18px;color:#cbd5e1;font-size:14px;line-height:1.6;">
                <div style="color:#64748b;font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px;">
                  Message from the administrator</div>
                {message.replace(chr(10), '<br>')}
              </div>
            </td></tr>"""

    creds_html = ""
    creds_text = ""
    if creds:
        c_email, c_pwd = creds
        link_html = (
            f'<a href="{login_url}" style="color:#38bdf8;">{login_url}</a>'
            if login_url else "your SmartScheduler super-admin URL"
        )
        creds_html = f"""
            <tr><td style="padding:18px 28px 0;">
              <div style="background:linear-gradient(160deg,#10261c,#0c1f17);border:1px solid rgba(34,197,94,.32);
                          border-radius:12px;padding:18px 20px;">
                <div style="color:#86efac;font-size:11px;letter-spacing:.08em;text-transform:uppercase;margin-bottom:10px;">
                  Statistics dashboard access</div>
                <div style="color:#94a3b8;font-size:13px;line-height:1.6;margin-bottom:12px;">
                  As a University Timetable Coordinator you can view university-wide statistics.
                  Sign in to the analytics dashboard with the credentials below:
                </div>
                <table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;">
                  <tr><td style="color:#64748b;font-size:12px;padding:3px 0;width:90px;">Login URL</td>
                      <td style="color:#e2e8f0;font-size:13px;padding:3px 0;">{link_html}</td></tr>
                  <tr><td style="color:#64748b;font-size:12px;padding:3px 0;">Email</td>
                      <td style="color:#e2e8f0;font-size:13px;padding:3px 0;font-family:monospace;">{c_email}</td></tr>
                  <tr><td style="color:#64748b;font-size:12px;padding:3px 0;">Password</td>
                      <td style="color:#e2e8f0;font-size:13px;padding:3px 0;font-family:monospace;">{c_pwd}</td></tr>
                </table>
                <div style="color:#64748b;font-size:11.5px;line-height:1.5;margin-top:12px;">
                  Please keep these credentials confidential and do not share them.
                </div>
              </div>
            </td></tr>"""
        creds_text = (
            "\nStatistics dashboard access (University Timetable Coordinator):\n"
            f"  Login URL : {login_url or 'your SmartScheduler super-admin URL'}\n"
            f"  Email     : {c_email}\n"
            f"  Password  : {c_pwd}\n"
            "  Please keep these credentials confidential.\n"
        )

    subject = f"You have been appointed as {role} — SmartScheduler"

    text_body = (
        f"Hello {safe_name},\n\n"
        f"You have been appointed as {role}"
        + (f" for {dept_name}" if dept_name else "")
        + ".\n\n"
        + (f"Message from the administrator:\n{message}\n\n" if message else "")
        + "You can sign in to SmartScheduler to manage timetable activities for your role.\n"
        + creds_text
        + f"\nAppointed by: {appointer}\n"
        "— SmartScheduler"
    )

    html_body = f"""\
<!DOCTYPE html><html><body style="margin:0;background:#0b1220;
     font-family:'Segoe UI',system-ui,-apple-system,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
         style="background:#0b1220;padding:28px 12px;">
    <tr><td align="center">
      <table role="presentation" width="560" cellpadding="0" cellspacing="0"
             style="max-width:560px;width:100%;background:#111c30;border:1px solid rgba(148,163,184,.16);
                    border-radius:18px;overflow:hidden;">
        <tr><td style="background:linear-gradient(135deg,#38bdf8,#0ea5e9 55%,#0c3557);padding:26px 28px;">
          <table role="presentation" cellpadding="0" cellspacing="0"><tr>
            <td style="vertical-align:middle;">
              <div style="width:46px;height:46px;border-radius:13px;background:rgba(8,20,36,.55);
                          text-align:center;line-height:46px;">
                <img src="cid:smartscheduler_logo" width="34" height="41" alt="SmartScheduler"
                     style="display:inline-block;width:34px;height:41px;vertical-align:middle;">
              </div>
            </td>
            <td style="padding-left:14px;vertical-align:middle;">
              <div style="color:#ffffff;font-size:19px;font-weight:700;">SmartScheduler</div>
              <div style="color:rgba(255,255,255,.82);font-size:12px;">University Timetable Platform</div>
            </td>
          </tr></table>
        </td></tr>
        <tr><td style="padding:26px 28px 4px;">
          <div style="color:#e2e8f0;font-size:17px;font-weight:600;margin-bottom:6px;">
            Hello {safe_name},</div>
          <div style="color:#94a3b8;font-size:14px;line-height:1.65;">
            You have been appointed as the role below on SmartScheduler{dept_line}.
          </div>
        </td></tr>
        <tr><td style="padding:18px 28px 0;">
          <div style="background:linear-gradient(160deg,#0f1a2c,#0d1626);border:1px solid rgba(56,189,248,.28);
                      border-radius:12px;padding:18px 20px;">
            <div style="color:#64748b;font-size:11px;letter-spacing:.08em;text-transform:uppercase;">Role</div>
            <div style="color:#38bdf8;font-size:20px;font-weight:700;margin-top:4px;">{role}</div>
            {f'<div style="color:#94a3b8;font-size:13px;margin-top:8px;">Department · {dept_name}</div>' if dept_name else ''}
          </div>
        </td></tr>
        {note_html}
        {creds_html}
        <tr><td style="padding:22px 28px 6px;">
          <div style="color:#94a3b8;font-size:13.5px;line-height:1.65;">
            Please sign in to SmartScheduler to begin managing timetable activities for your role.
          </div>
        </td></tr>
        <tr><td style="padding:8px 28px 26px;">
          <div style="border-top:1px solid rgba(148,163,184,.16);padding-top:16px;
                      color:#64748b;font-size:12px;line-height:1.6;">
            Appointed by <span style="color:#cbd5e1;">{appointer}</span><br>
            This is an automated message from SmartScheduler.
          </div>
        </td></tr>
      </table>
    </td></tr>
  </table>
</body></html>"""

    return subject, text_body, html_body


def _superadmin_appoint_send(request):
    name = (request.POST.get("name") or "").strip()
    email = (request.POST.get("email") or "").strip()
    role = (request.POST.get("role") or "").strip()
    dept_name = (request.POST.get("department") or "").strip()
    message = (request.POST.get("message") or "").strip()

    if not name or not email or role not in APPOINT_ROLES:
        messages.error(request, "Please provide the teacher's name, email and a valid role.")
        return redirect("superadmin_appoint")
    if not _EMAIL_RE.match(email):
        messages.error(request, "That email address doesn't look valid.")
        return redirect("superadmin_appoint")
    if not (settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD):
        messages.error(
            request,
            "Email is not configured. Add EMAIL_HOST_USER and EMAIL_HOST_PASSWORD in .env, then restart the server.",
        )
        return redirect("superadmin_appoint")

    appointer = request.session.get(SESSION_EMAIL, "SmartScheduler Super Admin")

    # Only a University Timetable Coordinator receives super-admin analytics
    # login details so they can view university-wide statistics.
    creds = None
    login_url = ""
    if role == ANALYTICS_ROLE:
        creds = _viewer_credential()
        login_url = request.build_absolute_uri(reverse("superadmin_login"))

    subject, text_body, html_body = _appoint_email(
        name=name, role=role, dept_name=dept_name, message=message,
        appointer=appointer, creds=creds, login_url=login_url,
    )
    sender = getattr(settings, "DEFAULT_FROM_EMAIL", "") or settings.EMAIL_HOST_USER
    email_ok = False
    try:
        from email.utils import formataddr
        msg = EmailMultiAlternatives(
            subject=subject,
            body=text_body,
            from_email=sender,
            to=[formataddr((name, email))],
            reply_to=[appointer],
        )
        msg.attach_alternative(html_body, "text/html")
        _attach_logo(msg)
        msg.send(fail_silently=False)
        email_ok = True
        messages.success(request, f"Appointment email sent to {name} ({email}).")
    except Exception as exc:
        logger.exception("Appointment email failed")
        messages.error(request, f"Couldn't send the email: {exc}")

    # Persist the appointment so it can be tracked and listed role-wise.
    # An (email, role) pair is unique; re-appointing updates the record.
    try:
        CoordinatorAppointment.objects.update_or_create(
            email=email.lower(),
            role=role,
            defaults={
                "name": name,
                "department": dept_name,
                "message": message,
                "appointed_by": appointer,
                "analytics_access": role == ANALYTICS_ROLE,
                "email_sent": email_ok,
            },
        )
    except Exception:
        logger.exception("Could not save coordinator appointment")

    return redirect("superadmin_appoint")


@superadmin_required
def superadmin_appoint(request):
    if request.method == "POST":
        return _superadmin_appoint_send(request)

    ctx = _page_ctx(request, "appoint")
    owners = _active_owner_ids()
    rows = list(
        _scope_to_owners(Instructor.objects, owners)
        .order_by("name")
        .values("id", "uid", "name", "email", "designation")
    )
    # De-duplicate master data that may be repeated across owner accounts.
    seen, teachers = set(), []
    for t in rows:
        key = (t["name"].strip().lower(), (t["email"] or "").strip().lower())
        if key in seen:
            continue
        seen.add(key)
        teachers.append(t)
    ctx["appoint_teachers"] = teachers
    ctx["roles"] = APPOINT_ROLES

    # Existing appointments, grouped role-wise for the table below the form.
    appts = list(CoordinatorAppointment.objects.all().order_by("role", "name"))
    grouped = []
    for role_name in APPOINT_ROLES:
        members = [a for a in appts if a.role == role_name]
        grouped.append({"role": role_name, "count": len(members), "members": members})
    ctx["appointment_groups"] = grouped
    ctx["appointment_total"] = len(appts)
    return render(request, "superadmin_appoint.html", ctx)


@superadmin_required
def superadmin_drilldown(request):
    """University -> Department -> Section -> Teacher -> Subject drill-down (JSON)."""
    level = (request.GET.get("level") or "university").strip()
    key = (request.GET.get("id") or "").strip()
    slots = _active_slots()

    def _row(slot):
        return {
            "section": slot.section.section_id if slot.section else "—",
            "subject": getattr(slot.subject, "subject_name", "—"),
            "teacher": getattr(slot.instructor, "name", "—"),
            "room": getattr(slot.room, "r_number", "—"),
            "day": slot.meeting_time.day,
            "slot": str(slot.meeting_time.time),
            "type": "Lab" if slot.is_lab else "Theory",
        }

    if level == "university":
        agg = defaultdict(lambda: {"sections": set(), "teachers": set(), "classes": 0})
        for s in slots:
            dept = s.section.department if s.section else None
            if not dept:
                continue
            a = agg[(dept.id, dept.name, dept.code)]
            a["sections"].add(s.section.section_id)
            if s.instructor_id:
                a["teachers"].add(s.instructor_id)
            a["classes"] += 1
        data = [
            {
                "id": k[0],
                "name": k[1],
                "code": k[2],
                "sections": len(v["sections"]),
                "teachers": len(v["teachers"]),
                "classes": v["classes"],
            }
            for k, v in sorted(agg.items(), key=lambda x: x[0][1])
        ]
        return JsonResponse({"level": "university", "items": data})

    if level == "department":
        agg = defaultdict(lambda: {"teachers": set(), "classes": 0, "sem": ""})
        for s in slots:
            if not s.section or str(s.section.department_id) != key:
                continue
            a = agg[(s.section.id, s.section.section_id)]
            a["sem"] = _semester_of(s.section.section_id)
            if s.instructor_id:
                a["teachers"].add(s.instructor_id)
            a["classes"] += 1
        data = [
            {
                "id": k[0],
                "name": k[1],
                "sem": v["sem"],
                "teachers": len(v["teachers"]),
                "classes": v["classes"],
            }
            for k, v in sorted(agg.items(), key=lambda x: x[0][1])
        ]
        return JsonResponse({"level": "department", "items": data})

    if level == "section":
        rows = [_row(s) for s in slots if s.section and str(s.section_id) == key]
        rows.sort(key=lambda r: (_DAY_ORDER.get(r["day"], 99), r["slot"]))
        return JsonResponse({"level": "section", "items": rows})

    if level == "teacher":
        rows = [_row(s) for s in slots if str(s.instructor_id) == key]
        rows.sort(key=lambda r: (_DAY_ORDER.get(r["day"], 99), r["slot"]))
        return JsonResponse({"level": "teacher", "items": rows})

    if level == "subject":
        rows = [_row(s) for s in slots if str(s.subject_id) == key]
        rows.sort(key=lambda r: (r["section"], _DAY_ORDER.get(r["day"], 99), r["slot"]))
        return JsonResponse({"level": "subject", "items": rows})

    return JsonResponse({"level": level, "items": []})


@superadmin_required
def superadmin_export_excel(request):
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except Exception:
        messages.error(request, "Excel export library is not available.")
        return redirect("superadmin_dashboard")

    ctx = _build_analytics(request)
    wb = Workbook()

    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="2563EB")

    def _style_header(ws):
        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill

    ws = wb.active
    ws.title = "KPIs"
    ws.append(["Metric", "Value"])
    for label, value in [
        ("Departments Active", ctx["kpis"]["departments_active"]),
        ("Teachers Active", ctx["kpis"]["teachers_active"]),
        ("Sections Scheduled", ctx["kpis"]["sections_scheduled"]),
        ("Rooms Total", ctx["kpis"]["rooms_total"]),
        ("Labs Total", ctx["kpis"]["labs_total"]),
        ("Classes Scheduled", ctx["kpis"]["classes_scheduled"]),
        ("Overall Utilization %", ctx["kpis"]["overall_util"]),
        ("Conflicts Detected", ctx["kpis"]["conflicts"]),
    ]:
        ws.append([label, value])
    _style_header(ws)

    ws2 = wb.create_sheet("Department Utilization")
    ws2.append(["Department", "Code", "Utilization %", "Used Cells", "Rooms"])
    for d in ctx["dept_util"]:
        ws2.append([d["name"], d["code"], d["util"], d["used"], d["rooms"]])
    _style_header(ws2)

    ws3 = wb.create_sheet("Room Utilization")
    ws3.append(["Room", "Type", "Department", "Used", "Capacity", "Utilization %"])
    for r in ctx["room_util"]:
        ws3.append([r["number"], r["type"], r["dept"], r["used"], r["capacity"], r["util"]])
    _style_header(ws3)

    ws4 = wb.create_sheet("Teacher Workload")
    ws4.append(["Teacher", "Designation", "Load (hrs)", "Max", "Utilization %"])
    for t in ctx["teacher_workload"]:
        ws4.append([t["name"], t["designation"], t["load"], t["max"], t["util"]])
    _style_header(ws4)

    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    resp = HttpResponse(
        buffer.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    resp["Content-Disposition"] = f'attachment; filename="superadmin_analytics_{stamp}.xlsx"'
    return resp


@superadmin_required
def superadmin_export_pdf(request):
    ctx = _build_analytics(request)
    ctx["generated_at"] = timezone.localtime(timezone.now()).strftime("%d %b %Y, %H:%M")
    html = render(request, "superadmin_report.html", ctx).content.decode("utf-8")
    try:
        from xhtml2pdf import pisa
    except Exception:
        messages.error(request, "PDF export library is not available.")
        return redirect("superadmin_dashboard")

    buffer = io.BytesIO()
    result = pisa.CreatePDF(io.StringIO(html), dest=buffer)
    if result.err:
        messages.error(request, "Could not render the PDF report.")
        return redirect("superadmin_dashboard")
    buffer.seek(0)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    resp = HttpResponse(buffer.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="superadmin_report_{stamp}.pdf"'
    return resp


# ---------------------------------------------------------------------------
# Resource Utilization — room analytics by utilization bucket (real data)
# ---------------------------------------------------------------------------
def _sorted_times(universe):
    times = sorted({t for _, t in universe}, key=lambda x: int(x) if x.isdigit() else 99)
    days = sorted({d for d, _ in universe}, key=lambda d: _DAY_ORDER.get(d, 99))
    return days, times


def _room_occupancy():
    """room_id -> {(day,time): {section, subject, teacher, is_lab}} from active slots."""
    occ = defaultdict(dict)
    for slot in _active_slots():
        room = slot.room
        if not room:
            continue
        cells = [(slot.meeting_time.day, str(slot.meeting_time.time))]
        if slot.is_lab:
            cells += [(mt.day, str(mt.time)) for mt in slot.lab_slots.all()]
        info = {
            "section": slot.section.section_id if slot.section else "—",
            "subject": getattr(slot.subject, "subject_name", "—"),
            "teacher": getattr(slot.instructor, "name", "—"),
            "is_lab": slot.is_lab,
        }
        for day, time in cells:
            if day:
                occ[room.id][(day, time)] = info
    return occ


def _bucket_of(util):
    if util > 70:
        return "gt70"
    if util >= 50:
        return "50-70"
    if util >= 20:
        return "20-50"
    return "ideal"


_BUCKET_LABELS = {
    "gt70": "Above 70% (High load)",
    "50-70": "50% – 70% (Healthy)",
    "20-50": "20% – 50% (Moderate)",
    "ideal": "Ideal (< 20%, plenty free)",
    "all": "All Rooms",
}


@superadmin_required
def superadmin_room_analytics(request):
    """Detailed room analytics filtered by utilization bucket (real DB data)."""
    bucket = (request.GET.get("bucket") or "all").strip()
    dept_filter = (request.GET.get("dept") or "all").strip()

    universe = _slot_universe()
    universe_count = len(universe) or 1
    days, times = _sorted_times(universe)
    occ = _room_occupancy()

    rooms_qs = _scope_to_owners(
        Room.objects.select_related("department"), _active_owner_ids()
    ).order_by("r_number")
    if dept_filter != "all":
        rooms_qs = rooms_qs.filter(department_id=dept_filter)

    rooms = []
    bucket_counts = {"gt70": 0, "50-70": 0, "20-50": 0, "ideal": 0}
    for room in rooms_qs:
        cells = occ.get(room.id, {})
        used = len(cells)
        util = _pct(used, universe_count)
        b = _bucket_of(util)
        bucket_counts[b] += 1
        if bucket != "all" and b != bucket:
            continue

        free_slots = [
            {"day": d, "slot": t} for (d, t) in sorted(
                universe - set(cells.keys()), key=lambda c: (_DAY_ORDER.get(c[0], 99), int(c[1]) if c[1].isdigit() else 99)
            )
        ]
        grid = []
        for d in days:
            row = {"day": d, "cells": []}
            for t in times:
                cell = cells.get((d, t))
                row["cells"].append(
                    {
                        "free": cell is None,
                        "section": cell["section"] if cell else "",
                        "subject": cell["subject"] if cell else "",
                        "is_lab": cell["is_lab"] if cell else False,
                    }
                )
            grid.append(row)

        rooms.append(
            {
                "id": room.id,
                "number": room.r_number,
                "type": room.room_type,
                "lab_category": room.lab_category or "—",
                "department": room.department.name if room.department_id else "—",
                "capacity": room.seating_capacity,
                "used": used,
                "total": universe_count,
                "util": util,
                "free_count": universe_count - used,
                "free_slots": free_slots,
                "grid": grid,
                "bucket": b,
            }
        )

    rooms.sort(key=lambda r: r["util"], reverse=True)
    class_count = sum(r["used"] for r in rooms)
    avg_util = round(sum(r["util"] for r in rooms) / len(rooms), 1) if rooms else 0.0

    return JsonResponse(
        {
            "bucket": bucket,
            "bucket_label": _BUCKET_LABELS.get(bucket, "Rooms"),
            "bucket_counts": bucket_counts,
            "days": days,
            "times": times,
            "summary": {
                "rooms": len(rooms),
                "classes": class_count,
                "avg_util": avg_util,
            },
            "rooms": rooms,
        }
    )


# ---------------------------------------------------------------------------
# Teacher analytics — full profile + schedule (real data)
# ---------------------------------------------------------------------------
@superadmin_required
def superadmin_teacher_detail(request):
    """Complete profile + day/time schedule + workload stats for one teacher."""
    tid = (request.GET.get("id") or "").strip()
    try:
        instr = Instructor.objects.get(id=tid)
    except (Instructor.DoesNotExist, ValueError):
        raise Http404("Teacher not found")

    universe = _slot_universe()
    days, times = _sorted_times(universe)

    schedule = []
    grid_map = {}
    departments = set()
    subjects = set()
    sections = set()
    lab_count = 0
    theory_count = 0
    per_day = defaultdict(int)

    for slot in _active_slots():
        if slot.instructor_id != instr.id and slot.second_instructor_id != instr.id:
            continue
        sec = slot.section
        if sec and sec.department_id:
            departments.add(sec.department.name)
        subjects.add(getattr(slot.subject, "subject_name", "—"))
        if sec:
            sections.add(sec.section_id)

        cells = [(slot.meeting_time.day, str(slot.meeting_time.time))]
        if slot.is_lab:
            cells += [(mt.day, str(mt.time)) for mt in slot.lab_slots.all()]
            lab_count += 1
        else:
            theory_count += 1

        for day, time in cells:
            if not day:
                continue
            entry = {
                "day": day,
                "slot": time,
                "section": sec.section_id if sec else "—",
                "subject": getattr(slot.subject, "subject_name", "—"),
                "room": getattr(slot.room, "r_number", "—"),
                "type": "Lab" if slot.is_lab else "Theory",
            }
            schedule.append(entry)
            grid_map[(day, time)] = entry
            per_day[day] += 1

    schedule.sort(key=lambda e: (_DAY_ORDER.get(e["day"], 99), int(e["slot"]) if e["slot"].isdigit() else 99))
    load = len(schedule)
    grid = [
        {
            "day": d,
            "cells": [grid_map.get((d, t)) for t in times],
        }
        for d in days
    ]
    busiest_day = max(per_day.items(), key=lambda x: x[1])[0] if per_day else "—"

    # Department from sections taught (fallback to TeacherSection mappings).
    if not departments:
        for ts in TeacherSection.objects.filter(instructor=instr).select_related("section__department"):
            if ts.section and ts.section.department_id:
                departments.add(ts.section.department.name)

    return JsonResponse(
        {
            "profile": {
                "id": instr.id,
                "uid": instr.uid,
                "name": instr.name,
                "designation": instr.designation,
                "email": instr.email,
                "contact": instr.contact_number,
                "department": ", ".join(sorted(departments)) or "—",
            },
            "stats": {
                "load": load,
                "max": instr.max_workload,
                "util": _pct(load, instr.max_workload),
                "sections": len(sections),
                "subjects": len(subjects),
                "labs": lab_count,
                "theory": theory_count,
                "busiest_day": busiest_day,
            },
            "subjects": sorted(subjects),
            "days": days,
            "times": times,
            "grid": grid,
            "schedule": schedule,
            "per_day": [{"day": d, "count": per_day.get(d, 0)} for d in days],
        }
    )


# ---------------------------------------------------------------------------
# Saved timetable management — list / detail / drag-drop edit (real data)
# ---------------------------------------------------------------------------
@superadmin_required
def superadmin_saved_list(request):
    """Every saved timetable across all users (admin oversight)."""
    items = []
    qs = (
        SavedTimetable.objects.select_related("department", "user")
        .order_by("-created_at")
    )
    for st in qs:
        slots = st.slots.all()
        section_count = len({s.section_id for s in slots})
        items.append(
            {
                "id": st.id,
                "label": st.department.name if st.department_id else "All Departments",
                "owner": getattr(st.user, "username", "—") if st.user_id else "—",
                "slots": len(slots),
                "sections": section_count,
                "published": st.is_published,
                "created": timezone.localtime(st.created_at).strftime("%d %b %Y, %H:%M")
                if st.created_at
                else "",
            }
        )
    return JsonResponse({"items": items})


@superadmin_required
def superadmin_saved_detail(request, tid):
    """Section-wise editable grid for one saved timetable."""
    try:
        st = SavedTimetable.objects.get(id=tid)
    except SavedTimetable.DoesNotExist:
        raise Http404("Timetable not found")

    universe = _slot_universe()
    days, times = _sorted_times(universe)

    slots = (
        st.slots.select_related("section", "subject", "instructor", "room", "meeting_time")
        .prefetch_related("lab_slots")
        .order_by("section__section_id", "meeting_time__day", "meeting_time__time")
    )

    sections = {}
    for slot in slots:
        sec = slot.section
        if not sec:
            continue
        key = sec.section_id
        if key not in sections:
            sections[key] = {
                "section": key,
                "department": sec.department.name if sec.department_id else "—",
                "cells": {},
            }
        cell = {
            "slot_id": slot.id,
            "subject": getattr(slot.subject, "subject_name", "—"),
            "teacher": getattr(slot.instructor, "name", "—"),
            "room": getattr(slot.room, "r_number", "—"),
            "is_lab": slot.is_lab,
            "day": slot.meeting_time.day,
            "time": str(slot.meeting_time.time),
        }
        sections[key]["cells"][f"{slot.meeting_time.day}|{slot.meeting_time.time}"] = cell

    section_list = []
    for data in sections.values():
        grid = []
        for d in days:
            row = {"day": d, "cells": []}
            for t in times:
                row["cells"].append(data["cells"].get(f"{d}|{t}"))
            grid.append(row)
        section_list.append(
            {"section": data["section"], "department": data["department"], "grid": grid}
        )
    section_list.sort(key=lambda s: s["section"])

    return JsonResponse(
        {
            "id": st.id,
            "label": st.department.name if st.department_id else "All Departments",
            "published": st.is_published,
            "days": days,
            "times": times,
            "sections": section_list,
        }
    )


@superadmin_required
@require_POST
def superadmin_move_slot(request):
    """Drag-drop edit: move a saved ScheduledSlot to a new day/time cell.

    This edits *saved* timetable data only — it does NOT touch the
    scheduling/generation algorithm.
    """
    slot_id = (request.POST.get("slot_id") or "").strip()
    new_day = (request.POST.get("day") or "").strip()
    new_time = (request.POST.get("time") or "").strip()

    try:
        slot = ScheduledSlot.objects.select_related("timetable", "section").get(id=slot_id)
    except (ScheduledSlot.DoesNotExist, ValueError):
        return JsonResponse({"ok": False, "message": "Slot not found."}, status=404)

    owner_id = getattr(slot.timetable, "user_id", None)
    target = MeetingTime.objects.filter(day=new_day, time=new_time)
    if owner_id:
        target = target.filter(user_id=owner_id)
    target_mt = target.first()
    if not target_mt:
        return JsonResponse(
            {"ok": False, "message": f"No time slot configured for {new_day} slot {new_time}."},
            status=400,
        )

    # Prevent double-booking the same section cell (theory).
    clash = (
        ScheduledSlot.objects.filter(
            timetable=slot.timetable,
            section=slot.section,
            meeting_time=target_mt,
            is_lab=False,
        )
        .exclude(id=slot.id)
        .exists()
    )
    if clash and not slot.is_lab:
        return JsonResponse(
            {"ok": False, "message": "That section already has a class in this slot."},
            status=409,
        )

    with transaction.atomic():
        slot.meeting_time = target_mt
        slot.save(update_fields=["meeting_time"])
        if slot.is_lab:
            slot.lab_slots.set([target_mt])

    return JsonResponse(
        {
            "ok": True,
            "message": "Slot moved.",
            "slot_id": slot.id,
            "day": new_day,
            "time": new_time,
        }
    )


# ---------------------------------------------------------------------------
# Open a saved timetable in the EXISTING full-featured page (with full edit).
#
# The existing coordinator page (``saved_timetable`` view + saved_timetable.html)
# and all its edit endpoints are owner-scoped (``request.user``). To let a Super
# Admin use that same page with full editing, we temporarily impersonate the
# timetable's owner for the duration via :class:`SuperAdminImpersonationMiddleware`.
# Impersonation only ever applies to non-``/superadmin/`` paths, so the Super
# Admin's own analytics pages always run as themselves.
# ---------------------------------------------------------------------------
@superadmin_required
def superadmin_open_saved(request, tid):
    try:
        st = SavedTimetable.objects.get(id=tid)
    except SavedTimetable.DoesNotExist:
        raise Http404("Timetable not found")
    request.session[SA_IMPERSONATE] = st.user_id
    request.session.modified = True
    return redirect("saved_timetable", tid=tid)


@superadmin_required
def superadmin_stop_impersonate(request):
    request.session.pop(SA_IMPERSONATE, None)
    request.session.modified = True
    return redirect("superadmin_saved_page")


class SuperAdminImpersonationMiddleware:
    """When a Super Admin opens a saved timetable, run owner-scoped pages as
    that owner so the existing full-featured editor works end-to-end.

    Active only when:
      * the session is an authenticated Super Admin, AND
      * an impersonation target (owner uid) is stored in the session, AND
      * the request path is NOT under ``/superadmin/``.

    A small floating banner is injected so the admin can exit back to the
    Super Admin area at any time. This never touches the scheduling algorithm.
    """

    EXIT_PATH = "/superadmin/stop-impersonate/"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        impersonated_user = None
        if (
            request.session.get(SESSION_FLAG)
            and request.session.get(SA_IMPERSONATE)
            and not request.path.startswith("/superadmin/")
        ):
            from django.contrib.auth import get_user_model

            User = get_user_model()
            try:
                impersonated_user = User.objects.get(id=request.session[SA_IMPERSONATE])
                request.user = impersonated_user
            except User.DoesNotExist:
                request.session.pop(SA_IMPERSONATE, None)
                request.session.modified = True

        response = self.get_response(request)

        if impersonated_user is not None:
            self._inject_banner(response, impersonated_user)
        return response

    def _inject_banner(self, response, user):
        try:
            content_type = response.get("Content-Type", "")
            if "text/html" not in content_type or not getattr(response, "content", None):
                return
            html = response.content.decode("utf-8")
            if "</body>" not in html:
                return
            label = getattr(user, "username", "") or getattr(user, "email", "") or "owner"
            banner = (
                '<div style="position:fixed;left:50%;bottom:18px;transform:translateX(-50%);'
                "z-index:99999;background:#0f1a2c;border:1px solid rgba(139,92,246,.5);"
                "color:#e2e8f0;padding:10px 16px;border-radius:12px;font-size:13px;"
                "font-family:system-ui,sans-serif;box-shadow:0 18px 50px rgba(0,0,0,.5);"
                'display:flex;align-items:center;gap:12px">'
                "<span>🛡️ Super Admin — editing <b>" + label + "</b>'s timetable</span>"
                '<a href="' + self.EXIT_PATH + '" style="background:linear-gradient(135deg,'
                "#3b82f6,#8b5cf6);color:#fff;padding:6px 12px;border-radius:8px;"
                'text-decoration:none;font-weight:600">Exit to Super Admin</a></div>'
            )
            response.content = html.replace("</body>", banner + "</body>", 1).encode("utf-8")
            if response.get("Content-Length") is not None:
                response["Content-Length"] = len(response.content)
        except Exception:
            # Never break the page over a cosmetic banner.
            pass
