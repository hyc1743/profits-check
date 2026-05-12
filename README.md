# Profits Check

Crypto portfolio asset tracking — connect exchange accounts (CEX) and on-chain wallets, take snapshots, and view aggregated balances in a single dashboard.

## Features

- **Multi-channel support**: Binance, Gate, OKX, Bitget, Bybit, Aster (CEX) + BSC / On-chain wallets
- **Snapshot history**: Save portfolio snapshots and track asset trends over time
- **Live refresh**: Pull real-time balances from all connected channels
- **Asset distribution**: Pie chart breakdown by channel and account category
- **Profit calendar**: Daily profit/loss view with monthly/yearly aggregation
- **Scheduled snapshots**: Auto-save at configured times
- **Encrypted secrets**: API keys stored with Fernet symmetric encryption

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python 3.12+, FastAPI, SQLAlchemy, Alembic, APScheduler |
| Frontend | React 19, TypeScript, Vite, TanStack Query, ECharts |
| Package managers | uv (Python), bun (Node.js) |
| Database | SQLite (default, configurable via `DATABASE_URL`) |

## Quick Start

### Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (Python package manager)
- [bun](https://bun.sh/) (JavaScript runtime & package manager)

### Run Both Services

```bash
export APP_ENCRYPTION_KEY="$(cd backend && uv run python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
)"
export PROFITS_CHECK_BOOTSTRAP_PASSWORD="change-this-password"
python run_dev.py
```

- Backend: `http://127.0.0.1:8200`
- Frontend: `http://127.0.0.1:8300` (proxies `/api` to backend)

### Manual Setup

**Backend:**

```bash
cd backend
uv sync                          # install dependencies
uv run alembic upgrade head      # run migrations
uv run uvicorn profits_check_backend.main:create_app --factory --host 127.0.0.1 --port 8200
```

**Frontend:**

```bash
cd frontend
bun install
bun run dev
```

### Configuration

Set via environment variables (`PROFITS_CHECK_` prefix or bare names):

| Variable | Default | Description |
|----------|---------|-------------|
| `DATABASE_URL` | `sqlite:///./data/app.db` | Database connection string |
| `APP_ENCRYPTION_KEY` | required | Base64-encoded 32-byte Fernet key for secret encryption |
| `PROFITS_CHECK_BOOTSTRAP_PASSWORD` | required on first startup | Initial single-user admin password; stored as a password hash after first startup |
| `PROFITS_CHECK_COOKIE_SECURE` | `false` | Set to `true` when your reverse proxy serves the app over HTTPS |
| `PROFITS_CHECK_BACKEND_HOST` | `127.0.0.1` | Host used by `python run_dev.py` for the backend |
| `PROFITS_CHECK_FRONTEND_HOST` | `127.0.0.1` | Host used by `python run_dev.py` for the frontend |

Generate an encryption key with:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

For public deployment, put TLS and public routing in your reverse proxy. The app does not force HTTPS itself. Back up the database and `APP_ENCRYPTION_KEY` together; losing the key means stored exchange secrets cannot be decrypted.

## Development

### Backend

```bash
cd backend
uv run pytest                          # run all tests
uv run pytest tests/test_providers.py -k "test_binance"  # single test
uv run ruff check .                    # lint
uv run ruff format --check .           # format check
uv run mypy src tests                  # type check
```

### Frontend

```bash
cd frontend
bun run test        # vitest
bun run test:watch  # watch mode
bun run lint        # ESLint
bun run typecheck   # TypeScript
bun run build       # production build
```

## Architecture

```
backend/src/profits_check_backend/
├── main.py              # FastAPI app factory, API routes
├── config.py            # pydantic-settings configuration
├── db.py                # SQLAlchemy engine/session
├── models.py            # ORM models
├── security.py          # Fernet SecretCipher
├── domain/models.py     # ProviderType enum
├── providers/           # Exchange/chain adapters (ABC pattern)
│   ├── base.py          # Provider ABC
│   ├── registry.py      # Factory: ProviderType → provider class
│   ├── binance.py, gate.py, okx.py, bitget.py, bybit.py, aster.py
│   └── bsc.py           # BSC on-chain via RPC
└── services/
    ├── channels.py      # Channel CRUD, config encryption
    └── snapshots.py     # Snapshot execution, asset aggregation

frontend/src/
├── App.tsx              # Single-page dashboard
├── components/
│   └── chart-surface.tsx  # ECharts wrapper
└── lib/
    ├── api.ts           # Typed API client
    ├── format.ts        # Display formatters
    └── schedule-schema.ts
```

Each provider implements `async collect_snapshot() -> ProviderSnapshot`. API secrets are stored encrypted in the database using Fernet symmetric encryption. Snapshots run sequentially (one channel at a time).

## License

MIT
