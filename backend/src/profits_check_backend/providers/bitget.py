from __future__ import annotations

import base64
import hashlib
import hmac
import time
from decimal import Decimal

import httpx

from profits_check_backend.providers.base import (
    AssetBalance,
    ContractMarginBalanceRisk,
    ContractPositionRisk,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client


class BitgetProvider(Provider):
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

    def _signature_headers(
        self, method: str, request_path: str, query: str = "", body: str = ""
    ) -> dict[str, str]:
        api_key = str(self.secrets.get("apiKey", ""))
        api_secret = str(self.secrets.get("apiSecret", ""))
        passphrase = str(self.secrets.get("passphrase", ""))
        if not api_key or not api_secret or not passphrase:
            raise ProviderError("Bitget API credentials are incomplete")

        timestamp = str(self.now_factory())
        query_suffix = f"?{query}" if query else ""
        prehash = f"{timestamp}{method}{request_path}{query_suffix}{body}"
        signature = base64.b64encode(
            hmac.new(api_secret.encode("utf-8"), prehash.encode("utf-8"), hashlib.sha256).digest()
        ).decode()
        return {
            "ACCESS-KEY": api_key,
            "ACCESS-SIGN": signature,
            "ACCESS-TIMESTAMP": timestamp,
            "ACCESS-PASSPHRASE": passphrase,
            "locale": "en-US",
        }

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bitget.com"))
        ).rstrip("/")

        async with provider_http_client() as client:
            assets, total_value = await self._collect_spot(client, base_url)
            futures_assets, futures_total = await self._collect_futures(client, base_url)
            assets.extend(futures_assets)
            total_value += futures_total
            return ProviderSnapshot(total_value_usd=total_value, assets=assets)

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bitget.com"))
        ).rstrip("/")
        path = "/api/v2/mix/position/all-position"
        product_type = str(self.config.get("productType", "USDT-FUTURES"))
        query = f"productType={product_type}"
        headers = self._signature_headers("GET", path, query=query)
        async with provider_http_client() as client:
            response = await client.get(
                f"{base_url}{path}", headers=headers, params={"productType": product_type}
            )
            response.raise_for_status()
            payload = response.json()
        return [
            self._position_from_payload(item)
            for item in payload.get("data", [])
            if Decimal(str(item.get("total", item.get("size", "0")))) != 0
        ]

    async def collect_contract_margin_balance(self) -> ContractMarginBalanceRisk | None:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bitget.com"))
        ).rstrip("/")
        path = "/api/v2/mix/account/accounts"
        product_type = str(self.config.get("productType", "USDT-FUTURES"))
        query = f"productType={product_type}"
        headers = self._signature_headers("GET", path, query=query)
        async with provider_http_client() as client:
            response = await client.get(
                f"{base_url}{path}", headers=headers, params={"productType": product_type}
            )
            response.raise_for_status()
            payload = response.json()
        wallet_balance = Decimal("0")
        margin_balance = Decimal("0")
        unrealized_pnl = Decimal("0")
        for item in payload.get("data", []):
            equity = Decimal(str(item.get("accountEquity", "0")))
            unrealized = Decimal(str(item.get("unrealizedPL", "0")))
            margin_balance += equity
            unrealized_pnl += unrealized
            wallet_balance += equity - unrealized
        if wallet_balance == 0 and margin_balance == 0 and unrealized_pnl == 0:
            return None
        return ContractMarginBalanceRisk(
            provider="bitget",
            channel_name=self.channel_name,
            wallet_balance=wallet_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
            raw_payload=dict(payload),
        )

    def _position_from_payload(self, item: dict[str, object]) -> ContractPositionRisk:
        return ContractPositionRisk(
            provider="bitget",
            channel_name=self.channel_name,
            symbol=str(item.get("symbol", "")),
            side=str(item.get("holdSide", "")),
            quantity=Decimal(str(item.get("total", item.get("size", "0")))),
            entry_price=_optional_decimal(item.get("openPriceAvg")),
            mark_price=Decimal(str(item.get("markPrice", "0"))),
            liquidation_price=_optional_decimal(item.get("liquidationPrice")),
            unrealized_pnl=_optional_decimal(item.get("unrealizedPL")),
            margin_mode=str(item.get("marginMode", "")) or None,
            leverage=str(item.get("leverage", "")) or None,
            updated_at_ms=_optional_int(item.get("uTime")),
            raw_payload=dict(item),
        )

    async def _collect_spot(
        self, client: httpx.AsyncClient, base_url: str
    ) -> tuple[list[AssetBalance], Decimal]:
        path = "/api/v2/spot/account/assets"
        query = "assetType=all"
        headers = self._signature_headers("GET", path, query=query)

        response = await client.get(
            f"{base_url}{path}", headers=headers, params={"assetType": "all"}
        )
        response.raise_for_status()
        payload = response.json()

        assets: list[AssetBalance] = []
        total_value = Decimal("0")
        for item in payload.get("data", []):
            available = Decimal(str(item.get("available", "0")))
            frozen = Decimal(str(item.get("frozen", "0")))
            locked = Decimal(str(item.get("locked", "0")))
            quantity = available + frozen + locked
            if quantity == 0:
                continue
            asset = str(item.get("coin", "")).upper()
            value = await self._estimate_usd_value(client, base_url, asset, quantity)
            assets.append(
                AssetBalance(
                    asset_symbol=asset,
                    quantity=quantity,
                    value_usd=value,
                    metadata={"source": "bitget", "type": "spot"},
                )
            )
            if value is not None:
                total_value += value
        return assets, total_value

    async def _collect_futures(
        self, client: httpx.AsyncClient, base_url: str
    ) -> tuple[list[AssetBalance], Decimal]:
        try:
            path = "/api/v2/mix/account/accounts"
            query = "productType=USDT-FUTURES"
            headers = self._signature_headers("GET", path, query=query)

            response = await client.get(
                f"{base_url}{path}", headers=headers, params={"productType": "USDT-FUTURES"}
            )
            response.raise_for_status()
            payload = response.json()

            assets: list[AssetBalance] = []
            total_value = Decimal("0")
            for item in payload.get("data", []):
                equity = Decimal(str(item.get("accountEquity", "0")))
                if equity == 0:
                    continue
                unrealized = Decimal(str(item.get("unrealizedPL", "0")))
                margin_coin = str(item.get("marginCoin", "USDT")).upper()
                assets.append(
                    AssetBalance(
                        asset_symbol=margin_coin,
                        quantity=equity,
                        value_usd=equity,
                        metadata={
                            "source": "bitget",
                            "type": "futures",
                            "available": str(item.get("available", "0")),
                            "unrealizedPL": str(unrealized),
                        },
                    )
                )
                total_value += equity
            return assets, total_value
        except Exception:
            return [], Decimal("0")

    async def _estimate_usd_value(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        asset: str,
        quantity: Decimal,
    ) -> Decimal | None:
        if asset in {"USDT", "USDC", "USD"}:
            return quantity

        try:
            response = await client.get(
                f"{base_url}/api/v2/spot/market/tickers",
                params={"symbol": f"{asset}USDT"},
            )
            response.raise_for_status()
            data = response.json().get("data", [])
            if not data:
                return None
            return quantity * Decimal(str(data[0]["lastPr"]))
        except Exception:
            return None


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    return None if parsed == 0 else parsed


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))
