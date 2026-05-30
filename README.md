# Profits Check

Profits Check 是一个加密资产看板，用于连接交易所账户和链上钱包，保存资产快照，并在一个页面里查看总资产、渠道分布和收益变化。

## 功能

- **多渠道接入**：支持 Binance、Gate、OKX、Bitget、Bybit、Aster，以及 EVM 链上钱包。
- **资产快照**：保存每次资产统计结果，用于查看历史变化。
- **实时刷新**：从已配置渠道拉取实时余额。
- **资产分布**：按渠道和账户类型展示资产占比。
- **收益日历**：按日、月、年查看资产变化。
- **定时快照**：按配置时间自动保存快照。
- **仓位风险监控**：监控合约爆仓风险、保证金余额风险，并支持按 UTC+8 每日时段检测疑似 ADL。
- **密钥加密**：交易所 API 密钥使用 Fernet 对称加密后存储。

## 技术栈

| 层级 | 技术 |
| --- | --- |
| 后端 | Python 3.12+、FastAPI、SQLAlchemy、Alembic、APScheduler |
| 前端 | React 19、TypeScript、Vite、TanStack Query、ECharts |
| 包管理 | uv（Python）、bun（Node.js） |
| 数据库 | SQLite（默认，可通过 `DATABASE_URL` 配置） |

## 快速启动

### 环境要求

- Python 3.12+
- [uv](https://docs.astral.sh/uv/)（Python 包管理器）
- [bun](https://bun.sh/)（JavaScript 运行时和包管理器）

### 构建前端并启动后端

```bash
python3 run_dev.py
```

脚本会自动执行：

- 创建或补全 `backend/.env`
- 生成 `APP_ENCRYPTION_KEY`
- 首次启动时要求设置初始登录密码
- 安装 `uv` / `bun`（如果本机缺失）
- 安装 Python 3.12（如果需要）
- 同步后端和前端依赖
- 执行 `bun run build` 构建前端静态文件
- 启动后端：`http://127.0.0.1:8200`

前端构建产物位于：

```text
frontend/dist
```

生产环境建议用 Nginx 直接托管 `frontend/dist`，并把 `/api` 反向代理到 `http://127.0.0.1:8200`。脚本不再启动 Vite 开发服务器，因此不会再常驻占用前端 Node 进程内存。

### 宝塔 / Nginx 部署建议

宝塔里选择 HTML 项目或静态站点，网站根目录指向：

```text
/www/wwwroot/profits-check/frontend/dist
```

Nginx 配置示例：

```nginx
location / {
    try_files $uri $uri/ /index.html;
}

location /api/ {
    proxy_pass http://127.0.0.1:8200/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

如果使用宝塔生成的完整站点配置，可以参考：

```text
docs/deploy/baota-nginx.conf
```

检查并重载 Nginx：

```bash
nginx -t && systemctl reload nginx
```

### 手动启动

后端：

```bash
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn profits_check_backend.main:create_app --factory --host 127.0.0.1 --port 8200
```

前端构建：

```bash
cd frontend
bun install
bun run build
```

开发时如果确实需要 Vite：

```bash
cd frontend
bun run dev
```

## 配置

配置可以通过环境变量设置。项目支持 `PROFITS_CHECK_` 前缀，也兼容部分无前缀变量名。

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./data/app.db` | 数据库连接地址 |
| `APP_ENCRYPTION_KEY` | 必填 | Fernet 使用的 32 字节 Base64 密钥 |
| `PROFITS_CHECK_BOOTSTRAP_PASSWORD` | 首次启动必填 | 初始单用户管理员密码，启动后会保存为密码哈希 |
| `PROFITS_CHECK_COOKIE_SECURE` | `false` | 站点通过 HTTPS 访问时建议设置为 `true` |
| `PROFITS_CHECK_ALLOWED_HOSTS` | 空 | Vite 开发服务器允许的主机名；生产静态部署通常不需要 |
| `PROFITS_CHECK_BACKEND_HOST` | `127.0.0.1` | `python3 run_dev.py` 启动后端时绑定的地址 |
| `OKX_DEX_API_KEY` | 空 | OKX DEX API Key，用于读取 EVM 链上钱包总估值 |
| `OKX_DEX_API_SECRET` | 空 | OKX DEX API Secret |
| `OKX_DEX_API_PASSPHRASE` | 空 | OKX DEX API Passphrase |

生成加密密钥：

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

生产环境需要同时备份数据库和 `APP_ENCRYPTION_KEY`。如果密钥丢失，已保存的交易所密钥无法解密。

## 开发命令

### 后端

```bash
cd backend
uv run pytest
uv run pytest tests/test_providers.py -k "test_binance"
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
```

### 前端

```bash
cd frontend
bun run test
bun run test:watch
bun run lint
bun run typecheck
bun run build
```

## 项目结构

```text
backend/src/profits_check_backend/
├── main.py              # FastAPI 应用工厂和 API 路由
├── config.py            # pydantic-settings 配置
├── db.py                # SQLAlchemy engine/session
    ├── models.py            # ORM 模型
├── security.py          # Fernet SecretCipher
├── domain/models.py     # ProviderType 枚举
├── providers/           # 交易所和链上适配器
│   ├── base.py          # Provider 抽象基类
│   ├── registry.py      # ProviderType 到 provider class 的工厂
│   ├── binance.py, gate.py, okx.py, bitget.py, bybit.py, aster.py
│   └── onchain.py       # EVM 链上钱包总估值适配
└── services/
    ├── channels.py      # 渠道 CRUD 和配置加密
    ├── liquidation_monitor.py # 爆仓、保证金余额和 ADL 风险监控
    └── snapshots.py     # 快照执行和资产聚合

frontend/src/
├── App.tsx              # 单页资产看板
├── components/
│   └── chart-surface.tsx  # ECharts 封装
└── lib/
    ├── api.ts           # 类型化 API 客户端
    ├── format.ts        # 显示格式化工具
    └── schedule-schema.ts
```

每个 provider 都实现 `async collect_snapshot() -> ProviderSnapshot`。API 密钥加密后保存在数据库中。快照执行目前按渠道顺序处理，不并发执行。

## License

MIT
