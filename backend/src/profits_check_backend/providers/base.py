from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True, eq=True)
class AssetBalance:
    asset_symbol: str
    quantity: Decimal
    value_usd: Decimal | None
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True, eq=True)
class ProviderSnapshot:
    total_value_usd: Decimal
    assets: list[AssetBalance]


class Provider:
    async def collect_snapshot(self) -> ProviderSnapshot:
        raise NotImplementedError
