"""Shared by the household scheduler entry points."""

from django.core.management import call_command


def run_chain(command, steps, verbosity):
    """Run each step, isolating failures, and exit non-zero if any failed.

    The same shape as finance's chains: a broken sync must not stop chores
    rolling forward or digests going out, and a failure must show in
    Heroku's logs rather than passing silently.
    """
    failures = []
    for name, kwargs in steps:
        try:
            call_command(name, verbosity=verbosity, **kwargs)
        except SystemExit as exc:
            # A nested chain (finance_hourly) signals its own failures this way.
            if exc.code:
                failures.append(f"{name}: exited {exc.code}")
                command.stderr.write(command.style.ERROR(f"{name} reported failures"))
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
            command.stderr.write(command.style.ERROR(f"{name} failed: {exc}"))

    if failures:
        raise SystemExit(1)
