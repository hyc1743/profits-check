from __future__ import annotations

from enum import StrEnum


class ProviderType(StrEnum):
    GATE = "gate"
    BINANCE = "binance"
    OKX = "okx"
    BITGET = "bitget"
    BYBIT = "bybit"
    ASTER = "aster"
    BSC = "bsc"
    ONCHAIN = "onchain"
