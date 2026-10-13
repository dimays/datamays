"""Redirect-target validation.

`?next=` and hidden `next` fields are attacker-controllable, so a bare
`redirect(request.POST["next"])` will happily send a signed-in person to
another host. Everything that honours a caller-supplied destination goes
through here.
"""


def is_safe_path(value) -> bool:
    """True only for same-site absolute paths.

    Rejects scheme-relative (`//evil.example`), absolute URLs, and anything
    carrying a scheme such as `javascript:`. Backslashes and newlines are
    rejected too — some browsers normalize the former to forward slashes, and
    the latter would allow header injection.
    """
    if not value or not isinstance(value, str):
        return False

    if not value.startswith("/") or value.startswith("//"):
        return False

    return "\\" not in value and "\r" not in value and "\n" not in value


def safe_next(request, default):
    """The caller's requested destination, or `default` if it is not safe.

    `default` is required rather than inferred. Falling back to the current
    path suits a list page that should stay put, but on an auth screen it
    would bounce the visitor straight back to the page they just cleared.
    """
    candidate = request.POST.get("next") or request.GET.get("next")

    return candidate if is_safe_path(candidate) else default
