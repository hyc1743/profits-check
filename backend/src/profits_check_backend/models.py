from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def utc_now() -> datetime:
    return datetime.now(UTC)


class Channel(Base):
    __tablename__ = "channels"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32), default="cex")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    public_config_json: Mapped[str] = mapped_column(Text, default="{}")
    secret_config_encrypted: Mapped[str] = mapped_column(Text, default="{}")
    last_test_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_test_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )

    snapshots: Mapped[list[Snapshot]] = relationship(
        back_populates="channel", cascade="all, delete-orphan"
    )


class Snapshot(Base):
    __tablename__ = "snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    run_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="success")
    total_value_usd: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    channel: Mapped[Channel] = relationship(back_populates="snapshots")
    assets: Mapped[list[SnapshotAsset]] = relationship(
        back_populates="snapshot", cascade="all, delete-orphan"
    )


class SnapshotAsset(Base):
    __tablename__ = "snapshot_assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    snapshot_id: Mapped[int] = mapped_column(ForeignKey("snapshots.id"))
    provider: Mapped[str] = mapped_column(String(32))
    account_scope: Mapped[str] = mapped_column(String(200))
    asset_symbol: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    available: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    locked: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    borrowed: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    value_usd: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")

    snapshot: Mapped[Snapshot] = relationship(back_populates="assets")


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[str] = mapped_column(Text, default="{}")


class LiquidationPosition(Base):
    __tablename__ = "liquidation_positions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    provider: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(32))
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    entry_price: Mapped[Decimal | None] = mapped_column(Numeric(32, 12), nullable=True)
    mark_price: Mapped[Decimal] = mapped_column(Numeric(32, 12), default=Decimal("0"))
    liquidation_price: Mapped[Decimal | None] = mapped_column(Numeric(32, 12), nullable=True)
    distance_percent: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("5"))
    status: Mapped[str] = mapped_column(String(32), default="ok")
    unrealized_pnl: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    margin_mode: Mapped[str | None] = mapped_column(String(32), nullable=True)
    leverage: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_alert_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_alert_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    source_updated_at_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class LiquidationMarginBalance(Base):
    __tablename__ = "liquidation_margin_balances"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"), unique=True)
    provider: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(120))
    wallet_balance: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    margin_balance: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    unrealized_pnl: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    risk_percent: Mapped[Decimal | None] = mapped_column(Numeric(24, 8), nullable=True)
    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("70"))
    status: Mapped[str] = mapped_column(String(32), default="ok")
    last_alert_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_alert_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class AdlPositionSample(Base):
    __tablename__ = "adl_position_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    provider: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(32))
    quantity_abs: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    sampled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AdlEvent(Base):
    __tablename__ = "adl_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    channel_id: Mapped[int] = mapped_column(ForeignKey("channels.id"))
    provider: Mapped[str] = mapped_column(String(32))
    channel_name: Mapped[str] = mapped_column(String(120))
    symbol: Mapped[str] = mapped_column(String(80))
    side: Mapped[str] = mapped_column(String(32))
    previous_quantity_abs: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    current_quantity_abs: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    drop_percent: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    threshold_percent: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("40"))
    window_seconds: Mapped[int] = mapped_column(Integer, default=60)
    status: Mapped[str] = mapped_column(String(32), default="suspected")
    last_alert_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_alert_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_alert_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class AuthSession(Base):
    __tablename__ = "auth_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
