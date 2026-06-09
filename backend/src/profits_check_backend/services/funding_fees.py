from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from profits_check_backend.models import Channel
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
class FundingFeeDailySummary:
    date: str
    start_time: datetime
    end_time: datetime
    received: Decimal
    paid: Decimal
    net: Decimal
    records_count: int
    channels: list[FundingFeeChannelSummary]


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


async def collect_daily_funding_fee_summary(
    *,
    date: str,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
) -> FundingFeeDailySummary:
    started_at = time.perf_counter()
    start_time, end_time, start_ms, end_ms = date_bounds_ms(date)
    logger.info(
        "funding_fees.start date=%s channels=%s start_ms=%s end_ms=%s",
        date,
        len(channels),
        start_ms,
        end_ms,
    )

    async def collect_channel(channel: Channel) -> FundingFeeChannelSummary:
        if not channel.enabled:
            logger.info(
                "funding_fees.channel_skipped channel_id=%s provider=%s name=%s status=disabled",
                channel.id,
                channel.provider,
                channel.name,
            )
            return FundingFeeChannelSummary(
                channel_id=channel.id,
                channel_name=channel.name,
                provider=channel.provider,
                status="disabled",
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
            return summarize_channel_records(channel, records)
        except Exception as exc:
            logger.exception(
                "funding_fees.channel_failed channel_id=%s provider=%s name=%s error=%s",
                channel.id,
                channel.provider,
                channel.name,
                exc,
            )
            return FundingFeeChannelSummary(
                channel_id=channel.id,
                channel_name=channel.name,
                provider=channel.provider,
                status="failed",
                error=str(exc),
            )

    channel_summaries = await asyncio.gather(*(collect_channel(channel) for channel in channels))
    received = sum((item.received for item in channel_summaries), Decimal("0"))
    paid = sum((item.paid for item in channel_summaries), Decimal("0"))
    net = sum((item.net for item in channel_summaries), Decimal("0"))
    records_count = sum(item.records_count for item in channel_summaries)
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
    return FundingFeeDailySummary(
        date=date,
        start_time=start_time,
        end_time=end_time,
        received=received,
        paid=paid,
        net=net,
        records_count=records_count,
        channels=channel_summaries,
    )


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


def funding_fee_summary_payload(summary: FundingFeeDailySummary) -> dict[str, object]:
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
    }


def _decimal_text(value: Decimal) -> str:
    return str(value.quantize(Decimal("0.00000001")))
