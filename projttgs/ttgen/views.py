"""View router for ttgen.

Default behavior:
- Export all non-generator views from `views_other`.
- If a private generator module exists outside this repo, use its endpoints.
- If no private generator module is available, the site still works and
  generator actions show a feature-unavailable message.
"""

import importlib.util
import json
import logging
import os
from pathlib import Path
import hashlib
import hmac
from functools import wraps

from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.csrf import csrf_exempt

from . import views_other as public_core
from .models import UserAccessPlan
from .views_other import *  # noqa: F401,F403

logger = logging.getLogger(__name__)

_GENERATOR_VIEW_NAMES = (
    "generate",
    "generate_timetable_loading",
    "generate_timetables",
    "timetables_page",
    "show_timetable",
    "timetable",
    "update_slot",
    "move_slot_dragdrop",
    "delete_slot",
    "add_slot",
    "save_timetable",
    "substitute_teacher",
    "substitute_lab_teacher",
)

GENERATION_ACCESS_SESSION_KEY = "generation_access_granted"
GENERATION_PENDING_OPTIONS_SESSION_KEY = "generation_pending_options"
DEMO_MODE_SESSION_KEY = "demo_generation_active"
SUBSCRIPTION_FLOW_MODE_SESSION_KEY = "subscription_flow_mode"
RAZORPAY_KEY_ID = os.environ.get("RAZORPAY_KEY_ID", "rzp_test_5GzZRGBccnVG1H")
RAZORPAY_KEY_SECRET = os.environ.get("RAZORPAY_KEY_SECRET", "")
SUBSCRIPTION_PASS_KEY = os.environ.get("SUBSCRIPTION_PASS_KEY", "smartymcajcbosejbb")

PLAN_BASIC = "basic"
PLAN_PRO = "pro"
PLAN_CONFIGS = {
    PLAN_BASIC: {
        "code": PLAN_BASIC,
        "name": "Single Generate",
        "price_paise": 50000,
        "price_rupees": 500,
        "generation_limit": 1,
        "can_edit_delete": False,
        "can_substitute": False,
        "can_drag_drop": False,
        "tagline": "1 generation only",
    },
    PLAN_PRO: {
        "code": PLAN_PRO,
        "name": "Pro Credits",
        "price_paise": 200000,
        "price_rupees": 2000,
        "generation_limit": 6,
        "can_edit_delete": True,
        "can_substitute": True,
        "can_drag_drop": True,
        "tagline": "6 generations + edit/delete/substitute/drag-drop",
    },
}


def _private_file_path(env_var, filename):
    configured_path = os.environ.get(env_var)
    if configured_path:
        return Path(configured_path).expanduser()
    configured_dir = os.environ.get("TTGEN_PRIVATE_DIR")
    if configured_dir:
        return Path(configured_dir).expanduser() / filename
    return Path.home() / ".ttgen_private" / filename


def _generator_unavailable(request, *args, **kwargs):
    messages.error(request, "You are not able to access this feature right now.")
    return redirect("generate")


def _render_generator_unavailable_page(request):
    unavailable_message = "You are not able to access this feature right now."
    return render(
        request,
        "generate.html",
        {
            "generator_unavailable": True,
            "generator_unavailable_message": unavailable_message,
        },
    )


def _get_user_access_plan(user):
    if not getattr(user, "is_authenticated", False):
        return None
    access_plan, _ = UserAccessPlan.objects.get_or_create(user=user)
    return access_plan


def _get_active_access_plan(user):
    access_plan = _get_user_access_plan(user)
    if access_plan and access_plan.is_active and access_plan.generations_remaining > 0:
        return access_plan
    return access_plan


def _selected_plan_code_from_request(request):
    raw_plan_code = (
        request.POST.get("plan_code")
        if request.method == "POST"
        else request.GET.get("plan_code")
    )
    if raw_plan_code in PLAN_CONFIGS:
        return raw_plan_code
    return PLAN_BASIC


def _selected_plan_config(request):
    return PLAN_CONFIGS[_selected_plan_code_from_request(request)]


def _get_pending_generation_options(request):
    stored = request.session.get(GENERATION_PENDING_OPTIONS_SESSION_KEY, {})
    if not isinstance(stored, dict):
        stored = {}
    use_pso = stored.get("use_pso", True)
    return {
        "use_pso": bool(use_pso),
    }


def _set_pending_generation_options(request):
    raw_flag = request.POST.get("use_pso") if request.method == "POST" else request.GET.get("use_pso")
    use_pso = True if raw_flag is None else str(raw_flag).lower() not in {"0", "false", "off", "no"}
    request.session[GENERATION_PENDING_OPTIONS_SESSION_KEY] = {
        "use_pso": use_pso,
    }


def _grant_generation_access(request, source):
    options = _get_pending_generation_options(request)
    _set_demo_mode(request, False)
    request.session[SUBSCRIPTION_FLOW_MODE_SESSION_KEY] = "generate"
    request.session[GENERATION_ACCESS_SESSION_KEY] = {
        "source": source,
        "use_pso": options["use_pso"],
    }
    request.session.modified = True


def _set_demo_mode(request, active):
    request.session[DEMO_MODE_SESSION_KEY] = bool(active)
    request.session.modified = True


def _demo_mode_active(request):
    return bool(request.session.get(DEMO_MODE_SESSION_KEY, False))


def _set_subscription_flow_mode(request, mode):
    request.session[SUBSCRIPTION_FLOW_MODE_SESSION_KEY] = mode
    request.session.modified = True


def _subscription_flow_mode(request):
    mode = request.session.get(SUBSCRIPTION_FLOW_MODE_SESSION_KEY, "generate")
    return mode if mode in {"generate", "subscribe_only"} else "generate"


def _subscribe_only_flow_active(request):
    return _subscription_flow_mode(request) == "subscribe_only"


def _render_subscription_success_modal(request):
    return render(request, "subscription_success_embed.html")


def _render_pass_key_redirect_modal(request, redirect_url):
    return render(request, "pass_key_redirect_embed.html", {"redirect_url": redirect_url})


def _create_razorpay_order_for_request(request):
    selected_plan = _selected_plan_config(request)
    payload = {
        "amount": selected_plan["price_paise"],
        "currency": "INR",
        "receipt": f"ss_{(request.session.session_key or 'guest')[:20]}",
        "notes": {
            "product": "SmartScheduler Generation Unlock",
            "plan_code": selected_plan["code"],
            "user_id": str(request.user.id) if getattr(request.user, "is_authenticated", False) else "",
        },
    }

    response = public_core.requests.post(
        "https://api.razorpay.com/v1/orders",
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    order_data = response.json()
    request.session["razorpay_order_id"] = order_data.get("id")
    request.session["selected_plan_code"] = selected_plan["code"]
    request.session.modified = True
    return order_data


def _fetch_razorpay_order(order_id):
    response = public_core.requests.get(
        f"https://api.razorpay.com/v1/orders/{order_id}",
        auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET),
        timeout=30,
    )
    response.raise_for_status()
    return response.json()


def _resolve_callback_user_and_plan(request, razorpay_order_id):
    user = request.user if getattr(request.user, "is_authenticated", False) else None
    plan_code = request.session.get("selected_plan_code", "")

    if user and plan_code in PLAN_CONFIGS:
        return user, plan_code

    try:
        order_data = _fetch_razorpay_order(razorpay_order_id)
    except Exception:
        return user, plan_code if plan_code in PLAN_CONFIGS else PLAN_BASIC

    notes = order_data.get("notes") or {}
    user_id = notes.get("user_id")
    resolved_plan_code = notes.get("plan_code", "")

    if resolved_plan_code not in PLAN_CONFIGS:
        resolved_plan_code = plan_code if plan_code in PLAN_CONFIGS else PLAN_BASIC

    if not user and user_id:
        UserModel = get_user_model()
        try:
            user = UserModel.objects.get(pk=user_id)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        except UserModel.DoesNotExist:
            user = None

    return user, resolved_plan_code


def _build_generation_loading_url(request):
    options = _get_pending_generation_options(request)
    use_pso_value = "1" if options["use_pso"] else "0"
    return f"{reverse('generate_timetable_loading')}?use_pso={use_pso_value}"


def _generation_access_granted(request):
    access = request.session.get(GENERATION_ACCESS_SESSION_KEY)
    return isinstance(access, dict)


def _generation_access_source(request):
    access = request.session.get(GENERATION_ACCESS_SESSION_KEY)
    if isinstance(access, dict):
        return access.get("source", "")
    return ""


def _pass_key_bypass_active(request):
    return _generation_access_source(request) == "pass_key"


def _clear_pass_key_access(request):
    if _pass_key_bypass_active(request):
        request.session.pop(GENERATION_ACCESS_SESSION_KEY, None)
        request.session.modified = True


def demo_generate_start(request):
    _set_pending_generation_options(request)
    _set_demo_mode(request, True)
    request.session.pop(GENERATION_ACCESS_SESSION_KEY, None)
    request.session.modified = True
    messages.info(request, "Demo generation started. Only preview sections will be fully visible.")
    return redirect(_build_generation_loading_url(request))


def _remaining_generations(user):
    access_plan = _get_user_access_plan(user)
    if not access_plan or not access_plan.is_active:
        return 0
    return access_plan.generations_remaining


def _has_generate_credit(user):
    return True  # TEMP: hardcoded for testing
    # return _remaining_generations(user) > 0


def _has_edit_delete_access(user):
    return True  # TEMP: hardcoded for testing
    # access_plan = _get_user_access_plan(user)
    # return bool(access_plan and access_plan.is_active and access_plan.can_edit_delete)


def _has_substitute_access(user):
    return True  # TEMP: hardcoded for testing
    # access_plan = _get_user_access_plan(user)
    # return bool(access_plan and access_plan.is_active and access_plan.can_substitute)


def _has_drag_drop_access(user):
    return True  # TEMP: hardcoded for testing
    # access_plan = _get_user_access_plan(user)
    # return bool(access_plan and access_plan.is_active and access_plan.can_drag_drop)


def _consume_generation_credit(user):
    return True  # TEMP: hardcoded for testing
    # access_plan = _get_user_access_plan(user)
    # if not access_plan or not access_plan.is_active or access_plan.generations_remaining <= 0:
    #     return False
    # access_plan.generations_used += 1
    # if access_plan.generations_used >= access_plan.generations_total:
    #     access_plan.is_active = False
    # access_plan.save(update_fields=["generations_used", "is_active", "purchased_at"])
    # return True


def _permission_denied_response(request, message):
    if request.headers.get("x-requested-with") == "XMLHttpRequest":
        return JsonResponse({"ok": False, "message": message}, status=403)
    messages.error(request, message)
    return redirect("subscription_gate")


def _apply_plan_purchase_for_user(user, plan_code, razorpay_order_id, razorpay_payment_id):
    plan_config = PLAN_CONFIGS[plan_code]
    access_plan = _get_user_access_plan(user)
    if access_plan is None:
        raise ValueError("Unable to load user access plan.")

    access_plan.plan_code = plan_config["code"]
    access_plan.plan_name = plan_config["name"]
    access_plan.amount_paid = plan_config["price_rupees"]
    access_plan.generations_total = plan_config["generation_limit"]
    access_plan.generations_used = 0
    access_plan.can_edit_delete = plan_config["can_edit_delete"]
    access_plan.can_substitute = plan_config["can_substitute"]
    access_plan.can_drag_drop = plan_config["can_drag_drop"]
    access_plan.is_active = True
    access_plan.razorpay_order_id = razorpay_order_id
    access_plan.razorpay_payment_id = razorpay_payment_id
    access_plan.save()


def _apply_plan_purchase(request, plan_code, razorpay_order_id, razorpay_payment_id):
    if not request.user.is_authenticated:
        raise ValueError("Authentication required to apply purchased plan.")
    _apply_plan_purchase_for_user(request.user, plan_code, razorpay_order_id, razorpay_payment_id)


def _redirect_to_subscription(request):
    messages.info(request, "Please enter the pass key or complete payment to continue.")
    return redirect("subscription_gate")


def _guard_generation_view(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not _demo_mode_active(request) and not _has_generate_credit(request.user) and not _generation_access_granted(request):
            return _redirect_to_subscription(request)
        return view_func(request, *args, **kwargs)

    return wrapped


def _wrap_generate_loading(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not _demo_mode_active(request) and not _has_generate_credit(request.user) and not _generation_access_granted(request):
            return _redirect_to_subscription(request)
        return view_func(request, *args, **kwargs)

    return wrapped


def _wrap_generate_timetables(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if not _demo_mode_active(request) and not _has_generate_credit(request.user) and not _generation_access_granted(request):
            return _redirect_to_subscription(request)
        if not _demo_mode_active(request):
            access_source = _generation_access_source(request)
            if access_source != "pass_key":
                if not _consume_generation_credit(request.user):
                    return _redirect_to_subscription(request)
        return view_func(request, *args, **kwargs)

    return wrapped


def _wrap_edit_delete(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if _has_edit_delete_access(request.user) or _pass_key_bypass_active(request):
            return view_func(request, *args, **kwargs)
        return _permission_denied_response(request, "Please upgrade your plan to use editing features.")

    return wrapped


def _wrap_substitute(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if _has_substitute_access(request.user) or _pass_key_bypass_active(request):
            return view_func(request, *args, **kwargs)
        return _permission_denied_response(request, "Please upgrade your plan to use substitute features.")

    return wrapped


def _wrap_drag_drop(view_func):
    @wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if _has_drag_drop_access(request.user) or _pass_key_bypass_active(request):
            return view_func(request, *args, **kwargs)
        return _permission_denied_response(request, "Please upgrade your plan to access drag-and-drop scheduling.")

    return wrapped


def subscription_gate(request):
    _set_pending_generation_options(request)
    _set_demo_mode(request, False)
    requested_mode = request.POST.get("flow_mode") if request.method == "POST" else request.GET.get("mode")
    if requested_mode == "subscribe_only":
        _set_subscription_flow_mode(request, "subscribe_only")
    elif requested_mode == "generate":
        _set_subscription_flow_mode(request, "generate")
    access_plan = _get_user_access_plan(request.user) if request.user.is_authenticated else None
    selected_plan = _selected_plan_config(request)
    preloaded_order = None

    if request.method == "POST" and request.POST.get("continue_current_plan") == "1" and _has_generate_credit(request.user):
        _grant_generation_access(request, "active_plan")
        return redirect(_build_generation_loading_url(request))

    if request.method == "POST" and "pass_key" not in request.POST and _has_generate_credit(request.user):
        _grant_generation_access(request, "active_plan")
        return redirect(_build_generation_loading_url(request))

    if request.method == "POST":
        submitted_pass_key = request.POST.get("pass_key", "").strip()
        if submitted_pass_key and submitted_pass_key == SUBSCRIPTION_PASS_KEY:
            _grant_generation_access(request, "pass_key")
            if _subscribe_only_flow_active(request):
                return _render_pass_key_redirect_modal(request, _build_generation_loading_url(request))
            messages.success(request, "Pass key verified. Generation is starting now.")
            return redirect(_build_generation_loading_url(request))
        if submitted_pass_key:
            messages.error(request, "Invalid pass key. Please try again or choose a plan.")

    if request.method == "GET" and RAZORPAY_KEY_SECRET:
        try:
            preloaded_order = _create_razorpay_order_for_request(request)
        except Exception:
            preloaded_order = None

    context = {
        "pass_key_hint": "Enter your pass key to unlock instant generation.",
        "razorpay_key_id": RAZORPAY_KEY_ID,
        "razorpay_name": "SmartScheduler",
        "use_pso": _get_pending_generation_options(request)["use_pso"],
        "payment_verification_ready": bool(RAZORPAY_KEY_SECRET),
        "plans": [PLAN_CONFIGS[PLAN_BASIC], PLAN_CONFIGS[PLAN_PRO]],
        "selected_plan_code": _selected_plan_code_from_request(request),
        "selected_plan": selected_plan,
        "active_plan": access_plan,
        "remaining_generations": _remaining_generations(request.user) if request.user.is_authenticated else 0,
        "preloaded_order_id": preloaded_order.get("id") if preloaded_order else "",
        "preloaded_order_amount": preloaded_order.get("amount", selected_plan["price_paise"]) if preloaded_order else selected_plan["price_paise"],
        "preloaded_order_currency": preloaded_order.get("currency", "INR") if preloaded_order else "INR",
        "subscription_flow_mode": _subscription_flow_mode(request),
    }
    return render(request, "subscription.html", context)


def create_razorpay_order(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Method not allowed."}, status=405)

    _set_pending_generation_options(request)

    if not RAZORPAY_KEY_SECRET:
        return JsonResponse(
            {
                "ok": False,
                "message": "Razorpay secret is not configured yet. Add it to enable live payment verification.",
            },
            status=503,
        )

    try:
        order_data = _create_razorpay_order_for_request(request)
    except Exception:
        return JsonResponse(
            {
                "ok": False,
                "message": "Unable to create Razorpay order right now.",
            },
            status=502,
        )

    request.session["razorpay_order_id"] = order_data.get("id")
    request.session.modified = True

    return JsonResponse(
        {
            "ok": True,
            "order_id": order_data.get("id"),
            "amount": order_data.get("amount", _selected_plan_config(request)["price_paise"]),
            "currency": order_data.get("currency", "INR"),
            "key": RAZORPAY_KEY_ID,
            "name": "SmartScheduler",
        }
    )


def verify_razorpay_payment(request):
    if request.method != "POST":
        return JsonResponse({"ok": False, "message": "Method not allowed."}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse(
            {
                "ok": False,
                "message": "Login session was not found. Please login again and complete payment from the subscription page.",
            },
            status=401,
        )

    if not RAZORPAY_KEY_SECRET:
        return JsonResponse(
            {
                "ok": False,
                "message": "Razorpay secret is not configured yet.",
            },
            status=503,
        )

    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"ok": False, "message": "Invalid payment payload."}, status=400)

    razorpay_order_id = payload.get("razorpay_order_id", "")
    razorpay_payment_id = payload.get("razorpay_payment_id", "")
    razorpay_signature = payload.get("razorpay_signature", "")
    expected_order_id = request.session.get("razorpay_order_id", "")

    if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
        return JsonResponse({"ok": False, "message": "Payment details are incomplete."}, status=400)

    if expected_order_id and razorpay_order_id != expected_order_id:
        return JsonResponse({"ok": False, "message": "Order mismatch detected."}, status=400)

    generated_signature = hmac.new(
        RAZORPAY_KEY_SECRET.encode("utf-8"),
        f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    if not hmac.compare_digest(generated_signature, razorpay_signature):
        return JsonResponse({"ok": False, "message": "Payment signature verification failed."}, status=400)

    plan_code = request.session.get("selected_plan_code", PLAN_BASIC)
    if plan_code not in PLAN_CONFIGS:
        plan_code = PLAN_BASIC
    try:
        _apply_plan_purchase(request, plan_code, razorpay_order_id, razorpay_payment_id)
    except ValueError:
        return JsonResponse(
            {
                "ok": False,
                "message": "Unable to link payment to your account. Please login again and retry.",
            },
            status=401,
        )
    if _subscribe_only_flow_active(request):
        request.session["razorpay_payment_id"] = razorpay_payment_id
        request.session.modified = True
        return JsonResponse(
            {
                "ok": True,
                "subscribed": True,
                "redirect_url": reverse("generate"),
            }
        )

    _grant_generation_access(request, "payment")
    request.session["razorpay_payment_id"] = razorpay_payment_id
    request.session.modified = True

    return JsonResponse(
        {
            "ok": True,
            "redirect_url": _build_generation_loading_url(request),
        }
    )


@csrf_exempt
def razorpay_payment_callback(request):
    try:
        if request.method != "POST":
            return redirect("subscription_gate")

        razorpay_order_id = request.POST.get("razorpay_order_id", "")
        razorpay_payment_id = request.POST.get("razorpay_payment_id", "")
        razorpay_signature = request.POST.get("razorpay_signature", "")
        expected_order_id = request.session.get("razorpay_order_id", "")

        if not RAZORPAY_KEY_SECRET:
            messages.error(request, "Razorpay secret is not configured yet.")
            return redirect("subscription_gate")

        if not razorpay_order_id or not razorpay_payment_id or not razorpay_signature:
            messages.error(request, "Payment details are incomplete.")
            return redirect("subscription_gate")

        if expected_order_id and razorpay_order_id != expected_order_id:
            messages.error(request, "Order mismatch detected.")
            return redirect("subscription_gate")

        generated_signature = hmac.new(
            RAZORPAY_KEY_SECRET.encode("utf-8"),
            f"{razorpay_order_id}|{razorpay_payment_id}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(generated_signature, razorpay_signature):
            messages.error(request, "Payment signature verification failed.")
            return redirect("subscription_gate")

        resolved_user, plan_code = _resolve_callback_user_and_plan(request, razorpay_order_id)
        if resolved_user is None:
            messages.error(request, "Could not resolve the user for this payment.")
            return redirect("subscription_gate")

        _apply_plan_purchase_for_user(resolved_user, plan_code, razorpay_order_id, razorpay_payment_id)
        if _subscribe_only_flow_active(request):
            _set_subscription_flow_mode(request, "generate")
            messages.success(request, "Subscription activated successfully.")
            return _render_subscription_success_modal(request)
        _grant_generation_access(request, "payment")
        request.session["razorpay_payment_id"] = razorpay_payment_id
        request.session.modified = True
        messages.success(request, "Payment successful. Generation is starting now.")
        return redirect(_build_generation_loading_url(request))
    except Exception:
        logger.exception("Razorpay callback failed")
        messages.error(request, "Payment was received but the callback could not finish. Please try again.")
        return redirect("subscription_gate")


def _load_external_views_main():
    external_path = _private_file_path("TTGEN_VIEWS_MAIN_PATH", "views_main.py")

    if (
        not external_path.exists()
        or not getattr(public_core, "GENERATOR_RULES_AVAILABLE", False)
        or not getattr(public_core, "GENERATOR_ALGO_AVAILABLE", False)
        or not getattr(public_core, "GENERATOR_RUNTIME_AVAILABLE", False)
    ):
        return None

    spec = importlib.util.spec_from_file_location("ttgen_private_views_main", external_path)
    if spec is None or spec.loader is None:
        return None

    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


try:
    _views_main = _load_external_views_main()
except ModuleNotFoundError as exc:
    missing_module = {
        "views_main",
        f"{__package__}.views_main",
    }
    if exc.name not in missing_module:
        raise
    _views_main = None


if _views_main and hasattr(_views_main, "generate"):
    _generate_view = getattr(_views_main, "generate")
else:
    def _generate_view(request):
        return _render_generator_unavailable_page(request)


def generate(request):
    _set_subscription_flow_mode(request, "generate")
    _set_demo_mode(request, False)
    _clear_pass_key_access(request)
    return _generate_view(request)


for _view_name in _GENERATOR_VIEW_NAMES:
    if _view_name == "generate":
        continue
    if _views_main and hasattr(_views_main, _view_name):
        _view = getattr(_views_main, _view_name)
    else:
        _view = _generator_unavailable

    if _view_name == "generate_timetable_loading":
        globals()[_view_name] = _wrap_generate_loading(_view)
    elif _view_name == "generate_timetables":
        globals()[_view_name] = _wrap_generate_timetables(_view)
    elif _view_name in {"update_slot", "delete_slot", "add_slot"}:
        globals()[_view_name] = _wrap_edit_delete(_view)
    elif _view_name in {"substitute_teacher", "substitute_lab_teacher"}:
        globals()[_view_name] = _wrap_substitute(_view)
    elif _view_name == "move_slot_dragdrop":
        globals()[_view_name] = _wrap_drag_drop(_view)
    else:
        globals()[_view_name] = _guard_generation_view(_view)
