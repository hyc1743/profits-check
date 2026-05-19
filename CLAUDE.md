# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Profits Check is a portfolio asset tracking application — connect crypto exchange accounts (CEX) and on-chain wallets (BSC), take snapshots, and view aggregated balances across channels in a single dashboard.

## Development Commands

### Build Frontend and Start Backend

```bash
python run_dev.py
```

Backend on `http://127.0.0.1:8200`. The script builds the frontend into `frontend/dist`; serve that directory with Nginx and proxy `/api` to the backend.

### Backend (Python 3.12+, package manager: `uv`)

```bash
cd backend
uv sync                          # install dependencies
uv run pytest                    # run all tests
uv run pytest tests/test_providers.py -k "test_binance"  # run a single test
uv run ruff check .              # lint
uv run ruff format --check .     # format check
uv run mypy src tests            # type check
uv run alembic upgrade head      # run migrations
```

The app uses a factory pattern — tests create the app via `from app.main import create_app` (the `app/` shim re-exports from `src/profits_check_backend`).

### Frontend (TypeScript, package manager: `bun`)

```bash
cd frontend
bun install         # install dependencies
bun run dev         # start dev server
bun run test        # run tests (vitest)
bun run test:watch  # watch mode
bun run lint        # ESLint
bun run typecheck   # TypeScript type checking
bun run build       # production build
```

## Architecture

### Backend Layers

```
backend/src/profits_check_backend/
├── main.py              # FastAPI app factory (create_app), all API routes
├── config.py            # AppSettings via pydantic-settings, reads .env
├── db.py                # SQLAlchemy engine/session factory
├── models.py            # ORM models: Channel, Snapshot, SnapshotAsset, AppSetting
├── security.py          # Fernet-based SecretCipher for API secret encryption at rest
├── domain/models.py     # ProviderType enum
├── providers/           # Exchange/chain adapters
│   ├── base.py          # Provider ABC with collect_snapshot() → ProviderSnapshot
│   ├── registry.py      # build_provider() factory — maps ProviderType → provider class
│   ├── binance.py       # Binance spot account via REST API
│   ├── gate.py, okx.py, bitget.py, bybit.py, aster.py  # Other CEX adapters
│   ├── bsc.py           # BSC on-chain wallet balance via RPC
│   └── placeholders.py  # Fallback for unknown provider types
└── services/
    ├── channels.py      # Channel CRUD, config encryption/decryption, AppSetting helpers
    └── snapshots.py     # Snapshot execution, live summary collection, asset aggregation
```

**Provider pattern**: Each provider takes `channel_name`, `config` (public), `secrets` (decrypted at call time) and implements `async collect_snapshot() -> ProviderSnapshot`. `build_provider()` in `registry.py` maps a `ProviderType` string to the right class. Secrets are stored encrypted in `Channel.secret_config_encrypted` using Fernet symmetric encryption.

**Data flow for a snapshot run**: `POST /api/snapshots/run` → `execute_snapshot_run()` iterates enabled channels → builds provider → calls `collect_snapshot()` → normalizes into `SnapshotAsset` rows → commits. `Snapshot.total_value_usd` is the sum of all asset USD values from that run.

**Configuration**: `AppSettings` reads from env vars (`PROFITS_CHECK_` prefix or bare names like `DATABASE_URL`). The `AppSetting` DB table stores runtime-adjustable settings (snapshot interval, max parallel fetches, BSC RPC URL).

### Frontend Structure

```
frontend/src/
├── App.tsx               # Single-page app: overview, snapshots, channels, schedule
├── components/
│   └── chart-surface.tsx # ECharts wrapper component
├── lib/
│   ├── api.ts            # Typed fetch helpers for all /api endpoints
│   ├── format.ts         # Display formatters (USD, provider names, status)
│   └── schedule-schema.ts
├── test/setup.ts         # Vitest + jsdom + Testing Library setup
└── assets/               # Static images
```

State management uses TanStack React Query with a single `QueryClientProvider`. Forms use React Hook Form with Zod validation. The Vite dev server proxies `/api` to the backend at `http://127.0.0.1:8200`.

### Database

SQLite by default (`sqlite:///./data/app.db`), configurable via `DATABASE_URL`. Alembic migrations in `backend/alembic/versions/`. Models are auto-created on startup via `Base.metadata.create_all()` — migrations are for production schema evolution.

### Key Design Decisions

- **Dual package layout**: `backend/app/` is a thin shim that re-exports from `backend/src/profits_check_backend/`. Tests import from `app.main` via the shim. `pyproject.toml` builds wheels from both `src/profits_check_backend` and `src/app`.
- **API shape**: Responses include both camelCase and snake_case keys for compatibility (e.g., `totalValueUsd` + `total_value_usd`).
- **Snapshots are sequential**: `execute_snapshot_run` processes channels one at a time in a loop, not in parallel. The `maxParallelFetches` setting exists in the schedule API but isn't wired into the snapshot executor yet.
- **Background scheduler**: APScheduler runs with a placeholder no-op job; the scheduling mechanism in `main.py` is legacy scaffolding.
- **Secrets**: API keys/secrets are encrypted with Fernet before DB storage, using `APP_ENCRYPTION_KEY` (base64, 32 bytes). The default key is hardcoded for dev — override in production.
