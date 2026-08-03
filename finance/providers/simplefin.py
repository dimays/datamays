"""SimpleFIN Bridge adapter.

SimpleFIN hands out a read-only Access URL with HTTP Basic credentials baked
into it. That credential can list accounts and transactions and nothing else —
it cannot move money — and it is revocable from the SimpleFIN side without
touching any bank password. That property is the whole reason this app never
stores institution credentials.

Setup is a one-time exchange: the user pastes a base64-encoded setup token,
we POST to the URL it decodes to, and SimpleFIN returns the Access URL, which
is then encrypted at rest.
"""

import base64
import binascii
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

import requests

from .base import (
    AccountPayload,
    FetchResult,
    ProviderAuthError,
    ProviderError,
    TransactionPayload,
)

TIMEOUT_SECONDS = 60


def claim_access_url(setup_token: str) -> str:
    """Exchange a one-time setup token for a durable Access URL.

    The token is single-use: SimpleFIN will refuse a second claim, so a failure
    here usually means the token was already redeemed and a fresh one is needed.
    """
    token = (setup_token or "").strip()

    if not token:
        raise ProviderError("Paste the setup token from SimpleFIN first.")

    try:
        claim_url = base64.b64decode(token, validate=True).decode()
    except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
        raise ProviderError(
            "That does not look like a SimpleFIN setup token. Copy the whole "
            "string from the SimpleFIN Bridge page."
        ) from exc

    if not claim_url.startswith("https://"):
        # A token decoding to plain HTTP would send the credential in clear text.
        raise ProviderError("Setup token did not decode to an HTTPS URL.")

    try:
        response = requests.post(claim_url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as exc:
        raise ProviderError(f"Could not reach SimpleFIN: {exc}") from exc

    if response.status_code == 403:
        raise ProviderAuthError(
            "SimpleFIN rejected that setup token. Tokens can only be claimed "
            "once — generate a new one and try again."
        )

    if not response.ok:
        raise ProviderError(
            f"SimpleFIN returned {response.status_code} when claiming the token."
        )

    access_url = response.text.strip()

    if not access_url.startswith("https://"):
        raise ProviderError("SimpleFIN did not return a usable access URL.")

    return access_url


def _to_decimal(value, field_name):
    if value is None or value == "":
        return None

    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError) as exc:
        raise ProviderError(f"Could not read {field_name} value {value!r}.") from exc


def _to_date(epoch_seconds):
    if epoch_seconds in (None, ""):
        return None

    try:
        return datetime.fromtimestamp(int(epoch_seconds), tz=timezone.utc).date()
    except (TypeError, ValueError, OSError) as exc:
        raise ProviderError(f"Unreadable timestamp {epoch_seconds!r}.") from exc


class SimpleFINAdapter:
    name = "simplefin"

    def fetch(self, *, access_secret: str, since: date) -> FetchResult:
        payload = self._get_accounts(access_secret, since)
        result = FetchResult(errors=list(payload.get("errors") or []))

        for raw_account in payload.get("accounts") or []:
            account_id = str(raw_account.get("id") or "").strip()

            if not account_id:
                result.errors.append("Skipped an account with no identifier.")
                continue

            organisation = raw_account.get("org") or {}

            result.accounts.append(
                AccountPayload(
                    provider_account_id=account_id,
                    name=str(raw_account.get("name") or "Account").strip(),
                    currency=str(raw_account.get("currency") or "USD")[:3],
                    official_name=str(raw_account.get("name") or "").strip(),
                    institution_name=str(organisation.get("name") or "").strip(),
                    raw_balance=_to_decimal(raw_account.get("balance"), "balance"),
                    raw_available_balance=_to_decimal(
                        raw_account.get("available-balance"), "available balance"
                    ),
                    balance_as_of=_to_date(raw_account.get("balance-date")),
                )
            )

            result.transactions[account_id] = self._parse_transactions(raw_account)

        return result

    def _get_accounts(self, access_secret, since):
        url = f"{access_secret.rstrip('/')}/accounts"
        params = {
            "start-date": int(
                datetime(since.year, since.month, since.day, tzinfo=timezone.utc).timestamp()
            ),
            # Ask for balances even when an account has no activity in the
            # window, so net-worth charts keep moving for quiet accounts.
            "balances-only": 0,
        }

        try:
            response = requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as exc:
            raise ProviderError(f"Could not reach SimpleFIN: {exc}") from exc

        if response.status_code in (401, 403):
            raise ProviderAuthError(
                "SimpleFIN rejected the stored access URL. Re-authorize this "
                "connection from settings."
            )

        if not response.ok:
            raise ProviderError(f"SimpleFIN returned {response.status_code}.")

        try:
            return response.json()
        except ValueError as exc:
            raise ProviderError("SimpleFIN returned a response that was not JSON.") from exc

    def _parse_transactions(self, raw_account):
        parsed = []

        for raw in raw_account.get("transactions") or []:
            posted_on = _to_date(raw.get("posted") or raw.get("transacted_at"))
            amount = _to_decimal(raw.get("amount"), "transaction amount")
            transaction_id = str(raw.get("id") or "").strip()

            if posted_on is None or amount is None or not transaction_id:
                # Dropping the row is safer than inventing a date or an amount;
                # the count mismatch shows up on the sync run.
                continue

            description = str(
                raw.get("description") or raw.get("payee") or raw.get("memo") or ""
            ).strip()

            parsed.append(
                TransactionPayload(
                    provider_txn_id=transaction_id,
                    posted_on=posted_on,
                    amount=amount,
                    description=description[:500],
                    merchant=str(raw.get("payee") or "").strip()[:160],
                    is_pending=bool(raw.get("pending", False)),
                )
            )

        return parsed
