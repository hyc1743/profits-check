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
                        asset_symbol="ONCHAIN_TOTAL",
                        quantity=Decimal("0"),
                        value_usd=Decimal("2100"),
                        metadata={"source": "onchain", "type": "token_total"},
                    ),
                    AssetBalance(
                        asset_symbol="ONCHAIN_TOTAL",
                        quantity=Decimal("0"),
                        value_usd=Decimal("1925"),
                        metadata={"source": "onchain", "type": "token_total"},
                    ),
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()

    onchain_response = client.post(
        "/api/channels",
        json={
            "provider": "onchain",
            "kind": "chain",
            "name": "EVM Wallets",
            "publicConfig": {
                "walletAddresses": ["0x1111111111111111111111111111111111111111"],
                "chainIndexes": ["1", "56"],
            },
            "secretConfig": {},
        },
    )
    assert onchain_response.status_code == 201

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
    assert summary["channels"][0]["provider"] in {"onchain", "binance"}


def test_provider_snapshot_to_balances_preserves_borrowed_metadata() -> None:
    from decimal import Decimal

    from profits_check_backend.models import Channel
    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot
    from profits_check_backend.services.snapshots import provider_snapshot_to_balances

    channel = Channel(id=1, provider="bybit", name="Bybit", kind="cex")
    provider_snapshot = ProviderSnapshot(
        total_value_usd=Decimal("5500"),
        assets=[
            AssetBalance(
                asset_symbol="USDT",
                quantity=Decimal("2000"),
                value_usd=Decimal("-3000"),
                metadata={
                    "source": "bybit",
                    "type": "unified",
                    "borrowed": "5000",
                },
            )
        ],
    )

    balances = provider_snapshot_to_balances(
        channel=channel,
        provider_snapshot=provider_snapshot,
    )

    assert balances[0].total == Decimal("2000")
    assert balances[0].borrowed == Decimal("5000")


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


def test_snapshot_run_overwrites_existing_run_for_same_shanghai_day(client) -> None:
    from decimal import Decimal

    from profits_check_backend.models import Snapshot
    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    totals_by_run = [Decimal("3500"), Decimal("4200")]
    current_run = {"index": 0}

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
        total = totals_by_run[current_run["index"]]
        if channel_name == "Binance Main":
            return StubProvider(total, "BTC")
        return StubProvider(total + Decimal("500"), "ETH")

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

    first_run = client.post("/api/snapshots/run")
    assert first_run.status_code == 200
    first_run_id = first_run.json()["id"]
    assert first_run.json()["totalValueUsd"] == "7500.00000000"

    current_run["index"] = 1
    second_run = client.post("/api/snapshots/run")
    assert second_run.status_code == 200
    second_run_id = second_run.json()["id"]
    assert second_run.json()["totalValueUsd"] == "8900.00000000"

    series_response = client.get("/api/snapshots/series")
    assert series_response.status_code == 200
    assert series_response.json() == [
        {
            "id": second_run_id,
            "status": "success",
            "totalValueUsd": "8900.00000000",
            "createdAt": series_response.json()[0]["createdAt"],
            "snapshotCount": 2,
        }
    ]

    snapshots_response = client.get("/api/snapshots")
    assert snapshots_response.status_code == 200
    assert [item["runId"] for item in snapshots_response.json()] == [second_run_id, second_run_id]
    assert all(item["runId"] != first_run_id for item in snapshots_response.json())

    with client.app.state.session_factory() as session:
        saved_snapshots = list(session.query(Snapshot).order_by(Snapshot.id))
        assert len(saved_snapshots) == 2
        assert {snapshot.run_id for snapshot in saved_snapshots} == {second_run_id}


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


def test_live_summary_excludes_informational_assets_from_account_category_totals(
    client,
) -> None:
    from decimal import Decimal

    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("2500"),
                assets=[
                    AssetBalance(
                        asset_symbol="USDT",
                        quantity=Decimal("2500"),
                        value_usd=Decimal("2500"),
                        metadata={"source": "okx", "type": "trading"},
                    ),
                    AssetBalance(
                        asset_symbol="BTC-USDT-SWAP",
                        quantity=Decimal("1"),
                        value_usd=Decimal("600"),
                        metadata={
                            "source": "okx",
                            "type": "strategy_signal",
                            "portfolioAccounting": "informational",
                        },
                    ),
                ],
            )

    client.app.state.provider_builder = lambda **_: StubProvider()
    channel_response = client.post(
        "/api/channels",
        json={
            "provider": "okx",
            "kind": "cex",
            "name": "OKX",
            "publicConfig": {},
            "secretConfig": {
                "apiKey": "key-1",
                "apiSecret": "secret-1",
                "passphrase": "pass-1",
            },
        },
    )
    assert channel_response.status_code == 201

    summary_response = client.get("/api/summary/live")

    assert summary_response.status_code == 200
    summary = summary_response.json()
    assert summary["totalValueUsd"] == "2500.00000000"
    assert summary["accountCategoryTotals"] == [
        {
            "provider": "okx",
            "channelName": "OKX",
            "accountScope": "trading",
            "valueUsd": "2500.00000000",
            "assetCount": 1,
        }
    ]


def test_binance_live_summary_ignores_unreadable_okx_dex_config(client) -> None:
    from decimal import Decimal

    from profits_check_backend.models import AppSetting
    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("10500"),
                assets=[
                    AssetBalance(
                        asset_symbol="BTC",
                        quantity=Decimal("0.1"),
                        value_usd=Decimal("10500"),
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
            "name": "Binance Live",
            "publicConfig": {"accountType": "spot"},
            "secretConfig": {"apiKey": "key-1", "apiSecret": "secret-1"},
        },
    )
    assert channel_response.status_code == 201

    with client.app.state.session_factory() as session:
        session.add(
            AppSetting(
                key="okxDexConfig",
                value_json='{"apiKey":"stale","apiSecretEncrypted":"unreadable"}',
            )
        )
        session.commit()

    summary_response = client.get("/api/summary/live")

    assert summary_response.status_code == 200
    assert summary_response.json()["totalValueUsd"] == "10500.00000000"


def test_binance_snapshot_run_ignores_unreadable_okx_dex_config(client) -> None:
    from decimal import Decimal

    from profits_check_backend.models import AppSetting
    from profits_check_backend.providers.base import AssetBalance, ProviderSnapshot

    class StubProvider:
        async def collect_snapshot(self) -> ProviderSnapshot:
            return ProviderSnapshot(
                total_value_usd=Decimal("10500"),
                assets=[
                    AssetBalance(
                        asset_symbol="BTC",
                        quantity=Decimal("0.1"),
                        value_usd=Decimal("10500"),
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
            "name": "Binance Live",
            "publicConfig": {"accountType": "spot"},
            "secretConfig": {"apiKey": "key-1", "apiSecret": "secret-1"},
        },
    )
    assert channel_response.status_code == 201

    with client.app.state.session_factory() as session:
        session.add(
            AppSetting(
                key="okxDexConfig",
                value_json='{"apiKey":"stale","apiSecretEncrypted":"unreadable"}',
            )
        )
        session.commit()

    run_response = client.post("/api/snapshots/run")

    assert run_response.status_code == 200
    assert run_response.json()["totalValueUsd"] == "10500.00000000"
