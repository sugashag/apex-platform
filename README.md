# APEX — AI-Powered CRM Platform

APEX is the Salesforce killer for NetSuite shops. It is a fully multi-tenant, AI-native CRM that treats NetSuite as a first-class system of record, ships a complete sales workflow out of the box (deals, communications, automation, attribution, payments, MSAs), and lets companies self-serve onto the product with a 14-day trial.

## Tech stack

- **Python 3.11** + **Poetry**
- **FastAPI** (async) on **Uvicorn**
- **PostgreSQL 16** + **SQLAlchemy 2.0** (async) + **Alembic**
- **Redis 7** (cache, rate limits, **ARQ** background worker)
- **Pydantic v2** (validation, settings)
- **JWT** + **X-API-Key** authentication (python-jose, bcrypt)
- **Stripe** (customer billing + APEX subscriptions)
- **Twilio** (voice + SMS), **Resend** (email)
- **Anthropic Claude** (AI agents)
- **NetSuite SuiteTalk REST** via OAuth 1.0a

## What APEX does

APEX is the complete revenue-operations stack for a small-to-mid SaaS or services company. It ships the eight feature areas below; this README's roadmap lists the phase each one landed in.

### Phase 0 — Foundation
Multi-tenant workspaces, JWT auth, role-based users (admin/manager/rep/readonly), workspace-scoped middleware, NetSuite-ready schema.

### Phase 1 — Core CRM
Contacts, companies, deals, leads, pipeline stages, unified activity timeline, lead scoring, assignment rules.

### Phase 2 — Communications
Email (Resend), SMS + voice (Twilio), unified inbox, threads, SLA tracking, message routing.

### Phase 3 — AI agents
Lead scorer, call summarizer, outbound drafter, reply drafter, objection handler, pipeline forecaster — all backed by Claude with retry + observability.

### Phase 4 — Attribution
First-touch + last-touch attribution, tracking JS snippet, visitor sessions, page views, form submissions, UTM + click ID capture.

### Phase 5 — Workflows
Trigger-based workflows (lead created, deal stage changed, payment received, …), conditions, multi-step actions, approval gates, run inspection. Plus drip sequences.

### Phase 6 — Intelligence & reporting
Pipeline reports, revenue by month/rep/source, lead velocity, source attribution, pipeline forecasting, dashboard metric caching.

### Phase 7 — Payments, MSAs, NetSuite bridge
Stripe payments tied to deals, MSA generation + signing, per-workspace NetSuite OAuth credentials, bi-directional sync log, customer/sales-order/invoice/payment sync.

### Phase 8 — Productization & GTM
Three subscription plans (Starter / Growth / Enterprise) enforced by middleware, 14-day trials, self-serve onboarding checklist with auto-detection, public **API keys** (X-API-Key auth), workspace user management, RBAC enforcement on sensitive endpoints, full CSV/ZIP data export, and the VAR partner referral foundation.

## Quick start

```bash
# 1. Clone
git clone https://github.com/sugashag/apex-platform.git
cd apex-platform

# 2. Configure environment
cp .env.example .env
# (edit .env to point at your local services / set provider API keys)

# 3. Start postgres + redis + api
make dev

# 4. Apply database migrations (creates 9 tables + seeds 3 plans)
make migrate

# 5. Verify
curl http://localhost:8000/health
open http://localhost:8000/docs
```

### Register a workspace

```bash
curl -X POST http://localhost:8000/auth/register \
  -H 'content-type: application/json' \
  -d '{
    "email": "you@example.com",
    "password": "correct-horse-battery-staple",
    "first_name": "Ada",
    "last_name": "Lovelace",
    "workspace_name": "ACME Corp",
    "workspace_slug": "acme"
  }'
```

The response contains an `access_token` (JWT). Send it as `Authorization: Bearer <token>` on every subsequent request. Registration automatically:
- creates the default 6-stage pipeline
- creates the workspace's onboarding checklist
- starts a 14-day trial on the Starter plan
- mints a public `tracking_token` for the marketing-site snippet

## Common commands

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

## Authentication

APEX accepts two auth methods on every workspace-scoped route:

1. **JWT bearer token** — issued by `POST /auth/login`, sent as `Authorization: Bearer <token>`. Tied to a user; preserves the user's role for RBAC.
2. **API key** — issued by `POST /api/v1/api-keys` (admin only), sent as `X-API-Key: apex_live_…`. Returns the workspace's admin user for downstream RBAC checks. Keys are stored as bcrypt hashes; the plaintext is shown to the user **exactly once** at creation.

```bash
# Create an API key (admin JWT required)
curl -X POST http://localhost:8000/api/v1/api-keys \
  -H "Authorization: Bearer $JWT" \
  -H 'content-type: application/json' \
  -d '{"name": "Zapier integration", "scopes": ["contacts:read", "deals:read"]}'

# Use it
curl http://localhost:8000/api/v1/contacts \
  -H "X-API-Key: apex_live_xxxxxxxxxxxx"
```

## Subscription plans

Plan limits are enforced by middleware (`app/middleware/plan_enforcement.py`). Endpoints that exceed a workspace's plan return **HTTP 402 Payment Required**.

| Plan | Monthly | Annual | Max users | NetSuite | AI agents |
|---|---|---|---|---|---|
| Starter | $75 | $750 | 5 | ❌ | ✅ |
| Growth | $85 | $850 | 25 | ✅ | ✅ |
| Enterprise | $95 | $950 | unlimited | ✅ | ✅ |

Workspaces start on Starter with a 14-day trial. Upgrade via `POST /api/v1/billing/subscribe`.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `DATABASE_URL` | ✅ | Async URL, e.g. `postgresql+asyncpg://apex:apex@postgres:5432/apex` |
| `DATABASE_URL_SYNC` | ✅ | Sync URL for Alembic, e.g. `postgresql+psycopg://apex:apex@postgres:5432/apex` |
| `REDIS_URL` | ✅ | e.g. `redis://redis:6379/0` |
| `SECRET_KEY` | ✅ | Long random string — used to sign JWTs |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | | Defaults to 60 |
| `STRIPE_SECRET_KEY` | | Live mode requires it; mock mode works without it |
| `STRIPE_WEBHOOK_SECRET` | | Required to verify Stripe signatures in production |
| `RESEND_API_KEY` | | Outbound email — mock mode without it |
| `RESEND_WEBHOOK_SECRET` | | Required to verify inbound Resend webhooks |
| `RESEND_FROM_EMAIL` | | Default `From:` address |
| `TWILIO_ACCOUNT_SID` / `TWILIO_AUTH_TOKEN` / `TWILIO_FROM_NUMBER` | | Voice + SMS |
| `TWILIO_TWIML_APP_SID` / `TWILIO_API_KEY_SID` / `TWILIO_API_KEY_SECRET` | | Browser-based dialing |
| `ANTHROPIC_API_KEY` | | AI agents — mock responses without it |
| `POSTHOG_WEBHOOK_SECRET` | | PostHog → APEX event ingestion |
| `API_BASE_URL` | | Public base URL — used in the tracking snippet |
| `TRACKING_RATE_LIMIT_PER_MINUTE` | | Default 100 |
| `MSA_TEMPLATE_PATH` | | Defaults to bundled template |
| `MSA_STORAGE_PATH` | | Local dev only — use object storage in prod |
| `NETSUITE_DEFAULT_ACCOUNT_ID` | | Optional platform-level fallback; per-workspace creds always win |

All variables and their defaults are documented in `.env.example`.

## Deploying to Railway

APEX is designed to deploy as three services: API, ARQ worker, and Postgres + Redis add-ons.

1. **Create a Railway project.** Add the Postgres and Redis plugins; copy their connection strings into the project's variables as `DATABASE_URL`, `DATABASE_URL_SYNC` (swap `+asyncpg` for `+psycopg`), and `REDIS_URL`.
2. **Push the repo.** Railway autodetects the `Dockerfile` and builds the image.
3. **API service.** Use the default Docker start command (`uvicorn app.main:app --host 0.0.0.0 --port $PORT`). Set all the env vars from the table above.
4. **Worker service.** Add a second service that points at the same image with the start command `arq app.worker.main.WorkerSettings`. It shares the same Postgres + Redis as the API.
5. **Migrate.** Either set the Railway start command to `alembic upgrade head && uvicorn …`, or run `railway run alembic upgrade head` locally against the production database after the first deploy.
6. **Domain.** Add a custom domain to the API service; point your DNS at the Railway target. Update `API_BASE_URL` so the embedded tracking snippet uses the public URL.
7. **Webhooks.** Configure the public URL in Stripe (`/webhooks/stripe`), Resend (`/webhooks/resend`), Twilio (`/webhooks/twilio`), and PostHog (`/webhooks/posthog`). Copy the signing secrets back into Railway env vars.

A minimal `Dockerfile` is included; production uses Fluid-Compute-style multi-worker uvicorn (`--workers 4`) once memory headroom permits.

## Architecture notes

- **Multi-tenant from day one.** Every domain row is scoped by `workspace_id`; the workspace middleware surfaces it on the request, and every query filters by it.
- **RBAC at the dependency level.** `app/middleware/rbac.py` provides `require_admin()` and `require_manager_or_above()` FastAPI dependencies used on sensitive routes.
- **Plan enforcement at the service layer.** `app/middleware/plan_enforcement.py` raises HTTP 402 before write operations that would exceed a workspace's plan.
- **NetSuite-ready schema.** Per-workspace NetSuite OAuth credentials in `netsuite_configs` (encrypted in production); bi-directional sync log records every attempt with direction, status, and conflict state.
- **Async all the way.** FastAPI + asyncpg + SQLAlchemy async sessions. No blocking I/O on the request path. Long-running work goes through ARQ.
- **Strict typing.** `mypy --strict` on `app/`; Pydantic v2 schemas at every boundary.

## Project layout

```
apex-platform/
├── app/
│   ├── main.py             # FastAPI app + router registration
│   ├── config.py           # Pydantic Settings
│   ├── database.py         # Async engine + session factory
│   ├── dependencies.py     # FastAPI DI (db, current_user, api_key)
│   ├── agents/             # AI agents (Claude-backed)
│   ├── models/             # SQLAlchemy models
│   ├── schemas/            # Pydantic request/response schemas
│   ├── routers/            # API routes
│   ├── services/           # Business logic + integrations
│   ├── middleware/         # Workspace isolation, RBAC, plan limits
│   ├── templates/          # MSA + email templates
│   ├── utils/              # Pagination, rate limit helpers
│   └── worker/             # ARQ background jobs
├── alembic/                # Migrations (0001 → 0009)
├── tests/                  # pytest suite
├── docker-compose.yml
├── Dockerfile
├── Makefile
└── pyproject.toml
```

## License

Proprietary — internal use only during pre-launch.
