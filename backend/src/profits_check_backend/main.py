from __future__ import annotations

import asyncio
import json
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import Depends, FastAPI, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from profits_check_backend.config import AppSettings, get_settings
from profits_check_backend.db import build_session_factory, init_database
from profits_check_backend.models import Channel, Snapshot
from profits_check_backend.providers.registry import build_provider
from profits_check_backend.security import SecretCipher
from profits_check_backend.services.channels import (
    channel_payload,
    create_channel,
    decode_public_config,
    decode_secret_config,
    get_or_create_setting,
    list_channels,
)
from profits_check_backend.services.snapshots import (
    _get_okx_dex_secrets,
    collect_live_summary,
    delete_snapshot_run,
    execute_snapshot_run,
    get_latest_summary,
    list_snapshot_runs,
    quantize_decimal,
    snapshot_detail,
)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    app_settings = settings or get_settings()
    session_factory = build_session_factory(app_settings)
    init_database(session_factory)
    cipher = SecretCipher.from_settings(app_settings)
    scheduler_timezone = ZoneInfo("Asia/Shanghai")
    scheduler = BackgroundScheduler(timezone=scheduler_timezone)

    def get_schedule_times(session: Session) -> str:
        return json.loads(
            get_or_create_setting(
                session,
                "snapshotScheduleTimes",
                json.dumps(app_settings.snapshot_schedule_times),
            ).value_json
        )

    def get_scheduler_enabled(session: Session) -> bool:
        return bool(
            json.loads(
                get_or_create_setting(
                    session,
                    "snapshotSchedulerEnabled",
                    json.dumps(app_settings.scheduler_enabled),
                ).value_json
            )
        )

    def run_scheduled_snapshot() -> None:
        with session_factory() as session:
            channels = list(
                session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id))
            )
            asyncio.run(
                execute_snapshot_run(
                    session=session,
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
            )

    def scheduled_jobs_payload() -> list[dict[str, str]]:
        return [{"id": job.id, "trigger": str(job.trigger)} for job in scheduler.get_jobs()]

    def parse_schedule_time(value: str) -> tuple[int, int]:
        hour_text, minute_text = value.strip().split(":", maxsplit=1)
        hour = int(hour_text)
        minute = int(minute_text)
        if not 0 <= hour <= 23 or not 0 <= minute <= 59:
            raise ValueError("Scheduled snapshot time must use HH:MM in UTC+8")
        return hour, minute

    def configure_scheduler(enabled: bool, schedule_times: str) -> None:
        for job in scheduler.get_jobs():
            scheduler.remove_job(job.id)
        if not enabled:
            return

        times = [item.strip() for item in schedule_times.split(",") if item.strip()]
        if not times:
            times = [app_settings.snapshot_schedule_times]
        for index, time_value in enumerate(times):
            hour, minute = parse_schedule_time(time_value)
            scheduler.add_job(
                run_scheduled_snapshot,
                CronTrigger(hour=hour, minute=minute, timezone=scheduler_timezone),
                id="scheduled-snapshot" if index == 0 else f"scheduled-snapshot-{index}",
                replace_existing=True,
                max_instances=1,
            )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = app_settings
        app.state.session_factory = session_factory
        app.state.cipher = cipher
        app.state.provider_builder = build_provider
        app.state.scheduler = scheduler
        with session_factory() as session:
            configure_scheduler(get_scheduler_enabled(session), get_schedule_times(session))
        scheduler.start()
        yield
        scheduler.shutdown(wait=False)

    app = FastAPI(title="Profits Check", lifespan=lifespan)

    def get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/channels")
    def get_channels(session: Session = Depends(get_session)):
        return [channel_payload(channel, cipher) for channel in list_channels(session)]

    @app.post("/api/channels", status_code=201)
    def post_channel(payload: dict[str, Any], session: Session = Depends(get_session)):
        provider = str(payload.get("provider") or payload.get("provider_type") or "")
        public_config = payload.get("publicConfig") or payload.get("config") or {}
        secret_config = payload.get("secretConfig") or payload.get("secrets") or {}
        channel = create_channel(
            session,
            cipher=cipher,
            name=payload["name"],
            provider=provider,
            kind=payload.get("kind", "cex"),
            enabled=payload.get("enabled", True),
            public_config=public_config,
            secret_config=secret_config,
        )
        return channel_payload(channel, cipher)

    @app.put("/api/channels/{channel_id}")
    def put_channel(channel_id: int, payload: dict[str, Any], session: Session = Depends(get_session)):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")

        if "name" in payload:
            channel.name = payload["name"]
        if "provider" in payload or "provider_type" in payload:
            channel.provider = str(payload.get("provider") or payload.get("provider_type") or channel.provider)
        if "kind" in payload:
            channel.kind = payload["kind"]
        if "enabled" in payload:
            channel.enabled = payload["enabled"]

        public_config = payload.get("publicConfig") or payload.get("config")
        if public_config is not None:
            channel.public_config_json = json.dumps(public_config)

        secret_config = payload.get("secretConfig") or payload.get("secrets")
        if secret_config is not None and secret_config:
            new_secrets = {key: cipher.encrypt(str(value)) for key, value in secret_config.items() if value}
            if new_secrets:
                try:
                    existing = json.loads(channel.secret_config_encrypted or "{}")
                except (json.JSONDecodeError, TypeError):
                    existing = {}
                existing.update(new_secrets)
                channel.secret_config_encrypted = json.dumps(existing)

        session.commit()
        session.refresh(channel)
        return channel_payload(channel, cipher)

    @app.post("/api/channels/{channel_id}/test")
    def test_channel(channel_id: int, session: Session = Depends(get_session)):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")

        secrets = decode_secret_config(channel, cipher)
        if channel.provider in ("bsc", "onchain"):
            secrets.update(_get_okx_dex_secrets(session, cipher))
        provider = app.state.provider_builder(
            provider_type=channel.provider,
            channel_name=channel.name,
            config=decode_public_config(channel),
            secrets=secrets,
        )
        try:
            snapshot = asyncio.run(provider.collect_snapshot())
        except Exception as exc:
            channel.last_test_status = "failed"
            channel.last_test_error = str(exc)
            session.commit()
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        channel.last_test_status = "ok"
        channel.last_test_error = None
        session.commit()
        return {
            "status": "ok",
            "assetCount": len(snapshot.assets),
            "totalValueUsd": quantize_decimal(snapshot.total_value_usd),
        }

    @app.delete("/api/channels/{channel_id}", status_code=204)
    def delete_channel(channel_id: int, session: Session = Depends(get_session)):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        session.delete(channel)
        session.commit()

    @app.post("/api/channels/{channel_id}/snapshots", status_code=201)
    def snapshot_channel(channel_id: int, session: Session = Depends(get_session)):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        result = asyncio.run(
            execute_snapshot_run(
                session=session,
                channels=[channel],
                cipher=cipher,
                provider_builder=app.state.provider_builder,
            )
        )
        detail = snapshot_detail(session, result["id"])
        if detail is None:
            raise HTTPException(status_code=500, detail="Snapshot was not persisted")
        return detail

    @app.get("/api/summary")
    def summary_legacy(session: Session = Depends(get_session)):
        return get_latest_summary(session)

    @app.get("/api/summary/latest")
    def summary_latest(session: Session = Depends(get_session)):
        return get_latest_summary(session)

    @app.get("/api/summary/live")
    def summary_live(session: Session = Depends(get_session)):
        channels = list(
            session.scalars(
                select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
            )
        )
        return asyncio.run(
            collect_live_summary(
                channels=channels,
                cipher=cipher,
                provider_builder=app.state.provider_builder,
                session=session,
            )
        )

    @app.post("/api/snapshots/run")
    def run_snapshots(session: Session = Depends(get_session)):
        channels = list(session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)))
        return asyncio.run(
            execute_snapshot_run(
                session=session,
                channels=channels,
                cipher=cipher,
                provider_builder=app.state.provider_builder,
            )
        )

    @app.get("/api/snapshots")
    def get_snapshots(session: Session = Depends(get_session)):
        snapshots = list(session.scalars(select(Snapshot).order_by(Snapshot.id)))
        return [
            {
                "id": snapshot.id,
                "runId": snapshot.run_id or snapshot.id,
                "channelId": snapshot.channel_id,
                "status": snapshot.status,
                "totalValueUsd": str(snapshot.total_value_usd.quantize(__import__("decimal").Decimal("0.00000001"))),
                "createdAt": snapshot.created_at.replace(tzinfo=UTC).isoformat(),
            }
            for snapshot in snapshots
        ]

    @app.get("/api/snapshots/series")
    def get_snapshot_series(session: Session = Depends(get_session)):
        return list_snapshot_runs(session)

    @app.delete("/api/snapshots/runs/{run_id}", status_code=204)
    def delete_snapshot_series_run(run_id: int, session: Session = Depends(get_session)):
        if not delete_snapshot_run(session, run_id):
            raise HTTPException(status_code=404, detail="Snapshot run not found")

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(snapshot_id: int, session: Session = Depends(get_session)):
        detail = snapshot_detail(session, snapshot_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return detail

    @app.get("/api/schedule")
    def get_schedule(session: Session = Depends(get_session)):
        times = get_schedule_times(session)
        okx_dex_setting = get_or_create_setting(session, "okxDexConfig", "{}")
        okx_dex_config = json.loads(okx_dex_setting.value_json)
        return {
            "snapshotScheduleTimes": times,
            "okxDexApiKey": okx_dex_config.get("apiKey", ""),
            "okxDexSecretConfigured": bool(okx_dex_config.get("apiSecretEncrypted")),
        }

    @app.put("/api/schedule")
    def put_schedule(payload: dict, session: Session = Depends(get_session)):
        times = str(payload.get("snapshotScheduleTimes", app_settings.snapshot_schedule_times))
        try:
            for time_value in [item.strip() for item in times.split(",") if item.strip()]:
                parse_schedule_time(time_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        get_or_create_setting(session, "snapshotScheduleTimes", json.dumps(app_settings.snapshot_schedule_times)).value_json = json.dumps(times)

        okx_dex_api_key = str(payload.get("okxDexApiKey", ""))
        okx_dex_api_secret = str(payload.get("okxDexApiSecret", ""))
        okx_dex_passphrase = str(payload.get("okxDexPassphrase", ""))
        okx_dex_config: dict[str, str] = {}
        if okx_dex_api_key:
            okx_dex_config["apiKey"] = okx_dex_api_key
        if okx_dex_api_secret:
            okx_dex_config["apiSecretEncrypted"] = cipher.encrypt(okx_dex_api_secret)
        if okx_dex_passphrase:
            okx_dex_config["passphraseEncrypted"] = cipher.encrypt(okx_dex_passphrase)

        if okx_dex_config:
            existing = json.loads(get_or_create_setting(session, "okxDexConfig", "{}").value_json)
            existing.update(okx_dex_config)
            get_or_create_setting(session, "okxDexConfig", "{}").value_json = json.dumps(existing)

        session.commit()
        configure_scheduler(get_scheduler_enabled(session), times)
        return get_schedule(session)

    @app.get("/api/system/scheduler")
    def get_scheduler_status(session: Session = Depends(get_session)):
        enabled = get_scheduler_enabled(session)
        schedule_times = get_schedule_times(session)
        return {
            "enabled": enabled,
            "snapshot_schedule_times": schedule_times,
            "timezone": "Asia/Shanghai",
            "jobs": scheduled_jobs_payload(),
        }

    @app.put("/api/system/scheduler")
    def put_scheduler_status(payload: dict, session: Session = Depends(get_session)):
        enabled = bool(payload.get("enabled", True))
        get_or_create_setting(
            session,
            "snapshotSchedulerEnabled",
            json.dumps(app_settings.scheduler_enabled),
        ).value_json = json.dumps(enabled)
        session.commit()
        configure_scheduler(enabled, get_schedule_times(session))
        return get_scheduler_status(session)

    return app
