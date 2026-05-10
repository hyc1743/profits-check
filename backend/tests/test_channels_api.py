from __future__ import annotations


def test_create_channel_masks_secret_and_test_connection(client) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("2000"),
                assets=[
                    AssetBalance(
                        asset_symbol="USDT",
                        quantity=Decimal("2000"),
                        value_usd=Decimal("2000"),
                        metadata={"source": "stub", "type": "spot"},
                    )
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    payload = {
        "provider": "binance",
        "kind": "cex",
        "name": "Primary Binance",
        "publicConfig": {"accountType": "spot"},
        "secretConfig": {"apiKey": "key-1", "apiSecret": "secret-1"},
    }

    create_response = client.post("/api/channels", json=payload)

    assert create_response.status_code == 201
    created = create_response.json()
    assert created["provider"] == "binance"
    assert created["secretConfigured"] is True
    assert created["secretConfigMask"]["apiKey"] == "ke***-1"
    assert "secretConfig" not in created

    test_response = client.post(f"/api/channels/{created['id']}/test")

    assert test_response.status_code == 200
    assert test_response.json()["status"] == "ok"
    assert test_response.json()["assetCount"] == 1
    assert test_response.json()["totalValueUsd"] == "2000.00000000"


def test_unimplemented_channel_returns_test_failure(client) -> None:
    payload = {
        "provider": "aster",
        "kind": "cex",
        "name": "Aster Missing Credentials",
        "publicConfig": {},
        "secretConfig": {},
    }

    create_response = client.post("/api/channels", json=payload)
    assert create_response.status_code == 201

    test_response = client.post(f"/api/channels/{create_response.json()['id']}/test")

    assert test_response.status_code == 400
    assert "wallet address" in test_response.json()["detail"].lower()


def test_schedule_can_be_read_and_updated(client) -> None:
    initial = client.get("/api/schedule")
    assert initial.status_code == 200
    assert initial.json()["snapshotScheduleTimes"] == "08:00"

    update = client.put(
        "/api/schedule",
        json={"snapshotScheduleTimes": "08:00,20:00"},
    )

    assert update.status_code == 200
    assert update.json()["snapshotScheduleTimes"] == "08:00,20:00"
