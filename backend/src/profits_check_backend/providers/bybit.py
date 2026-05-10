from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from urllib.parse import urlencode

import httpx

from profits_check_backend.providers.base import AssetBalance, Provider, ProviderError, ProviderSnapshot


class BybitProvider(Provider):
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
        self.now_factory = now_factory or (lambda: str(int(time.time() * 1000)))

    def _signature_headers(self, query_string: str) -> dict[str, str]:
        api_key = str(self.secrets.get("apiKey", ""))
        api_secret = str(self.secrets.get("apiSecret", ""))
        recv_window = "5000"
        if not api_key or not api_secret:
            raise ProviderError("Bybit API credentials are incomplete")

        timestamp = str(self.now_factory())
        payload = f"{timestamp}{api_key}{recv_window}{query_string}"
        signature = hmac.new(
            api_secret.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "X-BAPI-API-KEY": api_key,
            "X-BAPI-TIMESTAMP": timestamp,
            "X-BAPI-RECV-WINDOW": recv_window,
            "X-BAPI-SIGN": signature,
        }

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(self.config.get("baseUrl", self.config.get("base_url", "https://api.bybit.com"))).rstrip("/")
        params = {"accountType": "UNIFIED"}
        query_string = urlencode(params)
        headers = self._signature_headers(query_string)

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base_url}/v5/account/wallet-balance",
                headers=headers,
                params=params,
            )
            response.raise_for_status()
            payload = response.json()

        if payload.get("retCode") not in {0, "0"}:
            raise ProviderError(str(payload.get("retMsg", "Bybit request failed")))

        accounts = payload.get("result", {}).get("list", [])
        if not accounts:
            return ProviderSnapshot(total_value_usd=Decimal("0"), assets=[])

        account = accounts[0]
        total_value = Decimal(str(account.get("totalWalletBalance", "0")))
        assets: list[AssetBalance] = []
        for item in account.get("coin", []):
            quantity = Decimal(str(item.get("equity", item.get("walletBalance", "0"))))
            if quantity == 0:
                continue
            assets.append(
                AssetBalance(
                    asset_symbol=str(item.get("coin", "")).upper(),
                    quantity=quantity,
                    value_usd=Decimal(str(item.get("usdValue", "0"))),
                    metadata={"source": "bybit", "type": "unified"},
                )
            )
        return ProviderSnapshot(total_value_usd=total_value, assets=assets)
