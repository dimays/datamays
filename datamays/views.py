from django.shortcuts import render

# The private apps share one 403 — the same page whichever door a stranger
# tried, so it reveals nothing about what is behind either.
PRIVATE_PREFIXES = ("/finance", "/household")


def _is_verified_member(user):
    from household.access import is_household_member

    return is_household_member(user) and getattr(user, "is_verified", lambda: False)()


def permission_denied(request, exception=None):
    """Project-wide 403 handler.

    The private apps get their own page. A verified household member refused
    something (the other person's chore, say) gets a member's explanation —
    the stranger's "you are not one of the two" page was wrong for them.
    Everyone else keeps the site's standard one.
    """
    if request.path.startswith(PRIVATE_PREFIXES):
        template = "household/403_member.html" if _is_verified_member(request.user) else "household/403.html"
    else:
        template = "403.html"

    return render(request, template, status=403)
