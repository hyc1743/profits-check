from __future__ import annotations

import httpx

PROVIDER_HTTP_TIMEOUT = httpx.Timeout(connect=5, read=15, write=10, pool=5)
PROVIDER_HTTP_LIMITS = httpx.Limits(max_connections=10, max_keepalive_connections=5)


def provider_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=PROVIDER_HTTP_TIMEOUT, limits=PROVIDER_HTTP_LIMITS)
