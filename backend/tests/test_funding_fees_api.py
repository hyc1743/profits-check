from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select

from profits_check_backend.models import Channel, MonthlyFundingFeeSummary
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
    assert payload["recentSevenDays"] == {
        "startDate": "2024-07-01",
        "endDate": "2024-07-07",
        "received": "1.50000000",
        "paid": "0.75000000",
        "net": "0.75000000",
        "recordsCount": 2,
    }


def test_monthly_funding_fee_summary_collects_previous_month_in_seven_day_segments(
    client,
) -> None:
    from profits_check_backend.services.funding_fees import (
        ensure_previous_month_funding_fee_summary,
    )

    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            amount = Decimal("2") if len(calls) % 2 else Decimal("-0.5")
            return [
                FundingFeeRecord(
                    provider="binance",
                    channel_name="binance main",
                    amount=amount,
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

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

    with client.app.state.session_factory() as session:
        channels = list(session.scalars(select(Channel).where(Channel.enabled.is_(True))))
        summary = ensure_previous_month_funding_fee_summary(
            session=session,
            channels=channels,
            cipher=client.app.state.cipher,
            provider_builder=lambda **_: StubProvider(),
            now_factory=lambda: datetime(2026, 6, 9, 8, tzinfo=UTC),
        )
        summary_id = summary.id
        summary_values = {
            "month": summary.month,
            "start_date": summary.start_date,
            "end_date": summary.end_date,
            "received": summary.received,
            "paid": summary.paid,
            "net": summary.net,
            "records_count": summary.records_count,
        }
        session.commit()

    assert summary_values == {
        "month": "2026-05",
        "start_date": "2026-05-01",
        "end_date": "2026-05-31",
        "received": Decimal("6.00000000"),
        "paid": Decimal("1.00000000"),
        "net": Decimal("5.00000000"),
        "records_count": 5,
    }
    assert len(calls) == 5
    assert all(end - start <= (7 * 24 * 60 * 60 * 1000) - 1 for start, end in calls)

    with client.app.state.session_factory() as session:
        channels = list(session.scalars(select(Channel).where(Channel.enabled.is_(True))))
        cached = ensure_previous_month_funding_fee_summary(
            session=session,
            channels=channels,
            cipher=client.app.state.cipher,
            provider_builder=lambda **_: StubProvider(),
            now_factory=lambda: datetime(2026, 6, 9, 8, tzinfo=UTC),
        )

    assert cached.id == summary_id
    assert len(calls) == 5

    with client.app.state.session_factory() as session:
        persisted = session.scalar(
            select(MonthlyFundingFeeSummary).where(
                MonthlyFundingFeeSummary.month == "2026-05"
            )
        )
        assert persisted is not None
        assert persisted.net == Decimal("5.00000000")


def test_previous_monthly_funding_fees_api_reads_persisted_summary(client) -> None:
    from profits_check_backend.services.funding_fees import previous_month_period

    month, start_date, end_date = previous_month_period()
    with client.app.state.session_factory() as session:
        session.add(
            MonthlyFundingFeeSummary(
                month=month,
                start_date=start_date,
                end_date=end_date,
                received=Decimal("11.25"),
                paid=Decimal("2.00"),
                net=Decimal("9.25"),
                records_count=4,
                status="success",
            )
        )
        session.commit()

    response = client.get("/api/funding-fees/monthly/previous")

    assert response.status_code == 200
    assert response.json() == {
        "month": month,
        "startDate": start_date,
        "endDate": end_date,
        "received": "11.25000000",
        "paid": "2.00000000",
        "net": "9.25000000",
        "recordsCount": 4,
        "status": "success",
        "error": None,
    }


def test_previous_monthly_funding_fees_api_reports_running_summary(client) -> None:
    from profits_check_backend.services.funding_fees import previous_month_period

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
    month, start_date, end_date = previous_month_period()
    assert client.app.state.monthly_funding_fee_lock.acquire(blocking=False)
    try:
        response = client.get("/api/funding-fees/monthly/previous")
    finally:
        client.app.state.monthly_funding_fee_lock.release()

    assert response.status_code == 200
    assert response.json() == {
        "month": month,
        "startDate": start_date,
        "endDate": end_date,
        "received": "0.00000000",
        "paid": "0.00000000",
        "net": "0.00000000",
        "recordsCount": 0,
        "status": "running",
        "error": None,
    }


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
