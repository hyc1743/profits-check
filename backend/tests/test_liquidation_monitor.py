from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from profits_check_backend.models import Channel, LiquidationMarginBalance
from profits_check_backend.providers.base import ContractMarginBalanceRisk, ContractPositionRisk
from profits_check_backend.services.liquidation_monitor import run_liquidation_monitor


def position(
    *,
    provider: str = "binance",
    channel_name: str = "Binance",
    symbol: str = "BTCUSDT",
    side: str = "LONG",
    quantity: str = "0.5",
    mark_price: str = "58100",
    liquidation_price: str = "58000",
) -> ContractPositionRisk:
    return ContractPositionRisk(
        provider=provider,
        channel_name=channel_name,
        symbol=symbol,
        side=side,
        quantity=Decimal(quantity),
        entry_price=Decimal("60000"),
        mark_price=Decimal(mark_price),
        liquidation_price=Decimal(liquidation_price),
        unrealized_pnl=Decimal("-950"),
        margin_mode="isolated",
        leverage="20",
        updated_at_ms=1700000000001,
        raw_payload={"symbol": symbol},
    )


def margin_balance(
    *,
    provider: str = "binance",
    channel_name: str = "Binance",
    wallet_balance: str = "1000",
    margin_balance_value: str = "650",
    unrealized_pnl: str = "-350",
) -> ContractMarginBalanceRisk:
    return ContractMarginBalanceRisk(
        provider=provider,
        channel_name=channel_name,
        wallet_balance=Decimal(wallet_balance),
        margin_balance=Decimal(margin_balance_value),
        unrealized_pnl=Decimal(unrealized_pnl),
        raw_payload={"asset": "USDT"},
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
    assert payload["config"]["barkPushUrlConfigured"] is False
    assert payload["config"]["miaoCode"] == "miao-123"
    assert "barkPushUrl" not in payload["config"]


def test_liquidation_monitor_config_round_trips_bark_push_url(client) -> None:
    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "2",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["barkPushUrlConfigured"] is True
    assert payload["config"]["barkPushUrl"] == "https://bark.example.com/device-key"

    keep_existing_response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "2",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
        },
    )

    assert keep_existing_response.status_code == 200
    assert keep_existing_response.json()["config"]["barkPushUrlConfigured"] is True

    clear_response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "2",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
            "barkPushUrl": "",
        },
    )

    assert clear_response.status_code == 200
    assert clear_response.json()["config"]["barkPushUrlConfigured"] is False


def test_liquidation_monitor_rejects_invalid_bark_push_url(client) -> None:
    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "thresholdPercent": "2",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
            "barkPushUrl": "ftp://bark.example.com/device-key",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Bark push URL must start with http:// or https://"


def test_liquidation_monitor_config_round_trips_independent_risk_controls(client) -> None:
    initial = client.get("/api/liquidation-monitor")

    assert initial.status_code == 200
    assert initial.json()["config"]["positionMonitorEnabled"] is False
    assert initial.json()["config"]["positionThresholdPercent"] == "5.00000000"
    assert initial.json()["config"]["marginBalanceMonitorEnabled"] is False
    assert initial.json()["config"]["marginBalanceThresholdPercent"] == "70.00000000"

    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": True,
            "positionThresholdPercent": "2",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "75",
            "checkIntervalSeconds": 45,
            "alertIntervalSeconds": 120,
            "miaoCode": "miao-123",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["monitorEnabled"] is True
    assert payload["config"]["positionMonitorEnabled"] is True
    assert payload["config"]["positionThresholdPercent"] == "2.00000000"
    assert payload["config"]["marginBalanceMonitorEnabled"] is True
    assert payload["config"]["marginBalanceThresholdPercent"] == "75.00000000"
    assert payload["config"]["thresholdPercent"] == "2.00000000"


def test_liquidation_monitor_config_round_trips_adl_controls(client) -> None:
    initial = client.get("/api/liquidation-monitor")

    assert initial.status_code == 200
    assert initial.json()["config"]["adlMonitorEnabled"] is False
    assert initial.json()["config"]["adlThresholdPercent"] == "40.00000000"
    assert initial.json()["config"]["adlWindowSeconds"] == 60
    assert initial.json()["config"]["adlSampleIntervalSeconds"] == 30
    assert initial.json()["config"]["adlStartTime"] == "00:00"
    assert initial.json()["config"]["adlEndTime"] == "23:59"

    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "adlMonitorEnabled": True,
            "adlThresholdPercent": "40",
            "adlWindowSeconds": 60,
            "adlSampleIntervalSeconds": 30,
            "adlStartTime": "21:00",
            "adlEndTime": "02:00",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["config"]["monitorEnabled"] is True
    assert payload["config"]["adlMonitorEnabled"] is True
    assert payload["config"]["adlThresholdPercent"] == "40.00000000"
    assert payload["config"]["adlWindowSeconds"] == 60
    assert payload["config"]["adlSampleIntervalSeconds"] == 30
    assert payload["config"]["adlStartTime"] == "21:00"
    assert payload["config"]["adlEndTime"] == "02:00"


def test_liquidation_monitor_rejects_invalid_adl_time(client) -> None:
    response = client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "adlMonitorEnabled": True,
            "adlThresholdPercent": "40",
            "adlWindowSeconds": 60,
            "adlSampleIntervalSeconds": 30,
            "adlStartTime": "24:00",
            "adlEndTime": "02:00",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ADL monitor time must use HH:MM in UTC+8"


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


def test_manual_refresh_keeps_positions_when_margin_balance_collection_fails(client) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position(provider="okx", channel_name="OKX", symbol="LAB-USDT-SWAP")]

        async def collect_contract_margin_balance(self):
            raise RuntimeError("OKX margin risk unavailable")

    client.app.state.provider_builder = lambda **_: StubProvider()
    create_response = client.post(
        "/api/channels",
        json={
            "provider": "okx",
            "kind": "cex",
            "name": "OKX",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret", "passphrase": "pass"},
        },
    )
    assert create_response.status_code == 201
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": True,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "70",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
        },
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["status"] == "partial"
    assert payload["failureCount"] == 1
    assert len(payload["positions"]) == 1
    assert payload["positions"][0]["symbol"] == "LAB-USDT-SWAP"
    assert payload["marginBalances"] == []


def test_margin_balance_collection_is_skipped_when_monitor_is_disabled(client) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position()]

        async def collect_contract_margin_balance(self):
            raise AssertionError("margin balance should not be collected")

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
            "positionMonitorEnabled": True,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "checkIntervalSeconds": 10,
            "alertIntervalSeconds": 120,
        },
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["status"] == "success"
    assert payload["failureCount"] == 0
    assert len(payload["positions"]) == 1
    assert payload["marginBalances"] == []


def test_manual_refresh_collects_margin_balance_risk_by_channel(client) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return []

        async def collect_contract_margin_balance(self):
            return margin_balance()

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
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "70",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
        },
    )
    assert update_response.status_code == 200

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["marginBalances"] == [
        {
            "id": "1:margin-balance",
            "channelId": 1,
            "provider": "binance",
            "channelName": "Binance",
            "walletBalance": "1000.00000000",
            "marginBalance": "650.00000000",
            "unrealizedPnl": "-350.00000000",
            "riskPercent": "65.00000000",
            "thresholdPercent": "70.00000000",
            "status": "warning",
            "lastAlertStatus": None,
            "lastAlertError": None,
            "lastAlertAt": None,
        }
    ]

    get_response = client.get("/api/liquidation-monitor")

    assert get_response.status_code == 200
    assert get_response.json()["marginBalances"] == payload["marginBalances"]
    with client.app.state.session_factory() as session:
        stored = session.scalar(select(LiquidationMarginBalance))
        assert stored is not None
        assert stored.raw_payload_json == "{}"


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


def test_manual_refresh_sends_bark_message_for_position_risk(client, httpx_mock) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return [position(provider="okx", channel_name="OKX", symbol="BTC-USDT-SWAP")]

    client.app.state.provider_builder = lambda **_: StubProvider()
    client.post(
        "/api/channels",
        json={
            "provider": "okx",
            "kind": "cex",
            "name": "OKX",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret", "passphrase": "pass"},
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
            "barkPushUrl": "https://bark.example.com/device-key",
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
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["alertCount"] == 1
    request = httpx_mock.get_request(url="https://bark.example.com/device-key")
    assert request is not None
    bark_payload = json.loads(request.read().decode())
    assert bark_payload["title"] == "OKX BTC-USDT-SWAP LONG"
    assert bark_payload["body"] == (
        "OKX BTC-USDT-SWAP LONG\nCurrent price: 58100\nLiquidation price: 58000"
    )


def test_manual_refresh_sends_bark_message_for_margin_balance_risk(client, httpx_mock) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return []

        async def collect_contract_margin_balance(self):
            return margin_balance(provider="bybit", channel_name="Bybit")

    client.app.state.provider_builder = lambda **_: StubProvider()
    client.post(
        "/api/channels",
        json={
            "provider": "bybit",
            "kind": "cex",
            "name": "Bybit",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "70",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    request = httpx_mock.get_request(url="https://bark.example.com/device-key")
    assert request is not None
    bark_payload = json.loads(request.read().decode())
    assert bark_payload["title"] == "Bybit risk ratio"
    assert bark_payload["body"] == "Bybit\nRisk ratio: 65%"


def test_margin_balance_risk_requires_miaotixing_phone_success_when_configured(
    client, httpx_mock
) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return []

        async def collect_contract_margin_balance(self):
            return margin_balance(provider="bybit", channel_name="Bybit")

    client.app.state.provider_builder = lambda **_: StubProvider()
    client.post(
        "/api/channels",
        json={
            "provider": "bybit",
            "kind": "cex",
            "name": "Bybit",
            "publicConfig": {},
            "secretConfig": {"apiKey": "key", "apiSecret": "secret"},
        },
    )
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": True,
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "70",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
            "miaoCode": "miao-123",
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://miaotixing.com/trigger",
        json={
            "code": 0,
            "msg": "完成",
            "data": {"success_sent": {"mptext": 1, "sms": 0, "phonecall": 0}},
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["alertCount"] == 0
    assert payload["marginBalances"][0]["lastAlertStatus"] == "warning"
    assert payload["marginBalances"][0]["lastAlertAt"] is not None
    assert (
        "Miaotixing did not report a phone call" in payload["marginBalances"][0]["lastAlertError"]
    )


def test_bark_failure_does_not_block_miaotixing_success(client, httpx_mock) -> None:
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
            "barkPushUrl": "https://bark.example.com/device-key",
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
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        status_code=500,
        json={"code": 500, "message": "failed"},
    )

    refresh_response = client.post("/api/liquidation-monitor/refresh")

    assert refresh_response.status_code == 200
    payload = refresh_response.json()
    assert payload["alertCount"] == 1
    assert payload["positions"][0]["lastAlertStatus"] == "sent"
    assert "Bark alert failed" in payload["positions"][0]["lastAlertError"]


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


def test_margin_balance_alert_uses_configured_alert_interval(client, httpx_mock) -> None:
    class StubProvider:
        async def collect_contract_positions(self):
            return []

        async def collect_contract_margin_balance(self):
            return margin_balance()

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
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": True,
            "marginBalanceThresholdPercent": "70",
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


def test_adl_monitor_detects_short_window_absolute_position_drop(client, httpx_mock) -> None:
    samples = [
        [position(quantity="1.0")],
        [position(quantity="0.59")],
    ]

    class StubProvider:
        async def collect_contract_positions(self):
            return samples.pop(0)

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
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "adlMonitorEnabled": True,
            "adlThresholdPercent": "40",
            "adlWindowSeconds": 60,
            "adlSampleIntervalSeconds": 30,
            "adlStartTime": "15:00",
            "adlEndTime": "17:00",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
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
    second = run_at(now + timedelta(seconds=30))

    assert first["adlEvents"] == []
    assert second["alertCount"] == 1
    assert second["adlEvents"][0]["channelName"] == "Binance"
    assert second["adlEvents"][0]["symbol"] == "BTCUSDT"
    assert second["adlEvents"][0]["side"] == "LONG"
    assert second["adlEvents"][0]["previousQuantity"] == "1.00000000"
    assert second["adlEvents"][0]["currentQuantity"] == "0.59000000"
    assert second["adlEvents"][0]["dropPercent"] == "41.00000000"
    assert second["adlEvents"][0]["lastAlertStatus"] == "sent"
    request = httpx_mock.get_request(url="https://bark.example.com/device-key")
    assert request is not None
    bark_payload = json.loads(request.read().decode())
    assert bark_payload["title"] == "Binance BTCUSDT LONG suspected ADL"


def test_adl_monitor_uses_absolute_quantity_and_missing_position_as_zero(client) -> None:
    samples = [
        [position(symbol="ETHUSDT", side="SHORT", quantity="-2.0")],
        [],
    ]

    class StubProvider:
        async def collect_contract_positions(self):
            return samples.pop(0)

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
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "adlMonitorEnabled": True,
            "adlThresholdPercent": "40",
            "adlWindowSeconds": 60,
            "adlSampleIntervalSeconds": 30,
            "adlStartTime": "15:00",
            "adlEndTime": "17:00",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
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

    run_at(now)
    second = run_at(now + timedelta(seconds=30))

    assert second["adlEvents"][0]["symbol"] == "ETHUSDT"
    assert second["adlEvents"][0]["side"] == "SHORT"
    assert second["adlEvents"][0]["previousQuantity"] == "2.00000000"
    assert second["adlEvents"][0]["currentQuantity"] == "0E-8"
    assert second["adlEvents"][0]["dropPercent"] == "100.00000000"


def test_adl_monitor_skips_detection_outside_utc8_daily_window(client) -> None:
    samples = [
        [position(quantity="1.0")],
        [position(quantity="0.1")],
    ]

    class StubProvider:
        async def collect_contract_positions(self):
            return samples.pop(0)

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
            "positionMonitorEnabled": False,
            "positionThresholdPercent": "5",
            "marginBalanceMonitorEnabled": False,
            "marginBalanceThresholdPercent": "70",
            "adlMonitorEnabled": True,
            "adlThresholdPercent": "40",
            "adlWindowSeconds": 60,
            "adlSampleIntervalSeconds": 30,
            "adlStartTime": "21:00",
            "adlEndTime": "02:00",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 120,
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

    run_at(now)
    second = run_at(now + timedelta(seconds=30))

    assert second["adlEvents"] == []


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


def test_liquidation_monitor_test_miaotixing_alert_only_uses_miao_code(client, httpx_mock) -> None:
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": False,
            "thresholdPercent": "5",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
            "miaoCode": "miao-123",
            "barkPushUrl": "https://bark.example.com/device-key",
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

    response = client.post("/api/liquidation-monitor/test-alert/miaotixing")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert httpx_mock.get_request(url="https://miaotixing.com/trigger") is not None
    assert httpx_mock.get_request(url="https://bark.example.com/device-key") is None


def test_liquidation_monitor_test_alert_uses_configured_bark_url(client, httpx_mock) -> None:
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": False,
            "thresholdPercent": "5",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
    )

    response = client.post("/api/liquidation-monitor/test-alert")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    request = httpx_mock.get_request(url="https://bark.example.com/device-key")
    assert request is not None
    assert "Profits Check liquidation monitor test alert." in request.read().decode()


def test_liquidation_monitor_test_bark_alert_only_uses_bark_url(client, httpx_mock) -> None:
    client.put(
        "/api/liquidation-monitor",
        json={
            "monitorEnabled": False,
            "thresholdPercent": "5",
            "checkIntervalSeconds": 60,
            "alertIntervalSeconds": 900,
            "miaoCode": "miao-123",
            "barkPushUrl": "https://bark.example.com/device-key",
        },
    )
    httpx_mock.add_response(
        method="POST",
        url="https://bark.example.com/device-key",
        json={"code": 200, "message": "success"},
    )

    response = client.post("/api/liquidation-monitor/test-alert/bark")

    assert response.status_code == 200
    assert response.json()["status"] == "sent"
    assert httpx_mock.get_request(url="https://bark.example.com/device-key") is not None
    assert httpx_mock.get_request(url="https://miaotixing.com/trigger") is None
