from __future__ import annotations

from decimal import Decimal

from profits_check_backend.providers.base import FundingFeeRecord


def test_funding_fees_api_summarizes_daily_records(client) -> None:
    class StubProvider:
        def __init__(self, provider: str, channel_name: str) -> None:
            self.provider = provider
            self.channel_name = channel_name

        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            assert start_time_ms == 1719244800000
            assert end_time_ms == 1719849599999
            return [
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("12.5") if self.provider == "binance" else Decimal("-3"),
                    asset="USDT",
                    timestamp_ms=1719763200000,
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

    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    payload = response.json()
    assert payload["date"] == "2024-07-01"
    assert payload["received"] == "12.50000000"
    assert payload["paid"] == "3.00000000"
    assert payload["net"] == "9.50000000"
    assert payload["recordsCount"] == 2
    assert payload["channels"][0]["received"] == "12.50000000"
    assert payload["channels"][1]["paid"] == "3.00000000"


def test_funding_fees_api_includes_recent_seven_day_totals(client) -> None:
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return [
                FundingFeeRecord(
                    provider="binance",
                    channel_name="binance main",
                    amount=Decimal("1.5"),
                    asset="USDT",
                    timestamp_ms=1719763200000,
                ),
                FundingFeeRecord(
                    provider="binance",
                    channel_name="binance main",
                    amount=Decimal("-0.75"),
                    asset="USDT",
                    timestamp_ms=1720281600000,
                ),
            ]

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

    response = client.get("/api/funding-fees?date=2024-07-07")

    assert response.status_code == 200
    assert calls == [(1719763200000, 1720367999999)]
    payload = response.json()
    assert payload["received"] == "0.00000000"
    assert payload["paid"] == "0.75000000"
    assert payload["net"] == "-0.75000000"
    assert [item["date"] for item in payload["recentDays"]] == [
        "2024-07-01",
        "2024-07-02",
        "2024-07-03",
        "2024-07-04",
        "2024-07-05",
        "2024-07-06",
        "2024-07-07",
    ]
    assert payload["recentDays"][0]["net"] == "1.50000000"
    assert payload["recentDays"][6]["paid"] == "0.75000000"


def test_funding_fees_api_rejects_invalid_date(client) -> None:
    response = client.get("/api/funding-fees?date=2024-02-30")

    assert response.status_code == 422


def test_funding_fees_api_queries_gate_recent_window_once(client) -> None:
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
                    timestamp_ms=1719763200000,
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

    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    assert calls == [(1719244800000, 1719849599999)]
    assert response.json()["received"] == "1.00000000"


def test_funding_fees_api_queries_bybit_recent_window_once(client) -> None:
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
                    timestamp_ms=1709136000000,
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

    response = client.get("/api/funding-fees?date=2024-02-29")

    assert response.status_code == 200
    assert calls == [(1708617600000, 1709222399999)]
    assert response.json()["paid"] == "0.50000000"


def test_funding_fees_api_queries_other_providers_by_date(client) -> None:
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

    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    assert calls == [(1719244800000, 1719849599999)]
