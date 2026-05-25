from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from profits_check_backend.models import AppSetting, Channel, Snapshot, SnapshotAsset
from profits_check_backend.providers.base import ProviderSnapshot
from profits_check_backend.security import SecretCipher
from profits_check_backend.services.channels import decode_public_config, decode_secret_config

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
OKX_DEX_PROVIDER_TYPES = {"onchain"}


def _get_okx_dex_secrets(session: Session, cipher: SecretCipher) -> dict[str, str]:
    setting = session.get(AppSetting, "okxDexConfig")
    if not setting:
        return {}
    config = json.loads(setting.value_json or "{}")
    secrets: dict[str, str] = {}
    if config.get("apiKey"):
        secrets["okxDexApiKey"] = config["apiKey"]
    if config.get("apiSecretEncrypted"):
        secrets["okxDexApiSecret"] = cipher.decrypt(config["apiSecretEncrypted"])
    if config.get("passphraseEncrypted"):
        secrets["okxDexPassphrase"] = cipher.decrypt(config["passphraseEncrypted"])
    return secrets


def quantize_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP))


def snapshot_shanghai_date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(SHANGHAI_TZ).date().isoformat()


@dataclass(slots=True)
class NormalizedAssetBalance:
    provider: str
    channel_id: int
    account_scope: str
    asset: str
    total: Decimal
    available: Decimal
    locked: Decimal
    borrowed: Decimal
    unrealized_pnl: Decimal
    value_usd: Decimal | None
    raw_payload: dict[str, Any] = field(default_factory=dict)


def provider_snapshot_to_balances(
    *, channel: Channel, provider_snapshot: ProviderSnapshot
) -> list[NormalizedAssetBalance]:
    balances = []
    for item in provider_snapshot.assets:
        if item.metadata.get("portfolioAccounting") == "informational":
            continue
        balances.append(
            NormalizedAssetBalance(
                provider=channel.provider,
                channel_id=channel.id,
                account_scope=item.metadata.get("type", "spot"),
                asset=item.asset_symbol,
                total=item.quantity,
                available=item.quantity,
                locked=Decimal("0"),
                borrowed=Decimal(str(item.metadata.get("borrowed", "0") or "0")),
                unrealized_pnl=Decimal("0"),
                value_usd=item.value_usd,
                raw_payload=item.metadata,
            )
        )
    return balances


def aggregate_account_category_totals(
    balances: list[NormalizedAssetBalance],
    channels: dict[int, Channel],
) -> list[dict[str, str | int | None]]:
    grouped: dict[tuple[int, str], dict[str, Any]] = {}
    for balance in balances:
        key = (balance.channel_id, balance.account_scope)
        current = grouped.setdefault(
            key,
            {"value_usd": Decimal("0"), "asset_count": 0},
        )
        if balance.value_usd is not None:
            current["value_usd"] = current["value_usd"] + balance.value_usd
        current["asset_count"] = int(current["asset_count"]) + 1

    ordered = sorted(
        grouped.items(),
        key=lambda item: (item[1]["value_usd"], channels[item[0][0]].name, item[0][1]),
        reverse=True,
    )
    return [
        {
            "provider": channels[channel_id].provider,
            "channelName": channels[channel_id].name,
            "accountScope": account_scope,
            "valueUsd": quantize_decimal(values["value_usd"]),
            "assetCount": int(values["asset_count"]),
        }
        for (channel_id, account_scope), values in ordered
    ]


async def execute_snapshot_run(
    *,
    session: Session,
    channels: list[Channel],
    cipher,
    provider_builder,
) -> dict[str, Any]:
    overwrite_date = snapshot_shanghai_date(datetime.now(UTC))
    existing_runs = {
        snapshot_run_key(snapshot)
        for snapshot in session.scalars(select(Snapshot).order_by(Snapshot.id))
        if snapshot_shanghai_date(snapshot.created_at) == overwrite_date
    }

    snapshots: list[Snapshot] = []
    total_value = Decimal("0")
    success_count = 0
    failure_count = 0
    run_id: int | None = None

    okx_dex_secrets = (
        _get_okx_dex_secrets(session, cipher)
        if any(channel.provider in OKX_DEX_PROVIDER_TYPES for channel in channels)
        else {}
    )

    for channel in channels:
        try:
            secrets = decode_secret_config(channel, cipher)
            if channel.provider in OKX_DEX_PROVIDER_TYPES:
                secrets.update(okx_dex_secrets)
            provider = provider_builder(
                provider_type=channel.provider,
                channel_name=channel.name,
                config=decode_public_config(channel),
                secrets=secrets,
            )
            provider_snapshot = await provider.collect_snapshot()
            snapshot = Snapshot(
                channel_id=channel.id,
                status="success",
                total_value_usd=provider_snapshot.total_value_usd,
            )
            session.add(snapshot)
            session.flush()
            if run_id is None:
                run_id = snapshot.id
            snapshot.run_id = run_id
            for balance in provider_snapshot_to_balances(
                channel=channel, provider_snapshot=provider_snapshot
            ):
                session.add(
                    SnapshotAsset(
                        snapshot_id=snapshot.id,
                        provider=balance.provider,
                        account_scope=balance.account_scope,
                        asset_symbol=balance.asset,
                        quantity=balance.total,
                        available=balance.available,
                        locked=balance.locked,
                        borrowed=balance.borrowed,
                        unrealized_pnl=balance.unrealized_pnl,
                        value_usd=balance.value_usd,
                        raw_payload_json=json.dumps(balance.raw_payload),
                    )
                )
            snapshots.append(snapshot)
            total_value += provider_snapshot.total_value_usd
            success_count += 1
        except Exception:
            failure_count += 1

    if success_count > 0:
        for existing_run_id in sorted(existing_runs):
            for snapshot in snapshots_for_run(session, existing_run_id):
                session.delete(snapshot)
        session.flush()

    session.commit()
    return {
        "id": run_id or 0,
        "status": "success" if success_count else "failed",
        "successCount": success_count,
        "failureCount": failure_count,
        "totalValueUsd": quantize_decimal(total_value),
    }


async def collect_live_summary(
    *,
    channels: list[Channel],
    cipher,
    provider_builder,
    session,
) -> dict[str, Any]:
    total_value = Decimal("0")
    asset_count = 0
    channel_summaries: list[dict[str, str | None]] = []
    all_balances: list[NormalizedAssetBalance] = []
    channel_map = {channel.id: channel for channel in channels}
    okx_dex_secrets = (
        _get_okx_dex_secrets(session, cipher)
        if any(channel.provider in OKX_DEX_PROVIDER_TYPES for channel in channels)
        else {}
    )

    for channel in channels:
        try:
            secrets = decode_secret_config(channel, cipher)
            if channel.provider in OKX_DEX_PROVIDER_TYPES:
                secrets.update(okx_dex_secrets)
            provider = provider_builder(
                provider_type=channel.provider,
                channel_name=channel.name,
                config=decode_public_config(channel),
                secrets=secrets,
            )
            provider_snapshot = await provider.collect_snapshot()
        except Exception:
            continue

        balances = provider_snapshot_to_balances(
            channel=channel,
            provider_snapshot=provider_snapshot,
        )
        all_balances.extend(balances)
        total_value += provider_snapshot.total_value_usd
        asset_count += len(balances)
        channel_summaries.append(
            {
                "provider": channel.provider,
                "name": channel.name,
                "latestSnapshotTotalUsd": quantize_decimal(provider_snapshot.total_value_usd),
                "latest_snapshot_total_usd": quantize_decimal(provider_snapshot.total_value_usd),
            }
        )

    return {
        "totalValueUsd": quantize_decimal(total_value),
        "total_value_usd": quantize_decimal(total_value),
        "assetCount": asset_count,
        "accountCategoryTotals": aggregate_account_category_totals(all_balances, channel_map),
        "channels": channel_summaries,
    }


def get_latest_summary(session: Session) -> dict[str, Any]:
    latest = session.scalar(select(Snapshot).order_by(desc(Snapshot.id)).limit(1))
    snapshots = snapshots_for_run(session, latest.run_id or latest.id) if latest is not None else []
    total_value = sum((snapshot.total_value_usd for snapshot in snapshots), Decimal("0"))
    channels = []
    all_balances: list[NormalizedAssetBalance] = []
    channel_map: dict[int, Channel] = {}

    for snapshot in snapshots:
        channel = session.get(Channel, snapshot.channel_id)
        if channel is None:
            continue
        channel_map[channel.id] = channel
        for asset in snapshot.assets:
            all_balances.append(
                NormalizedAssetBalance(
                    provider=asset.provider,
                    channel_id=channel.id,
                    account_scope=asset.account_scope,
                    asset=asset.asset_symbol,
                    total=asset.quantity,
                    available=asset.available,
                    locked=asset.locked,
                    borrowed=asset.borrowed,
                    unrealized_pnl=asset.unrealized_pnl,
                    value_usd=asset.value_usd,
                    raw_payload=json.loads(asset.raw_payload_json or "{}"),
                )
            )
        channels.append(
            {
                "provider": channel.provider,
                "name": channel.name,
                "latestSnapshotTotalUsd": quantize_decimal(snapshot.total_value_usd),
                "latest_snapshot_total_usd": quantize_decimal(snapshot.total_value_usd),
            }
        )

    return {
        "totalValueUsd": quantize_decimal(total_value),
        "total_value_usd": quantize_decimal(total_value),
        "assetCount": len(all_balances),
        "accountCategoryTotals": aggregate_account_category_totals(all_balances, channel_map),
        "channels": channels,
    }


def snapshot_run_key(snapshot: Snapshot) -> int:
    return snapshot.run_id or snapshot.id


def snapshots_for_run(session: Session, run_id: int) -> list[Snapshot]:
    snapshots = list(
        session.scalars(
            select(Snapshot)
            .where(
                (Snapshot.run_id == run_id)
                | ((Snapshot.run_id.is_(None)) & (Snapshot.id == run_id))
            )
            .order_by(Snapshot.id)
        )
    )
    return snapshots


def list_snapshot_runs(session: Session) -> list[dict[str, Any]]:
    snapshots = list(session.scalars(select(Snapshot).order_by(Snapshot.id)))
    grouped: dict[int, list[Snapshot]] = {}
    for snapshot in snapshots:
        grouped.setdefault(snapshot_run_key(snapshot), []).append(snapshot)

    runs = []
    for run_id, run_snapshots in grouped.items():
        total_value = sum((snapshot.total_value_usd for snapshot in run_snapshots), Decimal("0"))
        statuses = {snapshot.status for snapshot in run_snapshots}
        if statuses == {"success"}:
            status = "success"
        elif "success" in statuses:
            status = "partial"
        else:
            status = "failed"
        runs.append(
            {
                "id": run_id,
                "status": status,
                "totalValueUsd": quantize_decimal(total_value),
                "createdAt": max(snapshot.created_at for snapshot in run_snapshots)
                .replace(tzinfo=UTC)
                .isoformat(),
                "snapshotCount": len(run_snapshots),
            }
        )

    return sorted(runs, key=lambda item: (str(item["createdAt"]), int(item["id"])))


def delete_snapshot_run(session: Session, run_id: int) -> bool:
    snapshots = snapshots_for_run(session, run_id)
    if not snapshots:
        return False
    for snapshot in snapshots:
        session.delete(snapshot)
    session.commit()
    return True


def snapshot_detail(session: Session, snapshot_id: int) -> dict[str, Any] | None:
    snapshot = session.get(Snapshot, snapshot_id)
    if snapshot is None:
        return None
    channel = session.get(Channel, snapshot.channel_id) if snapshot.channel_id else None
    return {
        "id": snapshot.id,
        "channelId": snapshot.channel_id,
        "channel_id": snapshot.channel_id,
        "channelName": channel.name if channel else None,
        "channel_name": channel.name if channel else None,
        "provider": channel.provider if channel else None,
        "status": snapshot.status,
        "totalValueUsd": quantize_decimal(snapshot.total_value_usd),
        "total_value_usd": quantize_decimal(snapshot.total_value_usd),
    }
