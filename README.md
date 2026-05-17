# APEX — AI-Powered CRM Platform

APEX is an AI-powered CRM built for companies running on NetSuite. It is designed as a Salesforce alternative that treats NetSuite as a first-class system of record, not an afterthought.

## Tech stack

- **Python 3.11** + **Poetry**
- **FastAPI** (async)
- **PostgreSQL 16** + **SQLAlchemy 2.0** (async) + **Alembic**
- **Redis 7** (cache, rate limiting, future job queues)
- **Pydantic v2** (validation, settings)
- **JWT** auth (python-jose) with **bcrypt** password hashing

## Quick start

```bash
# 1. Clone
git clone https://github.com/sugashag/apex-platform.git
cd apex-platform

# 2. Configure environment
cp .env.example .env
# (edit .env if you need to change defaults)

# 3. Start postgres + redis + api
make dev

# 4. Apply database migrations
make migrate

# 5. Verify
curl http://localhost:8000/health
open http://localhost:8000/docs
```

Common commands:

| Command | What it does |
|---|---|
| `make dev` | Start docker-compose stack (postgres, redis, api) |
| `make down` | Stop the stack |
| `make logs` | Tail the API logs |
| `make migrate` | Apply Alembic migrations |
| `make migration name=add_xxx` | Create a new migration |
| `make lint` | Run ruff |
| `make typecheck` | Run mypy |
| `make test` | Run pytest |
| `make shell` | Open psql in the postgres container |

## Phase roadmap

| Phase | Theme | Status |
|---|---|---|
| **Phase 0** | Foundation — repo, FastAPI skeleton, auth, workspaces, NetSuite-ready schema | **In progress** |
| Phase 1 | Core CRM — contacts, companies, deals, activities | Planned |
| Phase 2 | NetSuite bi-directional sync — customers, sales orders, invoices, payments | Planned |
| Phase 3 | AI layer — enrichment, summarization, next-best-action, voice notes | Planned |
| Phase 4 | Pipeline intelligence — forecasting, deal health, risk signals | Planned |
| Phase 5 | Multi-channel inbox — email, calendar, calls, meetings | Planned |
| Phase 6 | Marketplace + extensibility — public API, webhooks, custom objects | Planned |

## Architecture notes

- **Multi-tenant from day one.** Every domain row is scoped by `workspace_id`; the workspace middleware enforces this on every request.
- **NetSuite-ready schema.** Workspaces carry NetSuite OAuth credentials (encrypted in production). A `netsuite_sync_log` table tracks every sync attempt with direction, status, checksum, and conflict state.
- **Async all the way.** FastAPI + asyncpg + SQLAlchemy async sessions. No blocking I/O on the request path.
- **Strict typing.** `mypy --strict` on `app/`; Pydantic v2 schemas at every boundary.

## Project layout

```
apex-platform/
├── app/
│   ├── main.py             # FastAPI app + router registration
│   ├── config.py           # Pydantic Settings
│   ├── database.py         # Async engine + session factory
│   ├── dependencies.py     # FastAPI DI (get_db, get_current_user)
│   ├── models/             # SQLAlchemy models
│   ├── schemas/            # Pydantic request/response schemas
│   ├── routers/            # API routes
│   ├── services/           # Business logic (auth, etc.)
│   └── middleware/         # Workspace isolation
├── alembic/                # Migrations
├── tests/                  # pytest suite
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## License

Proprietary — internal use only during pre-launch.
