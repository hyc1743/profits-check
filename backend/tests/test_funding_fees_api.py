from __future__ import annotations

from decimal import Decimal

from profits_check_backend.providers.base import FundingFeeRecord


def test_funding_fees_api_summarizes_monthly_records(client) -> None:
    class StubProvider:
        def __init__(self, provider: str, channel_name: str) -> None:
            self.provider = provider
            self.channel_name = channel_name

        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            assert start_time_ms == 1719763200000
            assert end_time_ms == 1722441599999
            if self.provider == "binance":
                return [
                    FundingFeeRecord(
                        provider=self.provider,
                        channel_name=self.channel_name,
                        amount=Decimal("12.5"),
                        asset="USDT",
                        timestamp_ms=start_time_ms,
                    ),
                    FundingFeeRecord(
                        provider=self.provider,
                        channel_name=self.channel_name,
                        amount=Decimal("-2.25"),
                        asset="USDT",
                        timestamp_ms=end_time_ms,
                    ),
                ]
            return [
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("-3"),
                    asset="USDT",
                    timestamp_ms=end_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda provider_type, channel_name, **_: StubProvider(
        str(provider_type), channel_name
    )

    for provider in ("binance", "gate"):
        response = client.post(
            "/api/channels",
            json={
                "name": f"{provider} main",
                "provider": provider,
                "enabled": True,
                "publicConfig": {},
                "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
            },
        )
        assert response.status_code == 201

    response = client.get("/api/funding-fees?month=2024-07")

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] == "2024-07"
    assert payload["received"] == "12.50000000"
    assert payload["paid"] == "5.25000000"
    assert payload["net"] == "7.25000000"
    assert payload["recordsCount"] == 3
    assert payload["channels"][0]["received"] == "12.50000000"
    assert payload["channels"][1]["paid"] == "3.00000000"


def test_funding_fees_api_rejects_invalid_month(client) -> None:
    response = client.get("/api/funding-fees?month=2024-13")

    assert response.status_code == 422
