"""Shared by the household scheduler entry points."""

import logging

from django.core.management import call_command

logger = logging.getLogger(__name__)


def run_chain(command, steps, verbosity):
    """Run each step, isolating failures, and exit non-zero if any failed.

    The same shape as finance's chains: a broken sync must not stop chores
    rolling forward or digests going out, and a failure must be seen rather
    than pass silently — logged as an error (so Sentry reports it) and a
    non-zero exit (so Heroku's logs show it).
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
                logger.error("Scheduled step %s reported failures", name)
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{name}: {exc}")
            command.stderr.write(command.style.ERROR(f"{name} failed: {exc}"))
            # Logged, so it reaches Sentry with its traceback: stderr and an
            # exit code alone are seen only by someone reading Heroku's logs.
            logger.exception("Scheduled step %s failed", name)

    if failures:
        raise SystemExit(1)
