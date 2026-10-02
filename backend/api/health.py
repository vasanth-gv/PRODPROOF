"""
PRODPROOF — Health API.

GET /api/health

Reports the real status of:
- the PRODPROOF application itself
- the PRODPROOF database connection
- every external integration (as CONFIGURED / NOT_CONFIGURED — this endpoint
  does not reach out to external systems; per-integration health lives in
  each module's own status check, added in later phases).

This endpoint never fabricates a healthy result.
"""

from fastapi import APIRouter
from pydantic import BaseModel

from config import get_settings
from models.database import check_database_connection

router = APIRouter(prefix="/api", tags=["health"])


class IntegrationStatus(BaseModel):
    name: str
    configured: bool
    detail: str


class DatabaseStatus(BaseModel):
    connected: bool
    error: str | None = None


class HealthResponse(BaseModel):
    app_name: str
    app_env: str
    demo_mode: bool
    status: str
    database: DatabaseStatus
    integrations: list[IntegrationStatus]
    config_warnings: list[str]


@router.get("/health", response_model=HealthResponse)
def get_health() -> HealthResponse:
    settings = get_settings()

    db_ok, db_error = check_database_connection()

    integrations = [
        IntegrationStatus(
            name="jenkins",
            configured=settings.jenkins_enabled and bool(settings.jenkins_base_url),
            detail="CI/CD evidence source" if settings.jenkins_enabled else "disabled",
        ),
        IntegrationStatus(
            name="trivy",
            configured=settings.trivy_enabled and bool(settings.trivy_report_source),
            detail="container vulnerability evidence" if settings.trivy_enabled else "disabled",
        ),
        IntegrationStatus(
            name="gitleaks",
            configured=settings.gitleaks_enabled and bool(settings.gitleaks_report_source),
            detail="secret-scanning evidence" if settings.gitleaks_enabled else "disabled",
        ),
        IntegrationStatus(
            name="terraform",
            configured=settings.terraform_enabled and bool(settings.terraform_plan_source),
            detail="infrastructure change evidence" if settings.terraform_enabled else "disabled",
        ),
        IntegrationStatus(
            name="kubernetes",
            configured=settings.kubernetes_enabled and bool(settings.kube_config_path),
            detail="runtime readiness evidence" if settings.kubernetes_enabled else "disabled",
        ),
        IntegrationStatus(
            name="aws",
            configured=settings.aws_enabled and bool(settings.aws_region),
            detail="production context evidence" if settings.aws_enabled else "disabled",
        ),
        IntegrationStatus(
            name="production_db_monitor",
            configured=settings.prod_db_monitor_enabled and bool(settings.prod_db_connection_string),
            detail="production DB capacity evidence" if settings.prod_db_monitor_enabled else "disabled",
        ),
    ]

    overall_status = "healthy" if db_ok else "degraded"

    return HealthResponse(
        app_name=settings.app_name,
        app_env=settings.app_env,
        demo_mode=settings.demo_mode,
        status=overall_status,
        database=DatabaseStatus(connected=db_ok, error=db_error),
        integrations=integrations,
        config_warnings=settings.validate_runtime(),
    )
