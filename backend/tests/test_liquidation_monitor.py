from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from profits_check_backend.models import Channel
from profits_check_backend.providers.base import ContractPositionRisk
from profits_check_backend.services.liquidation_monitor import run_liquidation_monitor


def position(
    *,
    provider: str = "binance",
    channel_name: str = "Binance",
    symbol: str = "BTCUSDT",
    mark_price: str = "58100",
    liquidation_price: str = "58000",
) -> ContractPositionRisk:
    return ContractPositionRisk(
        provider=provider,
        channel_name=channel_name,
        symbol=symbol,
        side="LONG",
        quantity=Decimal("0.5"),
        entry_price=Decimal("60000"),
        mark_price=Decimal(mark_price),
        liquidation_price=Decimal(liquidation_price),
        unrealized_pnl=Decimal("-950"),
        margin_mode="isolated",
        leverage="20",
        updated_at_ms=1700000000001,
        raw_payload={"symbol": symbol},
    )


def test_position_risk_distance_uses_mark_price() -> None:
    assert position().distance_percent == Decimal("0.17211704")


def test_liquidation_monitor_config_round_trips(client) -> None:
    initial = client.get("/api/liquidation-monitor")

    assert initial.status_code == 200
    assert initial.json()["config"]["monitorEnabled"] is False
    assert initial.json()["config"]["alertEnabled"] is False
    assert initial.json()["config"]["thresholdPercent"] == "5.00000000"
    assert initial.json()["config"]["checkIntervalSeconds"] == 60
    assert initial.json()["config"]["alertIntervalSeconds"] == 900

    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "2",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
            "miaoCode": "miao-123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["monitorEnabled"] is True
    assert payload["config"]["alertEnabled"] is True
    assert payload["config"]["thresholdPercent"] == "2.00000000"
    assert payload["config"]["checkIntervalSeconds"] == 45
    assert payload["config"]["alertIntervalSeconds"] == 120
    assert payload["config"]["miaoCodeConfigured"] is True
    assert "miaoCode" not in payload["config"]


def test_liquidation_monitor_rejects_fractional_threshold(client) -> None:
    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "1.5",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Liquidation threshold must be an integer"


def test_manual_refresh_collects_positions_and_does_not_alert_when_alerts_disabled(client) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position()]

    client.app.state.provider_builder = lambda **_: StubProvider()
    create_response = client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Binance",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    assert create_response.status_code == 201
    update_response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": False,
            "thresholdPercent": "1",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
        },
    )
    assert update_response.status_code == 200

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["status"] == "success"
    assert payload["alertCount"] == 0
    assert payload["positions"][0]["status"] == "warning"
    assert payload["positions"][0]["distancePercent"] == "0.17211704"


def test_manual_refresh_triggers_miaotixing_when_alerts_enabled(client, httpx_mock) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position()]

    client.app.state.provider_builder = lambda **_: StubProvider()
    client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Binance",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "1",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
            "miaoCode": "miao-123",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://miaotixing.com/trigger",
        json={
            "code": 0,
            "msg": "完成",
            "data": {"success_sent": {"mptext": 1, "sms": 0, "phonecall": 1}},
        },
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["alertCount"] == 1
    assert payload["positions"][0]["lastAlertStatus"] == "sent"


def test_liquidation_monitor_uses_configured_alert_interval(client, httpx_mock) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position()]

    client.app.state.provider_builder = lambda **_: StubProvider()
    client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Binance",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "1",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
            "miaoCode": "miao-123",
        },
    )
    for _ in range(2):
        httpx_mock.add_response(
            method="POST",
            url="https://miaotixing.com/trigger",
            json={
                "code": 0,
                "msg": "完成",
                "data": {"success_sent": {"mptext": 1, "sms": 0, "phonecall": 1}},
            },
        )

    now = datetime(2026, 5, 12, 8, 0, tzinfo=UTC)
    def run_at(timestamp):
        with client.app.state.session_factory() as session:
            channels = list(session.scalars(select(Channel).where(Channel.enabled.is_(True))))
            return asyncio.run(
                run_liquidation_monitor(
                    session=session,
                    channels=channels,
                    cipher=client.app.state.cipher,
                    provider_builder=client.app.state.provider_builder,
                    now=timestamp,
                )
            )

    first = run_at(now)
    second = run_at(now + timedelta(seconds=119))
    third = run_at(now + timedelta(seconds=120))

    assert first["alertCount"] == 1
    assert second["alertCount"] == 0
    assert third["alertCount"] == 1


def test_liquidation_monitor_test_alert_uses_configured_miao_code(client, httpx_mock) -> None:
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": False,
            "thresholdPercent": "5",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
            "miaoCode": "miao-123",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://miaotixing.com/trigger",
        json={
            "code": 0,
            "msg": "完成",
            "data": {"success_sent": {"mptext": 1, "sms": 0, "phonecall": 1}},
        },
    )

    response = client.post("/api/liquidation-monitor/test-alert")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
