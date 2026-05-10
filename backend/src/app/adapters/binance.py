from __future__ import annotations

from decimal import Decimal

from app.adapters.base import NormalizedBalance


class BinanceAdapter:
    def normalize_mock_payload(self, channel_id: int, payload: dict) -> list[NormalizedBalance]:
        prices = payload["prices"]
        balances = []
        for item in payload["account"]["balances"]:
            total = Decimal(item["free"]) + Decimal(item["locked"])
            asset = item["asset"]
            balances.append(
                NormalizedBalance(
                    channel_id=channel_id,
                    provider="binance",
                    asset=asset,
                    total=total,
                    value_usd=total * Decimal(prices[f"{asset}USDT"]),
                    account_scope="spot",
                )
            )
        return balances
