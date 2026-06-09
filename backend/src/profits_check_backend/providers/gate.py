from __future__ import annotations

import hashlib
import hmac
import time
from decimal import Decimal

import httpx

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


class GateProvider(Provider):
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
        self.now_factory = now_factory or (lambda: str(int(time.time())))

    def _signature_headers(
        self, method: str, path: str, query: str = "", body: str = ""
    ) -> dict[str, str]:
        api_key = str(self.secrets.get("apiKey", self.secrets.get("api_key", "")))
        api_secret = str(self.secrets.get("apiSecret", self.secrets.get("api_secret", "")))
        if not api_key or not api_secret:
            raise ProviderError("Gate API credentials are incomplete")

        timestamp = str(self.now_factory())
        hashed_payload = hashlib.sha512(body.encode("utf-8")).hexdigest()
        sign_string = f"{method}\n{path}\n{query}\n{hashed_payload}\n{timestamp}"
        sign = hmac.new(
            api_secret.encode("utf-8"), sign_string.encode("utf-8"), hashlib.sha512
        ).hexdigest()
        return {
            "KEY": api_key,
            "Timestamp": timestamp,
            "SIGN": sign,
        }

    async def collect_snapshot(self) -> ProviderSnapshot:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.gateio.ws/api/v4"))
        ).rstrip("/")

        async with provider_http_client() as client:
            wallet_total = await self._fetch_wallet_total(client, base_url)

            if wallet_total:
                unified_value = Decimal("0")
                for detail in wallet_total.values():
                    amount = Decimal(str(detail.get("amount", "0")))
                    unreal = Decimal(str(detail.get("unrealised_pnl", "0")))
                    unified_value += amount + unreal
                assets: list[AssetBalance] = []
                if unified_value != 0:
                    assets.append(
                        AssetBalance(
                            asset_symbol="USDT",
                            quantity=unified_value,
                            value_usd=unified_value,
                            metadata={"source": "gate", "type": "unified"},
                        )
                    )
                return ProviderSnapshot(total_value_usd=unified_value, assets=assets)

            spot_assets, spot_total = await self._collect_spot(client, base_url)
            futures_assets, futures_total = await self._collect_futures(client, base_url)
            all_assets = spot_assets + futures_assets
            total_value = spot_total + futures_total
            return ProviderSnapshot(total_value_usd=total_value, assets=all_assets)

    async def collect_contract_positions(self) -> list[ContractPositionRisk]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.gateio.ws/api/v4"))
        ).rstrip("/")
        settle = str(self.config.get("settle", "usdt")).lower()
        path = f"/futures/{settle}/positions"
        headers = self._signature_headers("GET", "/api/v4" + path)
        async with provider_http_client() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        return [
            self._position_from_payload(item)
            for item in payload
            if Decimal(str(item.get("size", "0"))) != 0
        ]

    async def collect_contract_margin_balance(self) -> ContractMarginBalanceRisk | None:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.gateio.ws/api/v4"))
        ).rstrip("/")
        settle = str(self.config.get("settle", "usdt")).lower()
        path = f"/futures/{settle}/accounts"
        headers = self._signature_headers("GET", "/api/v4" + path)
        async with provider_http_client() as client:
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()
        wallet_balance = Decimal(str(payload.get("total", "0")))
        unrealized_pnl = Decimal(str(payload.get("unrealised_pnl", "0")))
        available = _decimal_or_none(payload.get("available"))
        cross_initial_margin = _decimal_or_none(payload.get("cross_initial_margin"))
        cross_order_margin = _decimal_or_none(payload.get("cross_order_margin")) or Decimal("0")
        if available is not None and cross_initial_margin is not None:
            wallet_balance = available + cross_initial_margin + cross_order_margin
            margin_balance = available
        else:
            margin_balance = wallet_balance + unrealized_pnl
        if wallet_balance == 0 and margin_balance == 0 and unrealized_pnl == 0:
            return None
        return ContractMarginBalanceRisk(
            provider="gate",
            channel_name=self.channel_name,
            wallet_balance=wallet_balance,
            margin_balance=margin_balance,
            unrealized_pnl=unrealized_pnl,
            raw_payload=dict(payload),
        )

    async def collect_funding_fee_records(
        self, start_time_ms: int, end_time_ms: int
    ) -> list[FundingFeeRecord]:
        base_url = str(
            self.config.get("baseUrl", self.config.get("base_url", "https://api.gateio.ws/api/v4"))
        ).rstrip("/")
        records: list[FundingFeeRecord] = []
        async with provider_http_client() as client:
            for settle in _gate_funding_fee_settles(self.config):
                path = f"/futures/{settle}/account_book"
                params = {
                    "from": str(start_time_ms // 1000),
                    "to": str(end_time_ms // 1000),
                    "type": "fund",
                    "limit": "1000",
                }
                query = "&".join(f"{key}={value}" for key, value in params.items())
                headers = self._signature_headers("GET", "/api/v4" + path, query=query)
                response = await client.get(f"{base_url}{path}", headers=headers, params=params)
                response.raise_for_status()
                payload = response.json()
                asset = settle.upper()
                records.extend(
                    FundingFeeRecord(
                        provider="gate",
                        channel_name=self.channel_name,
                        amount=Decimal(str(item.get("change", "0"))),
                        asset=asset,
                        timestamp_ms=int(Decimal(str(item.get("time", "0"))) * Decimal("1000")),
                        symbol=str(item.get("contract", ""))
                        or _gate_account_book_symbol(item.get("text")),
                        raw_payload=dict(item),
                    )
                    for item in payload
                    if Decimal(str(item.get("change", "0"))) != 0
                )
        return records

    def _position_from_payload(self, item: dict[str, object]) -> ContractPositionRisk:
        size = Decimal(str(item.get("size", "0")))
        side = "long" if size > 0 else "short"
        return ContractPositionRisk(
            provider="gate",
            channel_name=self.channel_name,
            symbol=str(item.get("contract", "")),
            side=side,
            quantity=size,
            entry_price=_optional_decimal(item.get("entry_price")),
            mark_price=Decimal(str(item.get("mark_price", item.get("markPrice", "0")))),
            liquidation_price=_optional_decimal(
                item.get("liq_price", item.get("liquidation_price"))
            ),
            unrealized_pnl=_optional_decimal(item.get("unrealised_pnl")),
            margin_mode=str(item.get("mode", "")) or None,
            leverage=str(item.get("leverage", "")) or None,
            updated_at_ms=_optional_int(item.get("update_time_ms")),
            raw_payload=dict(item),
        )

    async def _fetch_wallet_total(self, client: httpx.AsyncClient, base_url: str) -> dict | None:
        try:
            path = "/wallet/total_balance"
            headers = self._signature_headers("GET", "/api/v4" + path)
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            return response.json().get("details", {})
        except Exception:
            return None

    async def _collect_spot(
        self, client: httpx.AsyncClient, base_url: str
    ) -> tuple[list[AssetBalance], Decimal]:
        path = "/spot/accounts"
        headers = self._signature_headers("GET", "/api/v4" + path)

        response = await client.get(f"{base_url}{path}", headers=headers)
        response.raise_for_status()
        payload = response.json()

        assets: list[AssetBalance] = []
        total_value = Decimal("0")
        for item in payload:
            available = Decimal(str(item["available"]))
            locked = Decimal(str(item["locked"]))
            quantity = available + locked
            if quantity == 0:
                continue
            asset = str(item["currency"]).upper()
            value = await self._estimate_usd_value(client, base_url, asset, quantity)
            assets.append(
                AssetBalance(
                    asset_symbol=asset,
                    quantity=quantity,
                    value_usd=value,
                    metadata={"source": "gate", "type": "spot"},
                )
            )
            if value is not None:
                total_value += value
        return assets, total_value

    async def _collect_futures(
        self, client: httpx.AsyncClient, base_url: str
    ) -> tuple[list[AssetBalance], Decimal]:
        try:
            path = "/futures/usdt/accounts"
            headers = self._signature_headers("GET", "/api/v4" + path)
            response = await client.get(f"{base_url}{path}", headers=headers)
            response.raise_for_status()
            payload = response.json()

            total = Decimal(str(payload.get("total", "0")))
            if total == 0:
                return [], Decimal("0")

            asset = AssetBalance(
                asset_symbol="USDT",
                quantity=total,
                value_usd=total,
                metadata={
                    "source": "gate",
                    "type": "futures",
                    "unrealisedPnl": str(payload.get("unrealised_pnl", "0")),
                },
            )
            return [asset], total
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
                f"{base_url}/spot/tickers",
                params={"currency_pair": f"{asset}_USDT"},
            )
            response.raise_for_status()
            data = response.json()
            if not data:
                return None
            return quantity * Decimal(str(data[0]["last"]))
        except Exception:
            return None


def _gate_funding_fee_settles(config: dict[str, object]) -> list[str]:
    configured = config.get("settle")
    if configured:
        return [str(configured).lower()]
    configured_list = config.get("settles")
    if isinstance(configured_list, list):
        values = [
            str(item).lower() for item in configured_list if str(item).lower() in {"usdt", "btc"}
        ]
        if values:
            return list(dict.fromkeys(values))
    return ["usdt", "btc"]


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


def _gate_account_book_symbol(value: object) -> str | None:
    text = str(value or "")
    if ":" not in text:
        return text or None
    return text.split(":", maxsplit=1)[0] or None
