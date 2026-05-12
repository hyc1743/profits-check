from __future__ import annotations

from decimal import Decimal


def test_binance_adapter_normalizes_balances() -> None:
    from app.adapters.binance import BinanceAdapter

    adapter = BinanceAdapter()
    balances = adapter.normalize_mock_payload(
        channel_id=1,
        payload={
            "account": {
                "balances": [
                    {"asset": "BTC", "free": "0.25", "locked": "0.05"},
                    {"asset": "USDT", "free": "1200", "locked": "0"},
                ]
            },
            "prices": {"BTCUSDT": "95000", "USDTUSDT": "1"},
        },
    )

    assert len(balances) == 2
    assert balances[0].asset == "BTC"
    assert balances[0].total == Decimal("0.30")
    assert balances[0].value_usd == Decimal("28500")


def test_bsc_adapter_normalizes_native_and_token_balances() -> None:
    from app.adapters.bsc import BscAdapter

    adapter = BscAdapter()
    balances = adapter.normalize_mock_payload(
        channel_id=2,
        payload={
            "wallet": "0x1111111111111111111111111111111111111111",
            "native": {"symbol": "BNB", "balance": "3.5", "priceUsd": "600"},
            "tokens": [
                {"symbol": "USDT", "balance": "1200", "priceUsd": "1", "contractAddress": "0x2222"},
                {
                    "symbol": "CAKE",
                    "balance": "250",
                    "priceUsd": "2.9",
                    "contractAddress": "0x3333",
                },
            ],
        },
    )

    assert [item.asset for item in balances] == ["BNB", "USDT", "CAKE"]
    assert balances[0].account_scope == "wallet:0x1111111111111111111111111111111111111111"
    assert balances[2].value_usd == Decimal("725.0")
