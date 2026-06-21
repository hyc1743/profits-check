from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
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
    inclusion_key: Mapped[str | None] = mapped_column(String(260), nullable=True)
    included_in_totals: Mapped[bool] = mapped_column(Boolean, default=True)
    raw_payload_json: Mapped[str] = mapped_column(Text, default="{}")

    snapshot: Mapped[Snapshot] = relationship(back_populates="assets")


class PortfolioInclusionRule(Base):
    __tablename__ = "portfolio_inclusion_rules"

    key: Mapped[str] = mapped_column(String(260), primary_key=True)
    included_in_totals: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class MonthlyFundingFeeSummary(Base):
    __tablename__ = "monthly_funding_fee_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    month: Mapped[str] = mapped_column(String(7), unique=True)
    start_date: Mapped[str] = mapped_column(String(10))
    end_date: Mapped[str] = mapped_column(String(10))
    received: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    paid: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    records_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class DailyFundingFeeSummary(Base):
    __tablename__ = "daily_funding_fee_summaries"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    date: Mapped[str] = mapped_column(String(10), unique=True)
    start_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    end_time: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    paid: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    records_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
    channels: Mapped[list[DailyFundingFeeChannelSummary]] = relationship(
        back_populates="daily_summary",
        cascade="all, delete-orphan",
    )
    asset_details: Mapped[list[DailyFundingFeeAssetSummary]] = relationship(
        back_populates="daily_summary",
        cascade="all, delete-orphan",
    )


class DailyFundingFeeChannelSummary(Base):
    __tablename__ = "daily_funding_fee_channel_summaries"
    __table_args__ = (
        UniqueConstraint("daily_summary_id", "channel_id", name="uq_daily_funding_channel"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    daily_summary_id: Mapped[int] = mapped_column(ForeignKey("daily_funding_fee_summaries.id"))
    channel_id: Mapped[int] = mapped_column(Integer)
    channel_name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32))
    received: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    paid: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    net: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    records_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(32), default="success")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    daily_summary: Mapped[DailyFundingFeeSummary] = relationship(back_populates="channels")


class DailyFundingFeeAssetSummary(Base):
    __tablename__ = "daily_funding_fee_asset_summaries"
    __table_args__ = (
        UniqueConstraint(
            "daily_summary_id",
            "channel_id",
            "asset",
            name="uq_daily_funding_asset",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    daily_summary_id: Mapped[int] = mapped_column(ForeignKey("daily_funding_fee_summaries.id"))
    channel_id: Mapped[int] = mapped_column(Integer)
    channel_name: Mapped[str] = mapped_column(String(120))
    provider: Mapped[str] = mapped_column(String(32))
    asset: Mapped[str] = mapped_column(String(32))
    amount: Mapped[Decimal] = mapped_column(Numeric(24, 8), default=Decimal("0"))
    records_count: Mapped[int] = mapped_column(Integer, default=0)

    daily_summary: Mapped[DailyFundingFeeSummary] = relationship(back_populates="asset_details")


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
