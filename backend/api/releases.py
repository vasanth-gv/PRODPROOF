"""
PRODPROOF — Releases API.

POST /api/releases
    Create + persist a release to MySQL.

GET /api/releases
    List all releases, newest first.

GET /api/releases/{release_id}
    Fetch one release by ID.

POST /api/releases/evaluate
    Stateless risk evaluation.

POST /api/releases/{release_id}/override
    Override a REVIEW/BLOCK decision with reason + user.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.audit import AuditEvent
from models.database import get_db
from models.decision import Decision
from models.release import Release
from schemas.evidence import OverrideRequest
from schemas.release import (
    ReleaseCreateRequest,
    ReleaseEvaluationRequest,
    ReleaseEvaluationResponse,
    ReleaseResponse,
)
from services.risk_engine import evaluate_release as run_evaluation
from utils.logger import get_logger


router = APIRouter(
    prefix="/api/releases",
    tags=["releases"],
)

logger = get_logger("prodproof.api.releases")


# ---------------------------------------------------------------------------
# Create release
# ---------------------------------------------------------------------------

@router.post(
    "",
    response_model=ReleaseResponse,
    status_code=201,
)
def create_release(
    payload: ReleaseCreateRequest,
    db: Session = Depends(get_db),
) -> Release:
    release = Release(
        application=payload.application,
        version=payload.version,
        environment=payload.environment,
        git_commit=payload.git_commit,
        release_type=payload.release_type,
        status="READY_FOR_ANALYSIS",

        # Release requirements
        docker_image=payload.docker_image,
        expected_replicas=payload.expected_replicas,
        cpu_millicores=payload.cpu_millicores,
        memory_mb=payload.memory_mb,
        db_connections_required=payload.db_connections_required,
        dependency_list=payload.dependency_list,
        rollback_version=payload.rollback_version,

        # CI/CD integration
        jenkins_job_name=payload.jenkins_job_name,
    )

    db.add(release)

    try:
        db.commit()
    except Exception as exc:  # noqa: BLE001
        db.rollback()

        logger.error(
            "Failed to create release: %s",
            exc,
        )

        raise HTTPException(
            status_code=500,
            detail="Failed to save release to the database.",
        )

    db.refresh(release)

    logger.info(
        "Release created: %s %s (id=%s)",
        release.application,
        release.version,
        release.id,
    )

    db.add(
        AuditEvent(
            event_type="RELEASE_SUBMITTED",
            release_id=release.id,
            actor="system",
            detail=(
                f"Release {release.application} "
                f"{release.version} submitted "
                f"for {release.environment}."
            ),
        )
    )

    db.commit()

    return release


# ---------------------------------------------------------------------------
# List releases
# ---------------------------------------------------------------------------

@router.get(
    "",
    response_model=list[ReleaseResponse],
)
def list_releases(
    db: Session = Depends(get_db),
) -> list[Release]:
    return (
        db.query(Release)
        .order_by(
            desc(Release.created_at),
            desc(Release.id),
        )
        .all()
    )


# ---------------------------------------------------------------------------
# Get release
# ---------------------------------------------------------------------------

@router.get(
    "/{release_id}",
    response_model=ReleaseResponse,
)
def get_release(
    release_id: int,
    db: Session = Depends(get_db),
) -> Release:
    release = (
        db.query(Release)
        .filter(Release.id == release_id)
        .first()
    )

    if release is None:
        raise HTTPException(
            status_code=404,
            detail=f"Release {release_id} not found.",
        )

    return release


# ---------------------------------------------------------------------------
# Stateless risk evaluation
# ---------------------------------------------------------------------------

@router.post(
    "/evaluate",
    response_model=ReleaseEvaluationResponse,
)
def evaluate(
    payload: ReleaseEvaluationRequest,
) -> ReleaseEvaluationResponse:
    return run_evaluation(payload)


# ---------------------------------------------------------------------------
# Override decision
# ---------------------------------------------------------------------------

@router.post(
    "/{release_id}/override",
)
def override_decision(
    release_id: int,
    payload: OverrideRequest,
    db: Session = Depends(get_db),
) -> dict:
    """
    Override a REVIEW/BLOCK decision.

    Requires:
    - a reason
    - a user

    The original decision is preserved.
    The override is recorded in the audit trail.
    """

    release = (
        db.query(Release)
        .filter(Release.id == release_id)
        .first()
    )

    if release is None:
        raise HTTPException(
            status_code=404,
            detail=f"Release {release_id} not found.",
        )

    latest_decision = (
        db.query(Decision)
        .filter(Decision.release_id == release_id)
        .order_by(
            desc(Decision.created_at),
            desc(Decision.id),
        )
        .first()
    )

    if latest_decision is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "This release has not been analyzed yet — "
                "nothing to override."
            ),
        )

    if latest_decision.decision == "APPROVE":
        raise HTTPException(
            status_code=400,
            detail=(
                "This release is already APPROVE — "
                "no override needed."
            ),
        )

    latest_decision.overridden = True

    release.status = (
        f"OVERRIDDEN_{latest_decision.decision}"
    )

    db.add(
        AuditEvent(
            event_type="OVERRIDE_APPLIED",
            release_id=release.id,
            actor=payload.user,
            detail=(
                f"Overrode {latest_decision.decision} decision "
                f"(risk={latest_decision.risk_level}, "
                f"score={latest_decision.risk_score}). "
                f"Reason: {payload.reason}"
            ),
        )
    )

    db.commit()

    logger.info(
        "Decision overridden for release %s by %s: %s",
        release_id,
        payload.user,
        payload.reason,
    )

    return {
        "release_id": release.id,
        "original_decision": latest_decision.decision,
        "overridden": True,
        "overridden_by": payload.user,
        "reason": payload.reason,
    }