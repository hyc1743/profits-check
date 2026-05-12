from __future__ import annotations

from profits_check_backend.config import get_settings
from profits_check_backend.domain.models import ProviderType
from profits_check_backend.providers.aster import AsterProvider
from profits_check_backend.providers.base import Provider
from profits_check_backend.providers.binance import BinanceProvider
from profits_check_backend.providers.bitget import BitgetProvider
from profits_check_backend.providers.bsc import OnChainProvider
from profits_check_backend.providers.bybit import BybitProvider
from profits_check_backend.providers.gate import GateProvider
from profits_check_backend.providers.okx import OkxProvider
from profits_check_backend.providers.placeholders import PlaceholderProvider

CUSTOM_URL_KEYS = {
    "baseUrl",
    "base_url",
    "futuresBaseUrl",
    "futures_base_url",
    "rpcUrl",
    "rpc_url",
}


def reject_custom_provider_urls(config: dict[str, object]) -> None:
    if get_settings().allow_custom_provider_urls:
        return
    if CUSTOM_URL_KEYS.intersection(config):
        raise ValueError("Custom provider URLs are disabled")


def build_provider(
    provider_type: ProviderType | str,
    channel_name: str,
    config: dict[str, object],
    secrets: dict[str, object],
) -> Provider:
    reject_custom_provider_urls(config)
    try:
        provider_value = ProviderType(str(provider_type))
    except ValueError:
        return PlaceholderProvider(str(provider_type))
    if provider_value == ProviderType.BINANCE:
        return BinanceProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.GATE:
        return GateProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.OKX:
        return OkxProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.BITGET:
        return BitgetProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.BYBIT:
        return BybitProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.ASTER:
        return AsterProvider(channel_name=channel_name, config=config, secrets=secrets)
    if provider_value == ProviderType.BSC or provider_value == ProviderType.ONCHAIN:
        return OnChainProvider(channel_name=channel_name, config=config, secrets=secrets)
    return PlaceholderProvider(provider_value.value)
