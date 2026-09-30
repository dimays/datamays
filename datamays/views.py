from django.shortcuts import render

# The private apps share one 403 — the same page whichever door a stranger
# tried, so it reveals nothing about what is behind either.
PRIVATE_PREFIXES = ("/finance", "/household")


def permission_denied(request, exception=None):
    """Project-wide 403 handler.

    The private apps get their own page. Anything else keeps the site's
    standard one.
    """
    template = (
        "household/403.html"
        if request.path.startswith(PRIVATE_PREFIXES)
        else "403.html"
    )

    return render(request, template, status=403)
