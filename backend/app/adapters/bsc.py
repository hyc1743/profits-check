from profits_check_backend.providers.bsc import BscProvider


class BscAdapter(BscProvider):
    def __init__(self) -> None:
        super().__init__(channel_name="adapter", config={}, secrets={})
