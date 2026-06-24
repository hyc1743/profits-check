from __future__ import annotations

import contextlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from profits_check_backend.models import (
    AdlEvent,
    AdlPositionSample,
    Channel,
    LiquidationMarginBalance,
    LiquidationPosition,
)
from profits_check_backend.providers.base import ContractMarginBalanceRisk, ContractPositionRisk
from profits_check_backend.providers.http import provider_http_client
from profits_check_backend.security import SecretCipher
from profits_check_backend.services.channels import (
    decode_public_config,
    decode_secret_config,
    get_or_create_setting,
)
from profits_check_backend.services.snapshots import quantize_decimal

LIQUIDATION_MONITOR_SETTING_KEY = "liquidationMonitorConfig"
RECOVERY_BUFFER_PERCENT = Decimal("1")
MONITORED_PROVIDERS = {"binance", "gate", "okx", "bitget", "bybit", "aster"}
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


@dataclass(slots=True)
class LiquidationMonitorConfig:
    monitor_enabled: bool = False
    alert_enabled: bool = False
    position_monitor_enabled: bool = False
    position_threshold_percent: Decimal = Decimal("5")
    margin_balance_monitor_enabled: bool = False
    margin_balance_threshold_percent: Decimal = Decimal("70")
    adl_monitor_enabled: bool = False
    adl_threshold_percent: Decimal = Decimal("40")
    adl_window_seconds: int = 60
    adl_sample_interval_seconds: int = 30
    adl_start_time: str = "00:00"
    adl_end_time: str = "23:59"
    check_interval_seconds: int = 60
    alert_interval_seconds: int = 900
    miao_code: str = ""
    bark_push_url: str = ""

    @property
    def threshold_percent(self) -> Decimal:
        return self.position_threshold_percent


@dataclass(slots=True)
class AlertSendResult:
    status: str
    sent: bool = False
    attempted: bool = False
    error: str | None = None


def parse_adl_monitor_time(value: str) -> tuple[int, int]:
    try:
        hour_text, minute_text = value.strip().split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
    except ValueError as exc:
        raise ValueError("ADL monitor time must use HH:MM in UTC+8") from exc
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        raise ValueError("ADL monitor time must use HH:MM in UTC+8")
    if f"{hour:02d}:{minute:02d}" != value.strip():
        raise ValueError("ADL monitor time must use HH:MM in UTC+8")
    return hour, minute


def adl_monitor_active_at(config: LiquidationMonitorConfig, now: datetime) -> bool:
    if not config.adl_monitor_enabled:
        return False
    if now.tzinfo is None:
        now = now.replace(tzinfo=UTC)
    local_time = now.astimezone(SHANGHAI_TZ).time()
    start_hour, start_minute = parse_adl_monitor_time(config.adl_start_time)
    end_hour, end_minute = parse_adl_monitor_time(config.adl_end_time)
    start_minutes = start_hour * 60 + start_minute
    end_minutes = end_hour * 60 + end_minute
    current_minutes = local_time.hour * 60 + local_time.minute
    if start_minutes <= end_minutes:
        return start_minutes <= current_minutes <= end_minutes
    return current_minutes >= start_minutes or current_minutes <= end_minutes


def liquidation_config_payload(config: LiquidationMonitorConfig) -> dict[str, object]:
    return {
        "monitorEnabled": config.monitor_enabled,
        "alertEnabled": config.alert_enabled,
        "thresholdPercent": quantize_decimal(config.position_threshold_percent),
        "positionMonitorEnabled": config.position_monitor_enabled,
        "positionThresholdPercent": quantize_decimal(config.position_threshold_percent),
        "marginBalanceMonitorEnabled": config.margin_balance_monitor_enabled,
        "marginBalanceThresholdPercent": quantize_decimal(config.margin_balance_threshold_percent),
        "adlMonitorEnabled": config.adl_monitor_enabled,
        "adlThresholdPercent": quantize_decimal(config.adl_threshold_percent),
        "adlWindowSeconds": config.adl_window_seconds,
        "adlSampleIntervalSeconds": config.adl_sample_interval_seconds,
        "adlStartTime": config.adl_start_time,
        "adlEndTime": config.adl_end_time,
        "checkIntervalSeconds": config.check_interval_seconds,
        "alertIntervalSeconds": config.alert_interval_seconds,
        "miaoCodeConfigured": bool(config.miao_code),
        "barkPushUrlConfigured": bool(config.bark_push_url),
        **({"miaoCode": config.miao_code} if config.miao_code else {}),
        **({"barkPushUrl": config.bark_push_url} if config.bark_push_url else {}),
    }


def load_liquidation_monitor_config(
    session: Session, cipher: SecretCipher
) -> LiquidationMonitorConfig:
    setting = get_or_create_setting(session, LIQUIDATION_MONITOR_SETTING_KEY, "{}")
    payload = json.loads(setting.value_json or "{}")
    miao_code = ""
    if payload.get("miaoCodeEncrypted"):
        miao_code = cipher.decrypt(str(payload["miaoCodeEncrypted"]))
    bark_push_url = ""
    if payload.get("barkPushUrlEncrypted"):
        bark_push_url = cipher.decrypt(str(payload["barkPushUrlEncrypted"]))
    legacy_monitor_enabled = bool(payload.get("monitorEnabled", False))
    position_monitor_enabled = bool(payload.get("positionMonitorEnabled", legacy_monitor_enabled))
    margin_balance_monitor_enabled = bool(payload.get("marginBalanceMonitorEnabled", False))
    return LiquidationMonitorConfig(
        monitor_enabled=bool(
            payload.get(
                "monitorEnabled",
                position_monitor_enabled or margin_balance_monitor_enabled,
            )
        ),
        alert_enabled=bool(payload.get("alertEnabled", legacy_monitor_enabled)),
        position_monitor_enabled=position_monitor_enabled,
        position_threshold_percent=Decimal(
            str(payload.get("positionThresholdPercent", payload.get("thresholdPercent", "5")))
        ),
        margin_balance_monitor_enabled=margin_balance_monitor_enabled,
        margin_balance_threshold_percent=Decimal(
            str(payload.get("marginBalanceThresholdPercent", "70"))
        ),
        adl_monitor_enabled=bool(payload.get("adlMonitorEnabled", False)),
        adl_threshold_percent=Decimal(str(payload.get("adlThresholdPercent", "40"))),
        adl_window_seconds=int(payload.get("adlWindowSeconds", 60)),
        adl_sample_interval_seconds=int(payload.get("adlSampleIntervalSeconds", 30)),
        adl_start_time=str(payload.get("adlStartTime", "00:00")),
        adl_end_time=str(payload.get("adlEndTime", "23:59")),
        check_interval_seconds=int(payload.get("checkIntervalSeconds", 60)),
        alert_interval_seconds=int(payload.get("alertIntervalSeconds", 900)),
        miao_code=miao_code,
        bark_push_url=bark_push_url,
    )


def save_liquidation_monitor_config(
    session: Session,
    cipher: SecretCipher,
    *,
    monitor_enabled: bool,
    threshold_percent: Decimal | None = None,
    position_monitor_enabled: bool | None = None,
    position_threshold_percent: Decimal | None = None,
    margin_balance_monitor_enabled: bool | None = None,
    margin_balance_threshold_percent: Decimal | None = None,
    adl_monitor_enabled: bool | None = None,
    adl_threshold_percent: Decimal | None = None,
    adl_window_seconds: int | None = None,
    adl_sample_interval_seconds: int | None = None,
    adl_start_time: str | None = None,
    adl_end_time: str | None = None,
    check_interval_seconds: int,
    alert_interval_seconds: int,
    miao_code: str | None,
    bark_push_url: str | None = None,
) -> LiquidationMonitorConfig:
    if position_monitor_enabled is None:
        position_monitor_enabled = monitor_enabled
    if margin_balance_monitor_enabled is None:
        margin_balance_monitor_enabled = False
    if position_threshold_percent is None:
        position_threshold_percent = threshold_percent or Decimal("5")
    if margin_balance_threshold_percent is None:
        margin_balance_threshold_percent = Decimal("70")
    if adl_monitor_enabled is None:
        adl_monitor_enabled = False
    if adl_threshold_percent is None:
        adl_threshold_percent = Decimal("40")
    if adl_window_seconds is None:
        adl_window_seconds = 60
    if adl_sample_interval_seconds is None:
        adl_sample_interval_seconds = 30
    if adl_start_time is None:
        adl_start_time = "00:00"
    if adl_end_time is None:
        adl_end_time = "23:59"
    if check_interval_seconds <= 0:
        raise ValueError("Liquidation monitor frequency must be greater than 0")
    if alert_interval_seconds <= 0:
        raise ValueError("Liquidation alert frequency must be greater than 0")
    if position_threshold_percent <= 0 or margin_balance_threshold_percent <= 0:
        raise ValueError("Liquidation threshold must be greater than 0")
    if adl_threshold_percent <= 0:
        raise ValueError("ADL threshold must be greater than 0")
    if adl_window_seconds <= 0 or adl_sample_interval_seconds <= 0:
        raise ValueError("ADL monitor frequency must be greater than 0")
    if (
        position_threshold_percent != position_threshold_percent.to_integral_value()
        or margin_balance_threshold_percent != margin_balance_threshold_percent.to_integral_value()
        or adl_threshold_percent != adl_threshold_percent.to_integral_value()
    ):
        raise ValueError("Liquidation threshold must be an integer")
    parse_adl_monitor_time(adl_start_time)
    parse_adl_monitor_time(adl_end_time)
    if bark_push_url is not None:
        bark_push_url = bark_push_url.strip()
        if bark_push_url and not bark_push_url.startswith(("http://", "https://")):
            raise ValueError("Bark push URL must start with http:// or https://")

    setting = get_or_create_setting(session, LIQUIDATION_MONITOR_SETTING_KEY, "{}")
    existing = json.loads(setting.value_json or "{}")
    existing.update(
        {
            "monitorEnabled": monitor_enabled,
            "alertEnabled": monitor_enabled,
            "positionMonitorEnabled": position_monitor_enabled,
            "positionThresholdPercent": str(position_threshold_percent),
            "marginBalanceMonitorEnabled": margin_balance_monitor_enabled,
            "marginBalanceThresholdPercent": str(margin_balance_threshold_percent),
            "adlMonitorEnabled": adl_monitor_enabled,
            "adlThresholdPercent": str(adl_threshold_percent),
            "adlWindowSeconds": adl_window_seconds,
            "adlSampleIntervalSeconds": adl_sample_interval_seconds,
            "adlStartTime": adl_start_time,
            "adlEndTime": adl_end_time,
            "thresholdPercent": str(position_threshold_percent),
            "checkIntervalSeconds": check_interval_seconds,
            "alertIntervalSeconds": alert_interval_seconds,
        }
    )
    if miao_code is not None:
        if miao_code:
            existing["miaoCodeEncrypted"] = cipher.encrypt(miao_code)
        else:
            existing.pop("miaoCodeEncrypted", None)
    if bark_push_url is not None:
        if bark_push_url:
            existing["barkPushUrlEncrypted"] = cipher.encrypt(bark_push_url)
        else:
            existing.pop("barkPushUrlEncrypted", None)
    setting.value_json = json.dumps(existing)
    session.commit()
    return load_liquidation_monitor_config(session, cipher)


async def run_liquidation_monitor(
    *,
    session: Session,
    channels: list[Channel],
    cipher: SecretCipher,
    provider_builder,
    now: datetime | None = None,
) -> dict[str, Any]:
    config = load_liquidation_monitor_config(session, cipher)
    now = now or datetime.now(UTC)
    positions: list[LiquidationPosition] = []
    margin_balances: list[LiquidationMarginBalance] = []
    adl_events: list[AdlEvent] = []
    alert_count = 0
    failure_count = 0
    adl_active = adl_monitor_active_at(config, now)

    # Acquire the write lock before any read so the WAL snapshot is taken under
    # the lock and stays valid through the writes (no SQLITE_BUSY_SNAPSHOT). The
    # monitor runs with max_instances=1 and only a few seconds of HTTP, so holding
    # the lock across this section is acceptable; reads are never blocked.
    write_section = getattr(session, "write_section", None)
    section = write_section() if write_section is not None else contextlib.nullcontext()
    with section:
        existing = {
            (item.channel_id, item.symbol, item.side): item
            for item in session.scalars(select(LiquidationPosition))
        }
        existing_margin_balances = {
            item.channel_id: item for item in session.scalars(select(LiquidationMarginBalance))
        }
        seen_keys: set[tuple[int, str, str]] = set()
        seen_margin_balance_channel_ids: set[int] = set()
        checked_margin_balance_channel_ids: set[int] = set()
        active_channel_ids = {channel.id for channel in channels}

        for channel in channels:
            if channel.provider not in MONITORED_PROVIDERS:
                continue
            try:
                provider = provider_builder(
                    provider_type=channel.provider,
                    channel_name=channel.name,
                    config=decode_public_config(channel),
                    secrets=decode_secret_config(channel, cipher),
                )
                provider_positions = await provider.collect_contract_positions()
            except Exception:
                failure_count += 1
                continue

            if adl_active:
                detected_adl_events = await detect_adl_events(
                    session=session,
                    channel=channel,
                    provider_positions=provider_positions,
                    config=config,
                    now=now,
                )
                for adl_event in detected_adl_events:
                    if (
                        config.alert_enabled
                        and (config.miao_code or config.bark_push_url)
                        and should_send_adl_alert(adl_event, now, config.alert_interval_seconds)
                    ):
                        alert_result = await send_liquidation_alert(
                            miao_code=config.miao_code,
                            bark_push_url=config.bark_push_url,
                            title=adl_alert_title(adl_event),
                            text=adl_alert_text(adl_event),
                        )
                        adl_event.last_alert_status = alert_result.status
                        adl_event.last_alert_error = alert_result.error
                        adl_event.last_alert_at = now if alert_result.attempted else None
                        if alert_result.sent:
                            alert_count += 1
                adl_events.extend(detected_adl_events)

            provider_margin_balance = None
            if config.margin_balance_monitor_enabled:
                collect_margin_balance = getattr(provider, "collect_contract_margin_balance", None)
                try:
                    provider_margin_balance = (
                        await collect_margin_balance()
                        if collect_margin_balance is not None
                        else None
                    )
                    checked_margin_balance_channel_ids.add(channel.id)
                except Exception:
                    failure_count += 1

            for provider_position in provider_positions:
                model = upsert_liquidation_position(
                    session=session,
                    channel=channel,
                    risk=provider_position,
                    threshold_percent=config.position_threshold_percent,
                    existing=existing,
                    now=now,
                )
                seen_keys.add((model.channel_id, model.symbol, model.side))
                if (
                    config.position_monitor_enabled
                    and config.alert_enabled
                    and (config.miao_code or config.bark_push_url)
                    and should_send_alert(model, now, config.alert_interval_seconds)
                ):
                    alert_result = await send_liquidation_alert(
                        miao_code=config.miao_code,
                        bark_push_url=config.bark_push_url,
                        title=position_alert_title(model),
                        text=position_alert_text(model),
                    )
                    model.last_alert_status = alert_result.status
                    model.last_alert_error = alert_result.error
                    model.last_alert_at = now if alert_result.attempted else model.last_alert_at
                    if alert_result.sent:
                        alert_count += 1
                elif model.status != "warning" and model.distance_percent is not None:
                    recovery_line = config.threshold_percent + RECOVERY_BUFFER_PERCENT
                    if model.distance_percent > recovery_line:
                        model.last_alert_status = None
                        model.last_alert_error = None
                        model.last_alert_at = None
                positions.append(model)

            if provider_margin_balance is not None:
                margin_model = upsert_liquidation_margin_balance(
                    session=session,
                    channel=channel,
                    risk=provider_margin_balance,
                    threshold_percent=config.margin_balance_threshold_percent,
                    existing=existing_margin_balances,
                    now=now,
                )
                seen_margin_balance_channel_ids.add(channel.id)
                if (
                    config.margin_balance_monitor_enabled
                    and config.alert_enabled
                    and (config.miao_code or config.bark_push_url)
                    and margin_model.status == "warning"
                    and should_send_margin_balance_alert(
                        margin_model, now, config.alert_interval_seconds
                    )
                ):
                    alert_result = await send_liquidation_alert(
                        miao_code=config.miao_code,
                        bark_push_url=config.bark_push_url,
                        title=margin_balance_alert_title(channel),
                        text=margin_balance_alert_text(
                            channel,
                            provider_margin_balance,
                        ),
                    )
                    margin_model.last_alert_status = alert_result.status
                    margin_model.last_alert_error = alert_result.error
                    margin_model.last_alert_at = now if alert_result.attempted else None
                    if alert_result.sent:
                        alert_count += 1
                margin_balances.append(margin_model)

        for key, position_item in existing.items():
            if key not in seen_keys:
                session.delete(position_item)
        for channel_id, margin_balance_item in existing_margin_balances.items():
            if (
                channel_id not in active_channel_ids
                or channel_id in checked_margin_balance_channel_ids
                and channel_id not in seen_margin_balance_channel_ids
            ):
                session.delete(margin_balance_item)

        prune_adl_samples(session, now, max(config.adl_window_seconds * 2, 300))
    if write_section is None:
        session.commit()
    positions.sort(
        key=lambda item: (item.distance_percent is None, item.distance_percent or Decimal("999999"))
    )
    if not adl_events:
        adl_events = list(session.scalars(select(AdlEvent).order_by(AdlEvent.detected_at.desc())))
    return {
        "status": "success" if failure_count == 0 else "partial",
        "alertCount": alert_count,
        "failureCount": failure_count,
        "config": liquidation_config_payload(config),
        "positions": [liquidation_position_payload(position) for position in positions],
        "marginBalances": [
            liquidation_margin_balance_payload(margin_balance)
            for margin_balance in sorted(margin_balances, key=lambda item: item.id or 0)
        ],
        "adlEvents": [adl_event_payload(event) for event in adl_events],
    }


async def detect_adl_events(
    *,
    session: Session,
    channel: Channel,
    provider_positions: list[ContractPositionRisk],
    config: LiquidationMonitorConfig,
    now: datetime,
) -> list[AdlEvent]:
    current_by_key = {
        (channel.id, position.symbol, position.side): abs(position.quantity)
        for position in provider_positions
    }
    recent_samples = list(
        session.scalars(
            select(AdlPositionSample).where(
                AdlPositionSample.channel_id == channel.id,
                AdlPositionSample.sampled_at >= now - timedelta(seconds=config.adl_window_seconds),
                AdlPositionSample.sampled_at < now,
            )
        )
    )
    keys = set(current_by_key) | {
        (sample.channel_id, sample.symbol, sample.side) for sample in recent_samples
    }
    metadata_by_key = {
        (channel.id, position.symbol, position.side): (position.symbol, position.side)
        for position in provider_positions
    }
    for sample in recent_samples:
        metadata_by_key.setdefault(
            (sample.channel_id, sample.symbol, sample.side),
            (sample.symbol, sample.side),
        )

    events: list[AdlEvent] = []
    for key in sorted(keys):
        baseline = max(
            (
                sample.quantity_abs
                for sample in recent_samples
                if (sample.channel_id, sample.symbol, sample.side) == key
            ),
            default=Decimal("0"),
        )
        current_quantity = current_by_key.get(key, Decimal("0"))
        if baseline <= 0:
            continue
        drop_percent = (baseline - current_quantity) / baseline * Decimal("100")
        if drop_percent < config.adl_threshold_percent:
            continue
        if has_recent_adl_event(
            session=session,
            key=key,
            now=now,
            alert_interval_seconds=config.alert_interval_seconds,
        ):
            continue
        symbol, side = metadata_by_key[key]
        event = AdlEvent(
            channel_id=channel.id,
            provider=channel.provider,
            channel_name=channel.name,
            symbol=symbol,
            side=side,
            previous_quantity_abs=baseline,
            current_quantity_abs=current_quantity,
            drop_percent=drop_percent.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP),
            threshold_percent=config.adl_threshold_percent,
            window_seconds=config.adl_window_seconds,
            status="suspected",
            detected_at=now,
            created_at=now,
        )
        session.add(event)
        events.append(event)

    for key, quantity_abs in current_by_key.items():
        _, symbol, side = key
        session.add(
            AdlPositionSample(
                channel_id=channel.id,
                provider=channel.provider,
                channel_name=channel.name,
                symbol=symbol,
                side=side,
                quantity_abs=quantity_abs,
                sampled_at=now,
            )
        )
    for key in keys - set(current_by_key):
        _, symbol, side = key
        session.add(
            AdlPositionSample(
                channel_id=channel.id,
                provider=channel.provider,
                channel_name=channel.name,
                symbol=symbol,
                side=side,
                quantity_abs=Decimal("0"),
                sampled_at=now,
            )
        )
    return events


def has_recent_adl_event(
    *,
    session: Session,
    key: tuple[int, str, str],
    now: datetime,
    alert_interval_seconds: int,
) -> bool:
    channel_id, symbol, side = key
    return (
        session.scalar(
            select(AdlEvent.id).where(
                AdlEvent.channel_id == channel_id,
                AdlEvent.symbol == symbol,
                AdlEvent.side == side,
                AdlEvent.detected_at >= now - timedelta(seconds=alert_interval_seconds),
            )
        )
        is not None
    )


def prune_adl_samples(session: Session, now: datetime, retention_seconds: int) -> None:
    session.execute(
        delete(AdlPositionSample).where(
            AdlPositionSample.sampled_at < now - timedelta(seconds=retention_seconds)
        )
    )


def upsert_liquidation_position(
    *,
    session: Session,
    channel: Channel,
    risk: ContractPositionRisk,
    threshold_percent: Decimal,
    existing: dict[tuple[int, str, str], LiquidationPosition],
    now: datetime,
) -> LiquidationPosition:
    key = (channel.id, risk.symbol, risk.side)
    model = existing.get(key)
    if model is None:
        model = LiquidationPosition(
            channel_id=channel.id,
            provider=channel.provider,
            channel_name=channel.name,
            symbol=risk.symbol,
            side=risk.side,
            quantity=risk.quantity,
            mark_price=risk.mark_price,
            threshold_percent=threshold_percent,
            status="ok",
            raw_payload_json="{}",
            created_at=now,
            updated_at=now,
        )
        session.add(model)
        existing[key] = model

    distance = risk.distance_percent
    status = "unavailable"
    if distance is not None:
        status = "warning" if distance <= threshold_percent else "ok"

    model.provider = channel.provider
    model.channel_name = channel.name
    model.quantity = risk.quantity
    model.entry_price = risk.entry_price
    model.mark_price = risk.mark_price
    model.liquidation_price = risk.liquidation_price
    model.distance_percent = distance
    model.threshold_percent = threshold_percent
    model.status = status
    model.unrealized_pnl = risk.unrealized_pnl
    model.margin_mode = risk.margin_mode
    model.leverage = risk.leverage
    model.source_updated_at_ms = risk.updated_at_ms
    model.raw_payload_json = json.dumps(risk.raw_payload)
    model.updated_at = now
    return model


def upsert_liquidation_margin_balance(
    *,
    session: Session,
    channel: Channel,
    risk: ContractMarginBalanceRisk,
    threshold_percent: Decimal,
    existing: dict[int, LiquidationMarginBalance],
    now: datetime,
) -> LiquidationMarginBalance:
    model = existing.get(channel.id)
    if model is None:
        model = LiquidationMarginBalance(
            channel_id=channel.id,
            provider=channel.provider,
            channel_name=channel.name,
            wallet_balance=risk.wallet_balance,
            margin_balance=risk.margin_balance,
            unrealized_pnl=risk.unrealized_pnl,
            threshold_percent=threshold_percent,
            status="ok",
            raw_payload_json="{}",
            created_at=now,
            updated_at=now,
        )
        session.add(model)
        existing[channel.id] = model

    risk_percent = risk.risk_percent
    status = "unavailable"
    if risk_percent is not None:
        status = "warning" if risk_percent < threshold_percent else "ok"

    model.provider = channel.provider
    model.channel_name = channel.name
    model.wallet_balance = risk.wallet_balance
    model.margin_balance = risk.margin_balance
    model.unrealized_pnl = risk.unrealized_pnl or Decimal("0")
    model.risk_percent = risk_percent
    model.threshold_percent = threshold_percent
    model.status = status
    model.raw_payload_json = "{}"
    model.updated_at = now
    if status != "warning":
        model.last_alert_status = None
        model.last_alert_error = None
        model.last_alert_at = None
    return model


def should_send_alert(
    position: LiquidationPosition, now: datetime, alert_interval_seconds: int
) -> bool:
    return should_send_warning_alert(
        status=position.status,
        last_alert_at=position.last_alert_at,
        now=now,
        alert_interval_seconds=alert_interval_seconds,
    )


def should_send_margin_balance_alert(
    margin_balance: LiquidationMarginBalance, now: datetime, alert_interval_seconds: int
) -> bool:
    return should_send_warning_alert(
        status=margin_balance.status,
        last_alert_at=margin_balance.last_alert_at,
        now=now,
        alert_interval_seconds=alert_interval_seconds,
    )


def should_send_adl_alert(adl_event: AdlEvent, now: datetime, alert_interval_seconds: int) -> bool:
    return should_send_warning_alert(
        status="warning",
        last_alert_at=adl_event.last_alert_at,
        now=now,
        alert_interval_seconds=alert_interval_seconds,
    )


def should_send_warning_alert(
    *,
    status: str,
    last_alert_at: datetime | None,
    now: datetime,
    alert_interval_seconds: int,
) -> bool:
    if status != "warning":
        return False
    if last_alert_at is None:
        return True
    if last_alert_at.tzinfo is None:
        last_alert_at = last_alert_at.replace(tzinfo=UTC)
    return now - last_alert_at >= timedelta(seconds=alert_interval_seconds)


def position_alert_title(position: LiquidationPosition) -> str:
    return f"{position.channel_name} {position.symbol} {position.side}"


def position_alert_text(position: LiquidationPosition) -> str:
    return (
        f"{position.channel_name} {position.symbol} {position.side}\n"
        f"Current price: {position.mark_price}\n"
        f"Liquidation price: {position.liquidation_price}"
    )


def margin_balance_alert_title(channel: Channel) -> str:
    return f"{channel.name} risk ratio"


def margin_balance_alert_text(channel: Channel, risk: ContractMarginBalanceRisk) -> str:
    risk_percent = risk.risk_percent
    rendered_percent = (
        str(risk_percent.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
        if risk_percent is not None
        else "N/A"
    )
    return f"{channel.name}\nRisk ratio: {rendered_percent}%"


def adl_alert_title(event: AdlEvent) -> str:
    return f"{event.channel_name} {event.symbol} {event.side} suspected ADL"


def adl_alert_text(event: AdlEvent) -> str:
    rendered_drop = event.drop_percent.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return (
        f"{event.channel_name} {event.symbol} {event.side}\n"
        f"Suspected ADL: position size dropped {rendered_drop}%\n"
        f"Previous quantity: {event.previous_quantity_abs}\n"
        f"Current quantity: {event.current_quantity_abs}"
    )


async def send_miaotixing_alert(miao_code: str, text: str) -> dict[str, str]:
    async with provider_http_client() as client:
        response = await client.post(
            "https://miaotixing.com/trigger",
            data={"id": miao_code, "text": text, "type": "json"},
        )
        response.raise_for_status()
        payload = response.json()
    if payload.get("code") not in {0, "0"}:
        return {"status": "failed", "error": str(payload.get("msg", "Miaotixing alert failed"))}
    phonecall_count = int(payload.get("data", {}).get("success_sent", {}).get("phonecall", 0) or 0)
    if phonecall_count <= 0:
        return {"status": "warning", "error": "Miaotixing did not report a phone call"}
    return {"status": "sent"}


async def send_bark_alert(bark_push_url: str, title: str, body: str) -> dict[str, str]:
    try:
        async with provider_http_client() as client:
            response = await client.post(
                bark_push_url,
                json={"title": title, "body": body, "group": "profits-check"},
            )
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        return {"status": "failed", "error": f"Bark alert failed: {exc}"}
    if payload.get("code") not in {0, "0", 200, "200", None}:
        return {"status": "failed", "error": str(payload.get("message", "Bark alert failed"))}
    return {"status": "sent"}


async def send_liquidation_alert(
    *, miao_code: str, bark_push_url: str, title: str, text: str
) -> AlertSendResult:
    miao_result: dict[str, str] | None = None
    bark_result: dict[str, str] | None = None
    errors: list[str] = []

    if miao_code:
        miao_result = await send_miaotixing_alert(miao_code, text)
        if miao_result.get("status") != "sent" and miao_result.get("error"):
            errors.append(str(miao_result["error"]))
    if bark_push_url:
        bark_result = await send_bark_alert(bark_push_url, title, text)
        if bark_result.get("status") != "sent" and bark_result.get("error"):
            errors.append(str(bark_result["error"]))

    attempted = miao_result is not None or bark_result is not None
    if miao_result is not None:
        sent = miao_result.get("status") == "sent"
        status = "sent" if sent else miao_result.get("status", "failed")
    elif bark_result is not None:
        sent = bark_result.get("status") == "sent"
        status = bark_result.get("status", "failed")
    else:
        sent = False
        status = "failed"
    return AlertSendResult(
        status=status,
        sent=sent,
        attempted=attempted,
        error="; ".join(errors) if errors else None,
    )


def liquidation_position_payload(position: LiquidationPosition) -> dict[str, object]:
    return {
        "id": position.id,
        "channelId": position.channel_id,
        "provider": position.provider,
        "channelName": position.channel_name,
        "symbol": position.symbol,
        "side": position.side,
        "quantity": quantize_decimal(position.quantity),
        "entryPrice": quantize_decimal(position.entry_price),
        "markPrice": quantize_decimal(position.mark_price),
        "liquidationPrice": quantize_decimal(position.liquidation_price),
        "distancePercent": quantize_decimal(position.distance_percent),
        "thresholdPercent": quantize_decimal(position.threshold_percent),
        "status": position.status,
        "unrealizedPnl": quantize_decimal(position.unrealized_pnl),
        "marginMode": position.margin_mode,
        "leverage": position.leverage,
        "lastAlertStatus": position.last_alert_status,
        "lastAlertError": position.last_alert_error,
        "lastAlertAt": position.last_alert_at.replace(tzinfo=UTC).isoformat()
        if position.last_alert_at
        else None,
        "updatedAt": position.updated_at.replace(tzinfo=UTC).isoformat(),
    }


def liquidation_margin_balance_payload(
    margin_balance: LiquidationMarginBalance,
) -> dict[str, object]:
    return {
        "id": f"{margin_balance.channel_id}:margin-balance",
        "channelId": margin_balance.channel_id,
        "provider": margin_balance.provider,
        "channelName": margin_balance.channel_name,
        "walletBalance": quantize_decimal(margin_balance.wallet_balance),
        "marginBalance": quantize_decimal(margin_balance.margin_balance),
        "unrealizedPnl": quantize_decimal(margin_balance.unrealized_pnl),
        "riskPercent": quantize_decimal(margin_balance.risk_percent),
        "thresholdPercent": quantize_decimal(margin_balance.threshold_percent),
        "status": margin_balance.status,
        "lastAlertStatus": margin_balance.last_alert_status,
        "lastAlertError": margin_balance.last_alert_error,
        "lastAlertAt": margin_balance.last_alert_at.replace(tzinfo=UTC).isoformat()
        if margin_balance.last_alert_at
        else None,
    }


def adl_event_payload(event: AdlEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "channelId": event.channel_id,
        "provider": event.provider,
        "channelName": event.channel_name,
        "symbol": event.symbol,
        "side": event.side,
        "previousQuantity": quantize_decimal(event.previous_quantity_abs),
        "currentQuantity": quantize_decimal(event.current_quantity_abs),
        "dropPercent": quantize_decimal(event.drop_percent),
        "thresholdPercent": quantize_decimal(event.threshold_percent),
        "windowSeconds": event.window_seconds,
        "status": event.status,
        "lastAlertStatus": event.last_alert_status,
        "lastAlertError": event.last_alert_error,
        "lastAlertAt": event.last_alert_at.replace(tzinfo=UTC).isoformat()
        if event.last_alert_at
        else None,
        "detectedAt": event.detected_at.replace(tzinfo=UTC).isoformat(),
    }


def get_liquidation_monitor_payload(session: Session, cipher: SecretCipher) -> dict[str, object]:
    config = load_liquidation_monitor_config(session, cipher)
    positions = list(session.scalars(select(LiquidationPosition).order_by(LiquidationPosition.id)))
    margin_balances = list(
        session.scalars(select(LiquidationMarginBalance).order_by(LiquidationMarginBalance.id))
    )
    adl_events = list(session.scalars(select(AdlEvent).order_by(AdlEvent.detected_at.desc())))
    return {
        "config": liquidation_config_payload(config),
        "positions": [liquidation_position_payload(position) for position in positions],
        "marginBalances": [
            liquidation_margin_balance_payload(margin_balance) for margin_balance in margin_balances
        ],
        "adlEvents": [adl_event_payload(event) for event in adl_events],
    }


async def send_test_liquidation_alert(session: Session, cipher: SecretCipher) -> dict[str, str]:
    config = load_liquidation_monitor_config(session, cipher)
    if not config.miao_code and not config.bark_push_url:
        raise ValueError("No alert channel is configured")
    result = await send_liquidation_alert(
        miao_code=config.miao_code,
        bark_push_url=config.bark_push_url,
        title="Profits Check test alert",
        text="Profits Check liquidation monitor test alert.",
    )
    return {
        "status": result.status,
        **({"error": result.error} if result.error else {}),
    }


async def send_test_miaotixing_alert(session: Session, cipher: SecretCipher) -> dict[str, str]:
    config = load_liquidation_monitor_config(session, cipher)
    if not config.miao_code:
        raise ValueError("Miaotixing code is not configured")
    return await send_miaotixing_alert(
        config.miao_code,
        "Profits Check liquidation monitor test alert.",
    )


async def send_test_bark_alert(session: Session, cipher: SecretCipher) -> dict[str, str]:
    config = load_liquidation_monitor_config(session, cipher)
    if not config.bark_push_url:
        raise ValueError("Bark push URL is not configured")
    return await send_bark_alert(
        config.bark_push_url,
        "Profits Check test alert",
        "Profits Check liquidation monitor test alert.",
    )
