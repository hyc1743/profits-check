from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from profits_check_backend.models import Channel, LiquidationMarginBalance, LiquidationPosition
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


@dataclass(slots=True)
class LiquidationMonitorConfig:
    monitor_enabled: bool = False
    alert_enabled: bool = False
    position_monitor_enabled: bool = False
    position_threshold_percent: Decimal = Decimal("5")
    margin_balance_monitor_enabled: bool = False
    margin_balance_threshold_percent: Decimal = Decimal("70")
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
    error: str | None = None


def liquidation_config_payload(config: LiquidationMonitorConfig) -> dict[str, object]:
    return {
        "monitorEnabled": config.monitor_enabled,
        "alertEnabled": config.alert_enabled,
        "thresholdPercent": quantize_decimal(config.position_threshold_percent),
        "positionMonitorEnabled": config.position_monitor_enabled,
        "positionThresholdPercent": quantize_decimal(config.position_threshold_percent),
        "marginBalanceMonitorEnabled": config.margin_balance_monitor_enabled,
        "marginBalanceThresholdPercent": quantize_decimal(config.margin_balance_threshold_percent),
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
    if check_interval_seconds <= 0:
        raise ValueError("Liquidation monitor frequency must be greater than 0")
    if alert_interval_seconds <= 0:
        raise ValueError("Liquidation alert frequency must be greater than 0")
    if position_threshold_percent <= 0 or margin_balance_threshold_percent <= 0:
        raise ValueError("Liquidation threshold must be greater than 0")
    if (
        position_threshold_percent != position_threshold_percent.to_integral_value()
        or margin_balance_threshold_percent != margin_balance_threshold_percent.to_integral_value()
    ):
        raise ValueError("Liquidation threshold must be an integer")
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
    alert_count = 0
    failure_count = 0

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

        collect_margin_balance = getattr(provider, "collect_contract_margin_balance", None)
        try:
            provider_margin_balance = (
                await collect_margin_balance() if collect_margin_balance is not None else None
            )
            checked_margin_balance_channel_ids.add(channel.id)
        except Exception:
            failure_count += 1
            provider_margin_balance = None

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
                config.alert_enabled
                and (config.miao_code or config.bark_push_url)
                and should_send_alert(model, now, config.alert_interval_seconds)
            ):
                alert_result = await send_liquidation_alert(
                    miao_code=config.miao_code,
                    bark_push_url=config.bark_push_url,
                    title="Profits Check liquidation risk",
                    text=position_alert_text(model),
                )
                model.last_alert_status = alert_result.status
                model.last_alert_error = alert_result.error
                model.last_alert_at = now if alert_result.sent else model.last_alert_at
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
            ):
                alert_result = await send_liquidation_alert(
                    miao_code=config.miao_code,
                    bark_push_url=config.bark_push_url,
                    title="Profits Check margin balance risk",
                    text=margin_balance_alert_text(
                        channel,
                        provider_margin_balance,
                        config.margin_balance_threshold_percent,
                    ),
                )
                margin_model.last_alert_status = alert_result.status
                margin_model.last_alert_error = alert_result.error
                margin_model.last_alert_at = now if alert_result.sent else None
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
        "marginBalances": [
            liquidation_margin_balance_payload(margin_balance)
            for margin_balance in sorted(margin_balances, key=lambda item: item.id or 0)
        ],
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
    model.raw_payload_json = json.dumps(risk.raw_payload)
    model.updated_at = now
    if status != "warning":
        model.last_alert_status = None
        model.last_alert_error = None
        model.last_alert_at = None
    return model


def should_send_alert(
    position: LiquidationPosition, now: datetime, alert_interval_seconds: int
) -> bool:
    if position.status != "warning":
        return False
    if position.last_alert_at is None:
        return True
    last_alert_at = position.last_alert_at
    if last_alert_at.tzinfo is None:
        last_alert_at = last_alert_at.replace(tzinfo=UTC)
    return now - last_alert_at >= timedelta(seconds=alert_interval_seconds)


def position_alert_text(position: LiquidationPosition) -> str:
    return (
        f"{position.channel_name} {position.symbol} {position.side} liquidation risk. "
        f"Quantity {position.quantity}, "
        f"Mark {position.mark_price}, liquidation {position.liquidation_price}, "
        f"distance {quantize_decimal(position.distance_percent)}% <= "
        f"threshold {quantize_decimal(position.threshold_percent)}%."
    )


def margin_balance_alert_text(
    channel: Channel, risk: ContractMarginBalanceRisk, threshold_percent: Decimal
) -> str:
    return (
        f"{channel.name} margin balance risk. Wallet {risk.wallet_balance}, "
        f"margin balance {risk.margin_balance}, unrealized PnL {risk.unrealized_pnl}, "
        f"risk ratio {quantize_decimal(risk.risk_percent)}% < "
        f"threshold {quantize_decimal(threshold_percent)}%."
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

    status_source = miao_result or bark_result or {"status": "failed"}
    sent = any(
        result is not None and result.get("status") == "sent"
        for result in (miao_result, bark_result)
    )
    return AlertSendResult(
        status=status_source["status"],
        sent=sent,
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


def get_liquidation_monitor_payload(session: Session, cipher: SecretCipher) -> dict[str, object]:
    config = load_liquidation_monitor_config(session, cipher)
    positions = list(session.scalars(select(LiquidationPosition).order_by(LiquidationPosition.id)))
    margin_balances = list(
        session.scalars(select(LiquidationMarginBalance).order_by(LiquidationMarginBalance.id))
    )
    return {
        "config": liquidation_config_payload(config),
        "positions": [liquidation_position_payload(position) for position in positions],
        "marginBalances": [
            liquidation_margin_balance_payload(margin_balance) for margin_balance in margin_balances
        ],
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
