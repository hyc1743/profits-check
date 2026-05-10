from __future__ import annotations


def test_snapshot_run_persists_assets_and_summary(client) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("4025"),
                assets=[
                    AssetBalance(
                        asset_symbol="BNB",
                        quantity=Decimal("3.5"),
                        value_usd=Decimal("2100"),
                        metadata={"source": "bsc", "type": "native"},
                    ),
                    AssetBalance(
                        asset_symbol="USDT",
                        quantity=Decimal("1925"),
                        value_usd=Decimal("1925"),
                        metadata={"source": "bsc", "type": "token"},
                    ),
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    bsc_response = client.post(
        "/api/channels",
        json={
            "provider": "bsc",
            "kind": "chain",
            "name": "BSC Wallets",
            "publicConfig": {
                "rpcUrl": "https://bsc.local",
                "walletAddresses": ["0x1111111111111111111111111111111111111111"],
                "tokens": [{"contractAddress": "0x2222222222222222222222222222222222222222"}],
            },
            "secretConfig": {},
        },
    )
    assert bsc_response.status_code == 201

    run_response = client.post("/api/snapshots/run")

    assert run_response.status_code == 200
    run_payload = run_response.json()
    assert run_payload["status"] == "success"
    assert run_payload["successCount"] >= 1
    assert run_payload["totalValueUsd"] == "4025.00000000"

    summary_response = client.get("/api/summary/latest")
    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["totalValueUsd"] == "4025.00000000"
    assert summary["channels"][0]["provider"] in {"bsc", "binance"}


def test_snapshot_history_returns_run_details(client) -> None:
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
                        metadata={"source": "binance", "type": "spot"},
                    )
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    channel_response = client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Binance Trading",
            "publicConfig": {"accountType": "spot"},
            "secretConfig": {"apiKey": "key-1", "apiSecret": "secret-1"},
        },
    )
    assert channel_response.status_code == 201

    run_response = client.post("/api/snapshots/run")
    run_id = run_response.json()["id"]

    detail_response = client.get(f"/api/snapshots/{run_id}")
    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["channelName"] == "Binance Trading"
    assert detail["provider"] == "binance"
    assert detail["totalValueUsd"] == "1500.00000000"


def test_snapshot_series_aggregates_and_deletes_whole_runs(client) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        def __init__(self, total: Decimal, asset_symbol: str) -> None:
            self.total = total
            self.asset_symbol = asset_symbol

        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=self.total,
                assets=[
                    AssetBalance(
                        asset_symbol=self.asset_symbol,
                        quantity=Decimal("1"),
                        value_usd=self.total,
                        metadata={"source": "test", "type": "spot"},
                    )
                ],
            )

    def build_stub_provider(**kwargs):
        channel_name = kwargs["channel_name"]
        if channel_name == "Binance Main":
            return StubProvider(Decimal("1000"), "BTC")
        return StubProvider(Decimal("2500"), "ETH")

    client.app.state.provider_builder = build_stub_provider

    for name in ["Binance Main", "OKX Main"]:
        response = client.post(
            "/api/channels",
            json={
                "provider": "binance",
                "kind": "cex",
                "name": name,
                "publicConfig": {"accountType": "spot"},
                "secretConfig": {"apiKey": f"key-{name}", "apiSecret": f"secret-{name}"},
            },
        )
        assert response.status_code == 201

    run_response = client.post("/api/snapshots/run")
    assert run_response.status_code == 200
    run_id = run_response.json()["id"]
    assert run_response.json()["totalValueUsd"] == "3500.00000000"

    summary_response = client.get("/api/summary/latest")
    assert summary_response.status_code == 200
    assert summary_response.json()["totalValueUsd"] == "3500.00000000"

    series_response = client.get("/api/snapshots/series")
    assert series_response.status_code == 200
    assert series_response.json() == [
        {
            "id": run_id,
            "status": "success",
            "totalValueUsd": "3500.00000000",
            "createdAt": series_response.json()[0]["createdAt"],
            "snapshotCount": 2,
        }
    ]

    delete_response = client.delete(f"/api/snapshots/runs/{run_id}")
    assert delete_response.status_code == 204
    assert client.get("/api/snapshots/series").json() == []
    assert client.get("/api/snapshots").json() == []


def test_live_summary_returns_total_without_creating_snapshot(client) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("10500"),
                assets=[
                    AssetBalance(
                        asset_symbol="BTC",
                        quantity=Decimal("0.1"),
                        value_usd=Decimal("9500"),
                        metadata={"source": "binance", "type": "spot"},
                    ),
                    AssetBalance(
                        asset_symbol="USDT",
                        quantity=Decimal("1000"),
                        value_usd=Decimal("1000"),
                        metadata={"source": "binance", "type": "earn"},
                    ),
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    channel_response = client.post(
        "/api/channels",
        json={
            "provider": "binance",
            "kind": "cex",
            "name": "Binance Live",
            "publicConfig": {"accountType": "spot"},
            "secretConfig": {"apiKey": "key-1", "apiSecret": "secret-1"},
        },
    )
    assert channel_response.status_code == 201

    summary_response = client.get("/api/summary/live")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["totalValueUsd"] == "10500.00000000"
    assert summary["assetCount"] == 2
    assert summary["accountCategoryTotals"] == [
        {
            "provider": "binance",
            "channelName": "Binance Live",
            "accountScope": "spot",
            "valueUsd": "9500.00000000",
            "assetCount": 1,
        },
        {
            "provider": "binance",
            "channelName": "Binance Live",
            "accountScope": "earn",
            "valueUsd": "1000.00000000",
            "assetCount": 1,
        },
    ]
    assert summary["channels"][0]["provider"] == "binance"

    snapshots_response = client.get("/api/snapshots")
    assert snapshots_response.status_code == 200
    assert snapshots_response.json() == []
