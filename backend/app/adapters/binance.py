from profits_check_backend.providers.binance import BinanceProvider


class BinanceAdapter(BinanceProvider):
    def __init__(self) -> None:
        super().__init__(channel_name="adapter", config={}, secrets={})
