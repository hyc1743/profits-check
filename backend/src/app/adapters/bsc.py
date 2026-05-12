from __future__ import annotations

from decimal import Decimal

from app.adapters.base import NormalizedBalance


class BscAdapter:
    def normalize_mock_payload(self, channel_id: int, payload: dict) -> list[NormalizedBalance]:
        wallet = payload["wallet"]
        balances = [
            NormalizedBalance(
                channel_id=channel_id,
                provider="bsc",
                asset=payload["native"]["symbol"],
                total=Decimal(payload["native"]["balance"]),
                value_usd=(
                    Decimal(payload["native"]["balance"]) * Decimal(payload["native"]["priceUsd"])
                ),
                account_scope=f"wallet:{wallet}",
            )
        ]
        for token in payload["tokens"]:
            balances.append(
                NormalizedBalance(
                    channel_id=channel_id,
                    provider="bsc",
                    asset=token["symbol"],
                    total=Decimal(token["balance"]),
                    value_usd=Decimal(token["balance"]) * Decimal(token["priceUsd"]),
                    account_scope=f"wallet:{wallet}",
                )
            )
        return balances
