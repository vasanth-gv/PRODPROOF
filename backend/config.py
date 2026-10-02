"""
PRODPROOF — Central configuration.

All configuration is sourced from environment variables (via .env in dev).
No secrets or integration endpoints are ever hardcoded here.

Every external integration has an explicit `_ENABLED` flag. When a flag is
false, the corresponding service module must report status=NOT_CONFIGURED
rather than pretending to succeed.
"""

from functools import lru_cache
from typing import Literal, Optional

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # ---- Application ----
    app_name: str = "PRODPROOF"
    app_env: Literal["development", "staging", "production"] = "development"
    demo_mode: bool = False
    log_level: str = "INFO"

    # ---- Database (MySQL) ----
    database_url: str = "mysql+pymysql://prodproof:prodproof@localhost:3306/prodproof"

    # ---- Jenkins ----
    jenkins_enabled: bool = False
    jenkins_base_url: Optional[str] = None
    jenkins_user: Optional[str] = None
    jenkins_api_token: Optional[str] = None
    jenkins_timeout_seconds: int = 8

    # ---- Security scanners ----
    trivy_enabled: bool = False
    trivy_report_source: Optional[str] = None
    gitleaks_enabled: bool = False
    gitleaks_report_source: Optional[str] = None

    # ---- Terraform ----
    terraform_enabled: bool = False
    terraform_plan_source: Optional[str] = None

    # ---- Kubernetes ----
    kubernetes_enabled: bool = False
    kube_config_path: Optional[str] = None
    kube_context: Optional[str] = None
    kube_namespace: str = "default"

    # ---- AWS ----
    aws_enabled: bool = False
    aws_region: Optional[str] = None
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    # ---- Production DB monitor (target release DB, not PRODPROOF's own DB) ----
    prod_db_monitor_enabled: bool = False
    prod_db_connection_string: Optional[str] = None
    prod_db_max_connections: Optional[int] = None

    # ---- Timeouts ----
    default_integration_timeout_seconds: int = 8

    # ---- Security ----
    secret_key: str = "change-me-to-a-random-64-char-string"

    @field_validator(
        "jenkins_base_url",
        "jenkins_user",
        "jenkins_api_token",
        "trivy_report_source",
        "gitleaks_report_source",
        "terraform_plan_source",
        "kube_config_path",
        "kube_context",
        "aws_region",
        "aws_access_key_id",
        "aws_secret_access_key",
        "prod_db_connection_string",
        "prod_db_max_connections",
        mode="before",
    )
    @classmethod
    def _blank_string_to_none(cls, value: object) -> object:
        """Treat an empty-string env var as unset (None) rather than a parse error."""
        if isinstance(value, str) and value.strip() == "":
            return None
        return value

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    def validate_runtime(self) -> list[str]:
        """Return a list of configuration warnings (not fatal errors)."""
        warnings: list[str] = []
        if self.is_production and self.demo_mode:
            warnings.append(
                "DEMO_MODE is true while APP_ENV=production. Demo data must never "
                "be served in production. Set DEMO_MODE=false."
            )
        if self.secret_key == "change-me-to-a-random-64-char-string":
            warnings.append("SECRET_KEY is still the default placeholder value.")
        return warnings


@lru_cache
def get_settings() -> Settings:
    return Settings()
