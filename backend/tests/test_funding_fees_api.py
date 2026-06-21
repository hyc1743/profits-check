from __future__ import annotations

import asyncio
import base64
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select

from profits_check_backend.models import (
    Channel,
    DailyFundingFeeAssetSummary,
    DailyFundingFeeSummary,
    MonthlyFundingFeeSummary,
)
from profits_check_backend.providers.base import FundingFeeRecord
from profits_check_backend.services.funding_fees import date_bounds_ms, date_range


def test_funding_fees_api_summarizes_daily_records(client) -> None:
    class StubProvider:
        def __init__(self, provider: str, channel_name: str) -> None:
            self.provider = provider
            self.channel_name = channel_name

        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            assert start_time_ms == 1719763200000
            assert end_time_ms == 1719849599999
            return [
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("12.5") if self.provider == "binance" else Decimal("-3"),
                    asset="USDT",
                    timestamp_ms=1719763200000,
                ),
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("2.25") if self.provider == "binance" else Decimal("-0.5"),
                    asset="BTC",
                    timestamp_ms=1719763200000,
                ),
                FundingFeeRecord(
                    provider=self.provider,
                    channel_name=self.channel_name,
                    amount=Decimal("0.75") if self.provider == "binance" else Decimal("-1.5"),
                    asset="USDT",
                    timestamp_ms=1719763200000,
                ),
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
    assert payload["received"] == "15.50000000"
    assert payload["paid"] == "5.00000000"
    assert payload["net"] == "10.50000000"
    assert payload["recordsCount"] == 6
    assert payload["channels"][0]["received"] == "15.50000000"
    assert payload["channels"][1]["paid"] == "5.00000000"
    assert payload["details"] == [
        {
            "channelId": 1,
            "channelName": "binance main",
            "provider": "binance",
            "asset": "BTC",
            "amount": "2.25000000",
            "recordsCount": 1,
        },
        {
            "channelId": 1,
            "channelName": "binance main",
            "provider": "binance",
            "asset": "USDT",
            "amount": "13.25000000",
            "recordsCount": 2,
        },
        {
            "channelId": 2,
            "channelName": "okx main",
            "provider": "okx",
            "asset": "BTC",
            "amount": "-0.50000000",
            "recordsCount": 1,
        },
        {
            "channelId": 2,
            "channelName": "okx main",
            "provider": "okx",
            "asset": "USDT",
            "amount": "-4.50000000",
            "recordsCount": 2,
        },
    ]


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
    start_time, end_time, _, _ = date_bounds_ms("2024-07-01")
    with client.app.state.session_factory() as session:
        session.add(
            DailyFundingFeeSummary(
                date="2024-07-01",
                start_time=start_time,
                end_time=end_time,
                received=Decimal("1.5"),
                paid=Decimal("0"),
                net=Decimal("1.5"),
                records_count=1,
                status="success",
            )
        )
        session.commit()

    response = client.get("/api/funding-fees?date=2024-07-07")

    assert response.status_code == 200
    assert calls == [(1720281600000, 1720367999999)]
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


def test_funding_fees_api_reads_daily_and_recent_totals_from_database(client) -> None:
    def daily_summary(
        *, date: str, received: str, paid: str, net: str, records_count: int
    ) -> DailyFundingFeeSummary:
        start_time, end_time, _, _ = date_bounds_ms(date)
        summary = DailyFundingFeeSummary(
            date=date,
            start_time=start_time,
            end_time=end_time,
            received=Decimal(received),
            paid=Decimal(paid),
            net=Decimal(net),
            records_count=records_count,
            status="success",
        )
        summary.asset_details = [
            DailyFundingFeeAssetSummary(
                channel_id=1,
                channel_name="Binance",
                provider="binance",
                asset="USDT",
                amount=Decimal(net),
                records_count=records_count,
            )
        ]
        return summary

    with client.app.state.session_factory() as session:
        session.add_all(
            [
                daily_summary(date="2024-07-01", received="1", paid="0", net="1", records_count=1),
                daily_summary(date="2024-07-02", received="2", paid="0.5", net="1.5", records_count=2),
                daily_summary(date="2024-07-07", received="4", paid="1", net="3", records_count=3),
            ]
        )
        session.commit()

    def fail_provider_builder(**_):
        raise AssertionError("provider should not be called for cached funding fees")

    client.app.state.provider_builder = fail_provider_builder
    response = client.get("/api/funding-fees?date=2024-07-07")

    assert response.status_code == 200
    payload = response.json()
    assert payload["received"] == "4.00000000"
    assert payload["paid"] == "1.00000000"
    assert payload["net"] == "3.00000000"
    assert payload["recentSevenDays"] == {
        "startDate": "2024-07-01",
        "endDate": "2024-07-07",
        "received": "7.00000000",
        "paid": "1.50000000",
        "net": "5.50000000",
        "recordsCount": 6,
    }


def test_funding_fees_api_reads_asset_details_from_database(client) -> None:
    start_time, end_time, _, _ = date_bounds_ms("2024-07-01")
    with client.app.state.session_factory() as session:
        summary = DailyFundingFeeSummary(
            date="2024-07-01",
            start_time=start_time,
            end_time=end_time,
            received=Decimal("8"),
            paid=Decimal("3"),
            net=Decimal("5"),
            records_count=3,
            status="success",
            created_at=end_time,
            updated_at=end_time,
        )
        summary.asset_details = [
            DailyFundingFeeAssetSummary(
                channel_id=1,
                channel_name="Binance",
                provider="binance",
                asset="BTC",
                amount=Decimal("8"),
                records_count=1,
            ),
            DailyFundingFeeAssetSummary(
                channel_id=2,
                channel_name="OKX",
                provider="okx",
                asset="USDT",
                amount=Decimal("-3"),
                records_count=2,
            ),
        ]
        session.add(summary)
        session.commit()

    def fail_provider_builder(**_):
        raise AssertionError("provider should not be called for cached funding fee details")

    client.app.state.provider_builder = fail_provider_builder
    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    assert response.json()["details"] == [
        {
            "channelId": 1,
            "channelName": "Binance",
            "provider": "binance",
            "asset": "BTC",
            "amount": "8.00000000",
            "recordsCount": 1,
        },
        {
            "channelId": 2,
            "channelName": "OKX",
            "provider": "okx",
            "asset": "USDT",
            "amount": "-3.00000000",
            "recordsCount": 2,
        },
    ]


def test_funding_fees_api_refreshes_legacy_cache_without_asset_details(client) -> None:
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return [
                FundingFeeRecord(
                    provider="binance",
                    channel_name="Binance",
                    amount=Decimal("2.75"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
            ]

    client.app.state.provider_builder = lambda **_: StubProvider()
    channel_response = client.post(
        "/api/channels",
        json={
            "name": "Binance",
            "provider": "binance",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert channel_response.status_code == 201

    start_time, end_time, start_ms, end_ms = date_bounds_ms("2024-07-01")
    with client.app.state.session_factory() as session:
        session.add(
            DailyFundingFeeSummary(
                date="2024-07-01",
                start_time=start_time,
                end_time=end_time,
                received=Decimal("1"),
                paid=Decimal("0"),
                net=Decimal("1"),
                records_count=1,
                status="success",
                created_at=end_time,
                updated_at=end_time,
            )
        )
        session.commit()

    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    payload = response.json()
    assert payload["details"] == [
        {
            "channelId": 1,
            "channelName": "Binance",
            "provider": "binance",
            "asset": "USDT",
            "amount": "2.75000000",
            "recordsCount": 1,
        }
    ]
    assert calls == [(start_ms, end_ms)]


def test_funding_fees_api_refreshes_partial_cache_created_before_day_closed(client) -> None:
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
                    amount=Decimal("204.03602356"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
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

    start_time, end_time, start_ms, end_ms = date_bounds_ms("2024-07-01")
    with client.app.state.session_factory() as session:
        session.add(
            DailyFundingFeeSummary(
                date="2024-07-01",
                start_time=start_time,
                end_time=end_time,
                received=Decimal("1"),
                paid=Decimal("0"),
                net=Decimal("1"),
                records_count=1,
                status="success",
                created_at=start_time,
                updated_at=start_time,
            )
        )
        session.commit()

    response = client.get("/api/funding-fees?date=2024-07-01")

    assert response.status_code == 200
    payload = response.json()
    assert payload["net"] == "204.03602356"
    assert payload["recordsCount"] == 1
    assert calls == [(start_ms, end_ms)]

    with client.app.state.session_factory() as session:
        cached = session.scalar(
            select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == "2024-07-01")
        )
        assert cached is not None
        assert cached.net == Decimal("204.03602356")


def test_funding_fees_api_collects_daily_records_while_month_backfill_runs(client) -> None:
    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            return [
                FundingFeeRecord(
                    provider="binance",
                    channel_name="binance main",
                    amount=Decimal("1.25"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
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

    assert client.app.state.current_month_funding_fee_lock.acquire(blocking=False)
    try:
        response = client.get("/api/funding-fees?date=2024-07-01")
    finally:
        client.app.state.current_month_funding_fee_lock.release()

    assert response.status_code == 200
    assert response.json()["net"] == "1.25000000"


def test_funding_fees_api_waits_for_in_flight_same_day_collection(client) -> None:
    first_collection_started = threading.Event()
    calls: list[tuple[int, int]] = []

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            first_collection_started.set()
            await asyncio.sleep(0.05)
            return [
                FundingFeeRecord(
                    provider="binance",
                    channel_name="binance main",
                    amount=Decimal("2.50"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
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

    responses = []
    first_request = threading.Thread(
        target=lambda: responses.append(client.get("/api/funding-fees?date=2024-07-01"))
    )
    first_request.start()
    assert first_collection_started.wait(timeout=2)

    second_response = client.get("/api/funding-fees?date=2024-07-01")
    first_request.join(timeout=2)

    assert len(responses) == 1
    assert responses[0].status_code == 200
    assert second_response.status_code == 200
    assert second_response.json()["net"] == "2.50000000"
    assert len(calls) == 1


def test_funding_fees_api_collects_daily_channels_sequentially(client) -> None:
    active_channels = 0
    max_active_channels = 0
    call_order: list[str] = []

    class StubProvider:
        def __init__(self, channel_name: str) -> None:
            self.channel_name = channel_name

        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            nonlocal active_channels, max_active_channels
            active_channels += 1
            max_active_channels = max(max_active_channels, active_channels)
            call_order.append(self.channel_name)
            await asyncio.sleep(0)
            active_channels -= 1
            return []

    client.app.state.provider_builder = lambda channel_name, **_: StubProvider(channel_name)
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
    assert max_active_channels == 1
    assert call_order == ["binance main", "okx main"]


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


def test_previous_monthly_funding_fees_api_starts_missing_summary_in_background(client) -> None:
    from profits_check_backend.services.funding_fees import previous_month_period

    collection_started = threading.Event()
    release_collection = threading.Event()

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            collection_started.set()
            await asyncio.to_thread(release_collection.wait, 2)
            return []

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "Binance",
            "provider": "binance",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201
    month, start_date, end_date = previous_month_period()

    response = client.get("/api/funding-fees/monthly/previous")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["month"] == month
    assert response.json()["startDate"] == start_date
    assert response.json()["endDate"] == end_date
    assert collection_started.wait(timeout=2)
    release_collection.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if client.app.state.monthly_funding_fee_lock.acquire(blocking=False):
            client.app.state.monthly_funding_fee_lock.release()
            break
        time.sleep(0.02)


def test_current_monthly_funding_fees_collects_missing_days_once(client) -> None:
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
                    amount=Decimal("1"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
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

    response = client.get("/api/funding-fees/monthly/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["month"] == datetime.now(UTC).astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m")
    assert payload["status"] == "running"
    assert payload["cachedDays"] < payload["expectedDays"]
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if client.app.state.current_month_funding_fee_lock.acquire(blocking=False):
            client.app.state.current_month_funding_fee_lock.release()
            break
        time.sleep(0.02)
    assert len(calls) == payload["expectedDays"]

    response = client.get("/api/funding-fees/monthly/current")

    assert response.status_code == 200
    assert response.json()["cachedDays"] == response.json()["expectedDays"]
    assert len(calls) == payload["expectedDays"]


def test_current_monthly_funding_fees_starts_missing_days_in_background(client, monkeypatch) -> None:
    import profits_check_backend.main as main_module

    collection_started = threading.Event()
    release_collection = threading.Event()

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            collection_started.set()
            await asyncio.to_thread(release_collection.wait, 2)
            return []

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "Binance",
            "provider": "binance",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    now = datetime(2024, 7, 2, 2, tzinfo=UTC)

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(main_module, "datetime", FixedDateTime)
    response = client.get("/api/funding-fees/monthly/current")

    assert response.status_code == 200
    assert response.json()["status"] == "running"
    assert response.json()["cachedDays"] < response.json()["expectedDays"]
    assert collection_started.wait(timeout=2)
    release_collection.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        if client.app.state.current_month_funding_fee_lock.acquire(blocking=False):
            client.app.state.current_month_funding_fee_lock.release()
            break
        time.sleep(0.02)



def test_current_monthly_funding_fees_uses_legacy_daily_totals_without_asset_details(
    client,
    monkeypatch,
) -> None:
    from profits_check_backend.services.funding_fees import current_month_completed_period

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            raise AssertionError("current month totals should not refresh legacy detail caches")

    client.app.state.provider_builder = lambda **_: StubProvider()
    response = client.post(
        "/api/channels",
        json={
            "name": "Binance",
            "provider": "binance",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert response.status_code == 201

    now = datetime(2024, 7, 2, 2, tzinfo=UTC)
    _, start_date, _ = current_month_completed_period(now)
    start_time, end_time, _, _ = date_bounds_ms(start_date)
    with client.app.state.session_factory() as session:
        session.add(
            DailyFundingFeeSummary(
                date=start_date,
                start_time=start_time,
                end_time=end_time,
                received=Decimal("3"),
                paid=Decimal("1"),
                net=Decimal("2"),
                records_count=2,
                status="success",
                created_at=end_time,
                updated_at=end_time,
            )
        )
        session.commit()

    import profits_check_backend.main as main_module
    import profits_check_backend.services.funding_fees as funding_service

    class FixedDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return now.replace(tzinfo=None)
            return now.astimezone(tz)

    monkeypatch.setattr(main_module, "datetime", FixedDateTime)
    monkeypatch.setattr(funding_service, "datetime", FixedDateTime)
    response = client.get("/api/funding-fees/monthly/current")

    assert response.status_code == 200
    payload = response.json()
    assert payload["received"] == "3.00000000"
    assert payload["paid"] == "1.00000000"
    assert payload["net"] == "2.00000000"
    assert payload["cachedDays"] == 1


def test_current_monthly_funding_fees_waits_for_in_flight_daily_collection(client) -> None:
    from profits_check_backend.services.funding_fees import current_month_completed_period

    now = datetime.now(UTC)
    _, start_date, end_date = current_month_completed_period(now)
    if end_date is None:
        return
    _, _, start_time_ms, _ = date_bounds_ms(start_date)
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
                    amount=Decimal("1"),
                    asset="USDT",
                    timestamp_ms=start_time_ms,
                )
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

    held_lock = client.app.state.daily_funding_fee_date_locks.acquire(
        start_date,
        blocking=False,
    )
    assert held_lock is not None
    release_timer = threading.Timer(0.05, held_lock.release)
    release_timer.start()
    try:
        response = client.get("/api/funding-fees/monthly/current")
        assert response.status_code == 200
        assert response.json()["status"] == "running"
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline and not calls:
            time.sleep(0.02)
    finally:
        release_timer.cancel()
        if held_lock.locked():
            held_lock.release()

    assert calls[0][0] == start_time_ms


def test_app_startup_collects_previous_month_and_current_month_missing_days_once(
    tmp_path, monkeypatch
) -> None:
    from fastapi.testclient import TestClient

    from profits_check_backend.config import AppSettings
    from profits_check_backend.db import build_session_factory, init_database
    from profits_check_backend.main import create_app
    from profits_check_backend.security import SecretCipher
    from profits_check_backend.services.channels import create_channel
    from profits_check_backend.services.funding_fees import (
        current_month_completed_period,
        previous_month_period,
    )

    settings = AppSettings(
        app_encryption_key=base64.urlsafe_b64encode(
            b"0123456789ABCDEF0123456789ABCDEF"
        ).decode(),
        bootstrap_password="correct horse battery staple",
        database_url=f"sqlite:///{tmp_path / 'startup.db'}",
    )
    session_factory = build_session_factory(settings)
    init_database(session_factory)
    cipher = SecretCipher.from_settings(settings)
    with session_factory() as session:
        create_channel(
            session,
            name="binance main",
            provider="binance",
            kind="cex",
            enabled=True,
            public_config={},
            secret_config={"apiKey": "key", "apiSecret": "secret"},
            cipher=cipher,
        )
        session.commit()

    _, current_start_date, current_end_date = current_month_completed_period()
    current_expected_days = (
        len(date_range(current_start_date, current_end_date))
        if current_end_date is not None
        else 0
    )
    current_start_time, current_end_time, current_start_ms, current_end_ms = date_bounds_ms(
        current_start_date
    )
    with session_factory() as session:
        if current_expected_days:
            session.add(
                DailyFundingFeeSummary(
                    date=current_start_date,
                    start_time=current_start_time,
                    end_time=current_end_time,
                    received=Decimal("0"),
                    paid=Decimal("0"),
                    net=Decimal("0"),
                    records_count=0,
                    status="success",
                )
            )
            session.commit()

    calls: list[tuple[int, int]] = []
    previous_month, _, _ = previous_month_period()

    class StubProvider:
        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            calls.append((start_time_ms, end_time_ms))
            return []

    monkeypatch.setattr(
        "profits_check_backend.main.build_provider",
        lambda **_: StubProvider(),
    )

    def wait_for_previous_month_summary() -> MonthlyFundingFeeSummary | None:
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with session_factory() as session:
                summary = session.scalar(
                    select(MonthlyFundingFeeSummary).where(
                        MonthlyFundingFeeSummary.month == previous_month
                    )
                )
                if summary is not None:
                    return summary
            time.sleep(0.02)
        return None

    def wait_for_current_month_days() -> int:
        if current_end_date is None:
            return 0
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with session_factory() as session:
                count = len(
                    list(
                        session.scalars(
                            select(DailyFundingFeeSummary)
                            .where(DailyFundingFeeSummary.date >= current_start_date)
                            .where(DailyFundingFeeSummary.date <= current_end_date)
                        )
                    )
                )
                if count == current_expected_days:
                    return count
            time.sleep(0.02)
        return 0

    with TestClient(create_app(settings)):
        summary = wait_for_previous_month_summary()
        cached_days = wait_for_current_month_days()

    assert summary is not None
    first_startup_call_count = len(calls)
    assert first_startup_call_count > 0
    assert cached_days == current_expected_days
    if current_expected_days:
        assert (current_start_ms, current_end_ms) not in calls

    with TestClient(create_app(settings)):
        time.sleep(0.05)

    assert len(calls) == first_startup_call_count


def test_previous_monthly_funding_fee_summary_collects_channels_sequentially(client) -> None:
    from profits_check_backend.services.funding_fees import (
        ensure_previous_month_funding_fee_summary,
    )

    active_channels = 0
    max_active_channels = 0
    call_order: list[str] = []

    class StubProvider:
        def __init__(self, channel_name: str) -> None:
            self.channel_name = channel_name

        async def collect_funding_fee_records(
            self, start_time_ms: int, end_time_ms: int
        ) -> list[FundingFeeRecord]:
            nonlocal active_channels, max_active_channels
            active_channels += 1
            max_active_channels = max(max_active_channels, active_channels)
            call_order.append(self.channel_name)
            await asyncio.sleep(0)
            active_channels -= 1
            return []

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

    with client.app.state.session_factory() as session:
        channels = list(
            session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id))
        )
        ensure_previous_month_funding_fee_summary(
            session=session,
            channels=channels,
            cipher=client.app.state.cipher,
            provider_builder=lambda channel_name, **_: StubProvider(channel_name),
            now_factory=lambda: datetime(2026, 6, 9, 8, tzinfo=UTC),
        )

    assert max_active_channels == 1
    assert call_order == ["binance main"] * 5 + ["okx main"] * 5


def test_daily_funding_fee_increment_job_is_scheduled(client) -> None:
    jobs = {job.id: str(job.trigger) for job in client.app.state.scheduler.get_jobs()}

    assert "daily-funding-fee-increment" in jobs
    assert "hour='8'" in jobs["daily-funding-fee-increment"]
    assert "minute='5'" in jobs["daily-funding-fee-increment"]


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
    assert calls == [(1719763200000, 1719849599999)]
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
    assert calls == [(1709136000000, 1709222399999)]
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
    assert calls == [(1719763200000, 1719849599999)]
