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

MONTH_PATTERN = re.compile(r"^\d{4}-\d{2}$")
MONTH_TIMEZONE = ZoneInfo("Asia/Shanghai")
SEVEN_DAY_WINDOW_PROVIDERS = {"gate", "bybit"}
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
class FundingFeeMonthlySummary:
    month: str
    start_time: datetime
    end_time: datetime
    received: Decimal
    paid: Decimal
    net: Decimal
    records_count: int
    channels: list[FundingFeeChannelSummary]


def month_bounds_ms(month: str) -> tuple[datetime, datetime, int, int]:
    if not MONTH_PATTERN.match(month):
        raise ValueError("month must use YYYY-MM")
    year, month_number = (int(part) for part in month.split("-", maxsplit=1))
    if not 1 <= month_number <= 12:
        raise ValueError("month must use YYYY-MM")
    start_local = datetime(year, month_number, 1, tzinfo=MONTH_TIMEZONE)
    if month_number == 12:
        next_start_local = datetime(year + 1, 1, 1, tzinfo=MONTH_TIMEZONE)
    else:
        next_start_local = datetime(year, month_number + 1, 1, tzinfo=MONTH_TIMEZONE)
    end_local = next_start_local
    start_ms = int(start_local.astimezone(UTC).timestamp() * 1000)
    end_ms = int(end_local.astimezone(UTC).timestamp() * 1000) - 1
    return start_local, end_local, start_ms, end_ms


async def collect_monthly_funding_fee_summary(
    *,
    month: str,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
) -> FundingFeeMonthlySummary:
    started_at = time.perf_counter()
    start_time, end_time, start_ms, end_ms = month_bounds_ms(month)
    logger.info(
        "funding_fees.start month=%s channels=%s start_ms=%s end_ms=%s",
        month,
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
            windows = funding_fee_query_windows(channel.provider, start_time, end_time)
            channel_started_at = time.perf_counter()
            logger.info(
                "funding_fees.channel_start channel_id=%s provider=%s name=%s windows=%s",
                channel.id,
                channel.provider,
                channel.name,
                len(windows),
            )
            window_records = await asyncio.gather(
                *(
                    collect_channel_window(
                        provider=provider,
                        channel=channel,
                        index=index,
                        start_time_ms=window_start_ms,
                        end_time_ms=window_end_ms,
                    )
                    for index, (window_start_ms, window_end_ms) in enumerate(windows, start=1)
                )
            )
            records = [record for records in window_records for record in records]
            duration_ms = int((time.perf_counter() - channel_started_at) * 1000)
            logger.info(
                "funding_fees.channel_success channel_id=%s provider=%s name=%s "
                "windows=%s records=%s duration_ms=%s",
                channel.id,
                channel.provider,
                channel.name,
                len(windows),
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
        "funding_fees.done month=%s channels=%s failed=%s records=%s duration_ms=%s",
        month,
        len(channel_summaries),
        failed_count,
        records_count,
        duration_ms,
    )
    return FundingFeeMonthlySummary(
        month=month,
        start_time=start_time,
        end_time=end_time,
        received=received,
        paid=paid,
        net=net,
        records_count=records_count,
        channels=channel_summaries,
    )


async def collect_channel_window(
    *,
    provider: Provider,
    channel: Channel,
    index: int,
    start_time_ms: int,
    end_time_ms: int,
) -> list[FundingFeeRecord]:
    started_at = time.perf_counter()
    logger.info(
        "funding_fees.window_start channel_id=%s provider=%s name=%s window=%s "
        "start_ms=%s end_ms=%s",
        channel.id,
        channel.provider,
        channel.name,
        index,
        start_time_ms,
        end_time_ms,
    )
    try:
        records = await provider.collect_funding_fee_records(start_time_ms, end_time_ms)
    except Exception as exc:
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        logger.exception(
            "funding_fees.window_failed channel_id=%s provider=%s name=%s window=%s "
            "start_ms=%s end_ms=%s duration_ms=%s error=%s",
            channel.id,
            channel.provider,
            channel.name,
            index,
            start_time_ms,
            end_time_ms,
            duration_ms,
            exc,
        )
        raise
    duration_ms = int((time.perf_counter() - started_at) * 1000)
    logger.info(
        "funding_fees.window_success channel_id=%s provider=%s name=%s window=%s "
        "start_ms=%s end_ms=%s records=%s duration_ms=%s",
        channel.id,
        channel.provider,
        channel.name,
        index,
        start_time_ms,
        end_time_ms,
        len(records),
        duration_ms,
    )
    return records


def funding_fee_query_windows(
    provider: str, start_time: datetime, end_time: datetime
) -> list[tuple[int, int]]:
    if provider.lower() not in SEVEN_DAY_WINDOW_PROVIDERS:
        return [
            (
                int(start_time.astimezone(UTC).timestamp() * 1000),
                int(end_time.astimezone(UTC).timestamp() * 1000) - 1,
            )
        ]

    windows: list[tuple[int, int]] = []
    current = start_time
    while current < end_time:
        next_time = min(current + timedelta(days=7), end_time)
        windows.append(
            (
                int(current.astimezone(UTC).timestamp() * 1000),
                int(next_time.astimezone(UTC).timestamp() * 1000) - 1,
            )
        )
        current = next_time
    return windows


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


def funding_fee_summary_payload(summary: FundingFeeMonthlySummary) -> dict[str, object]:
    return {
        "month": summary.month,
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
