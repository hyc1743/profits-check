from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal
from urllib.parse import urlencode

from profits_check_backend.providers.base import (
    AssetBalance,
    ContractMarginBalanceRisk,
    ContractPositionRisk,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client


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
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bybit.com"))
        ).rstrip("/")
        params = {"accountType": "UNIFIED"}
        query_string = urlencode(params)
        headers = self._signature_headers(query_string)

        async with provider_http_client() as client:
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

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bybit.com"))
        ).rstrip("/")
        category = str(self.config.get("positionCategory", self.config.get("category", "linear")))
        params = {"category": category}
        if category == "linear":
            params["settleCoin"] = str(
                self.config.get("settleCoin", self.config.get("settle_coin", "USDT"))
            ).upper()
        query_string = urlencode(params)
        headers = self._signature_headers(query_string)
        async with provider_http_client() as client:
            response = await client.get(
                f"{base_url}/v5/position/list", headers=headers, params=params
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("retCode") not in {0, "0"}:
            raise ProviderError(str(payload.get("retMsg", "Bybit request failed")))
        return [
            self._position_from_payload(item)
            for item in payload.get("result", {}).get("list", [])
            if Decimal(str(item.get("size", "0"))) != 0
        ]

    async def collect_contract_margin_balance(self) -> ContractMarginBalanceRisk | None:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bybit.com"))
        ).rstrip("/")
        params = {"accountType": "UNIFIED"}
        query_string = urlencode(params)
        headers = self._signature_headers(query_string)
        async with provider_http_client() as client:
            response = await client.get(
                f"{base_url}/v5/account/wallet-balance", headers=headers, params=params
            )
            response.raise_for_status()
            payload = response.json()
        if payload.get("retCode") not in {0, "0"}:
            raise ProviderError(str(payload.get("retMsg", "Bybit request failed")))
        accounts = payload.get("result", {}).get("list", [])
        if not accounts:
            return None
        account = accounts[0]
        wallet_balance = Decimal(str(account.get("totalWalletBalance", "0")))
        margin_balance = Decimal(str(account.get("totalMarginBalance", account.get("totalEquity", "0"))))
        unrealized_pnl = Decimal(str(account.get("totalPerpUPL", "0")))
        if wallet_balance == 0 and margin_balance == 0 and unrealized_pnl == 0:
            return None
        return ContractMarginBalanceRisk(
            provider="bybit",
            channel_name=self.channel_name,
            wallet_balance=wallet_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
            raw_payload=dict(account),
        )

    def _position_from_payload(self, item: dict[str, object]) -> ContractPositionRisk:
        return ContractPositionRisk(
            provider="bybit",
            channel_name=self.channel_name,
            symbol=str(item.get("symbol", "")),
            side=str(item.get("side", "")),
            quantity=Decimal(str(item.get("size", "0"))),
            entry_price=_optional_decimal(item.get("avgPrice")),
            mark_price=Decimal(str(item.get("markPrice", "0"))),
            liquidation_price=_optional_decimal(item.get("liqPrice")),
            unrealized_pnl=_optional_decimal(item.get("unrealisedPnl")),
            margin_mode=str(item.get("tradeMode", "")) or None,
            leverage=str(item.get("leverage", "")) or None,
            updated_at_ms=_optional_int(item.get("updatedTime")),
            raw_payload=dict(item),
        )


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    return None if parsed == 0 else parsed


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))
