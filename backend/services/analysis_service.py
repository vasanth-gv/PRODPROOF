"""
PRODPROOF — Analysis orchestrator.

Runs the complete release analysis pipeline:

RELEASE
→ CI/CD
→ SECURITY
→ INFRASTRUCTURE
→ PRODUCTION CONTEXT
→ DEPENDENCIES
→ KUBERNETES
→ BLAST RADIUS
→ ROLLBACK
→ RISK ENGINE
→ POLICY ENGINE
→ DECISION

Every analysis run creates:
- Decision history
- Audit events

The complete analysis bundle is persisted inside Decision.reasons_json,
including:
- all reasons
- policy overrides
- stage evidence
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from models.audit import AuditEvent
from models.decision import Decision
from models.release import Release
from schemas.evidence import (
    AnalysisBundle,
    AnalysisStage,
    EvidenceEnvelope,
)
from services import (
    blast_radius_service,
    dependency_service,
    jenkins_service,
    kubernetes_service,
    policy_engine,
    production_context_service,
    rollback_service,
    security_service,
    terraform_service,
)
from services.decision_engine import decide
from services.risk_engine import compute_composite_risk
from utils.logger import get_logger


logger = get_logger(
    "prodproof.services.analysis"
)


# ---------------------------------------------------------------------------
# Audit helper
# ---------------------------------------------------------------------------

def _log_audit(
    db: Session,
    event_type: str,
    release_id: int | None,
    detail: str,
) -> None:
    db.add(
        AuditEvent(
            event_type=event_type,
            release_id=release_id,
            actor="system",
            detail=detail,
        )
    )


# ---------------------------------------------------------------------------
# Flatten evidence for Policy Engine
# ---------------------------------------------------------------------------

def _flatten(
    stage_evidence: dict[str, EvidenceEnvelope],
) -> dict:
    """
    Flatten stage metrics so policy expressions can use dotted fields.

    Example:

        infrastructure.security_group_changes
        dependencies.has_critical_failure
        production.cpu_utilization_pct
    """

    flat: dict = {}

    for stage_name, evidence in stage_evidence.items():
        metrics = dict(evidence.metrics)

        if stage_name == "dependencies":
            metrics["has_critical_failure"] = any(
                node.status in ("FAIL", "UNAVAILABLE")
                and node.criticality == "CRITICAL"
                for node in evidence.graph
            )

        flat[stage_name] = metrics

    return flat


# ---------------------------------------------------------------------------
# Run full analysis
# ---------------------------------------------------------------------------

def run_analysis(
    db: Session,
    release_id: int,
) -> AnalysisBundle:
    release = (
        db.query(Release)
        .filter(Release.id == release_id)
        .first()
    )

    if release is None:
        raise ValueError(
            f"Release {release_id} not found."
        )

    _log_audit(
        db,
        "ANALYSIS_STARTED",
        release.id,
        (
            f"Analysis started for "
            f"{release.application} {release.version}."
        ),
    )

    db.commit()

    # -----------------------------------------------------------------------
    # Resolve Jenkins job
    #
    # New releases:
    #     release.jenkins_job_name
    #
    # Older releases:
    #     release.application
    #
    # This preserves backward compatibility.
    # -----------------------------------------------------------------------

    jenkins_job_name = (
        release.jenkins_job_name
        or release.application
    )

    logger.info(
        "Using Jenkins job '%s' for release %s",
        jenkins_job_name,
        release.id,
    )

    # -----------------------------------------------------------------------
    # Collect evidence
    # -----------------------------------------------------------------------

    stage_evidence: dict[str, EvidenceEnvelope] = {
      "cicd": jenkins_service.get_cicd_evidence(
    job_name=release.jenkins_job_name or release.application
),
        "security": (
            security_service.get_security_evidence()
        ),

        "infrastructure": (
            terraform_service.get_infrastructure_changes()
        ),

        "production": (
            production_context_service.get_production_context()
        ),

        "dependencies": (
            dependency_service.get_dependency_evidence(
                release
            )
        ),

        "kubernetes": (
            kubernetes_service.get_kubernetes_readiness(
                release
            )
        ),

        "blast_radius": (
            blast_radius_service.compute_blast_radius(
                release
            )
        ),

        "rollback": (
            rollback_service.get_rollback_readiness(
                release
            )
        ),
    }

    # -----------------------------------------------------------------------
    # Risk engine
    # -----------------------------------------------------------------------

    flat_evidence = _flatten(
        stage_evidence
    )

    score, risk_level, reasons = (
        compute_composite_risk(
            release,
            stage_evidence,
        )
    )

    # -----------------------------------------------------------------------
    # Policy engine
    # -----------------------------------------------------------------------

    policy_violations = (
        policy_engine.evaluate_policies(
            db,
            flat_evidence,
        )
    )

    # -----------------------------------------------------------------------
    # Decision engine
    # -----------------------------------------------------------------------

    decision, policy_messages = decide(
        risk_level,
        policy_violations,
    )

    all_reasons = (
        reasons + policy_messages
    )

    primary_reason = (
        policy_messages[0]
        if policy_messages
        else (
            reasons[0]
            if reasons
            else "No risk factors detected."
        )
    )

    # -----------------------------------------------------------------------
    # Analysis stages
    # -----------------------------------------------------------------------

    stages = [
        AnalysisStage(
            name=name.upper().replace("_", " "),
            evidence=evidence,
        )
        for name, evidence in stage_evidence.items()
    ]

    analyzed_at = datetime.now(
        timezone.utc
    )

    # -----------------------------------------------------------------------
    # Persist Decision
    #
    # IMPORTANT:
    # policy_overrides is persisted separately so GET /analysis can
    # reconstruct the same information returned by POST /analyze.
    # -----------------------------------------------------------------------

    reasons_payload = {
        "reasons": all_reasons,
        "policy_overrides": policy_messages,
        "stages": {
            name: evidence.model_dump()
            for name, evidence
            in stage_evidence.items()
        },
    }

    decision_row = Decision(
        release_id=release.id,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        primary_reason=primary_reason,
        reasons_json=json.dumps(
            reasons_payload
        ),
        overridden=False,
        created_at=analyzed_at,
    )

    db.add(decision_row)

    # -----------------------------------------------------------------------
    # Update release status
    # -----------------------------------------------------------------------

    release.status = (
        f"ANALYZED_{decision}"
    )

    # -----------------------------------------------------------------------
    # Audit
    # -----------------------------------------------------------------------

    _log_audit(
        db,
        "DECISION_GENERATED",
        release.id,
        (
            f"Decision: {decision} "
            f"(risk={risk_level}, score={score}). "
            f"{primary_reason}"
        ),
    )

    db.commit()

    logger.info(
        "Analysis complete: release=%s decision=%s risk=%s score=%s",
        release.id,
        decision,
        risk_level,
        score,
    )

    return AnalysisBundle(
        release_id=release.id,
        application=release.application,
        version=release.version,
        environment=release.environment,
        stages=stages,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        primary_reason=primary_reason,
        reasons=all_reasons,
        policy_overrides=policy_messages,
        analyzed_at=analyzed_at,
    )


# ---------------------------------------------------------------------------
# Get latest analysis
# ---------------------------------------------------------------------------

def get_latest_analysis(
    db: Session,
    release_id: int,
) -> AnalysisBundle | None:

    decision_row = (
        db.query(Decision)
        .filter(
            Decision.release_id == release_id
        )
        .order_by(
            Decision.created_at.desc(),
            Decision.id.desc(),
        )
        .first()
    )

    if decision_row is None:
        return None

    # -----------------------------------------------------------------------
    # Decode persisted analysis payload
    # -----------------------------------------------------------------------

    try:
        bundle_raw = json.loads(
            decision_row.reasons_json
        )
    except (
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        logger.exception(
            "Failed to decode persisted analysis for release %s",
            release_id,
        )
        return None

    release = (
        db.query(Release)
        .filter(Release.id == release_id)
        .first()
    )

    # -----------------------------------------------------------------------
    # Rebuild stages
    # -----------------------------------------------------------------------

    stages = []

    for name, evidence in (
        bundle_raw.get("stages", {}).items()
    ):
        stages.append(
            AnalysisStage(
                name=name.upper().replace("_", " "),
                evidence=EvidenceEnvelope(
                    **evidence
                ),
            )
        )

    # -----------------------------------------------------------------------
    # Restore policy overrides
    #
    # Older records may not contain this key, so .get(..., []) keeps
    # backward compatibility.
    # -----------------------------------------------------------------------

    policy_overrides = bundle_raw.get(
        "policy_overrides",
        [],
    )

    # -----------------------------------------------------------------------
    # Rebuild AnalysisBundle
    # -----------------------------------------------------------------------

    return AnalysisBundle(
        release_id=release_id,
        application=(
            release.application
            if release
            else ""
        ),
        version=(
            release.version
            if release
            else ""
        ),
        environment=(
            release.environment
            if release
            else ""
        ),
        stages=stages,
        risk_score=decision_row.risk_score,
        risk_level=decision_row.risk_level,
        decision=decision_row.decision,
        primary_reason=decision_row.primary_reason,
        reasons=bundle_raw.get(
            "reasons",
            [],
        ),
        policy_overrides=policy_overrides,
        analyzed_at=decision_row.created_at,
    )