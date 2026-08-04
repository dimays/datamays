from ..models import Provider
from .base import ProviderAdapter, ProviderError
from .simplefin import SimpleFINAdapter

_ADAPTERS = {
    Provider.SIMPLEFIN: SimpleFINAdapter,
}


def get_adapter(provider: str) -> ProviderAdapter:
    try:
        return _ADAPTERS[provider]()
    except KeyError:
        raise ProviderError(
            f"No adapter for provider {provider!r}. Accounts on this provider "
            "are maintained by CSV import or by hand."
        ) from None


def is_automated(provider: str) -> bool:
    return provider in _ADAPTERS
