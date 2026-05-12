from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlencode

import httpx

from profits_check_backend.providers.base import (
    AssetBalance,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client


class BinanceProvider(Provider):
    def __init__(
        self,
        channel_name: str,
        config: dict[str, object],
        secrets: dict[str, object],
        now_factory=None,
        signature_factory=None,
    ) -> None:
        self.channel_name = channel_name
        self.config = config
        self.secrets = secrets
        self.now_factory = now_factory or (lambda: int(time.time() * 1000))
        self.signature_factory = signature_factory or self._sign

    def _sign(self, query: str, secret: str) -> str:
        return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(
            self.config.get("base_url", self.config.get("baseUrl", "https://api.binance.com"))
        ).rstrip("/")
        futures_base_url = str(
            self.config.get(
                "futures_base_url", self.config.get("futuresBaseUrl", "https://fapi.binance.com")
            )
        ).rstrip("/")
        api_key = str(
            self.config.get(
                "api_key",
                self.config.get(
                    "apiKey", self.secrets.get("api_key", self.secrets.get("apiKey", ""))
                ),
            )
        )
        api_secret = str(self.secrets.get("api_secret", self.secrets.get("apiSecret", "")))
        if not base_url or not api_key or not api_secret:
            raise ProviderError("Binance API credentials are incomplete")

        async with provider_http_client() as client:
            assets, total_value = await self._collect_spot(client, base_url, api_key, api_secret)
            futures_assets, futures_total = await self._collect_futures(
                client, futures_base_url, api_key, api_secret
            )
            earn_assets, earn_total = await self._collect_earn(
                client, base_url, api_key, api_secret
            )
            loan_assets, loan_total = await self._collect_loans(
                client, base_url, api_key, api_secret
            )
            assets.extend(futures_assets)
            assets.extend(earn_assets)
            assets.extend(loan_assets)
            total_value += futures_total + earn_total + loan_total
            return ProviderSnapshot(total_value_usd=total_value, assets=assets)

    async def _collect_spot(
        self, client: httpx.AsyncClient, base_url: str, api_key: str, api_secret: str
    ) -> tuple[list[AssetBalance], Decimal]:
        timestamp = int(self.now_factory())
        query = urlencode({"timestamp": timestamp})
        signature = self.signature_factory(query, api_secret)
        account_url = f"{base_url}/api/v3/account?{query}&signature={signature}"

        account_response = await client.get(account_url, headers={"X-MBX-APIKEY": api_key})
        account_response.raise_for_status()
        account_payload = account_response.json()

        assets: list[AssetBalance] = []
        total_value = Decimal("0")
        for balance in account_payload.get("balances", []):
            asset_name = str(balance["asset"])
            free = Decimal(str(balance["free"]))
            locked = Decimal(str(balance["locked"]))
            quantity = free + locked
            if quantity == 0:
                continue
            value_usd = await self._estimate_asset_usd(
                client, base_url, api_key, asset_name, quantity
            )
            assets.append(
                AssetBalance(
                    asset_symbol=asset_name,
                    quantity=quantity,
                    value_usd=value_usd,
                    metadata={"source": "binance", "type": "spot"},
                )
            )
            if value_usd is not None:
                total_value += value_usd
        return assets, total_value

    async def _estimate_asset_usd(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        api_key: str,
        asset_name: str,
        quantity: Decimal,
    ) -> Decimal | None:
        if asset_name in ("USDT", "USDC", "USD", "BUSD", "FDUSD"):
            return quantity
        try:
            price_response = await client.get(
                f"{base_url}/api/v3/ticker/price?symbol={asset_name}USDT",
                headers={"X-MBX-APIKEY": api_key},
            )
            price_response.raise_for_status()
            price = Decimal(str(price_response.json()["price"]))
            return quantity * price
        except Exception:
            return None

    async def _collect_futures(
        self, client: httpx.AsyncClient, futures_base_url: str, api_key: str, api_secret: str
    ) -> tuple[list[AssetBalance], Decimal]:
        try:
            timestamp = int(self.now_factory())
            query = urlencode({"timestamp": timestamp})
            signature = self.signature_factory(query, api_secret)
            account_url = f"{futures_base_url}/fapi/v2/account?{query}&signature={signature}"

            response = await client.get(account_url, headers={"X-MBX-APIKEY": api_key})
            response.raise_for_status()
            payload = response.json()

            assets: list[AssetBalance] = []
            total_value = Decimal("0")

            for item in payload.get("assets", []):
                wallet_balance = Decimal(str(item.get("walletBalance", "0")))
                unrealized = Decimal(str(item.get("unrealizedProfit", "0")))
                if wallet_balance == 0 and unrealized == 0:
                    continue
                asset_name = str(item.get("asset", "")).upper()
                value_usd = wallet_balance + unrealized
                assets.append(
                    AssetBalance(
                        asset_symbol=asset_name,
                        quantity=wallet_balance,
                        value_usd=value_usd,
                        metadata={
                            "source": "binance",
                            "type": "futures",
                            "unrealizedProfit": str(unrealized),
                        },
                    )
                )
                total_value += value_usd

            return assets, total_value
        except Exception:
            return [], Decimal("0")

    async def _collect_earn(
        self, client: httpx.AsyncClient, base_url: str, api_key: str, api_secret: str
    ) -> tuple[list[AssetBalance], Decimal]:
        assets: list[AssetBalance] = []
        total_value = Decimal("0")

        for earn_type, path in [
            ("earn_flexible", "/sapi/v1/simple-earn/flexible/position"),
            ("earn_locked", "/sapi/v1/simple-earn/locked/position"),
        ]:
            try:
                timestamp = int(self.now_factory())
                query = urlencode({"timestamp": timestamp})
                signature = self.signature_factory(query, api_secret)
                url = f"{base_url}{path}?{query}&signature={signature}"

                response = await client.get(url, headers={"X-MBX-APIKEY": api_key})
                response.raise_for_status()
                payload = response.json()

                for item in payload.get("rows", []):
                    total_amount = Decimal(str(item.get("totalAmount", "0")))
                    if total_amount == 0:
                        continue
                    asset_name = str(item.get("asset", "")).upper()
                    value_usd = await self._estimate_asset_usd(
                        client, base_url, api_key, asset_name, total_amount
                    )
                    assets.append(
                        AssetBalance(
                            asset_symbol=asset_name,
                            quantity=total_amount,
                            value_usd=value_usd,
                            metadata={"source": "binance", "type": earn_type},
                        )
                    )
                    if value_usd is not None:
                        total_value += value_usd
            except Exception:
                pass

        return assets, total_value

    async def _collect_loans(
        self, client: httpx.AsyncClient, base_url: str, api_key: str, api_secret: str
    ) -> tuple[list[AssetBalance], Decimal]:
        try:
            timestamp = int(self.now_factory())
            query = urlencode({"timestamp": timestamp})
            signature = self.signature_factory(query, api_secret)
            url = f"{base_url}/sapi/v2/loan/flexible/ongoing/orders?{query}&signature={signature}"

            response = await client.get(url, headers={"X-MBX-APIKEY": api_key})
            response.raise_for_status()
            payload = response.json()

            assets: list[AssetBalance] = []
            total_value = Decimal("0")

            for order in payload.get("rows", []):
                collateral_coin = str(order.get("collateralCoin", "")).upper()
                collateral_amount = Decimal(str(order.get("collateralAmount", "0")))
                if collateral_coin and collateral_amount > 0:
                    value_usd = await self._estimate_asset_usd(
                        client, base_url, api_key, collateral_coin, collateral_amount
                    )
                    assets.append(
                        AssetBalance(
                            asset_symbol=collateral_coin,
                            quantity=collateral_amount,
                            value_usd=value_usd,
                            metadata={
                                "source": "binance",
                                "type": "loan_collateral",
                                "ltv": str(order.get("currentLTV", "0")),
                            },
                        )
                    )
                    if value_usd is not None:
                        total_value += value_usd

                loan_coin = str(order.get("loanCoin", "")).upper()
                total_debt = Decimal(str(order.get("totalDebt", "0")))
                if loan_coin and total_debt > 0:
                    debt_value = await self._estimate_asset_usd(
                        client, base_url, api_key, loan_coin, total_debt
                    )
                    assets.append(
                        AssetBalance(
                            asset_symbol=loan_coin,
                            quantity=-total_debt,
                            value_usd=-debt_value if debt_value is not None else None,
                            metadata={"source": "binance", "type": "loan_debt"},
                        )
                    )
                    if debt_value is not None:
                        total_value -= debt_value

            return assets, total_value
        except Exception:
            return [], Decimal("0")

    def normalize_mock_payload(self, channel_id: int, payload: dict[str, object]) -> list[Any]:
        from profits_check_backend.services.snapshots import NormalizedAssetBalance

        prices = cast(dict[str, object], payload["prices"])
        account = cast(dict[str, object], payload["account"])
        balances_payload = cast(list[dict[str, object]], account["balances"])
        balances = []
        for item in balances_payload:
            total = Decimal(str(item["free"])) + Decimal(str(item["locked"]))
            price = Decimal(str(prices.get(f"{item['asset']}USDT", "1")))
            balances.append(
                NormalizedAssetBalance(
                    provider="binance",
                    channel_id=channel_id,
                    account_scope="spot",
                    asset=str(item["asset"]),
                    total=total,
                    available=Decimal(str(item["free"])),
                    locked=Decimal(str(item["locked"])),
                    borrowed=Decimal("0"),
                    unrealized_pnl=Decimal("0"),
                    value_usd=total * price,
                    raw_payload={"balance": item},
                )
            )
        return balances
