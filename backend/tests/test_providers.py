from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from profits_check_backend.providers.base import AssetBalance, ProviderError
from profits_check_backend.providers.registry import build_provider


def add_empty_bybit_asset_overview_response(httpx_mock) -> None:
    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/asset/asset-overview?valuationCurrency=USD",
        json={"retCode": 0, "result": {"totalEquity": "0", "list": []}},
    )


def add_empty_okx_strategy_responses(httpx_mock) -> None:
    for algo_ord_type in ("grid", "contract_grid"):
        httpx_mock.add_response(
            method="GET",
            url=(
                "https://www.okx.com/api/v5/tradingBot/grid/orders-algo-pending"
                f"?algoOrdType={algo_ord_type}&limit=100"
            ),
            json={"code": "0", "data": []},
        )
    for algo_ord_type in ("spot_dca", "contract_dca"):
        httpx_mock.add_response(
            method="GET",
            url=(
                "https://www.okx.com/api/v5/tradingBot/dca/ongoing-list"
                f"?algoOrdType={algo_ord_type}&limit=100"
            ),
            json={"code": "0", "data": []},
        )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/signal/orders-algo-pending"
            "?algoOrdType=contract&limit=100"
        ),
        json={"code": "0", "data": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/tradingBot/recurring/orders-algo-pending?limit=100",
        json={"code": "0", "data": []},
    )


@pytest.mark.asyncio
async def test_binance_provider_collects_balances_and_prices(httpx_mock) -> None:
    from profits_check_backend.providers.binance import BinanceProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/api/v3/account?timestamp=1700000000000&signature=expected",
        json={
            "balances": [
                {"asset": "BTC", "free": "0.1", "locked": "0"},
                {"asset": "USDT", "free": "1000", "locked": "0"},
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        json={"price": "5000"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://fapi.binance.com/fapi/v2/account?timestamp=1700000000000&signature=expected",
        json={"assets": [], "positions": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v1/simple-earn/flexible/position?timestamp=1700000000000&signature=expected",
        json={"rows": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v1/simple-earn/locked/position?timestamp=1700000000000&signature=expected",
        json={"rows": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v2/loan/flexible/ongoing/orders?timestamp=1700000000000&signature=expected",
        json={"rows": [], "total": 0},
    )

    provider = BinanceProvider(
        channel_name="Main",
        config={"api_key": "public", "base_url": "https://api.binance.com"},
        secrets={"api_secret": "secret"},
        now_factory=lambda: 1700000000000,
        signature_factory=lambda query, secret: "expected",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1500")
    assert snapshot.assets == [
        AssetBalance(
            asset_symbol="BTC",
            quantity=Decimal("0.1"),
            value_usd=Decimal("500"),
            metadata={"source": "binance", "type": "spot"},
        ),
        AssetBalance(
            asset_symbol="USDT",
            quantity=Decimal("1000"),
            value_usd=Decimal("1000"),
            metadata={"source": "binance", "type": "spot"},
        ),
    ]


@pytest.mark.asyncio
async def test_binance_provider_uses_secret_api_key_and_default_base_url(httpx_mock) -> None:
    from profits_check_backend.providers.binance import BinanceProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/api/v3/account?timestamp=1700000000000&signature=expected",
        json={
            "balances": [
                {"asset": "BTC", "free": "0.2", "locked": "0"},
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/api/v3/ticker/price?symbol=BTCUSDT",
        json={"price": "5000"},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://fapi.binance.com/fapi/v2/account?timestamp=1700000000000&signature=expected",
        json={"assets": [], "positions": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v1/simple-earn/flexible/position?timestamp=1700000000000&signature=expected",
        json={"rows": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v1/simple-earn/locked/position?timestamp=1700000000000&signature=expected",
        json={"rows": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.binance.com/sapi/v2/loan/flexible/ongoing/orders?timestamp=1700000000000&signature=expected",
        json={"rows": [], "total": 0},
    )

    provider = BinanceProvider(
        channel_name="Main",
        config={},
        secrets={"apiKey": "public-from-secret", "apiSecret": "secret"},
        now_factory=lambda: 1700000000000,
        signature_factory=lambda query, secret: "expected",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1000")
    assert snapshot.assets == [
        AssetBalance(
            asset_symbol="BTC",
            quantity=Decimal("0.2"),
            value_usd=Decimal("1000"),
            metadata={"source": "binance", "type": "spot"},
        )
    ]


@pytest.mark.asyncio
async def test_onchain_provider_collects_token_total_value_for_multiple_wallets(httpx_mock) -> None:
    from profits_check_backend.providers.onchain import OnChainProvider

    httpx_mock.add_response(
        method="GET",
        url="https://web3.okx.com/api/v6/dex/balance/total-value-by-address?address=0x1111111111111111111111111111111111111111&chains=1,56&assetType=1&excludeRiskToken=true",
        json={
            "code": "0",
            "msg": "success",
            "data": [{"totalValue": "1202.5"}],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://web3.okx.com/api/v6/dex/balance/total-value-by-address?address=0x2222222222222222222222222222222222222222&chains=1,56&assetType=1&excludeRiskToken=true",
        json={
            "code": "0",
            "msg": "success",
            "data": [{"totalValue": "300"}],
        },
    )

    import os

    os.environ["OKX_DEX_API_KEY"] = "key"
    os.environ["OKX_DEX_API_SECRET"] = "secret"
    os.environ["OKX_DEX_API_PASSPHRASE"] = "pass"

    provider = OnChainProvider(
        channel_name="Wallet",
        config={
            "walletAddresses": [
                "0x1111111111111111111111111111111111111111",
                "0x2222222222222222222222222222222222222222",
            ],
            "chainIndexes": ["1", "56"],
        },
        secrets={},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1502.5")
    assert len(snapshot.assets) == 2
    assert snapshot.assets[0] == AssetBalance(
        asset_symbol="ONCHAIN_TOTAL",
        quantity=Decimal("0"),
        value_usd=Decimal("1202.5"),
        metadata={
            "source": "onchain",
            "type": "token_total",
            "walletAddress": "0x1111111111111111111111111111111111111111",
            "chainIndexes": ["1", "56"],
            "assetType": "1",
        },
    )
    assert snapshot.assets[1] == AssetBalance(
        asset_symbol="ONCHAIN_TOTAL",
        quantity=Decimal("0"),
        value_usd=Decimal("300"),
        metadata={
            "source": "onchain",
            "type": "token_total",
            "walletAddress": "0x2222222222222222222222222222222222222222",
            "chainIndexes": ["1", "56"],
            "assetType": "1",
        },
    )


@pytest.mark.asyncio
async def test_onchain_provider_defaults_to_eth_and_bsc_when_chain_indexes_are_missing(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.onchain import OnChainProvider

    httpx_mock.add_response(
        method="GET",
        url="https://web3.okx.com/api/v6/dex/balance/total-value-by-address?address=0x367c518a67289e9bf6a18e0016aaea526d769459&chains=1,56&assetType=1&excludeRiskToken=true",
        json={"code": "0", "msg": "success", "data": [{"totalValue": "14061.66"}]},
    )

    import os

    os.environ["OKX_DEX_API_KEY"] = "key"
    os.environ["OKX_DEX_API_SECRET"] = "secret"
    os.environ["OKX_DEX_API_PASSPHRASE"] = "pass"

    provider = OnChainProvider(
        channel_name="Wallet",
        config={"walletAddresses": ["0x367c518a67289e9bf6a18e0016aaea526d769459"]},
        secrets={},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("14061.66")
    assert snapshot.assets[0].metadata["chainIndexes"] == ["1", "56"]


@pytest.mark.asyncio
async def test_gate_provider_collects_spot_balances(httpx_mock) -> None:
    from profits_check_backend.providers.gate import GateProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/wallet/total_balance",
        status_code=404,
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/spot/accounts",
        json=[
            {"currency": "BTC", "available": "0.1", "locked": "0"},
            {"currency": "USDT", "available": "1000", "locked": "0"},
        ],
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/spot/tickers?currency_pair=BTC_USDT",
        json=[{"last": "5000"}],
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/futures/usdt/accounts",
        json={"total": "0", "unrealised_pnl": "0"},
    )

    provider = GateProvider(
        channel_name="Gate",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1500")
    assert snapshot.assets[0].metadata["type"] == "spot"


@pytest.mark.asyncio
async def test_gate_provider_collects_contract_margin_balance_from_available_margin_resource(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.gate import GateProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/futures/usdt/accounts",
        json={
            "total": "0.000000003287",
            "available": "4512.70602",
            "cross_initial_margin": "762.3803",
            "cross_order_margin": "0",
            "cross_maintenance_margin": "47.316225",
            "unrealised_pnl": "-36.15200001",
        },
    )
    provider = GateProvider(
        channel_name="Gate",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000",
    )

    risk = await provider.collect_contract_margin_balance()

    assert risk is not None
    assert risk.wallet_balance == Decimal("5275.08632")
    assert risk.margin_balance == Decimal("4512.70602")
    assert risk.unrealized_pnl == Decimal("-36.15200001")
    assert risk.risk_percent == Decimal("85.54752939")


@pytest.mark.asyncio
async def test_gate_provider_falls_back_to_total_when_margin_resource_is_unavailable(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.gate import GateProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.gateio.ws/api/v4/futures/usdt/accounts",
        json={"total": "1000", "unrealised_pnl": "-350"},
    )
    provider = GateProvider(
        channel_name="Gate",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000",
    )

    risk = await provider.collect_contract_margin_balance()

    assert risk is not None
    assert risk.wallet_balance == Decimal("1000")
    assert risk.margin_balance == Decimal("650")
    assert risk.unrealized_pnl == Decimal("-350")
    assert risk.risk_percent == Decimal("65.00000000")


@pytest.mark.asyncio
async def test_okx_provider_collects_trading_balances(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/balance",
        json={
            "data": [
                {
                    "totalEq": "2500",
                    "details": [
                        {"ccy": "BTC", "eq": "0.1", "eqUsd": "1500"},
                        {"ccy": "USDT", "eq": "1000", "eqUsd": "1000"},
                    ],
                }
            ]
        },
    )
    add_empty_okx_strategy_responses(httpx_mock)

    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("2500")
    assert snapshot.assets[0].metadata["type"] == "trading"


@pytest.mark.asyncio
async def test_okx_provider_collects_strategy_assets(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/balance",
        json={
            "code": "0",
            "data": [
                {
                    "totalEq": "2500",
                    "details": [
                        {"ccy": "USDT", "eq": "2500", "eqUsd": "2500"},
                    ],
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/grid/orders-algo-pending"
            "?algoOrdType=grid&limit=100"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "grid-1",
                    "algoOrdType": "grid",
                    "instId": "BTC-USDT",
                    "instType": "SPOT",
                    "investment": "100",
                    "totalPnl": "5",
                    "state": "running",
                    "uTime": "1700000000000",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/grid/orders-algo-pending"
            "?algoOrdType=contract_grid&limit=100"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "contract-grid-1",
                    "algoOrdType": "contract_grid",
                    "instId": "SPACEX-USDT-SWAP",
                    "instType": "SWAP",
                    "investment": "500",
                    "totalPnl": "104.44875307343695",
                    "state": "running",
                    "uTime": "1700000000001",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/grid/positions"
            "?algoId=contract-grid-1&algoOrdType=contract_grid"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "contract-grid-1",
                    "instId": "SPACEX-USDT-SWAP",
                    "instType": "SWAP",
                    "ccy": "USDT",
                    "pos": "500",
                    "notionalUsd": "604.4",
                    "upl": "-0.01",
                    "uTime": "1700000000002",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/dca/ongoing-list?algoOrdType=spot_dca&limit=100"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "spot-dca-1",
                    "algoOrdType": "spot_dca",
                    "instId": "ETH-USDT",
                    "investmentAmt": "200",
                    "investmentCcy": "USDT",
                    "totalPnl": "10",
                    "state": "running",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/dca/ongoing-list"
            "?algoOrdType=contract_dca&limit=100"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "contract-dca-1",
                    "algoOrdType": "contract_dca",
                    "instId": "ETH-USDT-SWAP",
                    "investmentAmt": "300",
                    "investmentCcy": "USDT",
                    "totalPnl": "-20",
                    "state": "running",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/dca/position-details"
            "?algoId=contract-dca-1&algoOrdType=contract_dca"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "contract-dca-1",
                    "instId": "ETH-USDT-SWAP",
                    "instType": "SWAP",
                    "ccy": "USDT",
                    "pos": "15",
                    "notionalUsd": "280",
                    "upl": "-20",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/signal/orders-algo-pending"
            "?algoOrdType=contract&limit=100"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "signal-1",
                    "algoOrdType": "contract",
                    "instType": "SWAP",
                    "instIds": ["BTC-USDT-SWAP"],
                    "totalEq": "26.824296901312227",
                    "totalPnl": "-73.1757030986877733",
                    "state": "running",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/signal/positions"
            "?algoId=signal-1&algoOrdType=contract"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "signal-1",
                    "instId": "BTC-USDT-SWAP",
                    "instType": "SWAP",
                    "ccy": "USDT",
                    "pos": "1",
                    "notionalUsd": "26.8",
                    "upl": "-1",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/tradingBot/recurring/orders-algo-pending?limit=100",
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "recurring-1",
                    "algoOrdType": "recurring",
                    "instType": "SPOT",
                    "investmentAmt": "50",
                    "investmentCcy": "USDT",
                    "totalPnl": "2",
                    "state": "running",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/recurring/orders-algo-details?algoId=recurring-1"
        ),
        json={
            "code": "0",
            "data": [
                {
                    "algoId": "recurring-1",
                    "algoOrdType": "recurring",
                    "instType": "SPOT",
                    "investmentAmt": "50",
                    "investmentCcy": "USDT",
                    "totalPnl": "2",
                    "recurringList": [{"ccy": "BTC", "totalAmt": "0.001", "profit": "2"}],
                    "state": "running",
                }
            ],
        },
    )

    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("2500")
    strategy_assets = [
        asset for asset in snapshot.assets if asset.metadata["type"].startswith("strategy_")
    ]
    assert all(
        asset.metadata["portfolioAccounting"] == "informational" for asset in strategy_assets
    )
    assert {asset.metadata["type"] for asset in strategy_assets} == {
        "strategy_grid",
        "strategy_contract_grid",
        "strategy_contract_grid_position",
        "strategy_spot_dca",
        "strategy_contract_dca",
        "strategy_contract_dca_position",
        "strategy_signal",
        "strategy_signal_position",
        "strategy_recurring",
    }
    assert any(
        asset.asset_symbol == "SPACEX-USDT-SWAP"
        and asset.quantity == Decimal("500")
        and asset.value_usd == Decimal("604.4")
        for asset in strategy_assets
    )
    assert any(
        asset.metadata["algoId"] == "recurring-1"
        and asset.asset_symbol == "RECURRING"
        and asset.value_usd == Decimal("52")
        for asset in strategy_assets
    )


@pytest.mark.asyncio
async def test_okx_provider_keeps_trading_balances_when_strategy_collection_fails(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/balance",
        json={
            "code": "0",
            "data": [
                {
                    "totalEq": "2500",
                    "details": [
                        {"ccy": "USDT", "eq": "2500", "eqUsd": "2500"},
                    ],
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/grid/orders-algo-pending"
            "?algoOrdType=grid&limit=100"
        ),
        json={"code": "50011", "msg": "APIKey does not have permission", "data": []},
    )
    for algo_ord_type in ("contract_grid",):
        httpx_mock.add_response(
            method="GET",
            url=(
                "https://www.okx.com/api/v5/tradingBot/grid/orders-algo-pending"
                f"?algoOrdType={algo_ord_type}&limit=100"
            ),
            json={"code": "0", "data": []},
        )
    for algo_ord_type in ("spot_dca", "contract_dca"):
        httpx_mock.add_response(
            method="GET",
            url=(
                "https://www.okx.com/api/v5/tradingBot/dca/ongoing-list"
                f"?algoOrdType={algo_ord_type}&limit=100"
            ),
            json={"code": "0", "data": []},
        )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/tradingBot/signal/orders-algo-pending"
            "?algoOrdType=contract&limit=100"
        ),
        json={"code": "0", "data": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/tradingBot/recurring/orders-algo-pending?limit=100",
        json={"code": "0", "data": []},
    )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("2500")
    assert snapshot.assets == [
        AssetBalance(
            asset_symbol="USDT",
            quantity=Decimal("2500"),
            value_usd=Decimal("2500"),
            metadata={"source": "okx", "type": "trading"},
        )
    ]


@pytest.mark.asyncio
async def test_bitget_provider_collects_spot_balances(httpx_mock) -> None:
    from profits_check_backend.providers.bitget import BitgetProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bitget.com/api/v2/spot/account/assets?assetType=all",
        json={
            "data": [
                {"coin": "BTC", "available": "0.1", "frozen": "0", "locked": "0"},
                {"coin": "USDT", "available": "1000", "frozen": "0", "locked": "0"},
            ]
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.bitget.com/api/v2/spot/market/tickers?symbol=BTCUSDT",
        json={"data": [{"lastPr": "5000"}]},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.bitget.com/api/v2/mix/account/accounts?productType=USDT-FUTURES",
        json={"data": []},
    )

    provider = BitgetProvider(
        channel_name="Bitget",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "1700000000000",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1500")
    assert snapshot.assets[0].metadata["type"] == "spot"


@pytest.mark.asyncio
async def test_bybit_provider_collects_unified_balances(httpx_mock) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED",
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "totalWalletBalance": "2500",
                        "coin": [
                            {"coin": "BTC", "equity": "0.1", "usdValue": "1500"},
                            {"coin": "USDT", "equity": "1000", "usdValue": "1000"},
                        ],
                    }
                ]
            },
        },
    )
    add_empty_bybit_asset_overview_response(httpx_mock)

    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000000",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("2500")
    assert snapshot.assets[0].metadata["type"] == "unified"


@pytest.mark.asyncio
async def test_bybit_provider_uses_coin_usd_values_when_wallet_total_excludes_assets(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED",
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "totalEquity": "15471.73",
                        "totalWalletBalance": "6971.73",
                        "coin": [
                            {"coin": "USDT", "equity": "6971.73", "usdValue": "6971.73"},
                            {"coin": "USD1", "equity": "8500", "usdValue": "8500"},
                        ],
                    }
                ]
            },
        },
    )
    add_empty_bybit_asset_overview_response(httpx_mock)

    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000000",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("15471.73")
    assert [asset.asset_symbol for asset in snapshot.assets] == ["USDT", "USD1"]


@pytest.mark.asyncio
async def test_bybit_provider_preserves_wallet_balance_and_borrowed_amount(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED",
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "totalEquity": "5500",
                        "totalWalletBalance": "10500",
                        "coin": [
                            {
                                "coin": "USD1",
                                "equity": "8500",
                                "walletBalance": "8500",
                                "usdValue": "8500",
                                "borrowAmount": "0",
                                "spotBorrow": "0",
                            },
                            {
                                "coin": "USDT",
                                "equity": "-3000",
                                "walletBalance": "2000",
                                "usdValue": "-3000",
                                "borrowAmount": "5000",
                                "spotBorrow": "5000",
                            },
                        ],
                    }
                ]
            },
        },
    )
    add_empty_bybit_asset_overview_response(httpx_mock)

    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000000",
    )

    snapshot = await provider.collect_snapshot()

    usdt = next(asset for asset in snapshot.assets if asset.asset_symbol == "USDT")
    assert snapshot.total_value_usd == Decimal("5500")
    assert usdt.quantity == Decimal("2000")
    assert usdt.value_usd == Decimal("-3000")
    assert usdt.metadata["equity"] == "-3000"
    assert usdt.metadata["borrowed"] == "5000"


@pytest.mark.asyncio
async def test_bybit_provider_collects_crypto_loans_from_asset_overview(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/account/wallet-balance?accountType=UNIFIED",
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "totalEquity": "136.82",
                        "coin": [{"coin": "USDT", "equity": "127.456", "usdValue": "127.34"}],
                    }
                ]
            },
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/asset/asset-overview?valuationCurrency=USD",
        json={
            "retCode": 0,
            "result": {
                "totalEquity": "3488.87",
                "list": [
                    {
                        "accountType": "CryptoLoans",
                        "totalEquity": "3348.59",
                        "valuationCurrency": "USD",
                        "coinDetail": [
                            {"coin": "USDT", "equity": "-5200.0387"},
                            {"coin": "USD1", "equity": "8553.52"},
                        ],
                    },
                    {
                        "accountType": "FundingAccount",
                        "totalEquity": "3.44",
                        "valuationCurrency": "USD",
                        "coinDetail": [{"coin": "WLFI", "equity": "55.614135"}],
                    },
                    {
                        "accountType": "UnifiedTradingAccount",
                        "totalEquity": "136.82",
                        "valuationCurrency": "USD",
                        "coinDetail": [{"coin": "USDT", "equity": "127.456"}],
                    },
                ],
            },
        },
    )

    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000000",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("3488.87")
    crypto_loan_assets = [
        asset for asset in snapshot.assets if asset.metadata["type"] == "crypto_loans"
    ]
    assert [(asset.asset_symbol, asset.value_usd) for asset in crypto_loan_assets] == [
        ("CRYPTO_LOANS_TOTAL", Decimal("3348.59")),
    ]
    assert '"coin": "USD1"' in crypto_loan_assets[0].metadata["coinDetail"]
    assert not any(asset.metadata["type"] == "unified_trading_account" for asset in snapshot.assets)


@pytest.mark.asyncio
async def test_binance_provider_collects_contract_position_risk(httpx_mock) -> None:
    from profits_check_backend.providers.binance import BinanceProvider

    httpx_mock.add_response(
        method="GET",
        url="https://fapi.binance.com/fapi/v3/positionRisk?timestamp=1700000000000&signature=expected",
        json=[
            {
                "symbol": "BTCUSDT",
                "positionSide": "LONG",
                "positionAmt": "0.5",
                "entryPrice": "60000",
                "markPrice": "58100",
                "liquidationPrice": "58000",
                "unRealizedProfit": "-950",
                "marginType": "isolated",
                "leverage": "20",
                "updateTime": 1700000000001,
            },
            {
                "symbol": "ETHUSDT",
                "positionSide": "BOTH",
                "positionAmt": "0",
                "markPrice": "3000",
                "liquidationPrice": "0",
            },
        ],
    )
    provider = BinanceProvider(
        channel_name="Binance",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: 1700000000000,
        signature_factory=lambda query, secret: "expected",
    )

    positions = await provider.collect_contract_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "BTCUSDT"
    assert positions[0].side == "LONG"
    assert positions[0].quantity == Decimal("0.5")
    assert positions[0].mark_price == Decimal("58100")
    assert positions[0].liquidation_price == Decimal("58000")
    assert positions[0].distance_percent == Decimal("0.17211704")


@pytest.mark.asyncio
async def test_binance_provider_collects_contract_margin_balance_risk(httpx_mock) -> None:
    from profits_check_backend.providers.binance import BinanceProvider

    httpx_mock.add_response(
        method="GET",
        url="https://fapi.binance.com/fapi/v2/account?timestamp=1700000000000&signature=expected",
        json={
            "totalWalletBalance": "1000",
            "totalMarginBalance": "650",
            "totalUnrealizedProfit": "-350",
        },
    )
    provider = BinanceProvider(
        channel_name="Binance",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: 1700000000000,
        signature_factory=lambda query, secret: "expected",
    )

    risk = await provider.collect_contract_margin_balance()

    assert risk is not None
    assert risk.wallet_balance == Decimal("1000")
    assert risk.margin_balance == Decimal("650")
    assert risk.unrealized_pnl == Decimal("-350")
    assert risk.risk_percent == Decimal("65.00000000")


@pytest.mark.asyncio
async def test_okx_provider_collects_contract_position_risk(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/positions?instType=SWAP",
        json={"code": "0", "data": []},
    )
    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/positions?instType=FUTURES",
        json={
            "code": "0",
            "data": [
                {
                    "instType": "FUTURES",
                    "instId": "BTC-USDT-260626",
                    "posSide": "long",
                    "pos": "2",
                    "avgPx": "60000",
                    "markPx": "58100",
                    "liqPx": "58000",
                    "upl": "-200",
                    "mgnMode": "cross",
                    "lever": "10",
                    "uTime": "1700000000001",
                }
            ],
        },
    )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    positions = await provider.collect_contract_positions()

    assert len(positions) == 1
    assert positions[0].symbol == "BTC-USDT-260626"
    assert positions[0].side == "long"
    assert positions[0].quantity == Decimal("2")
    assert positions[0].distance_percent == Decimal("0.17211704")


@pytest.mark.asyncio
async def test_okx_provider_collects_contract_margin_balance_risk_ratio(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/account-position-risk",
        json={
            "code": "0",
            "data": [
                {
                    "adjEq": "1000",
                    "mgnRatio": "1.25",
                    "uTime": "1700000000001",
                    "posData": [
                        {
                            "upl": "-100",
                        }
                    ],
                }
            ],
        },
    )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    risk = await provider.collect_contract_margin_balance()

    assert risk is not None
    assert risk.wallet_balance == Decimal("1100")
    assert risk.margin_balance == Decimal("1000")
    assert risk.unrealized_pnl == Decimal("-100")
    assert risk.updated_at_ms == 1700000000001
    assert risk.risk_percent == Decimal("90.90909091")


@pytest.mark.asyncio
async def test_okx_provider_falls_back_to_balance_for_contract_margin_balance_risk(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/account-position-risk",
        json={
            "code": "0",
            "data": [
                {
                    "adjEq": "",
                    "mgnRatio": "",
                    "posData": [
                        {
                            "upl": "-100",
                        }
                    ],
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url="https://www.okx.com/api/v5/account/balance",
        json={
            "code": "0",
            "data": [
                {
                    "totalEq": "10011.89897304795",
                    "upl": "-942.1965263679089",
                    "uTime": "1778829138809",
                    "details": [
                        {
                            "ccy": "USDT",
                            "availEq": "2932.814574222276",
                            "upl": "-949.3814399999994",
                            "mgnRatio": "50.7479390483589",
                        },
                        {
                            "ccy": "ETC",
                            "availEq": "34.8258067094214",
                            "upl": "7.184913632090456",
                            "mgnRatio": "38.84565635477536",
                        },
                    ],
                }
            ],
        },
    )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    risk = await provider.collect_contract_margin_balance()

    assert risk is not None
    assert risk.wallet_balance == Decimal("10954.0954994158589")
    assert risk.margin_balance == Decimal("10011.89897304795")
    assert risk.unrealized_pnl == Decimal("-942.1965263679089")
    assert risk.updated_at_ms == 1778829138809
    assert risk.risk_percent == Decimal("91.39868256")


@pytest.mark.asyncio
async def test_bybit_provider_collects_contract_position_risk(httpx_mock) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url="https://api.bybit.com/v5/position/list?category=linear&settleCoin=USDT",
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "side": "Buy",
                        "size": "0.5",
                        "avgPrice": "60000",
                        "markPrice": "58100",
                        "liqPrice": "58000",
                        "unrealisedPnl": "-950",
                        "positionIdx": 1,
                        "leverage": "20",
                        "updatedTime": "1700000000001",
                    }
                ]
            },
        },
    )
    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1700000000000",
    )

    positions = await provider.collect_contract_positions()

    assert len(positions) == 1
    assert positions[0].side == "Buy"
    assert positions[0].distance_percent == Decimal("0.17211704")


@pytest.mark.asyncio
async def test_aster_provider_collects_spot_and_futures_balances(httpx_mock) -> None:
    from profits_check_backend.providers.aster import AsterProvider

    httpx_mock.add_response(
        method="POST",
        url="https://tapi.asterdex.com/info",
        json={
            "result": {
                "perpAssets": [
                    {"asset": "USDT", "walletBalance": "1200"},
                ],
                "spotAssets": [
                    {"asset": "ASTER", "walletBalance": "10"},
                    {"asset": "USDT", "walletBalance": "500"},
                ],
                "positions": [
                    {
                        "tradingProduct": "perps",
                        "positions": [
                            {
                                "symbol": "BTCUSDT",
                                "positionAmount": "0.05",
                                "unrealizedProfit": "-100",
                                "entryPrice": "40000",
                                "markPrice": "38000",
                            }
                        ],
                    }
                ],
            }
        },
    )

    provider = AsterProvider(
        channel_name="Aster",
        config={"walletAddress": "0xTest"},
        secrets={},
    )

    async def fake_price(c, a, q):
        if a == "ASTER":
            return Decimal("2.5") * q
        return q if a in ("USDT", "USDC") else None

    provider._estimate_spot_price = fake_price  # type: ignore[method-assign]

    snapshot = await provider.collect_snapshot()

    # total = perp(1200) + positionPnL(-100) + spotUSDT(500) + spotASTER(10*2.5=25) = 1625
    assert snapshot.total_value_usd == Decimal("1625")


@pytest.mark.asyncio
async def test_aster_provider_collects_api_wallet_position_risk(httpx_mock) -> None:
    from profits_check_backend.providers.aster import AsterProvider

    httpx_mock.add_response(
        method="POST",
        url="https://tapi.asterdex.com/info",
        json={
            "result": {
                "perpAssets": [{"asset": "USDT", "walletBalance": "1000"}],
                "spotAssets": [],
                "positions": [],
            }
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://fapi.asterdex.com/fapi/v3/positionRisk?"
            "user=0xUser&signer=0xSigner&nonce=1700000000000&signature=expected"
        ),
        json=[
            {
                "symbol": "BTCUSDT",
                "positionAmt": "0.5",
                "entryPrice": "40000",
                "markPrice": "38000",
                "liquidationPrice": "30000",
                "unRealizedProfit": "-100",
                "positionSide": "LONG",
            }
        ],
    )

    provider = AsterProvider(
        channel_name="Aster",
        config={"walletAddress": "0xTest"},
        secrets={"user": "0xUser", "signer": "0xSigner", "privateKey": "secret"},
        now_factory=lambda: "1700000000000",
        signature_factory=lambda message_body, private_key: "expected",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.assets[0].metadata["positionCount"] == "1"
    assert snapshot.assets[0].metadata["positions"] == (
        '[{"symbol":"BTCUSDT","positionAmt":"0.5","positionSide":"LONG",'
        '"entryPrice":"40000","markPrice":"38000","liquidationPrice":"30000",'
        '"liquidationDistancePct":"21.05263158","unRealizedProfit":"-100"}]'
    )
    assert snapshot.total_value_usd == Decimal("900")


@pytest.mark.asyncio
async def test_aster_provider_uses_infinity_distance_when_liquidation_price_is_missing(
    httpx_mock,
) -> None:
    from profits_check_backend.providers.aster import AsterProvider

    httpx_mock.add_response(
        method="POST",
        url="https://tapi.asterdex.com/info",
        json={
            "result": {
                "perpAssets": [],
                "spotAssets": [],
                "positions": [
                    {
                        "positions": [
                            {
                                "symbol": "ETHUSDT",
                                "positionAmount": "2",
                                "entryPrice": "3000",
                                "markPrice": "3200",
                                "unrealizedProfit": "400",
                            }
                        ],
                    }
                ],
            }
        },
    )

    provider = AsterProvider(
        channel_name="Aster",
        config={"walletAddress": "0xTest"},
        secrets={},
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.assets[0].metadata["positionCount"] == "1"
    assert '"liquidationDistancePct":"∞"' in snapshot.assets[0].metadata["positions"]


@pytest.mark.asyncio
async def test_aster_provider_requires_credentials() -> None:
    from profits_check_backend.providers.aster import AsterProvider

    provider = AsterProvider(
        channel_name="Aster",
        config={},
        secrets={},
    )

    with pytest.raises(ProviderError, match="wallet address"):
        await provider.collect_snapshot()


def test_provider_registry_exposes_placeholders_and_contract() -> None:
    provider = build_provider(
        provider_type="mystery",
        channel_name="Unused",
        config={},
        secrets={},
    )

    with pytest.raises(ProviderError):
        asyncio.run(provider.collect_snapshot())


@pytest.mark.asyncio
async def test_binance_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.binance import BinanceProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://fapi.binance.com/fapi/v1/income?incomeType=FUNDING_FEE"
            "&startTime=1700000000000&endTime=1702591999999&limit=1000"
            "&timestamp=1702600000000&signature=expected"
        ),
        json=[
            {"symbol": "BTCUSDT", "income": "1.25", "asset": "USDT", "time": 1700000000000},
            {"symbol": "ETHUSDT", "income": "-0.5", "asset": "USDT", "time": 1700003600000},
        ],
    )
    provider = BinanceProvider(
        channel_name="Main",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: 1702600000000,
        signature_factory=lambda query, secret: "expected",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert [record.amount for record in records] == [Decimal("1.25"), Decimal("-0.5")]
    assert records[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_gate_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.gate import GateProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.gateio.ws/api/v4/futures/usdt/account_book"
            "?from=1700000000&to=1702591999&type=fund&limit=1000"
        ),
        json=[
            {
                "time": 1700000000,
                "change": "2",
                "balance": "10",
                "type": "fund",
                "text": "BTC_USDT:1",
            },
            {
                "time": 1700003600,
                "change": "-0.75",
                "balance": "9.25",
                "type": "fund",
                "text": "ETH_USDT:2",
            },
        ],
    )
    provider = GateProvider(
        channel_name="Gate",
        config={"settle": "usdt"},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1702600000",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert [record.amount for record in records] == [Decimal("2"), Decimal("-0.75")]
    assert records[0].symbol == "BTC_USDT"


@pytest.mark.asyncio
async def test_gate_provider_collects_default_usdt_and_btc_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.gate import GateProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.gateio.ws/api/v4/futures/usdt/account_book"
            "?from=1700000000&to=1702591999&type=fund&limit=1000"
        ),
        json=[],
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.gateio.ws/api/v4/futures/btc/account_book"
            "?from=1700000000&to=1702591999&type=fund&limit=1000"
        ),
        json=[
            {
                "time": 1700000000,
                "change": "0.0002",
                "balance": "1.1",
                "type": "fund",
                "contract": "BTC_USD",
                "text": "BTC_USD:1",
            }
        ],
    )
    provider = GateProvider(
        channel_name="Gate",
        config={},
        secrets={"apiKey": "public", "apiSecret": "secret"},
        now_factory=lambda: "1702600000",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert len(records) == 1
    assert records[0].amount == Decimal("0.0002")
    assert records[0].asset == "BTC"
    assert records[0].symbol == "BTC_USD"


@pytest.mark.asyncio
async def test_okx_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    for subtype, pnl in (("173", "-1.2"), ("174", "3.4")):
        httpx_mock.add_response(
            method="GET",
            url=(
                "https://www.okx.com/api/v5/account/bills-archive"
                f"?subType={subtype}&begin=1700000000000&end=1702591999999&limit=100"
            ),
            json={
                "code": "0",
                "data": [
                    {
                        "subType": subtype,
                        "pnl": pnl,
                        "ccy": "USDT",
                        "ts": "1700000000000",
                        "instId": "BTC-USDT-SWAP",
                    }
                ],
            },
        )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "key", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2024-01-01T00:00:00.000Z",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert [record.amount for record in records] == [Decimal("-1.2"), Decimal("3.4")]
    assert records[0].symbol == "BTC-USDT-SWAP"


@pytest.mark.asyncio
async def test_okx_provider_retries_funding_fee_rate_limit(httpx_mock) -> None:
    from profits_check_backend.providers.okx import OkxProvider

    expense_url = (
        "https://www.okx.com/api/v5/account/bills-archive"
        "?subType=173&begin=1700000000000&end=1702591999999&limit=100"
    )
    httpx_mock.add_response(
        method="GET",
        url=expense_url,
        status_code=429,
        headers={"Retry-After": "0"},
        json={"code": "50011", "msg": "Too Many Requests"},
    )
    httpx_mock.add_response(
        method="GET",
        url=expense_url,
        json={
            "code": "0",
            "data": [
                {
                    "subType": "173",
                    "pnl": "-1.2",
                    "ccy": "USDT",
                    "ts": "1700000000000",
                    "instId": "BTC-USDT-SWAP",
                }
            ],
        },
    )
    httpx_mock.add_response(
        method="GET",
        url=(
            "https://www.okx.com/api/v5/account/bills-archive"
            "?subType=174&begin=1700000000000&end=1702591999999&limit=100"
        ),
        json={"code": "0", "data": []},
    )
    provider = OkxProvider(
        channel_name="OKX",
        config={},
        secrets={"apiKey": "key", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "2024-01-01T00:00:00.000Z",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert [record.amount for record in records] == [Decimal("-1.2")]


@pytest.mark.asyncio
async def test_bitget_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.bitget import BitgetProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.bitget.com/api/v2/mix/account/bill?productType=USDT-FUTURES"
            "&businessType=contract_settle_fee&startTime=1700000000000"
            "&endTime=1702591999999&limit=100"
        ),
        json={
            "code": "00000",
            "data": {
                "bills": [
                    {
                        "billId": "1",
                        "symbol": "BTCUSDT",
                        "amount": "-0.9",
                        "businessType": "contract_settle_fee",
                        "coin": "USDT",
                        "cTime": "1700000000000",
                    }
                ],
                "endId": "",
            },
        },
    )
    provider = BitgetProvider(
        channel_name="Bitget",
        config={},
        secrets={"apiKey": "key", "apiSecret": "secret", "passphrase": "pass"},
        now_factory=lambda: "1702600000000",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert len(records) == 1
    assert records[0].amount == Decimal("-0.9")
    assert records[0].symbol == "BTCUSDT"


@pytest.mark.asyncio
async def test_bybit_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.bybit import BybitProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://api.bybit.com/v5/account/transaction-log?accountType=UNIFIED"
            "&category=linear&startTime=1700000000000&endTime=1702591999999&limit=50"
        ),
        json={
            "retCode": 0,
            "result": {
                "list": [
                    {
                        "symbol": "BTCUSDT",
                        "currency": "USDT",
                        "funding": "4.2",
                        "transactionTime": "1700000000000",
                    },
                    {
                        "symbol": "ETHUSDT",
                        "currency": "USDT",
                        "funding": "0",
                        "transactionTime": "1700000000001",
                    },
                ],
                "nextPageCursor": "",
            },
        },
    )
    provider = BybitProvider(
        channel_name="Bybit",
        config={},
        secrets={"apiKey": "key", "apiSecret": "secret"},
        now_factory=lambda: "1702600000000",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert len(records) == 1
    assert records[0].amount == Decimal("4.2")


@pytest.mark.asyncio
async def test_aster_provider_collects_funding_fee_records(httpx_mock) -> None:
    from profits_check_backend.providers.aster import AsterProvider

    httpx_mock.add_response(
        method="GET",
        url=(
            "https://fapi.asterdex.com/fapi/v3/income?incomeType=FUNDING_FEE"
            "&startTime=1700000000000&endTime=1702591999999&limit=1000"
            "&user=user&signer=signer&nonce=1702600000000000&signature=signature"
        ),
        json=[
            {
                "symbol": "BTCUSDT",
                "income": "0.33",
                "asset": "USDT",
                "time": 1700000000000,
            }
        ],
    )
    provider = AsterProvider(
        channel_name="Aster",
        config={},
        secrets={"user": "user", "signer": "signer", "privateKey": "private"},
        now_factory=lambda: 1702600000000000,
        signature_factory=lambda message, private_key: "signature",
    )

    records = await provider.collect_funding_fee_records(1700000000000, 1702591999999)

    assert len(records) == 1
    assert records[0].amount == Decimal("0.33")
