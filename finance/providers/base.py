"""The boundary between an outside financial institution and our data model.

Adapters do one job: turn whatever a provider returns into the normalised
payloads below. Everything downstream — sync, categorisation, dashboards —
depends on the conventions in `finance.models.base` already holding, so this is
the only layer allowed to reason about a provider's sign quirks or date
formats. Adding a second provider later should mean writing one adapter and
touching nothing else.
"""

import re
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol


CREDENTIAL_IN_URL = re.compile(r"(https?://)[^/\s:@]+:[^/\s@]+@")


def redact(message) -> str:
    """Strip embedded HTTP Basic credentials from text before it is stored.

    Provider errors land in `connection.last_error`, which is rendered on the
    connection page. A SimpleFIN access URL carries its credential in the
    userinfo, so any exception echoing the URL would put it on screen.
    `requests` happens not to today; this does not rely on that staying true.
    """
    return CREDENTIAL_IN_URL.sub(r"\1<redacted>@", str(message))


class ProviderError(Exception):
    """A provider call failed in a way worth surfacing on the connection."""


class ProviderAuthError(ProviderError):
    """Credentials were rejected. The connection needs re-authorizing."""


@dataclass(frozen=True)
class AccountPayload:
    provider_account_id: str
    name: str
    currency: str = "USD"

    official_name: str = ""
    mask: str = ""
    institution_name: str = ""

    # Signed as the provider reported it. Normalising into the household's
    # net-worth convention happens in the sync service, which knows the
    # account type and the household's per-account sign setting.
    raw_balance: Decimal | None = None
    raw_available_balance: Decimal | None = None
    balance_as_of: date | None = None


@dataclass(frozen=True)
class TransactionPayload:
    provider_txn_id: str
    posted_on: date
    amount: Decimal
    description: str

    merchant: str = ""
    is_pending: bool = False


@dataclass
class FetchResult:
    accounts: list[AccountPayload] = field(default_factory=list)
    transactions: dict[str, list[TransactionPayload]] = field(default_factory=dict)
    # Provider-reported problems that are not fatal — one account failing to
    # refresh should not discard the others.
    errors: list[str] = field(default_factory=list)


class ProviderAdapter(Protocol):
    name: str

    def fetch(self, *, access_secret: str, since: date) -> FetchResult:
        """Return accounts and their transactions posted on or after `since`."""
