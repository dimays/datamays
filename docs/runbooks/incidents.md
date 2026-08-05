# When something is wrong

Repo-wide incident notes. For finance-specific symptoms — a stale balance, a
liability with the wrong sign, uncategorized transactions — see
[`../../finance/docs/runbook.md`](../../finance/docs/runbook.md).

## First moves

```bash
heroku logs --tail --app datamays
```

```bash
heroku releases --app datamays
```

Check Sentry. Note that `/finance` request data is deliberately scrubbed, so a
finance error will have a stack trace but not the balances involved — that is
working as intended, not a gap to close.

## Production data is one command away

The repo's `.env` points `DATABASE_URL` at production. A local
`manage.py shell` or `manage.py test` without `--settings=datamays.settings_test`
talks to the live database.

Before running anything that mutates data in production:

1. **Dry-run it first.** Select and print what would change, and read the
   output. Every destructive operation in this repo's history was preceded by
   a read-only query that listed exactly what it would touch.
2. **Know the cascades.** `Category.parent` is `PROTECT`;
   `CategoryRule.category` and `MerchantCategoryMemo.category` are `CASCADE`;
   `Transaction.category` is `SET_NULL`. Deleting a category silently nulls
   every transaction filed under it unless you reassign first — which is why
   the Settings UI makes you pick a destination.
3. **Wrap it in a transaction** and report what happened afterward.

## Deployed code does not match `main`

Almost always the auto-deploy race — see
[`deploy.md`](deploy.md#️-the-auto-deploy-race). Confirm by grepping the
deployed file rather than trusting the release list:

```bash
heroku run "grep -n 'marker from your change' path/to/file.py" --app datamays
```

To force a correct deploy, push an empty commit to `main`:

```bash
git commit --allow-empty -m "Redeploy" && git push origin main
```

## A scheduled run failed

Both chains isolate step failures, so a partial failure is normal and
recoverable. Find which step:

```bash
heroku logs --app datamays --source app | grep -i "finance_hourly\|finance_daily"
```

Then re-run just that step — each is its own command:

```bash
heroku run python manage.py sync_accounts --app datamays
```

```bash
heroku run python manage.py categorize_transactions --app datamays
```

```bash
heroku run python manage.py rollup_budgets --app datamays
```

Order matters: alerts must see fresh budget numbers, and budgets must see
categorized transactions.

## Credentials look broken

If `FIELD_ENCRYPTION_KEYS` was rotated without re-saving each connection, the
stored access URLs cannot be decrypted. Settings pages still load in that
state — deliberately, so you can get in and reconnect — but syncing fails.

Recovery is re-authorizing the connection, not restoring a key you no longer
have. Full procedure in
[`../../finance/docs/runbook.md`](../../finance/docs/runbook.md#rotating-the-encryption-key).

## The local preview server serves stale HTML

Not a production issue, but it wastes time. After switching git branches, the
dev server can keep serving the *previous* branch's templates — surviving a
hard refresh and cache-busting query params, and not explained by Django's
template loaders (which are not cached in this project).

Root cause never fully identified. Reliable fix: stop the server and start it
again. Treat restarting after a branch switch as routine rather than
debugging what you are looking at.
