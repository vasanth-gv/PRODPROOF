# PRODPROOF — Production Release Readiness & Risk Engine

> Before deploying a release to production, PRODPROOF determines whether
> **that specific release** is actually safe for the **current** production
> environment — by correlating CI/CD, security, infrastructure, runtime,
> dependency, capacity, blast-radius, and rollback evidence into one
> explainable decision: **APPROVE / REVIEW / BLOCK**.

PRODPROOF is not a Jenkins dashboard, a vulnerability scanner, a Terraform
viewer, or a monitoring dashboard. Those tools already exist and PRODPROOF
does not re-implement them. PRODPROOF **consumes their evidence** and asks
the question none of them ask on their own:

> "Considering this release *and* the current state of production, what
> could go wrong if we release it now?"

## Why not just do this in Jenkins?

Jenkins executes the CI/CD workflow and reports pipeline evidence (build
passed, tests passed). PRODPROOF evaluates whether a *specific release* is
suitable for the *current* production environment by combining CI/CD,
security, infrastructure, runtime, dependency, capacity, blast-radius, and
rollback evidence into a single explainable release decision. A green
Jenkins pipeline says nothing about whether production's database has 3
spare connections or whether the target cluster has room for 5 more
replicas — PRODPROOF is built specifically to answer that.

## Status: All 14 phases complete

This project was built incrementally, per `BUILD_PLAN.md`. Every module
from the original spec is implemented:

- ✅ FastAPI backend, modular architecture (`api/`, `services/`, `models/`,
  `schemas/`, `utils/`) — 11 routers, 8 evidence services, a composite
  risk engine, a policy engine, and a decision engine
- ✅ Real MySQL database (not mocked) — `releases`, `decisions`,
  `audit_events`, `policies` tables
- ✅ Full Release Analysis pipeline: `POST /api/releases/{id}/analyze` runs
  CI/CD → Security → Infrastructure → Production Context → Dependencies →
  Kubernetes → Blast Radius → Rollback → Risk Engine → Decision, and
  persists the result
- ✅ Every evidence source honestly reports
  `PASS/WARNING/FAIL/UNAVAILABLE/NOT_CONFIGURED` — demo data only when
  `DEMO_MODE=true`, clearly labeled `source: "demo"` in every response
- ✅ Configurable Policy Engine (5 defaults auto-seeded) that can only
  escalate a decision, never downgrade it
- ✅ Override system requiring a reason + user, permanently audited
- ✅ Dark, high-density enterprise frontend — all 13 navigation sections
  are real, working pages; no placeholders remain

### Engineering principles enforced throughout

- **No fake success responses.** `/api/health` reports `database.connected:
  false` with the real error if MySQL is unreachable — it never shows
  a fake "healthy."
- **Explicit status vocabulary.** `utils/status.py` defines `PASS / WARNING
  / FAIL / UNAVAILABLE / NOT_CONFIGURED` — every future integration module
  must use these, not ad-hoc booleans.
- **Demo mode is explicit and loud.** `DEMO_MODE` must be set to `true` on
  purpose; the health endpoint reports it, and a running warning is logged
  if `DEMO_MODE=true` while `APP_ENV=production`.
- **No hardcoded secrets.** Every integration credential is an environment
  variable (see `backend/.env.example`); nothing is committed with real
  values.

## Project layout

```
prodproof/
├── README.md
├── BUILD_PLAN.md
├── docker-compose.yml
├── backend/
│   ├── app.py                     # FastAPI entrypoint, 11 routers registered
│   ├── config.py                   # env-driven settings (Pydantic Settings)
│   ├── requirements.txt
│   ├── .env.example
│   ├── api/
│   │   ├── health.py                # GET /api/health
│   │   ├── releases.py              # release CRUD, evaluate, override
│   │   ├── analysis.py              # analyze / analysis / decision
│   │   ├── production.py            # production context + capacity
│   │   ├── security.py              # security evidence
│   │   ├── terraform.py             # infrastructure changes
│   │   ├── kubernetes.py            # k8s readiness
│   │   ├── dependencies.py          # dependency map
│   │   ├── policies.py              # policy CRUD
│   │   ├── audit.py                 # audit trail
│   │   └── history.py               # release + decision history
│   ├── models/
│   │   ├── database.py              # SQLAlchemy engine/session (MySQL)
│   │   ├── release.py               # Release table (+ Phase 3+ fields)
│   │   ├── decision.py              # Decision history table
│   │   ├── audit.py                 # AuditEvent table
│   │   └── policy.py                # Policy table
│   ├── schemas/
│   │   ├── release.py               # Release CRUD + evaluate schemas
│   │   └── evidence.py              # shared evidence envelope, analysis bundle, policy/audit schemas
│   ├── services/
│   │   ├── risk_engine.py           # evaluate_release() + compute_composite_risk()
│   │   ├── decision_engine.py       # risk level + policy violations -> APPROVE/REVIEW/BLOCK
│   │   ├── policy_engine.py         # configurable policy evaluation, default seeding
│   │   ├── analysis_service.py      # orchestrates the full pipeline
│   │   ├── production_context_service.py
│   │   ├── jenkins_service.py
│   │   ├── security_service.py
│   │   ├── terraform_service.py
│   │   ├── kubernetes_service.py
│   │   ├── dependency_service.py
│   │   ├── blast_radius_service.py
│   │   └── rollback_service.py
│   └── utils/
│       ├── status.py                # EvidenceStatus / RiskLevel / ReleaseDecision enums
│       └── logger.py
└── frontend/
    └── index.html                  # Dark enterprise UI, all 13 nav sections fully live
```

## Running it locally

### 1. Database

PRODPROOF expects a real MySQL (or MariaDB) instance.

```bash
# Ubuntu/Debian example (MariaDB is MySQL-compatible and works the same way)
sudo apt-get install mariadb-server
sudo service mariadb start
sudo mysql -u root -e "
  CREATE DATABASE IF NOT EXISTS prodproof;
  CREATE USER IF NOT EXISTS 'prodproof'@'%' IDENTIFIED BY 'prodproof';
  GRANT ALL PRIVILEGES ON prodproof.* TO 'prodproof'@'%';
  FLUSH PRIVILEGES;
"
```

### 2. Backend

**macOS / Linux:**
```bash
cd backend
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # edit DATABASE_URL / integration settings as needed
uvicorn app:app --reload --port 8000
```

**Windows (PowerShell):**
```powershell
cd backend
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app:app --reload --port 8000
```
If `Activate.ps1` is blocked, run once: `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass`.
Your prompt should show `(venv)` after activating — that's what puts
`uvicorn` on PATH. Skipping activation causes `pip install` to fall back to
a `--user` install and `uvicorn` won't be found afterward. Windows uses
`python`, not `python3`.

Verify: `curl http://localhost:8000/api/health`

### 3. Frontend

The frontend is a static shell (no build step) that talks to the backend
at `http://localhost:8000`.

```bash
cd frontend
python3 -m http.server 8080      # Windows: python -m http.server 8080
```

Open `http://localhost:8080`.

## Deploying

### Option A — Docker Compose (recommended, one command)

This spins up MySQL, the backend, and the frontend together.

```bash
cd prodproof
docker compose up --build
```

- Frontend: http://localhost:8081
- Backend:  http://localhost:8000/api/health
- MySQL: localhost:3307 (user `prodproof` / password `prodproof` / db `prodproof`, root password `rootpass`) — mapped to 3307 since 3306 is commonly already in use on the host

To run in the background: `docker compose up --build -d`. To stop:
`docker compose down` (add `-v` to also drop the MySQL volume).

To point it at your real Jenkins/Trivy/Terraform/Kubernetes/AWS, either add
the relevant env vars to the `backend` service in `docker-compose.yml`, or
create a `backend/.env` file (copy `backend/.env.example`) and reference it
with `env_file: ./backend/.env` under `backend:`. Never commit that file.

**Before exposing this beyond your laptop:** remove the `3307:3306` port
mapping on `db` (MySQL shouldn't be reachable from outside the compose
network), set `APP_ENV=production` and `DEMO_MODE=false` on `backend`, put
a reverse proxy (nginx/Caddy/Traefik) with TLS in front of both services,
and set a real `SECRET_KEY`.

### Option B — Manual (systemd / bare metal / VM)

Follow "Running it locally" above on the target machine, but:

- Run uvicorn without `--reload` and behind a process manager, e.g.
  `uvicorn app:app --host 0.0.0.0 --port 8000 --workers 4`, wrapped in a
  systemd unit (or supervisor) so it restarts on crash/boot.
- Serve `frontend/index.html` from any static file host or web server
  (nginx, Caddy, S3+CloudFront, Netlify, Vercel static hosting) — it has
  no build step.
- Put a reverse proxy in front of the backend for TLS termination, and
  either serve frontend + backend from the same domain (so the frontend's
  same-origin API calls work automatically) or edit the `API_BASE` constant
  near the top of the `<script>` block in `frontend/index.html` to point at
  your backend's real URL.
- Use a managed or self-hosted MySQL/MariaDB instance; set `DATABASE_URL`
  accordingly.

### Option C — Platform-as-a-Service (Render, Railway, Fly.io, etc.)

The backend is a standard FastAPI app and each of these platforms can build
straight from `backend/Dockerfile` (or auto-detect via `requirements.txt` +
the uvicorn start command above). Provision a managed MySQL add-on on
the same platform, set `DATABASE_URL` to the value it gives you, and deploy
`frontend/index.html` as a static site on the same platform (or Netlify/
Vercel/S3) pointed at the backend's public URL.

### Notes for any deployment target

- `APP_ENV=production` + `DEMO_MODE=true` together is misconfigured —
  `/api/health` will surface this in `config_warnings` and the startup log
  will warn loudly. Fix by setting `DEMO_MODE=false`.
- Set a real, random `SECRET_KEY` before going anywhere near production.
- Every external integration (Jenkins, Trivy, Terraform, Kubernetes, AWS,
  prod DB monitor) stays `NOT_CONFIGURED` until you explicitly set its
  `_ENABLED` flag and credentials — nothing is silently "on."

## API Endpoints

Interactive docs (Swagger UI) are always available at `/docs` while the
backend is running.

| Method | Path | Purpose |
|--------|------|---------|
| GET | `/api/health` | Real DB connectivity + integration configuration status |
| POST | `/api/releases` | Create and persist a release to MySQL |
| GET | `/api/releases` | List all releases, newest first |
| GET | `/api/releases/{id}` | Fetch one release; 404 if it doesn't exist |
| POST | `/api/releases/evaluate` | Score six manual inputs (0–100, SAFE/CAUTION/BLOCKED) — stateless |
| POST | `/api/releases/{id}/analyze` | Run the full evidence pipeline + risk + decision engine against a stored release |
| GET | `/api/releases/{id}/analysis` | Fetch the latest analysis bundle for a release |
| GET | `/api/releases/{id}/decision` | Fetch just the latest decision (lightweight) |
| POST | `/api/releases/{id}/override` | Override a REVIEW/BLOCK decision — requires `reason` + `user`, permanently audited |
| GET | `/api/production/context` | Current production state (CPU, memory, DB connections, pods, disk, error rate, traffic) |
| GET | `/api/production/capacity` | Capacity-focused subset of the above |
| GET | `/api/security/evidence` | Trivy/Gitleaks-derived vulnerability and secret findings |
| GET | `/api/infrastructure/changes` | Terraform plan analysis (security group changes, resource deltas) |
| GET | `/api/kubernetes/readiness` | Replica/capacity readiness check |
| GET | `/api/dependencies` | Dependency map and health |
| GET | `/api/policies` | List configured policies (auto-seeds 5 defaults on first call) |
| POST | `/api/policies` | Add a new policy |
| GET | `/api/audit` | Full audit trail, newest first |
| GET | `/api/history` | Every release joined with its latest decision |

Example — create a release:

```bash
curl -X POST http://localhost:8000/api/releases \
  -H "Content-Type: application/json" \
  -d '{
    "application": "payment-service",
    "version": "v1.4.2",
    "environment": "production",
    "git_commit": "a82f91c",
    "release_type": "standard"
  }'
```

Example — evaluate risk (no release needs to be stored first):

```bash
curl -X POST http://localhost:8000/api/releases/evaluate \
  -H "Content-Type: application/json" \
  -d '{
    "application": "payment-service",
    "version": "v1.4.2",
    "environment": "production",
    "tests_passed": true,
    "security_scan_passed": true,
    "infrastructure_drift": false,
    "rollback_ready": true,
    "vulnerability_count": 0,
    "failed_pipeline_count": 0
  }'
```

Example — run the full evidence + decision pipeline against a stored release:

```bash
curl -X POST http://localhost:8000/api/releases \
  -H "Content-Type: application/json" \
  -d '{
    "application": "payment-service",
    "version": "v2.4",
    "environment": "production",
    "git_commit": "abc123",
    "release_type": "standard",
    "expected_replicas": 5,
    "db_connections_required": 60,
    "dependency_list": "payment-db,redis,auth-service,external-payment-api",
    "rollback_version": "v2.3"
  }'
# -> note the "id" in the response, then:
curl -X POST http://localhost:8000/api/releases/1/analyze
```

With demo mode on (the default), this reproduces the exact flagship
scenario from the spec: production has 50 max DB connections, this
release needs 60 — flagged even though CI/CD and security pass.

## Configuration

All integrations are **off by default** and must be explicitly enabled and
configured via environment variables — see `backend/.env.example` for the
full list (Jenkins, Trivy, Gitleaks, Terraform, Kubernetes, AWS, production
DB monitor). When an integration is disabled or missing credentials, every
API that depends on it reports `NOT_CONFIGURED`, never a fake `PASS`.

## Status

All 14 phases from the original build plan are complete — see
`BUILD_PLAN.md` for what was built in each one. To move this from a demo
build toward a real internal platform: wire real clients into
`kubernetes_service.py` and `production_context_service.py` (currently
honest `UNAVAILABLE` placeholders when those integrations are enabled),
point `TRIVY_REPORT_SOURCE`/`GITLEAKS_REPORT_SOURCE`/`TERRAFORM_PLAN_SOURCE`
at real report/plan files, and replace the static `DOWNSTREAM_MAP` in
`blast_radius_service.py` with a real service-catalog lookup.
