from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from profits_check_backend.models import Channel, LiquidationPosition
from profits_check_backend.providers.base import ContractPositionRisk
from profits_check_backend.providers.http import provider_http_client
from profits_check_backend.security import SecretCipher
from profits_check_backend.services.channels import (
    decode_public_config,
    decode_secret_config,
    get_or_create_setting,
)
from profits_check_backend.services.snapshots import quantize_decimal

LIQUIDATION_MONITOR_SETTING_KEY = "liquidationMonitorConfig"
SUPPORTED_FREQUENCIES = {30, 60, 180, 300, 900, 1800, 3600}
ALERT_COOLDOWN = timedelta(minutes=15)
RECOVERY_BUFFER_PERCENT = Decimal("1")
MONITORED_PROVIDERS = {"binance", "gate", "okx", "bitget", "bybit", "aster"}


@dataclass(slots=True)
class LiquidationMonitorConfig:
    monitor_enabled: bool = False
    alert_enabled: bool = False
    threshold_percent: Decimal = Decimal("5")
    check_interval_seconds: int = 60
    miao_code: str = ""


def liquidation_config_payload(config: LiquidationMonitorConfig) -> dict[str, object]:
    return {
        "monitorEnabled": config.monitor_enabled,
        "alertEnabled": config.alert_enabled,
        "thresholdPercent": quantize_decimal(config.threshold_percent),
        "checkIntervalSeconds": config.check_interval_seconds,
        "miaoCodeConfigured": bool(config.miao_code),
        "supportedFrequencies": sorted(SUPPORTED_FREQUENCIES),
    }


def load_liquidation_monitor_config(
    session: Session, cipher: SecretCipher
) -> LiquidationMonitorConfig:
    setting = get_or_create_setting(session, LIQUIDATION_MONITOR_SETTING_KEY, "{}")
    payload = json.loads(setting.value_json or "{}")
    miao_code = ""
    if payload.get("miaoCodeEncrypted"):
        miao_code = cipher.decrypt(str(payload["miaoCodeEncrypted"]))
    return LiquidationMonitorConfig(
        monitor_enabled=bool(payload.get("monitorEnabled", False)),
        alert_enabled=bool(payload.get("alertEnabled", False)),
        threshold_percent=Decimal(str(payload.get("thresholdPercent", "5"))),
        check_interval_seconds=int(payload.get("checkIntervalSeconds", 60)),
        miao_code=miao_code,
    )


def save_liquidation_monitor_config(
    session: Session,
    cipher: SecretCipher,
    *,
    monitor_enabled: bool,
    alert_enabled: bool,
    threshold_percent: Decimal,
    check_interval_seconds: int,
    miao_code: str | None,
) -> LiquidationMonitorConfig:
    if check_interval_seconds not in SUPPORTED_FREQUENCIES:
        raise ValueError("Unsupported liquidation monitor frequency")
    if threshold_percent <= 0:
        raise ValueError("Liquidation threshold must be greater than 0")

    setting = get_or_create_setting(session, LIQUIDATION_MONITOR_SETTING_KEY, "{}")
    existing = json.loads(setting.value_json or "{}")
    existing.update(
        {
            "monitorEnabled": monitor_enabled,
            "alertEnabled": alert_enabled,
            "thresholdPercent": str(threshold_percent),
            "checkIntervalSeconds": check_interval_seconds,
        }
    )
    if miao_code is not None:
        if miao_code:
            existing["miaoCodeEncrypted"] = cipher.encrypt(miao_code)
        else:
            existing.pop("miaoCodeEncrypted", None)
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
    alert_count = 0
    failure_count = 0

    existing = {
        (item.channel_id, item.symbol, item.side): item
        for item in session.scalars(select(LiquidationPosition))
    }
    seen_keys: set[tuple[int, str, str]] = set()

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

        for provider_position in provider_positions:
            model = upsert_liquidation_position(
                session=session,
                channel=channel,
                risk=provider_position,
                threshold_percent=config.threshold_percent,
                existing=existing,
                now=now,
            )
            seen_keys.add((model.channel_id, model.symbol, model.side))
            if config.alert_enabled and config.miao_code and should_send_alert(model, now):
                alert_result = await send_miaotixing_alert(config.miao_code, alert_text(model))
                model.last_alert_status = alert_result["status"]
                model.last_alert_error = alert_result.get("error")
                model.last_alert_at = (
                    now if alert_result["status"] == "sent" else model.last_alert_at
                )
                if alert_result["status"] == "sent":
                    alert_count += 1
            elif model.status != "warning" and model.distance_percent is not None:
                recovery_line = config.threshold_percent + RECOVERY_BUFFER_PERCENT
                if model.distance_percent > recovery_line:
                    model.last_alert_status = None
                    model.last_alert_error = None
                    model.last_alert_at = None
            positions.append(model)

    for key, item in existing.items():
        if key not in seen_keys:
            session.delete(item)

    session.commit()
    positions.sort(
        key=lambda item: (item.distance_percent is None, item.distance_percent or Decimal("999999"))
    )
    return {
        "status": "success" if failure_count == 0 else "partial",
        "alertCount": alert_count,
        "failureCount": failure_count,
        "config": liquidation_config_payload(config),
        "positions": [liquidation_position_payload(position) for position in positions],
    }


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


def should_send_alert(position: LiquidationPosition, now: datetime) -> bool:
    if position.status != "warning":
        return False
    if position.last_alert_at is None:
        return True
    last_alert_at = position.last_alert_at
    if last_alert_at.tzinfo is None:
        last_alert_at = last_alert_at.replace(tzinfo=UTC)
    return now - last_alert_at >= ALERT_COOLDOWN


def alert_text(position: LiquidationPosition) -> str:
    return (
        f"{position.channel_name} {position.symbol} {position.side} liquidation risk. "
        f"Mark {position.mark_price}, liquidation {position.liquidation_price}, "
        f"distance {quantize_decimal(position.distance_percent)}%."
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


def get_liquidation_monitor_payload(session: Session, cipher: SecretCipher) -> dict[str, object]:
    config = load_liquidation_monitor_config(session, cipher)
    positions = list(session.scalars(select(LiquidationPosition).order_by(LiquidationPosition.id)))
    return {
        "config": liquidation_config_payload(config),
        "positions": [liquidation_position_payload(position) for position in positions],
    }


async def send_test_liquidation_alert(session: Session, cipher: SecretCipher) -> dict[str, str]:
    config = load_liquidation_monitor_config(session, cipher)
    if not config.miao_code:
        raise ValueError("Miaotixing code is not configured")
    return await send_miaotixing_alert(
        config.miao_code,
        "Profits Check liquidation monitor test alert.",
    )
