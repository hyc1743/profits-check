from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from profits_check_backend.domain.models import ProviderType
from profits_check_backend.providers.base import AssetBalance, ProviderError, ProviderSnapshot
from profits_check_backend.providers.registry import build_provider


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
