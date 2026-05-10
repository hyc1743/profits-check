from __future__ import annotations


def test_manual_snapshot_persists_assets_and_summary(client) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("1500"),
                assets=[
                    AssetBalance(
                        asset_symbol="BTC",
                        quantity=Decimal("0.1"),
                        value_usd=Decimal("1500"),
                        metadata={"source": "test"},
                    )
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    create_response = client.post(
        "/api/channels",
        json={
            "name": "Main Binance",
            "provider_type": "binance",
            "enabled": True,
            "config": {
                "api_key": "public-key",
                "base_url": "https://binance.example",
            },
            "secrets": {
                "api_secret": "secret-key",
            },
        },
    )
    channel_id = create_response.json()["id"]

    snapshot_response = client.post(f"/api/channels/{channel_id}/snapshots")

    assert snapshot_response.status_code == 201
    snapshot = snapshot_response.json()
    assert snapshot["channel_id"] == channel_id
    assert snapshot["total_value_usd"] == "1500.00000000"
    assert snapshot["channelName"] == "Main Binance"

    summary_response = client.get("/api/summary")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["total_value_usd"] == "1500.00000000"
    assert summary["channels"][0]["latest_snapshot_total_usd"] == "1500.00000000"
