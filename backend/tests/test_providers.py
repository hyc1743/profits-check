from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from profits_check_backend.providers.base import AssetBalance, ProviderError
from profits_check_backend.providers.registry import build_provider


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
async def test_bsc_provider_collects_native_and_token_balances(httpx_mock) -> None:
    from profits_check_backend.providers.bsc import OnChainProvider

    httpx_mock.add_response(
        method="GET",
        url="https://web3.okx.com/api/v6/dex/balance/all-token-balances-by-address?address=0x1111111111111111111111111111111111111111&chains=56&excludeRiskToken=1",
        json={
            "code": "0",
            "msg": "success",
            "data": [
                {
                    "tokenAssets": [
                        {
                            "chainIndex": "56",
                            "tokenContractAddress": "",
                            "symbol": "BNB",
                            "balance": "2",
                            "tokenPrice": "600",
                            "isRiskToken": False,
                            "address": "0x1111111111111111111111111111111111111111",
                        },
                        {
                            "chainIndex": "56",
                            "tokenContractAddress": "0x55d398326f99059fF775485246999027B3197955",
                            "symbol": "USDT",
                            "balance": "2.5",
                            "tokenPrice": "1",
                            "isRiskToken": False,
                            "address": "0x1111111111111111111111111111111111111111",
                        },
                    ]
                }
            ],
        },
    )

    import os

    os.environ["OKX_DEX_API_KEY"] = "key"
    os.environ["OKX_DEX_API_SECRET"] = "secret"
    os.environ["OKX_DEX_API_PASSPHRASE"] = "pass"

    provider = OnChainProvider(
        channel_name="Wallet",
        config={
            "walletAddress": "0x1111111111111111111111111111111111111111",
        },
        secrets={},
        now_factory=lambda: "2026-05-09T00:00:00.000Z",
    )

    snapshot = await provider.collect_snapshot()

    assert snapshot.total_value_usd == Decimal("1202.5")
    assert len(snapshot.assets) == 2
    assert snapshot.assets[0] == AssetBalance(
        asset_symbol="BNB",
        quantity=Decimal("2"),
        value_usd=Decimal("1200"),
        metadata={"source": "onchain", "type": "native", "chainIndex": "56", "tokenPrice": "600"},
    )
    assert snapshot.assets[1] == AssetBalance(
        asset_symbol="USDT",
        quantity=Decimal("2.5"),
        value_usd=Decimal("2.5"),
        metadata={"source": "onchain", "type": "token", "chainIndex": "56", "tokenPrice": "1"},
    )


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
            "https://www.okx.com/api/v5/tradingBot/dca/ongoing-list"
            "?algoOrdType=spot_dca&limit=100"
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
            "https://www.okx.com/api/v5/tradingBot/recurring/orders-algo-details"
            "?algoId=recurring-1"
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
    strategy_assets = [asset for asset in snapshot.assets if asset.metadata["type"].startswith("strategy_")]
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
