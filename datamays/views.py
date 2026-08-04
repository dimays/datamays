from django.shortcuts import render


def permission_denied(request, exception=None):
    """Project-wide 403 handler.

    The finance app gets its own page. Anything else keeps the site's
    standard one.
    """
    template = (
        "finance/403.html"
        if request.path.startswith("/finance")
        else "403.html"
    )

    return render(request, template, status=403)
