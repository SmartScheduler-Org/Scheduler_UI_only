from .models import UserAccessPlan


def subscription_nav(request):
    user = getattr(request, "user", None)
    has_active_subscription = False
    subscription_generations_remaining = 0
    account_subscription_plan = "No active plan"
    account_subscription_amount = 0
    account_generations_total = 0

    if getattr(user, "is_authenticated", False):
        try:
            access_plan = UserAccessPlan.objects.get(user=user)
        except UserAccessPlan.DoesNotExist:
            access_plan = None

        if access_plan:
            account_subscription_plan = access_plan.plan_name or "No active plan"
            account_subscription_amount = access_plan.amount_paid or 0
            account_generations_total = access_plan.generations_total or 0

            if access_plan.is_active and access_plan.generations_remaining > 0:
                has_active_subscription = True
                subscription_generations_remaining = access_plan.generations_remaining

    return {
        "has_active_subscription": has_active_subscription,
        "subscription_generations_remaining": subscription_generations_remaining,
        "account_subscription_plan": account_subscription_plan,
        "account_subscription_amount": account_subscription_amount,
        "account_generations_total": account_generations_total,
    }
