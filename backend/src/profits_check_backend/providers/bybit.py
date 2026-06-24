from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from decimal import Decimal
from typing import Any
from urllib.parse import urlencode

from profits_check_backend.providers.base import (
    AssetBalance,
    ContractMarginBalanceRisk,
    ContractPositionRisk,
    FundingFeeRecord,
    Provider,
    ProviderError,
    ProviderSnapshot,
)
from profits_check_backend.providers.http import provider_http_client

BYBIT_RATE_LIMIT_RETRY_SECONDS = 2.0
BYBIT_RATE_LIMIT_MAX_RETRIES = 3
# Bybit's transaction-log nextPageCursor can cycle back to earlier pages instead
# of ending, so cap the pagination to a safe number of pages as a hard backstop.
BYBIT_FUNDING_MAX_PAGES = 200
BYBIT_RATE_LIMIT_RET_CODES = {10006, "10006"}


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
            overview_params = {"valuationCurrency": "USD"}
            overview_query_string = urlencode(overview_params)
            overview_headers = self._signature_headers(overview_query_string)
            overview_response = await client.get(
                f"{base_url}/v5/asset/asset-overview",
                headers=overview_headers,
                params=overview_params,
            )
            overview_response.raise_for_status()
            overview_payload = overview_response.json()

        if payload.get("retCode") not in {0, "0"}:
            raise ProviderError(str(payload.get("retMsg", "Bybit request failed")))

        accounts = payload.get("result", {}).get("list", [])
        if not accounts:
            return ProviderSnapshot(total_value_usd=Decimal("0"), assets=[])

        account = accounts[0]
        assets: list[AssetBalance] = []
        for item in account.get("coin", []):
            wallet_balance = Decimal(str(item.get("walletBalance", item.get("equity", "0"))))
            equity = Decimal(str(item.get("equity", wallet_balance)))
            borrowed = _first_decimal(item, "borrowAmount", "spotBorrow")
            value_usd = Decimal(str(item.get("usdValue", "0")))
            if wallet_balance == 0 and equity == 0 and borrowed == 0 and value_usd == 0:
                continue
            assets.append(
                AssetBalance(
                    asset_symbol=str(item.get("coin", "")).upper(),
                    quantity=wallet_balance,
                    value_usd=value_usd,
                    metadata={
                        "source": "bybit",
                        "type": "unified",
                        "equity": str(equity),
                        "borrowed": str(borrowed),
                        "walletBalance": str(wallet_balance),
                    },
                )
            )
        asset_total_value = sum(
            (asset.value_usd for asset in assets if asset.value_usd is not None),
            Decimal("0"),
        )
        equity_total_value = Decimal(str(account.get("totalEquity", "0")))
        wallet_total_value = Decimal(str(account.get("totalWalletBalance", "0")))
        total_value = equity_total_value or asset_total_value or wallet_total_value
        if overview_payload.get("retCode") in {0, "0"}:
            overview_assets, overview_total_value = _asset_overview_balances(overview_payload)
            assets.extend(overview_assets)
            if overview_total_value != 0:
                total_value = overview_total_value
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
        margin_balance = Decimal(
            str(account.get("totalMarginBalance", account.get("totalEquity", "0")))
        )
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

    async def collect_funding_fee_records(
        self, start_time_ms: int, end_time_ms: int
    ) -> list[FundingFeeRecord]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.bybit.com"))
        ).rstrip("/")
        category = str(self.config.get("fundingCategory", self.config.get("category", "linear")))
        records: list[FundingFeeRecord] = []
        cursor: str | None = None
        seen_cursors: set[str] = set()

        async with provider_http_client() as client:
            for _ in range(BYBIT_FUNDING_MAX_PAGES):
                params = {
                    "accountType": "UNIFIED",
                    "category": category,
                    "startTime": str(start_time_ms),
                    "endTime": str(end_time_ms),
                    "limit": "50",
                }
                if cursor:
                    params["cursor"] = cursor
                query_string = urlencode(params)
                payload = await self._get_bybit(
                    client,
                    base_url,
                    "/v5/account/transaction-log",
                    params,
                    query_string=query_string,
                )
                result = payload.get("result", {})
                items = result.get("list", []) if isinstance(result, dict) else []
                records.extend(
                    FundingFeeRecord(
                        provider="bybit",
                        channel_name=self.channel_name,
                        amount=Decimal(str(item.get("funding", "0"))),
                        asset=str(item.get("currency", "USDT")).upper(),
                        timestamp_ms=int(str(item.get("transactionTime", "0"))),
                        symbol=str(item.get("symbol", "")) or None,
                        raw_payload=dict(item),
                    )
                    for item in items
                    if isinstance(item, dict) and Decimal(str(item.get("funding", "0"))) != 0
                )
                next_cursor = (
                    str(result.get("nextPageCursor", "")) if isinstance(result, dict) else ""
                )
                # Terminate on an empty cursor, an immediate repeat, or any cursor
                # already requested — Bybit can return a cursor that cycles back to
                # an earlier page, which would otherwise loop forever.
                if not next_cursor or next_cursor == cursor or next_cursor in seen_cursors:
                    break
                seen_cursors.add(next_cursor)
                cursor = next_cursor

        return records

    async def _get_bybit(
        self,
        client,
        base_url: str,
        path: str,
        params: dict[str, str],
        *,
        query_string: str | None = None,
    ) -> dict[str, Any]:
        selected_query_string = query_string or urlencode(params)
        for attempt in range(BYBIT_RATE_LIMIT_MAX_RETRIES + 1):
            headers = self._signature_headers(selected_query_string)
            response = await client.get(f"{base_url}{path}", headers=headers, params=params)
            if response.status_code == 429 and attempt < BYBIT_RATE_LIMIT_MAX_RETRIES:
                retry_after = _retry_after_seconds(response)
                await asyncio.sleep(
                    retry_after if retry_after is not None else BYBIT_RATE_LIMIT_RETRY_SECONDS
                )
                continue
            response.raise_for_status()
            payload = response.json()
            if _is_bybit_rate_limited(payload) and attempt < BYBIT_RATE_LIMIT_MAX_RETRIES:
                await asyncio.sleep(BYBIT_RATE_LIMIT_RETRY_SECONDS)
                continue
            if payload.get("retCode") not in {0, "0"}:
                raise ProviderError(str(payload.get("retMsg", "Bybit request failed")))
            return dict(payload)
        raise ProviderError("Bybit request failed")

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


def _first_decimal(item: dict[str, object], *keys: str) -> Decimal:
    for key in keys:
        value = Decimal(str(item.get(key, "0") or "0"))
        if value != 0:
            return value
    return Decimal("0")


def _asset_overview_balances(payload: dict[str, object]) -> tuple[list[AssetBalance], Decimal]:
    result = payload.get("result", {})
    if not isinstance(result, dict):
        return [], Decimal("0")

    assets: list[AssetBalance] = []
    total_value = Decimal(str(result.get("totalEquity", "0") or "0"))
    for account in result.get("list", []):
        if not isinstance(account, dict):
            continue
        account_type = str(account.get("accountType", ""))
        account_scope = _asset_overview_scope(account_type)
        if account_scope is None:
            continue
        account_total_value = Decimal(str(account.get("totalEquity", "0") or "0"))
        if account_total_value != 0:
            assets.append(
                AssetBalance(
                    asset_symbol=f"{account_scope.upper()}_TOTAL",
                    quantity=Decimal("0"),
                    value_usd=account_total_value,
                    metadata={
                        "source": "bybit",
                        "type": account_scope,
                        "accountType": account_type,
                        "accountTotalEquity": str(account_total_value),
                        "coinDetail": json.dumps(account.get("coinDetail", [])),
                    },
                )
            )
    return assets, total_value


def _asset_overview_scope(account_type: str) -> str | None:
    if account_type == "UnifiedTradingAccount":
        return None
    mapping = {
        "CryptoLoans": "crypto_loans",
        "FundingAccount": "funding",
    }
    return mapping.get(account_type, _camel_to_snake(account_type))


def _camel_to_snake(value: str) -> str:
    output = []
    for index, char in enumerate(value):
        if char.isupper() and index > 0:
            output.append("_")
        output.append(char.lower())
    return "".join(output) or "asset_overview"


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))


def _is_bybit_rate_limited(payload: dict[str, Any]) -> bool:
    ret_msg = str(payload.get("retMsg", ""))
    return payload.get("retCode") in BYBIT_RATE_LIMIT_RET_CODES or "Too many visits" in ret_msg


def _retry_after_seconds(response: Any) -> float | None:
    retry_after = response.headers.get("Retry-After")
    if not retry_after:
        return None
    try:
        return max(float(retry_after), 0.0)
    except ValueError:
        return None
