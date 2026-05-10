from __future__ import annotations

from profits_check_backend.providers.base import Provider, ProviderError


class PlaceholderProvider(Provider):
    def __init__(self, provider_name: str) -> None:
        self.provider_name = provider_name

    async def collect_snapshot(self):
        raise ProviderError(f"{self.provider_name} is not implemented yet")
