from __future__ import annotations

import base64
import hashlib
import hmac
from datetime import UTC, datetime
from decimal import Decimal

import httpx

from profits_check_backend.providers.base import AssetBalance, Provider, ProviderError, ProviderSnapshot


class OkxProvider(Provider):
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
        self.now_factory = now_factory or (lambda: datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"))

    def _signature_headers(self, method: str, path_with_query: str) -> dict[str, str]:
        api_key = str(self.secrets.get("apiKey", ""))
        api_secret = str(self.secrets.get("apiSecret", ""))
        passphrase = str(self.secrets.get("passphrase", ""))
        if not api_key or not api_secret or not passphrase:
            raise ProviderError("OKX API credentials are incomplete")

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
        base_url = str(self.config.get("baseUrl", self.config.get("base_url", "https://www.okx.com"))).rstrip("/")
        path = "/api/v5/account/balance"
        headers = self._signature_headers("GET", path)

        async with httpx.AsyncClient() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data", [])
        if not data:
            return ProviderSnapshot(total_value_usd=Decimal("0"), assets=[])

        details = data[0].get("details", [])
        assets: list[AssetBalance] = []
        total_value = Decimal(str(data[0].get("totalEq", "0")))
        for item in details:
            quantity = Decimal(str(item.get("eq", "0")))
            if quantity == 0:
                continue
            assets.append(
                AssetBalance(
                    asset_symbol=str(item.get("ccy", "")).upper(),
                    quantity=quantity,
                    value_usd=Decimal(str(item.get("eqUsd", item.get("disEq", "0")))),
                    metadata={"source": "okx", "type": "trading"},
                )
            )
        return ProviderSnapshot(total_value_usd=total_value, assets=assets)
