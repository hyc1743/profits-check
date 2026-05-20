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
