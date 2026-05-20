from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any


class ProviderError(RuntimeError):
    pass


@dataclass(slots=True, eq=True)
class AssetBalance:
    asset_symbol: str
    quantity: Decimal
    value_usd: Decimal | None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, eq=True)
class ProviderSnapshot:
    total_value_usd: Decimal
    assets: list[AssetBalance]


@dataclass(slots=True, eq=True)
class ContractPositionRisk:
    provider: str
    channel_name: str
    symbol: str
    side: str
    quantity: Decimal
    entry_price: Decimal | None
    mark_price: Decimal
    liquidation_price: Decimal | None
    unrealized_pnl: Decimal | None
    margin_mode: str | None
    leverage: str | None
    updated_at_ms: int | None
    raw_payload: dict[str, object] = field(default_factory=dict)

    @property
    def distance_percent(self) -> Decimal | None:
        if self.mark_price == 0 or self.liquidation_price is None or self.liquidation_price == 0:
            return None
        value = abs(self.mark_price - self.liquidation_price) / self.mark_price * Decimal("100")
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


@dataclass(slots=True, eq=True)
class ContractMarginBalanceRisk:
    provider: str
    channel_name: str
    wallet_balance: Decimal
    margin_balance: Decimal
    unrealized_pnl: Decimal | None
    updated_at_ms: int | None = None
    risk_percent_override: Decimal | None = None
    raw_payload: dict[str, object] = field(default_factory=dict)

    @property
    def risk_percent(self) -> Decimal | None:
        if self.risk_percent_override is not None:
            return self.risk_percent_override.quantize(
                Decimal("0.00000001"), rounding=ROUND_HALF_UP
            )
        if self.wallet_balance == 0:
            return None
        value = self.margin_balance / self.wallet_balance * Decimal("100")
        return value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


class Provider:
    async def collect_snapshot(self) -> ProviderSnapshot:
        raise NotImplementedError

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        return []

    async def collect_contract_margin_balance(self) -> ContractMarginBalanceRisk | None:
        return None
