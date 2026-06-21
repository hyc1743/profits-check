from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from datetime import date as date_type
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from profits_check_backend.models import (
    Channel,
    DailyFundingFeeAssetSummary,
    DailyFundingFeeChannelSummary,
    DailyFundingFeeSummary,
    MonthlyFundingFeeSummary,
)
from profits_check_backend.providers.base import FundingFeeRecord, Provider
from profits_check_backend.security import SecretCipher
from profits_check_backend.services.channels import decode_public_config, decode_secret_config

DATE_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATE_TIMEZONE = ZoneInfo("Asia/Shanghai")
logger = logging.getLogger("profits_check.funding_fees")


@dataclass(slots=True)
class FundingFeeChannelSummary:
    channel_id: int
    channel_name: str
    provider: str
    received: Decimal = Decimal("0")
    paid: Decimal = Decimal("0")
    net: Decimal = Decimal("0")
    records_count: int = 0
    status: str = "success"
    error: str | None = None


@dataclass(slots=True)
class FundingFeeAssetDetail:
    channel_id: int
    channel_name: str
    provider: str
    asset: str
    amount: Decimal
    records_count: int


@dataclass(slots=True)
class FundingFeeChannelCollection:
    summary: FundingFeeChannelSummary
    records: list[FundingFeeRecord]


@dataclass(slots=True)
class FundingFeePeriodSummary:
    start_date: str
    end_date: str
    received: Decimal
    paid: Decimal
    net: Decimal
    records_count: int


@dataclass(slots=True)
class FundingFeeSummary:
    date: str
    start_time: datetime
    end_time: datetime
    received: Decimal
    paid: Decimal
    net: Decimal
    records_count: int
    channels: list[FundingFeeChannelSummary]
    details: list[FundingFeeAssetDetail]
    recent_seven_days: FundingFeePeriodSummary


@dataclass(slots=True)
class CurrentMonthFundingFeeSummary:
    month: str
    start_date: str
    end_date: str
    received: Decimal
    paid: Decimal
    net: Decimal
    records_count: int
    cached_days: int
    expected_days: int
    status: str


@dataclass(slots=True)
class MonthlyFundingFeeCollection:
    records: list[FundingFeeRecord]
    error: str | None = None


def date_bounds_ms(date: str) -> tuple[datetime, datetime, int, int]:
    if not DATE_PATTERN.match(date):
        raise ValueError("date must use YYYY-MM-DD")
    year, month_number, day = (int(part) for part in date.split("-"))
    try:
        start_local = datetime(year, month_number, day, tzinfo=DATE_TIMEZONE)
    except ValueError as exc:
        raise ValueError("date must use YYYY-MM-DD") from exc
    end_local = start_local + timedelta(days=1)
    start_ms = int(start_local.astimezone(UTC).timestamp() * 1000)
    end_ms = int(end_local.astimezone(UTC).timestamp() * 1000) - 1
    return start_local, end_local, start_ms, end_ms


def previous_month_period(now: datetime | None = None) -> tuple[str, str, str]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current_local = current.astimezone(DATE_TIMEZONE)
    current_month_start = date_type(current_local.year, current_local.month, 1)
    previous_month_end = current_month_start - timedelta(days=1)
    previous_month_start = date_type(previous_month_end.year, previous_month_end.month, 1)
    month = f"{previous_month_start.year:04d}-{previous_month_start.month:02d}"
    return month, previous_month_start.isoformat(), previous_month_end.isoformat()


def current_month_completed_period(now: datetime | None = None) -> tuple[str, str, str | None]:
    current = now or datetime.now(UTC)
    if current.tzinfo is None:
        current = current.replace(tzinfo=UTC)
    current_local = current.astimezone(DATE_TIMEZONE)
    month_start = date_type(current_local.year, current_local.month, 1)
    end = current_local.date() - timedelta(days=1)
    month = f"{month_start.year:04d}-{month_start.month:02d}"
    if end < month_start:
        return month, month_start.isoformat(), None
    return month, month_start.isoformat(), end.isoformat()


def date_range(start_date: str, end_date: str) -> list[str]:
    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    days: list[str] = []
    current = start
    while current <= end:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


def iter_date_segments(
    start_date: str, end_date: str, *, max_days: int = 7
) -> list[tuple[str, str, int, int]]:
    start = date_type.fromisoformat(start_date)
    end = date_type.fromisoformat(end_date)
    segments: list[tuple[str, str, int, int]] = []
    current = start
    while current <= end:
        segment_end = min(current + timedelta(days=max_days - 1), end)
        _, _, start_ms, _ = date_bounds_ms(current.isoformat())
        _, _, _, end_ms = date_bounds_ms(segment_end.isoformat())
        segments.append((current.isoformat(), segment_end.isoformat(), start_ms, end_ms))
        current = segment_end + timedelta(days=1)
    return segments


async def collect_daily_funding_fee_summary(
    *,
    date: str,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
) -> FundingFeeSummary:
    started_at = time.perf_counter()
    selected_start_time, selected_end_time, selected_start_ms, selected_end_ms = date_bounds_ms(
        date
    )
    start_ms = selected_start_ms
    end_ms = selected_end_ms
    logger.info(
        "funding_fees.start date=%s channels=%s start_ms=%s end_ms=%s",
        date,
        len(channels),
        start_ms,
        end_ms,
    )

    async def collect_channel(channel: Channel) -> FundingFeeChannelCollection:
        if not channel.enabled:
            logger.info(
                "funding_fees.channel_skipped channel_id=%s provider=%s name=%s status=disabled",
                channel.id,
                channel.provider,
                channel.name,
            )
            return FundingFeeChannelCollection(
                summary=FundingFeeChannelSummary(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    provider=channel.provider,
                    status="disabled",
                ),
                records=[],
            )
        try:
            provider: Provider = provider_builder(
                provider_type=channel.provider,
                channel_name=channel.name,
                config=decode_public_config(channel),
                secrets=decode_secret_config(channel, cipher),
            )
            channel_started_at = time.perf_counter()
            logger.info(
                "funding_fees.channel_start channel_id=%s provider=%s name=%s "
                "start_ms=%s end_ms=%s",
                channel.id,
                channel.provider,
                channel.name,
                start_ms,
                end_ms,
            )
            records = await provider.collect_funding_fee_records(start_ms, end_ms)
            duration_ms = int((time.perf_counter() - channel_started_at) * 1000)
            logger.info(
                "funding_fees.channel_success channel_id=%s provider=%s name=%s "
                "records=%s duration_ms=%s",
                channel.id,
                channel.provider,
                channel.name,
                len(records),
                duration_ms,
            )
            selected_records = [
                record
                for record in records
                if selected_start_ms <= record.timestamp_ms <= selected_end_ms
            ]
            return FundingFeeChannelCollection(
                summary=summarize_channel_records(channel, selected_records),
                records=selected_records,
            )
        except Exception as exc:
            logger.error(
                "funding_fees.channel_failed channel_id=%s provider=%s name=%s error=%s",
                channel.id,
                channel.provider,
                channel.name,
                exc,
            )
            return FundingFeeChannelCollection(
                summary=FundingFeeChannelSummary(
                    channel_id=channel.id,
                    channel_name=channel.name,
                    provider=channel.provider,
                    status="failed",
                    error=str(exc),
                ),
                records=[],
            )

    channel_collections: list[FundingFeeChannelCollection] = []
    for channel in channels:
        channel_collections.append(await collect_channel(channel))
    channel_summaries = [item.summary for item in channel_collections]
    received = sum((item.received for item in channel_summaries), Decimal("0"))
    paid = sum((item.paid for item in channel_summaries), Decimal("0"))
    net = sum((item.net for item in channel_summaries), Decimal("0"))
    records_count = sum(item.records_count for item in channel_summaries)
    details = summarize_asset_details(channel_collections)
    recent_seven_days = FundingFeePeriodSummary(
        start_date=date,
        end_date=date,
        received=received,
        paid=paid,
        net=net,
        records_count=records_count,
    )
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    failed_count = sum(1 for item in channel_summaries if item.status == "failed")
    logger.info(
        "funding_fees.done date=%s channels=%s failed=%s records=%s duration_ms=%s",
        date,
        len(channel_summaries),
        failed_count,
        records_count,
        duration_ms,
    )
    return FundingFeeSummary(
        date=date,
        start_time=selected_start_time,
        end_time=selected_end_time,
        received=received,
        paid=paid,
        net=net,
        records_count=records_count,
        channels=channel_summaries,
        details=details,
        recent_seven_days=recent_seven_days,
    )


def funding_fee_summary_from_daily_model(
    summary: DailyFundingFeeSummary,
    *,
    recent_seven_days: FundingFeePeriodSummary | None = None,
) -> FundingFeeSummary:
    daily_recent = recent_seven_days or FundingFeePeriodSummary(
        start_date=summary.date,
        end_date=summary.date,
        received=summary.received,
        paid=summary.paid,
        net=summary.net,
        records_count=summary.records_count,
    )
    return FundingFeeSummary(
        date=summary.date,
        start_time=summary.start_time,
        end_time=summary.end_time,
        received=summary.received,
        paid=summary.paid,
        net=summary.net,
        records_count=summary.records_count,
        channels=[
            FundingFeeChannelSummary(
                channel_id=item.channel_id,
                channel_name=item.channel_name,
                provider=item.provider,
                received=item.received,
                paid=item.paid,
                net=item.net,
                records_count=item.records_count,
                status=item.status,
                error=item.error,
            )
            for item in summary.channels
        ],
        details=[
            FundingFeeAssetDetail(
                channel_id=item.channel_id,
                channel_name=item.channel_name,
                provider=item.provider,
                asset=item.asset,
                amount=item.amount,
                records_count=item.records_count,
            )
            for item in sorted(summary.asset_details, key=lambda detail: (detail.channel_id, detail.asset))
        ],
        recent_seven_days=daily_recent,
    )


def save_daily_funding_fee_summary(
    session: Session,
    summary: FundingFeeSummary,
) -> DailyFundingFeeSummary:
    existing = session.scalar(
        select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == summary.date)
    )
    if existing is not None:
        return existing
    failed_errors = [item.error for item in summary.channels if item.error]
    model = DailyFundingFeeSummary(
        date=summary.date,
        start_time=summary.start_time,
        end_time=summary.end_time,
        received=_quantize_decimal(summary.received),
        paid=_quantize_decimal(summary.paid),
        net=_quantize_decimal(summary.net),
        records_count=summary.records_count,
        status="failed" if failed_errors else "success",
        error="; ".join(failed_errors) if failed_errors else None,
    )
    model.channels = [
        DailyFundingFeeChannelSummary(
            channel_id=item.channel_id,
            channel_name=item.channel_name,
            provider=item.provider,
            received=_quantize_decimal(item.received),
            paid=_quantize_decimal(item.paid),
            net=_quantize_decimal(item.net),
            records_count=item.records_count,
            status=item.status,
            error=item.error,
        )
        for item in summary.channels
    ]
    model.asset_details = [
        DailyFundingFeeAssetSummary(
            channel_id=item.channel_id,
            channel_name=item.channel_name,
            provider=item.provider,
            asset=item.asset,
            amount=_quantize_decimal(item.amount),
            records_count=item.records_count,
        )
        for item in summary.details
    ]
    session.add(model)
    session.flush()
    return model


def get_daily_funding_fee_summary(
    session: Session,
    date: str,
) -> DailyFundingFeeSummary | None:
    if not DATE_PATTERN.match(date):
        raise ValueError("date must use YYYY-MM-DD")
    return session.scalar(select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == date))


def is_daily_funding_fee_summary_complete(summary: DailyFundingFeeSummary) -> bool:
    created_at = summary.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    else:
        created_at = created_at.astimezone(UTC)

    end_time = summary.end_time
    if end_time.tzinfo is None:
        end_time = end_time.replace(tzinfo=DATE_TIMEZONE)
    return created_at >= end_time.astimezone(UTC)


def summarize_daily_models(
    summaries: list[DailyFundingFeeSummary], *, start_date: str, end_date: str
) -> FundingFeePeriodSummary:
    return FundingFeePeriodSummary(
        start_date=start_date,
        end_date=end_date,
        received=sum((item.received for item in summaries), Decimal("0")),
        paid=sum((item.paid for item in summaries), Decimal("0")),
        net=sum((item.net for item in summaries), Decimal("0")),
        records_count=sum(item.records_count for item in summaries),
    )


def recent_seven_day_summary_from_database(
    session: Session,
    date: str,
) -> FundingFeePeriodSummary:
    selected_start_time, _, _, _ = date_bounds_ms(date)
    start_date = (selected_start_time - timedelta(days=6)).date().isoformat()
    summaries = list(
        session.scalars(
            select(DailyFundingFeeSummary)
            .where(DailyFundingFeeSummary.date >= start_date)
            .where(DailyFundingFeeSummary.date <= date)
            .order_by(DailyFundingFeeSummary.date)
        )
    )
    return summarize_daily_models(summaries, start_date=start_date, end_date=date)


def ensure_daily_funding_fee_summary(
    *,
    session: Session,
    date: str,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
) -> DailyFundingFeeSummary:
    existing = get_daily_funding_fee_summary(session, date)
    if existing is not None and is_daily_funding_fee_summary_complete(existing):
        return existing
    if existing is not None:
        session.delete(existing)
        session.flush()
    summary = asyncio.run(
        collect_daily_funding_fee_summary(
            date=date,
            channels=channels,
            cipher=cipher,
            provider_builder=provider_builder,
        )
    )
    return save_daily_funding_fee_summary(session, summary)


def ensure_daily_funding_fee_summaries(
    *,
    session: Session,
    start_date: str,
    end_date: str,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
) -> list[DailyFundingFeeSummary]:
    summaries: list[DailyFundingFeeSummary] = []
    for date in date_range(start_date, end_date):
        summaries.append(
            ensure_daily_funding_fee_summary(
                session=session,
                date=date,
                channels=channels,
                cipher=cipher,
                provider_builder=provider_builder,
            )
        )
    return summaries


def current_month_funding_fee_summary_from_database(
    session: Session,
    *,
    now_factory=None,
) -> CurrentMonthFundingFeeSummary:
    now = now_factory() if now_factory else datetime.now(UTC)
    month, start_date, end_date = current_month_completed_period(now)
    if end_date is None:
        return CurrentMonthFundingFeeSummary(
            month=month,
            start_date=start_date,
            end_date=start_date,
            received=Decimal("0"),
            paid=Decimal("0"),
            net=Decimal("0"),
            records_count=0,
            cached_days=0,
            expected_days=0,
            status="success",
        )
    summaries = list(
        session.scalars(
            select(DailyFundingFeeSummary)
            .where(DailyFundingFeeSummary.date >= start_date)
            .where(DailyFundingFeeSummary.date <= end_date)
            .order_by(DailyFundingFeeSummary.date)
        )
    )
    period = summarize_daily_models(summaries, start_date=start_date, end_date=end_date)
    expected_days = len(date_range(start_date, end_date))
    failed = any(item.status == "failed" for item in summaries)
    return CurrentMonthFundingFeeSummary(
        month=month,
        start_date=start_date,
        end_date=end_date,
        received=period.received,
        paid=period.paid,
        net=period.net,
        records_count=period.records_count,
        cached_days=len(summaries),
        expected_days=expected_days,
        status="failed" if failed else "success",
    )


def ensure_current_month_funding_fee_summaries(
    *,
    session: Session,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
    now_factory=None,
) -> CurrentMonthFundingFeeSummary:
    now = now_factory() if now_factory else datetime.now(UTC)
    _, start_date, end_date = current_month_completed_period(now)
    if end_date is not None:
        ensure_daily_funding_fee_summaries(
            session=session,
            start_date=start_date,
            end_date=end_date,
            channels=channels,
            cipher=cipher,
            provider_builder=provider_builder,
        )
    return current_month_funding_fee_summary_from_database(session, now_factory=lambda: now)


async def collect_monthly_funding_fee_records(
    *,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
    start_date: str,
    end_date: str,
) -> MonthlyFundingFeeCollection:
    segments = iter_date_segments(start_date, end_date, max_days=7)

    async def collect_channel(channel: Channel) -> MonthlyFundingFeeCollection:
        if not channel.enabled:
            return MonthlyFundingFeeCollection(records=[])
        try:
            provider: Provider = provider_builder(
                provider_type=channel.provider,
                channel_name=channel.name,
                config=decode_public_config(channel),
                secrets=decode_secret_config(channel, cipher),
            )
            records: list[FundingFeeRecord] = []
            for _, _, start_ms, end_ms in segments:
                records.extend(await provider.collect_funding_fee_records(start_ms, end_ms))
            return MonthlyFundingFeeCollection(records=records)
        except Exception as exc:
            logger.error(
                "funding_fees.monthly_channel_failed channel_id=%s provider=%s name=%s error=%s",
                channel.id,
                channel.provider,
                channel.name,
                exc,
            )
            return MonthlyFundingFeeCollection(records=[], error=str(exc))

    collections: list[MonthlyFundingFeeCollection] = []
    for channel in channels:
        collections.append(await collect_channel(channel))
    records = [record for collection in collections for record in collection.records]
    errors = [collection.error for collection in collections if collection.error]
    return MonthlyFundingFeeCollection(records=records, error="; ".join(errors) if errors else None)


def ensure_previous_month_funding_fee_summary(
    *,
    session: Session,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
    now_factory=None,
) -> MonthlyFundingFeeSummary:
    now = now_factory() if now_factory else datetime.now(UTC)
    month, start_date, end_date = previous_month_period(now)
    existing = session.scalar(
        select(MonthlyFundingFeeSummary).where(MonthlyFundingFeeSummary.month == month)
    )
    if existing is not None:
        return existing

    collection = asyncio.run(
        collect_monthly_funding_fee_records(
            channels=channels,
            cipher=cipher,
            provider_builder=provider_builder,
            start_date=start_date,
            end_date=end_date,
        )
    )
    period = summarize_period_records(
        collection.records,
        start_date=start_date,
        end_date=end_date,
    )
    model = MonthlyFundingFeeSummary(
        month=month,
        start_date=start_date,
        end_date=end_date,
        received=_quantize_decimal(period.received),
        paid=_quantize_decimal(period.paid),
        net=_quantize_decimal(period.net),
        records_count=period.records_count,
        status="failed" if collection.error else "success",
        error=collection.error,
    )
    session.add(model)
    session.flush()
    return model


def summarize_channel_records(
    channel: Channel, records: list[FundingFeeRecord]
) -> FundingFeeChannelSummary:
    received = sum((record.amount for record in records if record.amount > 0), Decimal("0"))
    paid = sum((-record.amount for record in records if record.amount < 0), Decimal("0"))
    return FundingFeeChannelSummary(
        channel_id=channel.id,
        channel_name=channel.name,
        provider=channel.provider,
        received=received,
        paid=paid,
        net=received - paid,
        records_count=len(records),
    )


def summarize_asset_details(
    channel_collections: list[FundingFeeChannelCollection],
) -> list[FundingFeeAssetDetail]:
    grouped: dict[tuple[int, str], FundingFeeAssetDetail] = {}
    for collection in channel_collections:
        summary = collection.summary
        if summary.status != "success":
            continue
        for record in collection.records:
            asset = record.asset.upper()
            key = (summary.channel_id, asset)
            detail = grouped.get(key)
            if detail is None:
                detail = FundingFeeAssetDetail(
                    channel_id=summary.channel_id,
                    channel_name=summary.channel_name,
                    provider=summary.provider,
                    asset=asset,
                    amount=Decimal("0"),
                    records_count=0,
                )
                grouped[key] = detail
            detail.amount += record.amount
            detail.records_count += 1
    return sorted(grouped.values(), key=lambda item: (item.channel_id, item.asset))


def summarize_period_records(
    records: list[FundingFeeRecord], *, start_date: str, end_date: str
) -> FundingFeePeriodSummary:
    received = sum((record.amount for record in records if record.amount > 0), Decimal("0"))
    paid = sum((-record.amount for record in records if record.amount < 0), Decimal("0"))
    return FundingFeePeriodSummary(
        start_date=start_date,
        end_date=end_date,
        received=received,
        paid=paid,
        net=received - paid,
        records_count=len(records),
    )


def funding_fee_summary_payload(summary: FundingFeeSummary) -> dict[str, object]:
    return {
        "date": summary.date,
        "startTime": summary.start_time.isoformat(),
        "endTime": summary.end_time.isoformat(),
        "received": _decimal_text(summary.received),
        "paid": _decimal_text(summary.paid),
        "net": _decimal_text(summary.net),
        "recordsCount": summary.records_count,
        "channels": [
            {
                "channelId": item.channel_id,
                "channelName": item.channel_name,
                "provider": item.provider,
                "received": _decimal_text(item.received),
                "paid": _decimal_text(item.paid),
                "net": _decimal_text(item.net),
                "recordsCount": item.records_count,
                "status": item.status,
                "error": item.error,
            }
            for item in summary.channels
        ],
        "details": [
            {
                "channelId": item.channel_id,
                "channelName": item.channel_name,
                "provider": item.provider,
                "asset": item.asset,
                "amount": _decimal_text(item.amount),
                "recordsCount": item.records_count,
            }
            for item in summary.details
        ],
        "recentSevenDays": _period_summary_payload(summary.recent_seven_days),
    }


def monthly_funding_fee_summary_payload(summary: MonthlyFundingFeeSummary) -> dict[str, object]:
    return {
        "month": summary.month,
        "startDate": summary.start_date,
        "endDate": summary.end_date,
        "received": _decimal_text(summary.received),
        "paid": _decimal_text(summary.paid),
        "net": _decimal_text(summary.net),
        "recordsCount": summary.records_count,
        "status": summary.status,
        "error": summary.error,
    }


def current_month_funding_fee_summary_payload(
    summary: CurrentMonthFundingFeeSummary,
) -> dict[str, object]:
    return {
        "month": summary.month,
        "startDate": summary.start_date,
        "endDate": summary.end_date,
        "received": _decimal_text(summary.received),
        "paid": _decimal_text(summary.paid),
        "net": _decimal_text(summary.net),
        "recordsCount": summary.records_count,
        "cachedDays": summary.cached_days,
        "expectedDays": summary.expected_days,
        "status": summary.status,
    }


def running_monthly_funding_fee_summary_payload(
    *, month: str, start_date: str, end_date: str
) -> dict[str, object]:
    return {
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


def _period_summary_payload(summary: FundingFeePeriodSummary) -> dict[str, object]:
    return {
        "startDate": summary.start_date,
        "endDate": summary.end_date,
        "received": _decimal_text(summary.received),
        "paid": _decimal_text(summary.paid),
        "net": _decimal_text(summary.net),
        "recordsCount": summary.records_count,
    }


def _decimal_text(value: Decimal) -> str:
    return format(_quantize_decimal(value), "f")


def _quantize_decimal(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.00000001"))
