from __future__ import annotations

from decimal import Decimal
from typing import cast

import httpx

from profits_check_backend.providers.base import (
    AssetBalance,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client


class AsterProvider(Provider):
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

    async def collect_snapshot(self) -> ProviderSnapshot:
        rpc_url = str(
            self.config.get("rpcUrl", self.config.get("rpc_url", "https://tapi.asterdex.com/info"))
        )
        wallet_address = str(
            self.config.get("walletAddress", self.config.get("wallet_address", ""))
        )
        if not wallet_address:
            addresses = cast(list[str], self.config.get("walletAddresses", []))
            wallet_address = str(addresses[0]) if addresses else ""
        if not wallet_address:
            raise ProviderError("Aster wallet address is required")

        async with provider_http_client() as client:
            resp = await client.post(
                rpc_url,
                json={
                    "id": {},
                    "jsonrpc": "2.0",
                    "method": "aster_getBalance",
                    "params": [wallet_address, "latest"],
                },
            )
            resp.raise_for_status()
            payload = resp.json()
            if "error" in payload:
                raise ProviderError(str(payload["error"].get("message", payload["error"])))

        result = payload.get("result", {})
        assets: list[AssetBalance] = []
        total_value = Decimal("0")
        perp_value = Decimal("0")
        perp_quantity = Decimal("0")

        for item in result.get("perpAssets", []):
            balance = Decimal(str(item.get("walletBalance", "0")))
            if balance == 0:
                continue
            asset = str(item.get("asset", "")).upper()
            if asset == "USD1":
                asset = "USDT"
            perp_quantity += balance
            perp_value += balance

        for product in result.get("positions", []):
            for pos in product.get("positions", []):
                unrealized = Decimal(str(pos.get("unrealizedProfit", "0")))
                perp_value += unrealized

        if perp_quantity != 0 or perp_value != 0:
            assets.append(
                AssetBalance(
                    asset_symbol="USDT",
                    quantity=perp_quantity,
                    value_usd=perp_value,
                    metadata={"source": "aster", "type": "perp"},
                )
            )
            total_value += perp_value

        spot_total = Decimal("0")
        spot_count = 0
        for item in result.get("spotAssets", []):
            balance = Decimal(str(item.get("walletBalance", "0")))
            if balance == 0:
                continue
            spot_count += 1
            asset = str(item.get("asset", "")).upper()
            price = await self._estimate_spot_price(client, asset, balance)
            spot_total_asset = price if price is not None else Decimal("0")
            spot_total += spot_total_asset

        if spot_count > 0:
            assets.append(
                AssetBalance(
                    asset_symbol="USDT",
                    quantity=spot_total,
                    value_usd=spot_total if spot_total != 0 else None,
                    metadata={"source": "aster", "type": "spot"},
                )
            )
            total_value += spot_total

        if not assets:
            raise ProviderError("Aster returned no balances")
        return ProviderSnapshot(total_value_usd=total_value, assets=assets)

    async def _estimate_spot_price(
        self, client: httpx.AsyncClient, asset: str, quantity: Decimal
    ) -> Decimal | None:
        if asset in {"USDT", "USDC", "USD"}:
            return quantity
        try:
            fapi_base = str(self.config.get("futuresBaseUrl", "https://fapi.asterdex.com")).rstrip(
                "/"
            )
            resp = await client.get(
                f"{fapi_base}/fapi/v3/ticker/price", params={"symbol": f"{asset}USDT"}
            )
            resp.raise_for_status()
            payload = resp.json()
            price = payload.get("price") if isinstance(payload, dict) else None
            if price is None:
                return None
            return quantity * Decimal(str(price))
        except Exception:
            return None
