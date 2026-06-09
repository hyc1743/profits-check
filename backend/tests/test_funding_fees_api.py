from __future__ import annotations

import asyncio
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
            return [
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("12.5") if self.provider == "binance" else Decimal("-3"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda provider_type, channel_name, **_: StubProvider(
        str(provider_type), channel_name
    )

    for provider in ("binance", "okx"):
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
    assert payload["paid"] == "3.00000000"
    assert payload["net"] == "9.50000000"
    assert payload["recordsCount"] == 2
    assert payload["channels"][0]["received"] == "12.50000000"
    assert payload["channels"][1]["paid"] == "3.00000000"


def test_funding_fees_api_rejects_invalid_month(client) -> None:
    response = client.get("/api/funding-fees?month=2024-13")

    assert response.status_code == 422


def test_funding_fees_api_splits_gate_month_into_seven_day_windows(client) -> None:
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return [
                FundingFeeRecord(
                    provider="gate",
                    channel_name="gate main",
                    amount=Decimal("1"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "gate main",
            "provider": "gate",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    response = client.get("/api/funding-fees?month=2024-07")

    assert response.status_code == 200
    assert calls == [
        (1719763200000, 1720367999999),
        (1720368000000, 1720972799999),
        (1720972800000, 1721577599999),
        (1721577600000, 1722182399999),
        (1722182400000, 1722441599999),
    ]
    assert response.json()["received"] == "5.00000000"


def test_funding_fees_api_splits_bybit_month_into_seven_day_windows(client) -> None:
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return [
                FundingFeeRecord(
                    provider="bybit",
                    channel_name="bybit main",
                    amount=Decimal("-0.5"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "bybit main",
            "provider": "bybit",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    response = client.get("/api/funding-fees?month=2024-02")

    assert response.status_code == 200
    assert calls == [
        (1706716800000, 1707321599999),
        (1707321600000, 1707926399999),
        (1707926400000, 1708531199999),
        (1708531200000, 1709135999999),
        (1709136000000, 1709222399999),
    ]
    assert response.json()["paid"] == "2.50000000"


def test_funding_fees_api_queries_split_windows_concurrently(client) -> None:
    in_flight = 0
    max_in_flight = 0

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            nonlocal in_flight, max_in_flight
            in_flight += 1
            max_in_flight = max(max_in_flight, in_flight)
            await asyncio.sleep(0.01)
            in_flight -= 1
            return [
                FundingFeeRecord(
                    provider="gate",
                    channel_name="gate main",
                    amount=Decimal("1"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "gate main",
            "provider": "gate",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    response = client.get("/api/funding-fees?month=2024-07")

    assert response.status_code == 200
    assert max_in_flight > 1


def test_funding_fees_api_keeps_other_providers_as_single_month_query(client) -> None:
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return []

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "binance main",
            "provider": "binance",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    response = client.get("/api/funding-fees?month=2024-07")

    assert response.status_code == 200
    assert calls == [(1719763200000, 1722441599999)]
