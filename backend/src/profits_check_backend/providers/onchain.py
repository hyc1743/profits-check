from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

from profits_check_backend.config import get_settings
from profits_check_backend.providers.base import (
    AssetBalance,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client

OKX_DEX_BASE_URL = "https://web3.okx.com"
TOKEN_ASSET_TYPE = "1"
DEFAULT_EVM_CHAIN_INDEXES = {"1", "56"}
EVM_CHAIN_INDEXES = {
    "1",
    "10",
    "56",
    "137",
    "250",
    "324",
    "1101",
    "5000",
    "8453",
    "42161",
    "43114",
    "59144",
    "81457",
    "534352",
}


class OnChainProvider(Provider):
    def __init__(
        self,
        channel_name: str,
        config: dict[str, object],
        secrets: dict[str, object],
        now_factory=None,
    ) -> None:
        self.channel_name = channel_name
        self.config = config
        self.secrets = secrets
        self.now_factory = now_factory or (
            lambda: datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )

    def _credentials(self) -> tuple[str, str, str]:
        api_key = str(self.secrets.get("okxDexApiKey") or "")
        api_secret = str(self.secrets.get("okxDexApiSecret") or "")
        passphrase = str(self.secrets.get("okxDexPassphrase") or "")
        if not api_key:
            settings = get_settings()
            api_key = settings.okx_dex_api_key
            api_secret = settings.okx_dex_api_secret
            passphrase = settings.okx_dex_api_passphrase
        if not api_key or not api_secret or not passphrase:
            raise ProviderError(
                "OKX DEX API credentials not configured. "
                "Set OKX_DEX_API_KEY / OKX_DEX_API_SECRET / OKX_DEX_API_PASSPHRASE in .env"
            )
        return api_key, api_secret, passphrase

    def _signature_headers(self, method: str, path_with_query: str) -> dict[str, str]:
        api_key, api_secret, passphrase = self._credentials()
        timestamp = str(self.now_factory())
        prehash = f"{timestamp}{method}{path_with_query}"
        signature = base64.b64encode(
            hmac.new(api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode()
        return {
            "OK-ACCESS-KEY": api_key,
            "OK-ACCESS-SIGN": signature,
            "OK-ACCESS-TIMESTAMP": timestamp,
            "OK-ACCESS-PASSPHRASE": passphrase,
        }

    def _wallet_addresses(self) -> list[str]:
        addresses = [
            str(item).strip()
            for item in cast(list[object], self.config.get("walletAddresses", []))
            if str(item).strip()
        ]
        single_address = str(
            self.config.get("wallet_address", self.config.get("walletAddress", ""))
        ).strip()
        if single_address:
            addresses.insert(0, single_address)
        unique_addresses = list(dict.fromkeys(addresses))
        if not unique_addresses:
            raise ProviderError("Wallet address is missing")
        return unique_addresses

    def _chain_indexes(self) -> list[str]:
        raw_indexes = self.config.get("chainIndexes", self.config.get("chains", []))
        if isinstance(raw_indexes, str):
            indexes = [item.strip() for item in raw_indexes.split(",") if item.strip()]
        else:
            indexes = [
                str(item).strip() for item in cast(list[object], raw_indexes) if str(item).strip()
            ]
        unique_indexes = list(dict.fromkeys(indexes))
        if not unique_indexes:
            raise ProviderError("At least one EVM chain is required")
        return unique_indexes

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(
            self.config.get("base_url", self.config.get("baseUrl", OKX_DEX_BASE_URL))
        ).rstrip("/")
        chain_indexes = self._chain_indexes()
        chains = ",".join(chain_indexes)
        assets: list[AssetBalance] = []
        total_value = Decimal("0")

        async with provider_http_client() as client:
            for wallet_address in self._wallet_addresses():
                path = (
                    "/api/v6/dex/balance/total-value-by-address"
                    f"?address={wallet_address}&chains={chains}"
                    f"&assetType={TOKEN_ASSET_TYPE}&excludeRiskToken=true"
                )
                response = await client.get(
                    f"{base_url}{path}",
                    headers=self._signature_headers("GET", path),
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") != "0":
                    raise ProviderError(str(payload.get("msg", "OKX DEX API error")))
                value_usd = _extract_total_value(payload)
                assets.append(
                    AssetBalance(
                        asset_symbol="ONCHAIN_TOTAL",
                        quantity=Decimal("0"),
                        value_usd=value_usd,
                        metadata={
                            "source": "onchain",
                            "type": "token_total",
                            "walletAddress": wallet_address,
                            "chainIndexes": chain_indexes,
                            "assetType": TOKEN_ASSET_TYPE,
                        },
                    )
                )
                total_value += value_usd

        return ProviderSnapshot(total_value_usd=total_value, assets=assets)


def _extract_total_value(payload: dict[str, Any]) -> Decimal:
    data = payload.get("data")
    if isinstance(data, list) and data:
        return Decimal(str(cast(dict[str, object], data[0]).get("totalValue", "0")))
    if isinstance(data, dict):
        return Decimal(str(data.get("totalValue", "0")))
    return Decimal("0")


async def collect_supported_evm_chains() -> list[dict[str, object]]:
    async with provider_http_client() as client:
        response = await client.get(f"{OKX_DEX_BASE_URL}/api/v6/dex/balance/supported/chain")
        response.raise_for_status()
        payload = response.json()
    if payload.get("code") != "0":
        raise ProviderError(str(payload.get("msg", "OKX DEX API error")))
    chains = []
    for item in payload.get("data", []):
        chain_index = str(item.get("chainIndex", ""))
        if chain_index not in EVM_CHAIN_INDEXES:
            continue
        chain_name = str(item.get("chainName", item.get("name", chain_index)))
        short_name = str(item.get("shortName", chain_name))
        chains.append(
            {
                "chainIndex": chain_index,
                "chainName": chain_name,
                "shortName": short_name,
                "defaultSelected": chain_index in DEFAULT_EVM_CHAIN_INDEXES,
            }
        )
    return chains
