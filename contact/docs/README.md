# contact

The contact form. One model, one form, one view, about 100 lines.

## What it does

A visitor submits name, email and a message. The submission is stored and an
email is sent via the configured SMTP account (Gmail).

| Path | What |
|---|---|
| `/contact/` | The form, and its success state |

## The one thing worth knowing

**Email delivery depends on `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`.**
Without them the submission still saves — the record is not lost — but no mail
goes out and there is no loud failure. If someone reports "I sent a message and
heard nothing," check the config vars before checking the code.

The finance app's alerts and scheduled reports use the same SMTP settings, so
a mail problem here is usually a mail problem there too.

## Tests

```bash
uv run python manage.py test contact --settings=datamays.settings_test
```

Mail is captured by Django's locmem backend under the test settings. No test
sends real email.
