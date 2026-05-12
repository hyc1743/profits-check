from __future__ import annotations

from decimal import Decimal

from sqlalchemy import select

from profits_check_backend.models import AppSetting, AuthSession, Channel, Snapshot, SnapshotAsset
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


def create_channel_with_snapshot(client) -> None:
    client.app.state.provider_builder = lambda **_: StubProvider()
    create_response = client.post(
        "/api/channels",
        json={
            "name": "Main Binance",
            "provider": "binance",
            "kind": "cex",
            "enabled": True,
            "publicConfig": {},
            "secretConfig": {
                "apiKey": "public-key",
                "apiSecret": "secret-key",
            },
        },
    )
    assert create_response.status_code == 201
    channel_id = create_response.json()["id"]

    snapshot_response = client.post(f"/api/channels/{channel_id}/snapshots")
    assert snapshot_response.status_code == 201


def test_reset_requires_authentication(anonymous_client) -> None:
    response = anonymous_client.post("/api/system/reset")

    assert response.status_code == 401


def test_reset_deletes_channels_and_snapshots_but_keeps_auth_and_settings(client) -> None:
    create_channel_with_snapshot(client)
    client.put(
        "/api/schedule",
        json={"snapshotScheduleTimes": "09:30", "okxDexApiKey": "", "okxDexApiSecret": ""},
    )

    response = client.post("/api/system/reset")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "deletedChannels": 1,
        "deletedSnapshots": 1,
        "deletedAssets": 1,
    }
    assert client.get("/api/channels").json() == []
    assert client.get("/api/snapshots/series").json() == []
    assert client.get("/api/auth/session").json() == {"authenticated": True}
    assert client.get("/api/schedule").json()["snapshotScheduleTimes"] == "09:30"

    session_factory = client.app.state.session_factory
    with session_factory() as session:
        assert list(session.scalars(select(Channel))) == []
        assert list(session.scalars(select(Snapshot))) == []
        assert list(session.scalars(select(SnapshotAsset))) == []
        assert session.scalar(select(AppSetting)) is not None
        assert session.scalar(select(AuthSession)) is not None
