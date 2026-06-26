"""User activity / audit logging.

Captures meaningful coordinator actions (login, logout, generate, save,
delete, export, drag-and-drop slot moves, parking, publish, etc.) for the
Super Admin "Recent Activity" view.

This module is purely additive: it observes requests via middleware and auth
signals. It NEVER modifies the scheduling/generation algorithm or the
coordinator dashboard behaviour.
"""
from __future__ import annotations

import json
import logging

from django.contrib.auth.signals import user_logged_in, user_logged_out
from django.dispatch import receiver
from django.utils import timezone

logger = logging.getLogger(__name__)

# url_name -> (action, verb) for requests we care about.
ACTION_MAP = {
    "generate_timetables": ("generate", "Generated a timetable"),
    "save_timetable": ("save", "Saved a timetable"),
    "delete_saved_timetable": ("delete", "Deleted a saved timetable"),
    "saved_delete_slot": ("delete", "Deleted a slot"),
    "delete_slot": ("delete", "Deleted a slot"),
    "generated_delete_slot_item": ("delete", "Deleted a slot"),
    "generated_delete_parking_item": ("delete", "Deleted a parked slot"),
    "deleteinstructor": ("delete", "Deleted a teacher"),
    "delete_saved_prefill": ("delete", "Deleted a saved prefill"),
    "saved_move_slot_dragdrop": ("move", "Moved a slot (drag & drop)"),
    "move_slot_dragdrop": ("move", "Moved a slot (drag & drop)"),
    "saved_add_slot": ("add", "Added a slot"),
    "add_slot": ("add", "Added a slot"),
    "saved_update_slot": ("edit", "Edited a slot"),
    "update_slot": ("edit", "Edited a slot"),
    "saved_substitute_teacher": ("substitute", "Substituted a teacher"),
    "saved_substitute_lab_teacher": ("substitute", "Substituted a lab teacher"),
    "substitute_teacher": ("substitute", "Substituted a teacher"),
    "substitute_lab_teacher": ("substitute", "Substituted a lab teacher"),
    "generated_park_slot": ("park", "Parked a slot"),
    "saved_park_slot": ("park", "Parked a slot"),
    "generated_restore_parked_slot": ("restore", "Restored a parked slot"),
    "download_timetable": ("export", "Exported a timetable (PDF)"),
    "download_timetable_excel": ("export", "Exported a timetable (Excel)"),
    "download_timetable_excel_view": ("export", "Exported a timetable (Excel)"),
    "download_generated_timetable_excel": ("export", "Exported a timetable (Excel)"),
    "publish_timetable": ("publish", "Published a timetable"),
    "unpublish_timetable": ("unpublish", "Unpublished a timetable"),
}


def _client_ip(request):
    xff = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if xff:
        return xff.split(",")[0].strip()[:60]
    return (request.META.get("REMOTE_ADDR", "") or "")[:60]


def _user_agent(request):
    return (request.META.get("HTTP_USER_AGENT", "") or "")[:300]


def log_activity(action, *, request=None, user=None, summary="", detail=""):
    """Write a single ActivityLog row. Best-effort; never raises."""
    from .models import ActivityLog

    try:
        u = user
        if u is None and request is not None:
            u = getattr(request, "user", None)
        is_auth = bool(u and getattr(u, "is_authenticated", False))
        ActivityLog.objects.create(
            user=u if is_auth else None,
            username=(getattr(u, "username", "") or "") if u else "",
            email=(getattr(u, "email", "") or "") if u else "",
            action=action,
            summary=summary[:300],
            detail=detail or "",
            path=(getattr(request, "path", "") or "")[:300] if request else "",
            method=(getattr(request, "method", "") or "")[:8] if request else "",
            session_key=(request.session.session_key or "") if request and hasattr(request, "session") else "",
            ip=_client_ip(request) if request else "",
            created_at=timezone.now(),
        )
    except Exception:
        logger.exception("Failed to write ActivityLog")


def _open_session_for(user, session_key):
    from .models import UserSession

    qs = UserSession.objects.filter(logout_at__isnull=True)
    if session_key:
        s = qs.filter(session_key=session_key).order_by("-login_at").first()
        if s:
            return s
    if user is not None and getattr(user, "pk", None):
        return qs.filter(user=user).order_by("-login_at").first()
    return None


def _touch_session(request, user):
    """Update last_seen on the user's current open session (heartbeat)."""
    from .models import UserSession

    try:
        key = request.session.session_key if hasattr(request, "session") else ""
        s = _open_session_for(user, key)
        now = timezone.now()
        if s is None:
            UserSession.objects.create(
                user=user if getattr(user, "is_authenticated", False) else None,
                username=getattr(user, "username", "") or "",
                email=getattr(user, "email", "") or "",
                session_key=key or "",
                ip=_client_ip(request),
                user_agent=_user_agent(request),
                login_at=now,
                last_seen=now,
            )
        else:
            s.last_seen = now
            s.save(update_fields=["last_seen"])
    except Exception:
        logger.exception("Failed to touch UserSession")


# ---------------------------------------------------------------------------
# Auth signals: login / logout
# ---------------------------------------------------------------------------
@receiver(user_logged_in)
def _on_login(sender, request, user, **kwargs):
    from .models import UserSession

    try:
        if not hasattr(request, "session"):
            return
        if not request.session.session_key:
            request.session.save()
        key = request.session.session_key or ""
        now = timezone.now()
        UserSession.objects.create(
            user=user,
            username=getattr(user, "username", "") or "",
            email=getattr(user, "email", "") or "",
            session_key=key,
            ip=_client_ip(request),
            user_agent=_user_agent(request),
            login_at=now,
            last_seen=now,
        )
        log_activity("login", request=request, user=user, summary="Logged in")
    except Exception:
        logger.exception("Failed to record login")


@receiver(user_logged_out)
def _on_logout(sender, request, user, **kwargs):
    try:
        if user is None:
            return
        key = request.session.session_key if hasattr(request, "session") else ""
        s = _open_session_for(user, key)
        if s is not None:
            s.logout_at = timezone.now()
            s.save(update_fields=["logout_at"])
        log_activity("logout", request=request, user=user, summary="Logged out")
    except Exception:
        logger.exception("Failed to record logout")


# ---------------------------------------------------------------------------
# Middleware: log meaningful actions and keep the session heartbeat fresh
# ---------------------------------------------------------------------------
class ActivityTrackingMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        try:
            self._track(request, response)
        except Exception:
            logger.exception("ActivityTrackingMiddleware failed")
        return response

    def _track(self, request, response):
        user = getattr(request, "user", None)
        if not user or not getattr(user, "is_authenticated", False):
            return
        # Skip Super Admin sessions (incl. impersonation) — they are not the
        # real coordinator and would pollute the per-user activity.
        sess = getattr(request, "session", None)
        if sess is not None and (sess.get("is_superadmin") or sess.get("sa_impersonate")):
            return

        rm = getattr(request, "resolver_match", None)
        if rm is None or not rm.url_name:
            return
        spec = ACTION_MAP.get(rm.url_name)
        if spec is None:
            # Unknown route — just refresh the heartbeat occasionally.
            _touch_session(request, user)
            return
        if getattr(response, "status_code", 200) >= 400:
            return

        action, verb = spec
        summary = verb
        detail = self._detail(request, rm, action)
        log_activity(action, request=request, user=user, summary=summary, detail=detail)
        _touch_session(request, user)

    def _detail(self, request, rm, action):
        kw = rm.kwargs or {}
        parts = []
        section = kw.get("section")
        day = kw.get("day")
        slot = kw.get("slot")
        tid = kw.get("tid") or kw.get("index")
        if section:
            parts.append(f"section {section}")
        if day and slot:
            parts.append(f"{day} slot {slot}")
        if tid is not None:
            parts.append(f"timetable #{tid}")

        # For drag-and-drop moves, capture the destination from the JSON body.
        if action == "move":
            try:
                body = json.loads((request.body or b"").decode("utf-8") or "{}")
                t_day = body.get("target_day")
                t_slot = body.get("target_slot")
                mtype = body.get("move_type")
                if t_day and t_slot:
                    parts.append(f"→ {t_day} slot {t_slot}")
                if mtype:
                    parts.append(f"({mtype})")
            except Exception:
                pass
        return " · ".join(str(p) for p in parts)
