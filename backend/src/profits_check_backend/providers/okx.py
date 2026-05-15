from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
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

OKX_CONTRACT_POSITION_TYPES = ("SWAP", "FUTURES")
OKX_GRID_STRATEGY_TYPES = ("grid", "contract_grid")
OKX_DCA_STRATEGY_TYPES = ("spot_dca", "contract_dca")


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
        self.now_factory = now_factory or (
            lambda: datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        )

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
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://www.okx.com"))
        ).rstrip("/")
        path = "/api/v5/account/balance"

        async with provider_http_client() as client:
            payload = await self._get_okx(client, base_url, path)

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
            assets.extend(await self._collect_strategy_assets(client, base_url))
            return ProviderSnapshot(total_value_usd=total_value, assets=assets)

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://www.okx.com"))
        ).rstrip("/")
        positions: list[ContractPositionRisk] = []
        async with provider_http_client() as client:
            for inst_type in OKX_CONTRACT_POSITION_TYPES:
                path = f"/api/v5/account/positions?instType={inst_type}"
                headers = self._signature_headers("GET", path)
                response = await client.get(
                    f"{base_url}/api/v5/account/positions",
                    headers=headers,
                    params={"instType": inst_type},
                )
                response.raise_for_status()
                payload = response.json()
                if payload.get("code") not in {0, "0", None}:
                    raise ProviderError(str(payload.get("msg", "OKX request failed")))
                positions.extend(
                    self._position_from_payload(item)
                    for item in payload.get("data", [])
                    if _optional_decimal(item.get("pos")) not in (None, Decimal("0"))
                )
        return positions

    async def collect_contract_margin_balance(self) -> ContractMarginBalanceRisk | None:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://www.okx.com"))
        ).rstrip("/")
        path = "/api/v5/account/account-position-risk"
        headers = self._signature_headers("GET", path)
        async with provider_http_client() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in {0, "0", None}:
            raise ProviderError(str(payload.get("msg", "OKX request failed")))
        data = payload.get("data", [])
        if not data:
            return None
        account = data[0]
        margin_balance = _decimal_or_none(account.get("adjEq")) or _decimal_or_none(
            account.get("totalEq")
        )
        unrealized_pnl = _sum_optional_decimal(
            item.get("upl", "0") for item in account.get("posData", [])
        )
        if margin_balance is None:
            return await self._collect_contract_margin_balance_from_account_balance(base_url)
        wallet_balance = margin_balance - unrealized_pnl
        return ContractMarginBalanceRisk(
            provider="okx",
            channel_name=self.channel_name,
            wallet_balance=wallet_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
            updated_at_ms=_optional_int(account.get("uTime")),
            raw_payload=dict(account),
        )

    async def _collect_contract_margin_balance_from_account_balance(
        self, base_url: str
    ) -> ContractMarginBalanceRisk | None:
        path = "/api/v5/account/balance"
        headers = self._signature_headers("GET", path)
        async with provider_http_client() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        if payload.get("code") not in {0, "0", None}:
            raise ProviderError(str(payload.get("msg", "OKX request failed")))
        data = payload.get("data", [])
        if not data:
            return None
        account = data[0]
        margin_balance = _decimal_or_none(account.get("totalEq"))
        if margin_balance is None:
            return None
        details = account.get("details", [])
        unrealized_pnl = _decimal_or_none(account.get("upl"))
        if unrealized_pnl is None:
            unrealized_pnl = _sum_optional_decimal(item.get("upl", "0") for item in details)
        wallet_balance = margin_balance - unrealized_pnl
        return ContractMarginBalanceRisk(
            provider="okx",
            channel_name=self.channel_name,
            wallet_balance=wallet_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
            updated_at_ms=_optional_int(account.get("uTime")),
            raw_payload=dict(account),
        )

    async def _get_okx(
        self,
        client,
        base_url: str,
        path: str,
        params: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        query = urlencode(params or {})
        path_with_query = f"{path}?{query}" if query else path
        headers = self._signature_headers("GET", path_with_query)
        response = await client.get(f"{base_url}{path}", headers=headers, params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") not in {0, "0", None}:
            raise ProviderError(str(payload.get("msg", "OKX request failed")))
        return dict(payload)

    async def _collect_strategy_assets(self, client, base_url: str) -> list[AssetBalance]:
        assets: list[AssetBalance] = []
        assets.extend(await self._collect_grid_strategy_assets(client, base_url))
        assets.extend(await self._collect_dca_strategy_assets(client, base_url))
        assets.extend(await self._collect_signal_strategy_assets(client, base_url))
        assets.extend(await self._collect_recurring_strategy_assets(client, base_url))
        return assets

    async def _collect_grid_strategy_assets(self, client, base_url: str) -> list[AssetBalance]:
        assets: list[AssetBalance] = []
        path = "/api/v5/tradingBot/grid/orders-algo-pending"
        for algo_ord_type in OKX_GRID_STRATEGY_TYPES:
            payload = await self._get_okx(
                client, base_url, path, {"algoOrdType": algo_ord_type, "limit": "100"}
            )
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    continue
                assets.append(_strategy_asset(item, f"strategy_{algo_ord_type}"))
                if algo_ord_type == "contract_grid":
                    assets.extend(
                        await self._collect_strategy_positions(
                            client=client,
                            base_url=base_url,
                            path="/api/v5/tradingBot/grid/positions",
                            params={
                                "algoId": str(item.get("algoId", "")),
                                "algoOrdType": algo_ord_type,
                            },
                            metadata_type="strategy_contract_grid_position",
                        )
                    )
        return assets

    async def _collect_dca_strategy_assets(self, client, base_url: str) -> list[AssetBalance]:
        assets: list[AssetBalance] = []
        path = "/api/v5/tradingBot/dca/ongoing-list"
        for algo_ord_type in OKX_DCA_STRATEGY_TYPES:
            payload = await self._get_okx(
                client, base_url, path, {"algoOrdType": algo_ord_type, "limit": "100"}
            )
            for item in payload.get("data", []):
                if not isinstance(item, dict):
                    continue
                assets.append(_strategy_asset(item, f"strategy_{algo_ord_type}"))
                if algo_ord_type == "contract_dca":
                    assets.extend(
                        await self._collect_strategy_positions(
                            client=client,
                            base_url=base_url,
                            path="/api/v5/tradingBot/dca/position-details",
                            params={
                                "algoId": str(item.get("algoId", "")),
                                "algoOrdType": algo_ord_type,
                            },
                            metadata_type="strategy_contract_dca_position",
                        )
                    )
        return assets

    async def _collect_signal_strategy_assets(self, client, base_url: str) -> list[AssetBalance]:
        payload = await self._get_okx(
            client,
            base_url,
            "/api/v5/tradingBot/signal/orders-algo-pending",
            {"algoOrdType": "contract", "limit": "100"},
        )
        assets: list[AssetBalance] = []
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            assets.append(_strategy_asset(item, "strategy_signal"))
            assets.extend(
                await self._collect_strategy_positions(
                    client=client,
                    base_url=base_url,
                    path="/api/v5/tradingBot/signal/positions",
                    params={"algoId": str(item.get("algoId", "")), "algoOrdType": "contract"},
                    metadata_type="strategy_signal_position",
                )
            )
        return assets

    async def _collect_recurring_strategy_assets(self, client, base_url: str) -> list[AssetBalance]:
        payload = await self._get_okx(
            client,
            base_url,
            "/api/v5/tradingBot/recurring/orders-algo-pending",
            {"limit": "100"},
        )
        assets: list[AssetBalance] = []
        for item in payload.get("data", []):
            if not isinstance(item, dict):
                continue
            algo_id = str(item.get("algoId", ""))
            detail_payload = await self._get_okx(
                client,
                base_url,
                "/api/v5/tradingBot/recurring/orders-algo-details",
                {"algoId": algo_id},
            )
            detail_items = [
                detail for detail in detail_payload.get("data", []) if isinstance(detail, dict)
            ]
            assets.append(_strategy_asset(detail_items[0] if detail_items else item, "strategy_recurring"))
        return assets

    async def _collect_strategy_positions(
        self,
        *,
        client,
        base_url: str,
        path: str,
        params: dict[str, str],
        metadata_type: str,
    ) -> list[AssetBalance]:
        if not params.get("algoId"):
            return []
        payload = await self._get_okx(client, base_url, path, params)
        return [
            _strategy_position_asset(item, metadata_type)
            for item in payload.get("data", [])
            if isinstance(item, dict) and _optional_decimal(item.get("pos")) is not None
        ]

    def _position_from_payload(self, item: dict[str, object]) -> ContractPositionRisk:
        return ContractPositionRisk(
            provider="okx",
            channel_name=self.channel_name,
            symbol=str(item.get("instId", "")),
            side=str(item.get("posSide", "")),
            quantity=Decimal(str(item.get("pos", "0"))),
            entry_price=_optional_decimal(item.get("avgPx")),
            mark_price=Decimal(str(item.get("markPx", "0"))),
            liquidation_price=_optional_decimal(item.get("liqPx")),
            unrealized_pnl=_optional_decimal(item.get("upl")),
            margin_mode=str(item.get("mgnMode", "")) or None,
            leverage=str(item.get("lever", "")) or None,
            updated_at_ms=_optional_int(item.get("uTime")),
            raw_payload=dict(item),
        )


def _optional_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    parsed = Decimal(str(value))
    return None if parsed == 0 else parsed


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _optional_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    return int(str(value))


def _sum_optional_decimal(values) -> Decimal:
    total = Decimal("0")
    for value in values:
        if value not in (None, ""):
            total += Decimal(str(value))
    return total


def _strategy_asset(item: dict[str, object], metadata_type: str) -> AssetBalance:
    value_usd = _strategy_value_usd(item)
    asset_symbol = _strategy_symbol(item, default=metadata_type.removeprefix("strategy_").upper())
    return AssetBalance(
        asset_symbol=asset_symbol,
        quantity=_strategy_quantity(item, value_usd),
        value_usd=value_usd,
        metadata=_strategy_metadata(item, metadata_type),
    )


def _strategy_position_asset(item: dict[str, object], metadata_type: str) -> AssetBalance:
    value_usd = _first_decimal(item, "notionalUsd", "imr")
    asset_symbol = _strategy_symbol(item, default=str(item.get("ccy", "POSITION")).upper())
    return AssetBalance(
        asset_symbol=asset_symbol,
        quantity=_decimal_or_none(item.get("pos")) or Decimal("0"),
        value_usd=value_usd,
        metadata=_strategy_metadata(item, metadata_type),
    )


def _strategy_value_usd(item: dict[str, object]) -> Decimal | None:
    direct_value = _first_decimal(item, "totalEq", "notionalUsd", "mktCap", "totalAmt")
    if direct_value is not None:
        return direct_value
    investment = _first_decimal(item, "investment", "investmentAmt", "investAmt")
    pnl = _first_decimal(item, "totalPnl", "floatProfit", "floatPnl")
    if investment is None and pnl is None:
        return None
    return (investment or Decimal("0")) + (pnl or Decimal("0"))


def _strategy_quantity(item: dict[str, object], value_usd: Decimal | None) -> Decimal:
    quantity = _first_decimal(item, "totalAmt", "sz", "pos", "investment", "investmentAmt", "investAmt")
    if quantity is not None:
        return quantity
    return value_usd or Decimal("0")


def _first_decimal(item: dict[str, object], *keys: str) -> Decimal | None:
    for key in keys:
        value = _decimal_or_none(item.get(key))
        if value is not None:
            return value
    return None


def _strategy_symbol(item: dict[str, object], *, default: str) -> str:
    inst_id = item.get("instId")
    if inst_id not in (None, ""):
        return str(inst_id).upper()
    inst_ids = item.get("instIds")
    if isinstance(inst_ids, list) and inst_ids:
        return ",".join(str(value).upper() for value in inst_ids)
    ccy = item.get("ccy")
    if ccy not in (None, ""):
        return str(ccy).upper()
    return default


def _strategy_metadata(item: dict[str, object], metadata_type: str) -> dict[str, str]:
    metadata: dict[str, str] = {"source": "okx", "type": metadata_type}
    for key in (
        "algoId",
        "algoOrdType",
        "state",
        "instId",
        "instType",
        "ccy",
        "investmentCcy",
        "totalPnl",
        "floatProfit",
        "floatPnl",
        "realizedPnl",
        "upl",
        "notionalUsd",
        "liqPx",
        "lever",
        "actualLever",
        "uTime",
    ):
        value = item.get(key)
        if value not in (None, ""):
            metadata[key] = _metadata_value(value)
    if item.get("instIds"):
        metadata["instIds"] = _metadata_value(item["instIds"])
    if item.get("recurringList"):
        metadata["recurringList"] = _metadata_value(item["recurringList"])
    return metadata


def _metadata_value(value: object) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)
