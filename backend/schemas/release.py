"""
PRODPROOF — Release schemas.

Covers:
- Release creation / persistence
- Release response
- Stateless risk evaluation
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


Environment = Literal[
    "development",
    "staging",
    "production",
]

ReleaseType = Literal[
    "standard",
    "hotfix",
    "rollback",
]


# ---------------------------------------------------------------------------
# Release management
# ---------------------------------------------------------------------------

class ReleaseCreateRequest(BaseModel):
    application: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    version: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    environment: Environment

    git_commit: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    release_type: ReleaseType

    # Phase 3+ analysis inputs
    docker_image: str | None = Field(
        default=None,
        max_length=200,
    )

    expected_replicas: int | None = Field(
        default=None,
        ge=0,
    )

    cpu_millicores: int | None = Field(
        default=None,
        ge=0,
    )

    memory_mb: int | None = Field(
        default=None,
        ge=0,
    )

    db_connections_required: int | None = Field(
        default=None,
        ge=0,
    )

    dependency_list: str | None = Field(
        default=None,
        description="Comma-separated service names",
    )

    rollback_version: str | None = Field(
        default=None,
        max_length=100,
    )

    # Jenkins integration
    jenkins_job_name: str | None = Field(
        default=None,
        max_length=100,
        description="Jenkins job used for CI/CD evidence",
    )


class ReleaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    application: str
    version: str
    environment: str
    git_commit: str
    release_type: str
    status: str
    created_at: datetime

    docker_image: str | None = None
    expected_replicas: int | None = None
    cpu_millicores: int | None = None
    memory_mb: int | None = None
    db_connections_required: int | None = None
    dependency_list: str | None = None
    rollback_version: str | None = None

    jenkins_job_name: str | None = None


# ---------------------------------------------------------------------------
# Stateless risk evaluation
# ---------------------------------------------------------------------------

class ReleaseEvaluationRequest(BaseModel):
    application: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    version: str = Field(
        ...,
        min_length=1,
        max_length=100,
    )

    environment: Environment

    tests_passed: bool
    security_scan_passed: bool
    infrastructure_drift: bool
    rollback_ready: bool

    vulnerability_count: int = Field(
        ...,
        ge=0,
    )

    failed_pipeline_count: int = Field(
        ...,
        ge=0,
    )


class ReleaseEvaluationResponse(BaseModel):
    application: str
    version: str
    environment: str
    risk_score: int
    risk_level: str
    decision: str
    reasons: list[str]