"""Maps provider strings to FulfillmentProvider instances"""

from __future__ import annotations

from services.fulfillment_provider import FulfillmentProvider, ProviderNotFoundError


class ProviderRegistry:
    """Resolves a provider string (e.g. ``"ansible"``) to a FulfillmentProvider.

    Constructed once in the DI container at startup. Lifecycle and
    fulfillment code stay free of provider-specific branches — new
    mechanisms extend this registry rather than adding branches elsewhere.
    """

    def __init__(self, providers: dict[str, FulfillmentProvider]) -> None:
        self._providers = dict(providers)

    def require(self, provider: str) -> FulfillmentProvider:
        try:
            return self._providers[provider]
        except KeyError:
            raise ProviderNotFoundError(
                f"No FulfillmentProvider registered for provider={provider!r}"
            ) from None
