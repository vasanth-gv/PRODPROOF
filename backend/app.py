"""
PRODPROOF — Production Release Readiness & Risk Engine
Backend entrypoint.

Run:
    uvicorn app:app --reload --port 8000
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.analysis import router as analysis_router
from api.audit import router as audit_router
from api.dependencies import router as dependencies_router
from api.health import router as health_router
from api.history import router as history_router
from api.kubernetes import router as kubernetes_router
from api.policies import router as policies_router
from api.production import router as production_router
from api.releases import router as releases_router
from api.security import router as security_router
from api.terraform import router as terraform_router
from config import get_settings
from models.database import Base, engine
# Import every model module before create_all() so each table is
# registered on Base.metadata and actually gets created.
from models import audit as _audit_model  # noqa: F401
from models import decision as _decision_model  # noqa: F401
from models import policy as _policy_model  # noqa: F401
from models import release as _release_model  # noqa: F401
from utils.logger import get_logger

settings = get_settings()
logger = get_logger("prodproof.app")

app = FastAPI(
    title="PRODPROOF",
    description=(
        "Production Release Readiness & Risk Engine — determines whether a "
        "specific release is safe for the CURRENT production environment by "
        "correlating CI/CD, security, infrastructure, runtime, dependency, "
        "capacity, blast-radius and rollback evidence into an explainable "
        "release decision."
    ),
    version="0.3.0-phase3-14",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if not settings.is_production else [],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(releases_router)
app.include_router(analysis_router)
app.include_router(production_router)
app.include_router(security_router)
app.include_router(terraform_router)
app.include_router(kubernetes_router)
app.include_router(dependencies_router)
app.include_router(policies_router)
app.include_router(audit_router)
app.include_router(history_router)


@app.on_event("startup")
def on_startup() -> None:
    for warning in settings.validate_runtime():
        logger.warning("CONFIG WARNING: %s", warning)

    # Ensure schema exists — the Release model import above registers it on
    # Base.metadata, so this now also creates the `releases` table.
    try:
        Base.metadata.create_all(bind=engine)
        logger.info("Database schema verified/created.")
    except Exception as exc:  # noqa: BLE001
        logger.error("Database initialization failed: %s", exc)

    logger.info(
        "PRODPROOF started | env=%s | demo_mode=%s", settings.app_env, settings.demo_mode
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "PRODPROOF",
        "tagline": "Production Release Readiness & Risk Engine",
        "docs": "/docs",
        "health": "/api/health",
    }
