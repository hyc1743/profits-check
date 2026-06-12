from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from http import HTTPStatus
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from fastapi import Cookie, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from profits_check_backend.config import AppSettings, get_settings
from profits_check_backend.db import build_session_factory, init_database
from profits_check_backend.models import (
    AppSetting,
    Channel,
    DailyFundingFeeSummary,
    MonthlyFundingFeeSummary,
    Snapshot,
    SnapshotAsset,
)
from profits_check_backend.providers.onchain import collect_supported_evm_chains
from profits_check_backend.providers.registry import build_provider
from profits_check_backend.security import (
    PASSWORD_SETTING_KEY,
    SESSION_COOKIE_NAME,
    SecretCipher,
    create_session,
    ensure_admin_password,
    get_valid_session,
    hash_password,
    revoke_all_sessions,
    revoke_session,
    verify_password,
)
from profits_check_backend.services.channels import (
    channel_payload,
    create_channel,
    decode_public_config,
    decode_secret_config,
    get_or_create_setting,
    list_channels,
)
from profits_check_backend.services.funding_fees import (
    CurrentMonthFundingFeeSummary,
    current_month_completed_period,
    current_month_funding_fee_summary_from_database,
    current_month_funding_fee_summary_payload,
    date_range,
    ensure_daily_funding_fee_summary,
    ensure_previous_month_funding_fee_summary,
    funding_fee_summary_from_daily_model,
    funding_fee_summary_payload,
    is_daily_funding_fee_summary_complete,
    monthly_funding_fee_summary_payload,
    previous_month_period,
    recent_seven_day_summary_from_database,
    running_monthly_funding_fee_summary_payload,
)
from profits_check_backend.services.liquidation_monitor import (
    get_liquidation_monitor_payload,
    load_liquidation_monitor_config,
    run_liquidation_monitor,
    save_liquidation_monitor_config,
    send_test_bark_alert,
    send_test_liquidation_alert,
    send_test_miaotixing_alert,
)
from profits_check_backend.services.snapshots import (
    _get_okx_dex_secrets,
    collect_live_summary,
    delete_all_snapshots,
    delete_snapshot_run,
    execute_snapshot_run,
    get_latest_summary,
    list_snapshot_runs,
    quantize_decimal,
    snapshot_detail,
    update_portfolio_inclusion_rules,
)

SECRET_PUBLIC_CONFIG_KEYS = {
    "apiKey",
    "api_key",
    "apiSecret",
    "api_secret",
    "passphrase",
    "secret",
    "password",
}
logger = logging.getLogger("profits_check.api")

CUSTOM_URL_KEYS = {
    "baseUrl",
    "base_url",
    "futuresBaseUrl",
    "futures_base_url",
    "rpcUrl",
    "rpc_url",
}


class DateLockRegistry:
    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def acquire(self, key: str, *, blocking: bool = False) -> threading.Lock | None:
        with self._guard:
            lock = self._locks.setdefault(key, threading.Lock())
        if not lock.acquire(blocking=blocking):
            return None
        return lock


def validate_onchain_public_config(config: dict[str, object]) -> None:
    wallet_addresses = config.get("walletAddresses", [])
    chain_indexes = config.get("chainIndexes", [])
    if not isinstance(wallet_addresses, list) or not any(
        str(item).strip() for item in wallet_addresses
    ):
        raise ValueError("At least one wallet address is required")
    if not isinstance(chain_indexes, list) or not any(str(item).strip() for item in chain_indexes):
        raise ValueError("At least one EVM chain is required")


class LoginPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=1024)


class ChangePasswordPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(alias="currentPassword", min_length=1, max_length=1024)
    new_password: str = Field(alias="newPassword", min_length=12, max_length=1024)


class ChannelPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider: str | None = Field(default=None, max_length=32)
    provider_type: str | None = Field(default=None, alias="provider_type", max_length=32)
    kind: str = Field(default="cex", max_length=32)
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    public_config: dict[str, object] = Field(default_factory=dict, alias="publicConfig")
    config: dict[str, object] | None = None
    secret_config: dict[str, str] = Field(default_factory=dict, alias="secretConfig")
    secrets: dict[str, str] | None = None

    @field_validator("provider", "provider_type")
    @classmethod
    def validate_provider(cls, value: str | None) -> str | None:
        if value is None:
            return value
        from profits_check_backend.domain.models import ProviderType

        try:
            ProviderType(value)
        except ValueError as exc:
            raise ValueError("Unsupported provider") from exc
        return value

    @model_validator(mode="after")
    def require_provider(self) -> ChannelPayload:
        if self.provider is None and self.provider_type is None:
            raise ValueError("provider is required")
        return self

    def provider_value(self) -> str:
        return str(self.provider or self.provider_type)

    @field_validator("public_config", "config")
    @classmethod
    def validate_public_config(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return value
        forbidden = SECRET_PUBLIC_CONFIG_KEYS.intersection(value)
        if forbidden:
            raise ValueError("Secret fields must be sent in secretConfig")
        if CUSTOM_URL_KEYS.intersection(value):
            raise ValueError("Custom provider URLs are disabled")
        return value

    def merged_public_config(self) -> dict[str, object]:
        return self.public_config if self.config is None else self.config

    def merged_secret_config(self) -> dict[str, str]:
        return self.secret_config if self.secrets is None else self.secrets


class ChannelUpdatePayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    provider: str | None = Field(default=None, max_length=32)
    provider_type: str | None = Field(default=None, alias="provider_type", max_length=32)
    kind: str | None = Field(default=None, max_length=32)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    enabled: bool | None = None
    public_config: dict[str, object] | None = Field(default=None, alias="publicConfig")
    config: dict[str, object] | None = None
    secret_config: dict[str, str] | None = Field(default=None, alias="secretConfig")
    secrets: dict[str, str] | None = None

    @field_validator("public_config", "config")
    @classmethod
    def validate_public_config(cls, value: dict[str, object] | None) -> dict[str, object] | None:
        if value is None:
            return value
        forbidden = SECRET_PUBLIC_CONFIG_KEYS.intersection(value)
        if forbidden:
            raise ValueError("Secret fields must be sent in secretConfig")
        if CUSTOM_URL_KEYS.intersection(value):
            raise ValueError("Custom provider URLs are disabled")
        return value

    def merged_public_config(self) -> dict[str, object] | None:
        return self.public_config if self.config is None else self.config

    def merged_secret_config(self) -> dict[str, str] | None:
        return self.secret_config if self.secrets is None else self.secrets


class LiquidationMonitorPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    monitor_enabled: bool | None = Field(default=None, alias="monitorEnabled")
    threshold_percent: Decimal | None = Field(default=None, alias="thresholdPercent", gt=0)
    position_monitor_enabled: bool | None = Field(default=None, alias="positionMonitorEnabled")
    position_threshold_percent: Decimal | None = Field(
        default=None, alias="positionThresholdPercent", gt=0
    )
    margin_balance_monitor_enabled: bool | None = Field(
        default=None, alias="marginBalanceMonitorEnabled"
    )
    margin_balance_threshold_percent: Decimal | None = Field(
        default=None, alias="marginBalanceThresholdPercent", gt=0
    )
    adl_monitor_enabled: bool | None = Field(default=None, alias="adlMonitorEnabled")
    adl_threshold_percent: Decimal | None = Field(default=None, alias="adlThresholdPercent", gt=0)
    adl_window_seconds: int | None = Field(default=None, alias="adlWindowSeconds", gt=0)
    adl_sample_interval_seconds: int | None = Field(
        default=None, alias="adlSampleIntervalSeconds", gt=0
    )
    adl_start_time: str | None = Field(default=None, alias="adlStartTime", max_length=5)
    adl_end_time: str | None = Field(default=None, alias="adlEndTime", max_length=5)
    check_interval_seconds: int = Field(alias="checkIntervalSeconds", gt=0)
    alert_interval_seconds: int = Field(alias="alertIntervalSeconds", gt=0)
    miao_code: str | None = Field(default=None, alias="miaoCode", max_length=256)
    bark_push_url: str | None = Field(default=None, alias="barkPushUrl", max_length=2048)

    @property
    def resolved_position_monitor_enabled(self) -> bool:
        if self.position_monitor_enabled is not None:
            return self.position_monitor_enabled
        return bool(self.monitor_enabled)

    @property
    def resolved_margin_balance_monitor_enabled(self) -> bool:
        return bool(self.margin_balance_monitor_enabled)

    @property
    def resolved_adl_monitor_enabled(self) -> bool:
        return bool(self.adl_monitor_enabled)

    @property
    def resolved_monitor_enabled(self) -> bool:
        if self.monitor_enabled is not None and self.position_monitor_enabled is None:
            return self.monitor_enabled
        return (
            self.resolved_position_monitor_enabled
            or self.resolved_margin_balance_monitor_enabled
            or self.resolved_adl_monitor_enabled
        )


class PortfolioInclusionRuleItemPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(min_length=1, max_length=260)
    included_in_totals: bool = Field(alias="includedInTotals")


class PortfolioInclusionRulesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[PortfolioInclusionRuleItemPayload]


def configure_application_logging() -> None:
    app_logger = logging.getLogger("profits_check")
    app_logger.setLevel(logging.ERROR)
    app_logger.propagate = False
    if any(handler.name == "profits_check.stderr" for handler in app_logger.handlers):
        return
    handler = logging.StreamHandler()
    handler.name = "profits_check.stderr"
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    app_logger.addHandler(handler)


def create_app(settings: AppSettings | None = None) -> FastAPI:
    configure_application_logging()
    app_settings = settings or get_settings()
    session_factory = build_session_factory(app_settings)
    init_database(session_factory)
    cipher = SecretCipher.from_settings(app_settings)
    scheduler_timezone = ZoneInfo("Asia/Shanghai")
    scheduler = BackgroundScheduler(timezone=scheduler_timezone)
    snapshot_lock = threading.Lock()
    live_summary_lock = threading.Lock()
    channel_test_lock = threading.Lock()
    liquidation_monitor_lock = threading.Lock()
    monthly_funding_fee_lock = threading.Lock()
    current_month_funding_fee_lock = threading.Lock()
    daily_funding_fee_date_locks = DateLockRegistry()

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

    def _has_snapshot_today(session: Session) -> bool:
        now_utc = datetime.now(UTC)
        utc8_today = (now_utc + timedelta(hours=8)).date()
        cutoff = now_utc - timedelta(hours=48)
        recent = list(session.scalars(select(Snapshot).where(Snapshot.created_at >= cutoff)))
        for s in recent:
            created = s.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=UTC)
            if (created + timedelta(hours=8)).date() == utc8_today:
                return True
        return False

    def run_scheduled_snapshot() -> None:
        if not snapshot_lock.acquire(blocking=False):
            return
        with session_factory() as session:
            try:
                if _has_snapshot_today(session):
                    return
                channels = list(
                    session.scalars(
                        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                    )
                )
                asyncio.run(
                    execute_snapshot_run(
                        session=session,
                        channels=channels,
                        cipher=cipher,
                        provider_builder=app.state.provider_builder,
                    )
                )
            finally:
                snapshot_lock.release()

    def run_scheduled_liquidation_monitor() -> None:
        if not liquidation_monitor_lock.acquire(blocking=False):
            return
        with session_factory() as session:
            try:
                config = load_liquidation_monitor_config(session, cipher)
                if not config.monitor_enabled:
                    return
                channels = list(
                    session.scalars(
                        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                    )
                )
                asyncio.run(
                    run_liquidation_monitor(
                        session=session,
                        channels=channels,
                        cipher=cipher,
                        provider_builder=app.state.provider_builder,
                    )
                )
            finally:
                liquidation_monitor_lock.release()

    def run_previous_month_funding_fee_summary() -> None:
        if not monthly_funding_fee_lock.acquire(blocking=False):
            return
        with session_factory() as session:
            try:
                channels = list(
                    session.scalars(
                        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                    )
                )
                if not channels:
                    return
                ensure_previous_month_funding_fee_summary(
                    session=session,
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("api.monthly_funding_fees.startup_failed")
            finally:
                monthly_funding_fee_lock.release()

    def run_current_month_funding_fee_summary() -> None:
        if not current_month_funding_fee_lock.acquire(blocking=False):
            return
        with session_factory() as session:
            try:
                channels = list(
                    session.scalars(
                        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                    )
                )
                if not channels:
                    return
                ensure_current_month_funding_fee_summaries_with_date_locks(
                    session=session,
                    channels=channels,
                )
                session.commit()
            except Exception:
                session.rollback()
                logger.exception("api.current_month_funding_fees.startup_failed")
            finally:
                current_month_funding_fee_lock.release()

    def run_daily_funding_fee_increment() -> None:
        with session_factory() as session:
            try:
                yesterday = (datetime.now(UTC).astimezone(scheduler_timezone).date() - timedelta(days=1)).isoformat()
                channels = list(
                    session.scalars(
                        select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                    )
                )
                if not channels:
                    return
                ensure_daily_funding_fee_summary_with_date_lock(
                    session=session,
                    date=yesterday,
                    channels=channels,
                )
                session.commit()
            except HTTPException as exc:
                session.rollback()
                if exc.status_code != 409:
                    raise
            except Exception:
                session.rollback()
                logger.exception("api.daily_funding_fees.increment_failed")

    def run_startup_funding_fee_summaries() -> None:
        run_previous_month_funding_fee_summary()
        run_current_month_funding_fee_summary()

    def ensure_daily_funding_fee_summary_with_date_lock(
        *,
        session: Session,
        date: str,
        channels: list[Channel],
        wait_for_running: bool = False,
    ) -> DailyFundingFeeSummary:
        cached = session.scalar(
            select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == date)
        )
        if cached is not None and is_daily_funding_fee_summary_complete(cached):
            return cached
        date_lock = daily_funding_fee_date_locks.acquire(date, blocking=wait_for_running)
        if date_lock is None:
            cached = session.scalar(
                select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == date)
            )
            if cached is not None and is_daily_funding_fee_summary_complete(cached):
                return cached
            raise HTTPException(status_code=409, detail="Daily funding fee summary is running")
        try:
            cached = session.scalar(
                select(DailyFundingFeeSummary).where(DailyFundingFeeSummary.date == date)
            )
            if cached is not None and is_daily_funding_fee_summary_complete(cached):
                return cached
            summary = ensure_daily_funding_fee_summary(
                session=session,
                date=date,
                channels=channels,
                cipher=cipher,
                provider_builder=app.state.provider_builder,
            )
            session.commit()
            return summary
        finally:
            date_lock.release()

    def ensure_current_month_funding_fee_summaries_with_date_locks(
        *,
        session: Session,
        channels: list[Channel],
    ) -> CurrentMonthFundingFeeSummary:
        now = datetime.now(UTC)
        _, start_date, end_date = current_month_completed_period(now)
        if end_date is not None:
            for date in date_range(start_date, end_date):
                ensure_daily_funding_fee_summary_with_date_lock(
                    session=session,
                    date=date,
                    channels=channels,
                    wait_for_running=True,
                )
        return current_month_funding_fee_summary_from_database(session, now_factory=lambda: now)

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
            if not job.id.startswith("scheduled-snapshot"):
                continue
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

    def configure_liquidation_monitor_scheduler(config) -> None:
        for job in scheduler.get_jobs():
            if job.id == "liquidation-monitor":
                scheduler.remove_job(job.id)
        if not config.monitor_enabled:
            return
        interval_seconds = config.check_interval_seconds
        if config.adl_monitor_enabled:
            interval_seconds = min(interval_seconds, config.adl_sample_interval_seconds)
        scheduler.add_job(
            run_scheduled_liquidation_monitor,
            IntervalTrigger(seconds=interval_seconds, timezone=scheduler_timezone),
            id="liquidation-monitor",
            replace_existing=True,
            max_instances=1,
        )

    def configure_funding_fee_scheduler() -> None:
        scheduler.add_job(
            run_daily_funding_fee_increment,
            CronTrigger(hour=8, minute=5, timezone=scheduler_timezone),
            id="daily-funding-fee-increment",
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
        app.state.snapshot_lock = snapshot_lock
        app.state.live_summary_lock = live_summary_lock
        app.state.channel_test_lock = channel_test_lock
        app.state.liquidation_monitor_lock = liquidation_monitor_lock
        app.state.monthly_funding_fee_lock = monthly_funding_fee_lock
        app.state.current_month_funding_fee_lock = current_month_funding_fee_lock
        app.state.daily_funding_fee_date_locks = daily_funding_fee_date_locks
        with session_factory() as session:
            ensure_admin_password(session, app_settings)
            configure_scheduler(get_scheduler_enabled(session), get_schedule_times(session))
            configure_liquidation_monitor_scheduler(
                load_liquidation_monitor_config(session, cipher)
            )
            configure_funding_fee_scheduler()
        scheduler.start()
        threading.Thread(target=run_startup_funding_fee_summaries, daemon=True).start()
        yield
        scheduler.shutdown(wait=False)

    app = FastAPI(title="Profits Check", lifespan=lifespan)

    def get_session() -> Iterator[Session]:
        with session_factory() as session:
            yield session

    def require_session(
        profits_check_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        session: Session = Depends(get_session),
    ):
        auth_session = get_valid_session(session, profits_check_session)
        if auth_session is None:
            raise HTTPException(
                status_code=HTTPStatus.UNAUTHORIZED, detail="Authentication required"
            )
        return auth_session

    def set_session_cookie(response: Response, token: str) -> None:
        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            httponly=True,
            secure=app_settings.cookie_secure,
            samesite="lax",
            max_age=app_settings.session_ttl_days * 24 * 60 * 60,
            path="/",
        )

    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(SESSION_COOKIE_NAME, path="/", httponly=True, samesite="lax")

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/auth/login")
    def login(payload: LoginPayload, response: Response, session: Session = Depends(get_session)):
        password_setting = session.get(AppSetting, PASSWORD_SETTING_KEY)
        if password_setting is None:
            ensure_admin_password(session, app_settings)
            password_setting = session.get(AppSetting, PASSWORD_SETTING_KEY)
        if password_setting is None or not verify_password(
            payload.password, json.loads(password_setting.value_json)
        ):
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Invalid password")
        token, _ = create_session(session, ttl_days=app_settings.session_ttl_days)
        set_session_cookie(response, token)
        return {"authenticated": True}

    @app.post("/api/auth/logout")
    def logout(
        response: Response,
        profits_check_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        session: Session = Depends(get_session),
    ):
        revoke_session(session, profits_check_session)
        clear_session_cookie(response)
        return {"authenticated": False}

    @app.get("/api/auth/session")
    def auth_session(
        profits_check_session: str | None = Cookie(default=None, alias=SESSION_COOKIE_NAME),
        session: Session = Depends(get_session),
    ):
        return {"authenticated": get_valid_session(session, profits_check_session) is not None}

    @app.put("/api/auth/password")
    def change_password(
        payload: ChangePasswordPayload,
        response: Response,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        password_setting = session.get(AppSetting, PASSWORD_SETTING_KEY)
        if password_setting is None or not verify_password(
            payload.current_password,
            json.loads(password_setting.value_json),
        ):
            raise HTTPException(status_code=HTTPStatus.UNAUTHORIZED, detail="Invalid password")
        password_setting.value_json = json.dumps(hash_password(payload.new_password))
        session.commit()
        revoke_all_sessions(session)
        clear_session_cookie(response)
        return {"authenticated": False}

    @app.get("/api/channels")
    def get_channels(_: object = Depends(require_session), session: Session = Depends(get_session)):
        return [channel_payload(channel, cipher) for channel in list_channels(session)]

    @app.get("/api/onchain/chains")
    def get_onchain_chains(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        try:
            return asyncio.run(collect_supported_evm_chains(_get_okx_dex_secrets(session, cipher)))
        except Exception as exc:
            raise HTTPException(status_code=400, detail="Failed to load EVM chains") from exc

    @app.post("/api/channels", status_code=201)
    def post_channel(
        payload: ChannelPayload,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        public_config = payload.merged_public_config()
        secret_config = payload.merged_secret_config()
        if payload.provider_value() == "onchain":
            try:
                validate_onchain_public_config(public_config)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        channel = create_channel(
            session,
            cipher=cipher,
            name=payload.name,
            provider=payload.provider_value(),
            kind=payload.kind,
            enabled=payload.enabled,
            public_config=public_config,
            secret_config=dict(secret_config),
        )
        return channel_payload(channel, cipher)

    @app.put("/api/channels/{channel_id}")
    def put_channel(
        channel_id: int,
        payload: ChannelUpdatePayload,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")

        if payload.name is not None:
            channel.name = payload.name
        if payload.provider is not None or payload.provider_type is not None:
            channel.provider = str(payload.provider or payload.provider_type or channel.provider)
        if payload.kind is not None:
            channel.kind = payload.kind
        if payload.enabled is not None:
            channel.enabled = payload.enabled

        public_config = payload.merged_public_config()
        if public_config is not None:
            provider_value = str(payload.provider or payload.provider_type or channel.provider)
            if provider_value == "onchain":
                try:
                    validate_onchain_public_config(public_config)
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc
            channel.public_config_json = json.dumps(public_config)

        secret_config = payload.merged_secret_config()
        if secret_config is not None and secret_config:
            new_secrets = {
                key: cipher.encrypt(str(value)) for key, value in secret_config.items() if value
            }
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
    def test_channel(
        channel_id: int,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")

        secrets = decode_secret_config(channel, cipher)
        if channel.provider == "onchain":
            secrets.update(_get_okx_dex_secrets(session, cipher))
        provider = app.state.provider_builder(
            provider_type=channel.provider,
            channel_name=channel.name,
            config=decode_public_config(channel),
            secrets=secrets,
        )
        if not app.state.channel_test_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Channel test is already running")
        try:
            snapshot = asyncio.run(provider.collect_snapshot())
        except Exception as exc:
            channel.last_test_status = "failed"
            channel.last_test_error = str(exc)
            session.commit()
            raise HTTPException(status_code=400, detail="Channel test failed") from exc
        finally:
            app.state.channel_test_lock.release()

        channel.last_test_status = "ok"
        channel.last_test_error = None
        session.commit()
        return {
            "status": "ok",
            "assetCount": len(snapshot.assets),
            "totalValueUsd": quantize_decimal(snapshot.total_value_usd),
        }

    @app.get("/api/liquidation-monitor")
    def get_liquidation_monitor(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        return get_liquidation_monitor_payload(session, cipher)

    @app.put("/api/liquidation-monitor")
    def put_liquidation_monitor(
        payload: LiquidationMonitorPayload,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        try:
            config = save_liquidation_monitor_config(
                session,
                cipher,
                monitor_enabled=payload.resolved_monitor_enabled,
                threshold_percent=payload.threshold_percent,
                position_monitor_enabled=payload.resolved_position_monitor_enabled,
                position_threshold_percent=payload.position_threshold_percent,
                margin_balance_monitor_enabled=payload.resolved_margin_balance_monitor_enabled,
                margin_balance_threshold_percent=payload.margin_balance_threshold_percent,
                adl_monitor_enabled=payload.resolved_adl_monitor_enabled,
                adl_threshold_percent=payload.adl_threshold_percent,
                adl_window_seconds=payload.adl_window_seconds,
                adl_sample_interval_seconds=payload.adl_sample_interval_seconds,
                adl_start_time=payload.adl_start_time,
                adl_end_time=payload.adl_end_time,
                check_interval_seconds=payload.check_interval_seconds,
                alert_interval_seconds=payload.alert_interval_seconds,
                miao_code=payload.miao_code,
                bark_push_url=payload.bark_push_url,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        configure_liquidation_monitor_scheduler(config)
        return get_liquidation_monitor_payload(session, cipher)

    @app.post("/api/liquidation-monitor/refresh")
    def refresh_liquidation_monitor(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        if not app.state.liquidation_monitor_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Liquidation monitor is already running")
        try:
            channels = list(
                session.scalars(
                    select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                )
            )
            return asyncio.run(
                run_liquidation_monitor(
                    session=session,
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
            )
        finally:
            app.state.liquidation_monitor_lock.release()

    @app.post("/api/liquidation-monitor/test-alert")
    def test_liquidation_monitor_alert(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        try:
            return asyncio.run(send_test_liquidation_alert(session, cipher))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/liquidation-monitor/test-alert/miaotixing")
    def test_liquidation_monitor_miaotixing_alert(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        try:
            return asyncio.run(send_test_miaotixing_alert(session, cipher))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/liquidation-monitor/test-alert/bark")
    def test_liquidation_monitor_bark_alert(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        try:
            return asyncio.run(send_test_bark_alert(session, cipher))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/channels/{channel_id}", status_code=204)
    def delete_channel(
        channel_id: int,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        session.delete(channel)
        session.commit()

    @app.post("/api/channels/{channel_id}/snapshots", status_code=201)
    def snapshot_channel(
        channel_id: int,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        channel = session.get(Channel, channel_id)
        if channel is None:
            raise HTTPException(status_code=404, detail="Channel not found")
        if not app.state.snapshot_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Snapshot run is already running")
        try:
            result = asyncio.run(
                execute_snapshot_run(
                    session=session,
                    channels=[channel],
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
            )
        finally:
            app.state.snapshot_lock.release()
        detail = snapshot_detail(session, result["id"])
        if detail is None:
            raise HTTPException(status_code=500, detail="Snapshot was not persisted")
        return detail

    @app.get("/api/summary")
    def summary_legacy(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        return get_latest_summary(session)

    @app.get("/api/summary/latest")
    def summary_latest(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        return get_latest_summary(session)

    @app.get("/api/summary/live")
    def summary_live(_: object = Depends(require_session), session: Session = Depends(get_session)):
        channels = list(
            session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id))
        )
        if not app.state.live_summary_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Live summary is already running")
        try:
            return asyncio.run(
                collect_live_summary(
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                    session=session,
                )
            )
        finally:
            app.state.live_summary_lock.release()

    @app.get("/api/funding-fees")
    def funding_fees(
        date: str,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        started_at = time.perf_counter()
        channels = list(
            session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id))
        )
        logger.info("api.funding_fees.start date=%s enabled_channels=%s", date, len(channels))
        try:
            cached = ensure_daily_funding_fee_summary_with_date_lock(
                session=session,
                date=date,
                channels=channels,
                wait_for_running=True,
            )
            session.commit()
            summary = funding_fee_summary_from_daily_model(
                cached,
                recent_seven_days=recent_seven_day_summary_from_database(
                    session,
                    date,
                )
            )
        except ValueError as exc:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.warning(
                "api.funding_fees.invalid_date date=%s duration_ms=%s error=%s",
                date,
                duration_ms,
                exc,
            )
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            duration_ms = int((time.perf_counter() - started_at) * 1000)
            logger.exception(
                "api.funding_fees.failed date=%s enabled_channels=%s duration_ms=%s",
                date,
                len(channels),
                duration_ms,
            )
            raise
        duration_ms = int((time.perf_counter() - started_at) * 1000)
        failed_count = sum(1 for item in summary.channels if item.status == "failed")
        logger.info(
            "api.funding_fees.success date=%s enabled_channels=%s failed_channels=%s "
            "records=%s duration_ms=%s",
            date,
            len(channels),
            failed_count,
            summary.records_count,
            duration_ms,
        )
        return funding_fee_summary_payload(summary)

    @app.get("/api/funding-fees/monthly/current")
    def current_monthly_funding_fees(
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        if not app.state.current_month_funding_fee_lock.acquire(blocking=False):
            summary = current_month_funding_fee_summary_from_database(session)
            return current_month_funding_fee_summary_payload(summary)
        try:
            channels = list(
                session.scalars(
                    select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                )
            )
            if channels:
                summary = ensure_current_month_funding_fee_summaries_with_date_locks(
                    session=session,
                    channels=channels,
                )
                session.commit()
            else:
                summary = current_month_funding_fee_summary_from_database(session)
        finally:
            app.state.current_month_funding_fee_lock.release()
        return current_month_funding_fee_summary_payload(summary)

    @app.get("/api/funding-fees/monthly/previous")
    def previous_monthly_funding_fees(
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        month, start_date, end_date = previous_month_period()
        summary = session.scalar(
            select(MonthlyFundingFeeSummary).where(MonthlyFundingFeeSummary.month == month)
        )
        if summary is None:
            channels = list(
                session.scalars(
                    select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id)
                )
            )
            if not channels:
                raise HTTPException(status_code=404, detail="Monthly funding fee summary not found")
            if not app.state.monthly_funding_fee_lock.acquire(blocking=False):
                return running_monthly_funding_fee_summary_payload(
                    month=month,
                    start_date=start_date,
                    end_date=end_date,
                )
            try:
                summary = ensure_previous_month_funding_fee_summary(
                    session=session,
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
                session.commit()
            finally:
                app.state.monthly_funding_fee_lock.release()
        return monthly_funding_fee_summary_payload(summary)

    @app.put("/api/portfolio-inclusion-rules")
    def put_portfolio_inclusion_rules(
        payload: PortfolioInclusionRulesPayload,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        return {
            "items": update_portfolio_inclusion_rules(
                session,
                [
                    {
                        "key": item.key,
                        "includedInTotals": item.included_in_totals,
                    }
                    for item in payload.items
                ],
            )
        }

    @app.post("/api/snapshots/run")
    def run_snapshots(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        channels = list(
            session.scalars(select(Channel).where(Channel.enabled.is_(True)).order_by(Channel.id))
        )
        if not app.state.snapshot_lock.acquire(blocking=False):
            raise HTTPException(status_code=409, detail="Snapshot run is already running")
        try:
            return asyncio.run(
                execute_snapshot_run(
                    session=session,
                    channels=channels,
                    cipher=cipher,
                    provider_builder=app.state.provider_builder,
                )
            )
        finally:
            app.state.snapshot_lock.release()

    @app.get("/api/snapshots")
    def get_snapshots(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        snapshots = list(session.scalars(select(Snapshot).order_by(Snapshot.id)))
        return [
            {
                "id": snapshot.id,
                "runId": snapshot.run_id or snapshot.id,
                "channelId": snapshot.channel_id,
                "status": snapshot.status,
                "totalValueUsd": str(
                    snapshot.total_value_usd.quantize(__import__("decimal").Decimal("0.00000001"))
                ),
                "createdAt": snapshot.created_at.replace(tzinfo=UTC).isoformat(),
            }
            for snapshot in snapshots
        ]

    @app.get("/api/snapshots/series")
    def get_snapshot_series(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        return list_snapshot_runs(session)

    @app.delete("/api/snapshots/runs/{run_id}", status_code=204)
    def delete_snapshot_series_run(
        run_id: int, _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        if not delete_snapshot_run(session, run_id):
            raise HTTPException(status_code=404, detail="Snapshot run not found")

    @app.delete("/api/snapshots", status_code=204)
    def delete_all_snapshot_series(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        delete_all_snapshots(session)

    @app.get("/api/snapshots/{snapshot_id}")
    def get_snapshot(
        snapshot_id: int,
        _: object = Depends(require_session),
        session: Session = Depends(get_session),
    ):
        detail = snapshot_detail(session, snapshot_id)
        if detail is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return detail

    @app.get("/api/schedule")
    def get_schedule(_: object = Depends(require_session), session: Session = Depends(get_session)):
        times = get_schedule_times(session)
        okx_dex_setting = get_or_create_setting(session, "okxDexConfig", "{}")
        okx_dex_config = json.loads(okx_dex_setting.value_json)
        return {
            "snapshotScheduleTimes": times,
            "okxDexApiKey": okx_dex_config.get("apiKey", ""),
            "okxDexSecretConfigured": bool(okx_dex_config.get("apiSecretEncrypted")),
        }

    @app.put("/api/schedule")
    def put_schedule(
        payload: dict, _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        times = str(payload.get("snapshotScheduleTimes", app_settings.snapshot_schedule_times))
        try:
            for time_value in [item.strip() for item in times.split(",") if item.strip()]:
                parse_schedule_time(time_value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        get_or_create_setting(
            session, "snapshotScheduleTimes", json.dumps(app_settings.snapshot_schedule_times)
        ).value_json = json.dumps(times)

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
        return get_schedule(object(), session)

    @app.get("/api/system/scheduler")
    def get_scheduler_status(
        _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        enabled = get_scheduler_enabled(session)
        schedule_times = get_schedule_times(session)
        return {
            "enabled": enabled,
            "snapshot_schedule_times": schedule_times,
            "timezone": "Asia/Shanghai",
            "jobs": scheduled_jobs_payload(),
        }

    @app.put("/api/system/scheduler")
    def put_scheduler_status(
        payload: dict, _: object = Depends(require_session), session: Session = Depends(get_session)
    ):
        enabled = bool(payload.get("enabled", True))
        get_or_create_setting(
            session,
            "snapshotSchedulerEnabled",
            json.dumps(app_settings.scheduler_enabled),
        ).value_json = json.dumps(enabled)
        session.commit()
        configure_scheduler(enabled, get_schedule_times(session))
        return get_scheduler_status(object(), session)

    @app.post("/api/system/reset")
    def reset_system(_: object = Depends(require_session), session: Session = Depends(get_session)):
        deleted_assets = session.scalar(select(func.count()).select_from(SnapshotAsset)) or 0
        deleted_snapshots = session.scalar(select(func.count()).select_from(Snapshot)) or 0
        deleted_channels = session.scalar(select(func.count()).select_from(Channel)) or 0

        session.execute(delete(SnapshotAsset))
        session.execute(delete(Snapshot))
        session.execute(delete(Channel))
        session.commit()

        return {
            "status": "ok",
            "deletedChannels": deleted_channels,
            "deletedSnapshots": deleted_snapshots,
            "deletedAssets": deleted_assets,
        }

    return app
