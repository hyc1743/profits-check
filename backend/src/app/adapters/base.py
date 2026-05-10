from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class NormalizedBalance:
    channel_id: int
    provider: str
    asset: str
    total: Decimal
    value_usd: Decimal
    account_scope: str
