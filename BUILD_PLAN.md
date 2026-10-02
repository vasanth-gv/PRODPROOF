# PRODPROOF Build Plan

Built incrementally, in order. Each phase is meaningful and runnable on its
own — no phase depends on a giant preceding "big bang" implementation.

| Phase | Scope | Status |
|-------|-------|--------|
| 1 | Project architecture, FastAPI, database, frontend shell, health API | ✅ Done |
| 2 | Release management (`POST/GET /api/releases`, release model) | ✅ Done |
| 3 | Production context engine (CPU, memory, DB connections, capacity) | ✅ Done |
| 4 | Jenkins integration (CI/CD evidence) | ✅ Done |
| 5 | Security evidence ingestion (Trivy, Gitleaks, dependency scans) | ✅ Done |
| 6 | Terraform analysis (infrastructure change risk) | ✅ Done |
| 7 | Kubernetes readiness (replicas, requests/limits, probes) | ✅ Done |
| 8 | Dependency analysis (dependency map, health, criticality) | ✅ Done |
| 9 | Blast radius analysis | ✅ Done |
| 10 | Rollback readiness | ✅ Done |
| 11 | Risk engine (LOW/MEDIUM/HIGH/CRITICAL, explainable factors) | ✅ Done |
| 12 | Decision engine (APPROVE/REVIEW/BLOCK) + release comparison + history | ✅ Done |
| 13 | Policy engine + override system + audit trail | ✅ Done |
| 14 | Premium UI refinement (Release Analysis flow visualization, all pages live) | ✅ Done |

## Phase 1 — what was actually built

- `backend/config.py` — typed, env-driven settings for every integration
  (all default to disabled/unconfigured, never silently "on").
- `backend/models/database.py` — SQLAlchemy engine against a real
  MySQL database, with `check_database_connection()` used by the
  health API (not a hardcoded `True`).
- `backend/utils/status.py` — the shared `EvidenceStatus`, `RiskLevel`, and
  `ReleaseDecision` vocabulary every later module will use.
- `backend/api/health.py` + `backend/app.py` — `GET /api/health` and `GET /`,
  wired into a FastAPI app with CORS and startup schema verification.
- `frontend/index.html` — dark enterprise shell: sidebar with all 13
  sections grouped (Release / Evidence / Decision / Operations), topbar
  showing live DB + mode status, Overview page pulling real data from
  `/api/health`, and every unbuilt section showing an explicit "not built
  yet, ships in Phase N" placeholder instead of fabricated metrics.

## Phase 2 — what was actually built

- `backend/models/release.py` — `Release` SQLAlchemy model on the existing
  `Base` (no second declarative base), imported in `app.py` before
  `Base.metadata.create_all()` so the `releases` table is created
  automatically on startup.
- `backend/schemas/release.py` — `ReleaseCreateRequest` / `ReleaseResponse`
  (release CRUD) plus `ReleaseEvaluationRequest` / `ReleaseEvaluationResponse`
  (risk scoring, stateless — doesn't require a stored release).
- `backend/services/risk_engine.py` — deterministic, explainable scoring:
  every point added to the 0–100 score has a stated reason. Bands:
  0–29 SAFE→APPROVE, 30–59 CAUTION→REVIEW, 60–100 BLOCKED→BLOCK, reusing
  the shared `ReleaseDecision` vocabulary from `utils/status.py`.
- `backend/api/releases.py` — `POST /api/releases`, `GET /api/releases`,
  `GET /api/releases/{id}` (persisted to MySQL), and
  `POST /api/releases/evaluate` (stateless scoring).
- `frontend/index.html` — real "Releases" page: create-release form,
  live table from `/api/releases`, loading/empty/error states, no full
  page reload on create. Overview's "Recent Releases" table now shows
  real stored releases instead of a placeholder.

Verified end-to-end against a real MySQL instance (not mocked): created a
release via the API, confirmed the row with a direct `SELECT` against
MySQL, fetched it back by ID, confirmed 404 on a missing ID, and confirmed
422 on an invalid `environment` value.

## Phases 3–14 — what was actually built

All remaining modules from the original spec are implemented and wired
into one orchestrated pipeline (`services/analysis_service.py`), triggered
by `POST /api/releases/{id}/analyze`:

**Evidence sources** (each honestly reports `PASS/WARNING/FAIL/UNAVAILABLE/
NOT_CONFIGURED` — demo data only when `DEMO_MODE=true`, clearly labeled
`source: "demo"`):
- `services/production_context_service.py` — CPU, memory, DB connections,
  pods, disk, error rate, traffic
- `services/jenkins_service.py` — real `httpx` client with timeout against
  a configured Jenkins instance
- `services/security_service.py` — reads real Trivy/Gitleaks JSON reports
  when configured
- `services/terraform_service.py` — parses a real `terraform show -json`
  plan, flags open security groups
- `services/kubernetes_service.py` — replica/capacity check
- `services/dependency_service.py` — dependency map from a release's
  `dependency_list`
- `services/blast_radius_service.py` — downstream impact map
- `services/rollback_service.py` — checks a release's `rollback_version`

**Decision layer:**
- `services/risk_engine.py` — `compute_composite_risk()` combines every
  evidence source into a 0–100 score and LOW/MEDIUM/HIGH/CRITICAL level.
  Includes the flagship spec example verbatim: compares a release's
  `db_connections_required` against current production headroom
  (`db_connections_used`/`db_connections_max`) and flags it even when
  every other check passes.
- `services/policy_engine.py` — configurable `Policy` rows (5 sensible
  defaults auto-seeded), can only escalate a decision, never downgrade it
- `services/decision_engine.py` — turns risk level + policy violations
  into the final APPROVE/REVIEW/BLOCK
- Override system — `POST /api/releases/{id}/override` requires a reason
  and a user, never silent, recorded permanently in the audit trail

**New tables:** `decisions` (full history, powers History + comparison),
`audit_events` (append-only trail), `policies`.

**New API surface:** `/api/production/*`, `/api/security/evidence`,
`/api/infrastructure/changes`, `/api/kubernetes/readiness`,
`/api/dependencies`, `/api/releases/{id}/analyze`,
`/api/releases/{id}/analysis`, `/api/releases/{id}/decision`,
`/api/releases/{id}/override`, `/api/policies`, `/api/audit`, `/api/history`.

**Frontend:** every one of the 13 nav sections is now a real, working
page — no placeholders left. Release Analysis shows the full evidence
pipeline as clickable stage cards, runs a live analysis, and surfaces an
override form when the decision isn't APPROVE.

Verified with two automated test suites (not just manual spot checks):
a headless-DOM smoke test that renders every page against the live
backend and asserts zero runtime errors, and a fully interactive test
that creates a release through the actual UI form, analyzes it by
clicking the real Analyze button, expands a stage card, submits the
override form, and adds a policy — all through real DOM events, not
direct function calls.
