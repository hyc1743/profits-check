from __future__ import annotations

import hashlib
import hmac
import json
import time
import urllib.parse
from decimal import Decimal
from typing import Any, cast
from urllib.parse import urlencode

import httpx
from eth_account import Account
from eth_account.messages import encode_typed_data

from profits_check_backend.providers.base import (
    AssetBalance,
    ContractPositionRisk,
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
        signature_factory=None,
    ) -> None:
        self.channel_name = channel_name
        self.config = config
        self.secrets = secrets
        self.now_factory = now_factory or (lambda: int(time.time() * 1_000_000))
        self.position_now_factory = now_factory or (lambda: int(time.time() * 1000))
        self.signature_factory = signature_factory or self._sign

    def _sign(self, query: str, secret: str) -> str:
        return hmac.new(secret.encode(), query.encode(), hashlib.sha256).hexdigest()

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
            payload = await self._fetch_wallet_balance(client, rpc_url, wallet_address)
            result = payload.get("result", {})
            signed_positions = await self._collect_signed_positions(client)
            positions = self._normalize_positions(result.get("positions", []), signed_positions)

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

            for position in positions:
                perp_value += Decimal(position["unRealizedProfit"])

            if perp_quantity != 0 or perp_value != 0 or positions:
                metadata = {"source": "aster", "type": "perp"}
                if positions:
                    metadata["positionCount"] = str(len(positions))
                    metadata["positions"] = json.dumps(
                        positions, ensure_ascii=False, separators=(",", ":")
                    )
                assets.append(
                    AssetBalance(
                        asset_symbol="USDT",
                        quantity=perp_quantity,
                        value_usd=perp_value,
                        metadata=metadata,
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

    async def _fetch_wallet_balance(
        self, client: httpx.AsyncClient, rpc_url: str, wallet_address: str
    ) -> dict[str, Any]:
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
        return cast(dict[str, Any], payload)

    async def _collect_signed_positions(
        self, client: httpx.AsyncClient
    ) -> list[dict[str, Any]] | None:
        api_key = str(self.secrets.get("apiKey", self.secrets.get("api_key", "")))
        api_secret = str(self.secrets.get("apiSecret", self.secrets.get("api_secret", "")))
        if not api_key or not api_secret:
            return None

        try:
            fapi_base = str(self.config.get("futuresBaseUrl", "https://fapi.asterdex.com")).rstrip(
                "/"
            )
            timestamp = int(self.position_now_factory())
            query = urlencode({"timestamp": timestamp})
            signature = self.signature_factory(query, api_secret)
            response = await client.get(
                f"{fapi_base}/fapi/v3/positionRisk?{query}&signature={signature}",
                headers={"X-MBX-APIKEY": api_key},
            )
            response.raise_for_status()
            payload = response.json()
            return cast(list[dict[str, Any]], payload if isinstance(payload, list) else [])
        except Exception:
            return None

    def _normalize_positions(
        self,
        rpc_positions: object,
        signed_positions: list[dict[str, Any]] | None,
    ) -> list[dict[str, str]]:
        raw_positions = signed_positions if signed_positions is not None else []
        if signed_positions is None:
            for product in cast(list[dict[str, Any]], rpc_positions or []):
                raw_positions.extend(cast(list[dict[str, Any]], product.get("positions", [])))

        positions: list[dict[str, str]] = []
        for raw in raw_positions:
            amount = Decimal(str(raw.get("positionAmt", raw.get("positionAmount", "0"))))
            if amount == 0:
                continue
            entry_price = str(raw.get("entryPrice", "0"))
            mark_price = str(raw.get("markPrice", "0"))
            liquidation_price = str(raw.get("liquidationPrice", raw.get("liquidation_price", "0")))
            unrealized = str(raw.get("unRealizedProfit", raw.get("unrealizedProfit", "0")))
            position_side = str(raw.get("positionSide", "LONG" if amount > 0 else "SHORT"))
            positions.append(
                {
                    "symbol": str(raw.get("symbol", "")),
                    "positionAmt": str(raw.get("positionAmt", raw.get("positionAmount", "0"))),
                    "positionSide": position_side,
                    "entryPrice": entry_price,
                    "markPrice": mark_price,
                    "liquidationPrice": liquidation_price,
                    "liquidationDistancePct": self._liquidation_distance_pct(
                        mark_price, liquidation_price
                    ),
                    "unRealizedProfit": unrealized,
                }
            )
        return positions

    def _liquidation_distance_pct(self, mark_price: str, liquidation_price: str) -> str:
        mark = Decimal(str(mark_price or "0"))
        liquidation = Decimal(str(liquidation_price or "0"))
        if mark == 0 or liquidation == 0:
            return "∞"
        distance = abs(mark - liquidation) / mark * Decimal("100")
        return str(distance.quantize(Decimal("0.00000001")))

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        base_url = str(self.config.get("futuresBaseUrl", "https://fapi3.asterdex.com")).rstrip("/")
        path = "/fapi/v3/positionRisk"
        params = self._signed_params({})
        async with provider_http_client() as client:
            response = await client.get(f"{base_url}{path}", params=params)
            response.raise_for_status()
            payload = response.json()
        return [
            self._position_from_payload(item)
            for item in payload
            if Decimal(str(item.get("positionAmt", "0"))) != 0
        ]

    def _signed_params(self, params: dict[str, str]) -> dict[str, str]:
        user = str(self.secrets.get("user", self.secrets.get("asterUser", "")))
        signer = str(self.secrets.get("signer", self.secrets.get("asterSigner", "")))
        private_key = str(self.secrets.get("privateKey", self.secrets.get("asterPrivateKey", "")))
        if not user or not signer or not private_key:
            raise ProviderError("Aster API wallet credentials are incomplete")
        signed_params = {**params, "user": user, "signer": signer, "nonce": str(self.now_factory())}
        param_text = urllib.parse.urlencode(signed_params)
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                    {"name": "verifyingContract", "type": "address"},
                ],
                "Message": [{"name": "msg", "type": "string"}],
            },
            "primaryType": "Message",
            "domain": {
                "name": "AsterSignTransaction",
                "version": "1",
                "chainId": 1666,
                "verifyingContract": "0x0000000000000000000000000000000000000000",
            },
            "message": {"msg": param_text},
        }
        signed = Account.sign_message(encode_typed_data(full_message=typed_data), private_key)
        return {**signed_params, "signature": signed.signature.hex()}

    def _position_from_payload(self, item: dict[str, object]) -> ContractPositionRisk:
        return ContractPositionRisk(
            provider="aster",
            channel_name=self.channel_name,
            symbol=str(item.get("symbol", "")),
            side=str(item.get("positionSide", "BOTH")),
            quantity=Decimal(str(item.get("positionAmt", "0"))),
            entry_price=_optional_decimal(item.get("entryPrice")),
            mark_price=Decimal(str(item.get("markPrice", "0"))),
            liquidation_price=_optional_decimal(item.get("liquidationPrice")),
            unrealized_pnl=_optional_decimal(item.get("unRealizedProfit")),
            margin_mode=str(item.get("marginType", "")) or None,
            leverage=str(item.get("leverage", "")) or None,
            updated_at_ms=_optional_int(item.get("updateTime")),
            raw_payload=dict(item),
        )

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


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    return None if parsed == 0 else parsed


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))
