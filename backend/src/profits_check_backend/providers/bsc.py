from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast

import httpx

from profits_check_backend.config import get_settings
from profits_check_backend.providers.base import AssetBalance, Provider, ProviderError, ProviderSnapshot


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

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(
            self.config.get("base_url", self.config.get("baseUrl", "https://web3.okx.com"))
        ).rstrip("/")
        wallet_address = str(
            self.config.get("wallet_address", self.config.get("walletAddress", ""))
        )
        if not wallet_address:
            addresses = cast(list[str], self.config.get("walletAddresses", []))
            wallet_address = str(addresses[0]) if addresses else ""
        if not wallet_address:
            raise ProviderError("Wallet address is missing")

        chains = str(self.config.get("chains", "56"))
        path = (
            f"/api/v6/dex/balance/all-token-balances-by-address"
            f"?address={wallet_address}&chains={chains}&excludeRiskToken=1"
        )
        headers = self._signature_headers("GET", path)

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()

        if payload.get("code") != "0":
            raise ProviderError(str(payload.get("msg", "OKX DEX API error")))

        assets: list[AssetBalance] = []
        total_value = Decimal("0")

        for chain_data in payload.get("data", []):
            for item in chain_data.get("tokenAssets", []):
                symbol = str(item.get("symbol", "")).upper()
                balance = Decimal(str(item.get("balance", "0")))
                if balance == 0:
                    continue
                price = Decimal(str(item.get("tokenPrice", "0")))
                value_usd = balance * price
                is_native = not item.get("tokenContractAddress")
                chain_index = str(item.get("chainIndex", ""))
                assets.append(
                    AssetBalance(
                        asset_symbol=symbol,
                        quantity=balance,
                        value_usd=value_usd,
                        metadata={
                            "source": "onchain",
                            "type": "native" if is_native else "token",
                            "chainIndex": chain_index,
                            "tokenPrice": str(price),
                        },
                    )
                )
                total_value += value_usd

        return ProviderSnapshot(total_value_usd=total_value, assets=assets)


    def normalize_mock_payload(
        self, channel_id: int, payload: dict[str, object]
    ) -> list[Any]:
        from profits_check_backend.services.snapshots import NormalizedAssetBalance

        balances = []
        wallet = str(payload["wallet"])
        native = cast(dict[str, object], payload["native"])
        native_balance = Decimal(str(native["balance"]))
        native_price = Decimal(str(native["priceUsd"]))
        balances.append(
            NormalizedAssetBalance(
                provider="bsc",
                channel_id=channel_id,
                account_scope=f"wallet:{wallet}",
                asset=str(native["symbol"]),
                total=native_balance,
                available=native_balance,
                locked=Decimal("0"),
                borrowed=Decimal("0"),
                unrealized_pnl=Decimal("0"),
                value_usd=native_balance * native_price,
                raw_payload={"native": native},
            )
        )
        tokens = cast(list[dict[str, object]], payload["tokens"])
        for token in tokens:
            quantity = Decimal(str(token["balance"]))
            price = Decimal(str(token["priceUsd"]))
            balances.append(
                NormalizedAssetBalance(
                    provider="bsc",
                    channel_id=channel_id,
                    account_scope=f"wallet:{wallet}",
                    asset=str(token["symbol"]),
                    total=quantity,
                    available=quantity,
                    locked=Decimal("0"),
                    borrowed=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    value_usd=quantity * price,
                    raw_payload={"token": token},
                )
            )
        return balances


# Keep backward compatibility alias
BscProvider = OnChainProvider
