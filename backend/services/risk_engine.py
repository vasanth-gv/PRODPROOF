"""
PRODPROOF — Risk Engine (evaluation scoring).

Deterministic, explainable scoring for POST /api/releases/evaluate.

Every point added to the score has a stated reason — nothing here is a
black box.

This module contains two risk calculation paths:

1. evaluate_release()
   - Used by POST /api/releases/evaluate
   - Uses manually supplied evaluation inputs.

2. compute_composite_risk()
   - Used by the full Release Analysis pipeline
     POST /api/releases/{id}/analyze
   - Combines evidence from CI/CD, security, infrastructure,
     production, dependencies, Kubernetes, blast radius, rollback,
     and release-specific production requirements.

Important status semantics:
- PASS = confirmed healthy
- FAIL = confirmed unhealthy
- UNAVAILABLE = evidence could not be retrieved
- NOT_CONFIGURED = evidence/integration is not configured
- NOT_CONFIGURED must not automatically be treated as confirmed failure.
"""

from schemas.release import ReleaseEvaluationRequest, ReleaseEvaluationResponse
from utils.status import ReleaseDecision, RiskLevel


# ---------------------------------------------------------------------------
# Simple evaluation scoring constants
# ---------------------------------------------------------------------------

VULNERABILITY_POINTS_PER_ITEM = 3
VULNERABILITY_POINTS_CAP = 15

FAILED_PIPELINE_POINTS_PER_ITEM = 5
FAILED_PIPELINE_POINTS_CAP = 20


# ---------------------------------------------------------------------------
# Simple Risk Engine
#
# Used by:
# POST /api/releases/evaluate
#
# Scoring inputs:
#   tests failed              -> +25
#   security scan failed      -> +20
#   infrastructure drift     -> +15
#   rollback not ready        -> +20
#   vulnerabilities detected  -> +3 per vuln, capped at +15
#   failed pipeline runs      -> +5 per failure, capped at +20
#
# Score is capped at 100.
#
# Bands:
#   0-29   -> SAFE     -> APPROVE
#   30-59  -> CAUTION   -> REVIEW
#   60-100 -> BLOCKED   -> BLOCK
# ---------------------------------------------------------------------------


def evaluate_release(
    request: ReleaseEvaluationRequest,
) -> ReleaseEvaluationResponse:
    score = 0
    reasons: list[str] = []

    if not request.tests_passed:
        score += 25
        reasons.append("Tests did not pass.")

    if not request.security_scan_passed:
        score += 20
        reasons.append("Security scan did not pass.")

    if request.infrastructure_drift:
        score += 15
        reasons.append(
            "Infrastructure drift detected against the current environment."
        )

    if not request.rollback_ready:
        score += 20
        reasons.append("Rollback is not ready for this release.")

    if request.vulnerability_count > 0:
        points = min(
            request.vulnerability_count * VULNERABILITY_POINTS_PER_ITEM,
            VULNERABILITY_POINTS_CAP,
        )
        score += points

        reasons.append(
            f"{request.vulnerability_count} vulnerability(ies) detected "
            f"(+{points})."
        )

    if request.failed_pipeline_count > 0:
        points = min(
            request.failed_pipeline_count * FAILED_PIPELINE_POINTS_PER_ITEM,
            FAILED_PIPELINE_POINTS_CAP,
        )
        score += points

        reasons.append(
            f"{request.failed_pipeline_count} failed pipeline run(s) "
            f"(+{points})."
        )

    score = min(score, 100)

    if score <= 29:
        risk_level = "SAFE"
        decision = ReleaseDecision.APPROVE.value

    elif score <= 59:
        risk_level = "CAUTION"
        decision = ReleaseDecision.REVIEW.value

    else:
        risk_level = "BLOCKED"
        decision = ReleaseDecision.BLOCK.value

    if not reasons:
        reasons.append("No risk factors detected.")

    return ReleaseEvaluationResponse(
        application=request.application,
        version=request.version,
        environment=request.environment,
        risk_score=score,
        risk_level=risk_level,
        decision=decision,
        reasons=reasons,
    )


# ---------------------------------------------------------------------------
# Composite Risk Engine (Phase 11)
#
# Used by the complete Release Analysis pipeline:
#
# POST /api/releases/{id}/analyze
#
# Evidence sources:
#   - CI/CD
#   - Security
#   - Infrastructure
#   - Production
#   - Dependencies
#   - Kubernetes
#   - Blast Radius
#   - Rollback
#
# This also compares the release's own requirements against the
# CURRENT production environment.
#
# Output:
#   score      -> 0-100
#   risk_level -> LOW / MEDIUM / HIGH / CRITICAL
#   reasons    -> explicit explanations for every score contribution
# ---------------------------------------------------------------------------


def compute_composite_risk(
    release,
    stage_evidence: dict,
) -> tuple[int, str, list[str]]:
    """
    Compute the explainable composite risk score.

    Expected stage_evidence structure:

    {
        "cicd": ...,
        "security": ...,
        "infrastructure": ...,
        "production": ...,
        "dependencies": ...,
        "kubernetes": ...,
        "blast_radius": ...,
        "rollback": ...
    }

    Returns:
        (score, risk_level, reasons)
    """

    score = 0
    reasons: list[str] = []

    # -----------------------------------------------------------------------
    # CI/CD
    # -----------------------------------------------------------------------

    cicd = stage_evidence.get("cicd")

    if cicd:
        build_status = cicd.metrics.get("build_status")

        if (
            build_status not in ("SUCCESS", None)
            and cicd.status == "FAIL"
        ):
            score += 25
            reasons.append(
                "CI/CD pipeline did not pass."
            )

        elif cicd.status == "UNAVAILABLE":
            score += 5
            reasons.append(
                "CI/CD evidence could not be retrieved."
            )

    # -----------------------------------------------------------------------
    # SECURITY
    # -----------------------------------------------------------------------

    security = stage_evidence.get("security")

    if security:
        critical_vulnerabilities = (
            security.metrics.get(
                "critical_vulnerabilities",
                0,
            )
            or 0
        )

        high_vulnerabilities = (
            security.metrics.get(
                "high_vulnerabilities",
                0,
            )
            or 0
        )

        secret_findings = (
            security.metrics.get(
                "secret_findings",
                0,
            )
            or 0
        )

        if critical_vulnerabilities:
            points = min(
                critical_vulnerabilities * 15,
                40,
            )

            score += points

            reasons.append(
                f"{critical_vulnerabilities} critical "
                f"vulnerability(ies) detected (+{points})."
            )

        if high_vulnerabilities:
            points = min(
                high_vulnerabilities * 5,
                20,
            )

            score += points

            reasons.append(
                f"{high_vulnerabilities} high-severity "
                f"vulnerability(ies) detected (+{points})."
            )

        if secret_findings:
            score += 25

            reasons.append(
                f"{secret_findings} exposed secret(s) detected (+25)."
            )

    # -----------------------------------------------------------------------
    # INFRASTRUCTURE
    # -----------------------------------------------------------------------

    infrastructure = stage_evidence.get("infrastructure")

    if infrastructure:
        security_group_changes = (
            infrastructure.metrics.get(
                "security_group_changes",
                0,
            )
            or 0
        )

        if security_group_changes:
            points = min(
                security_group_changes * 15,
                30,
            )

            score += points

            reasons.append(
                f"{security_group_changes} risky security group "
                f"change(s) detected (+{points})."
            )

    # -----------------------------------------------------------------------
    # PRODUCTION
    # -----------------------------------------------------------------------

    production = stage_evidence.get("production")

    if production and production.status != "NOT_CONFIGURED":

        cpu_utilization = production.metrics.get(
            "cpu_utilization_pct"
        )

        memory_utilization = production.metrics.get(
            "memory_utilization_pct"
        )

        db_connections_used = production.metrics.get(
            "db_connections_used"
        )

        db_connections_max = production.metrics.get(
            "db_connections_max"
        )

        # High CPU utilization
        if (
            cpu_utilization is not None
            and cpu_utilization >= 85
        ):
            score += 10

            reasons.append(
                f"Production CPU utilization is high "
                f"({cpu_utilization}%)."
            )

        # High memory utilization
        if (
            memory_utilization is not None
            and memory_utilization >= 85
        ):
            score += 10

            reasons.append(
                f"Production memory utilization is high "
                f"({memory_utilization}%)."
            )

        # -------------------------------------------------------------------
        # Release-specific DB capacity check
        #
        # This compares the release's stated requirement against the
        # currently available production DB capacity.
        # -------------------------------------------------------------------

        if (
            release is not None
            and release.db_connections_required
            and db_connections_used is not None
            and db_connections_max is not None
        ):
            headroom = (
                db_connections_max
                - db_connections_used
            )

            required = release.db_connections_required

            # Requirement exceeds total production capacity
            if required > db_connections_max:
                score += 30

                reasons.append(
                    f"Release requires {required} DB connections, "
                    f"exceeding total production capacity of "
                    f"{db_connections_max}."
                )

            # Requirement exceeds currently available headroom
            elif required > headroom:
                score += 20

                reasons.append(
                    f"Release requires {required} DB connections "
                    f"but only {headroom} are currently free "
                    f"(production: "
                    f"{db_connections_used}/{db_connections_max})."
                )

    # -----------------------------------------------------------------------
    # KUBERNETES
    # -----------------------------------------------------------------------

    k8s = stage_evidence.get("kubernetes")

    if k8s and k8s.status != "NOT_CONFIGURED":

        requested_replicas = k8s.metrics.get(
            "requested_replicas"
        )

        # Phase 7 live Kubernetes implementation exposes:
        # schedulable_replica_capacity
        #
        # Keep available_capacity as a fallback so older evidence records
        # remain compatible.
        schedulable_capacity = k8s.metrics.get(
            "schedulable_replica_capacity"
        )

        if schedulable_capacity is None:
            schedulable_capacity = k8s.metrics.get(
                "available_capacity"
            )

        if (
            requested_replicas is not None
            and schedulable_capacity is not None
            and requested_replicas > schedulable_capacity
        ):
            score += 25

            reasons.append(
                f"Requested replicas ({requested_replicas}) "
                f"exceed available cluster capacity "
                f"({schedulable_capacity})."
            )

    # -----------------------------------------------------------------------
    # DEPENDENCIES
    # -----------------------------------------------------------------------

    deps = stage_evidence.get("dependencies")

    if deps and deps.status != "NOT_CONFIGURED":

        for node in deps.graph:

            # IMPORTANT:
            #
            # NOT_CONFIGURED does NOT mean confirmed unhealthy.
            #
            # Example:
            #   payment-db -> NOT_CONFIGURED
            #
            # means PRODPROOF could not find live Kubernetes evidence.
            # Therefore it must NOT receive the same risk score as a
            # confirmed FAIL or UNAVAILABLE dependency.
            #
            # Only confirmed FAIL or UNAVAILABLE states contribute risk.
            if (
                node.status in ("FAIL", "UNAVAILABLE")
                and node.criticality in ("HIGH", "CRITICAL")
            ):
                score += 15

                reasons.append(
                    f"Dependency '{node.name}' "
                    f"({node.criticality}) is not healthy."
                )

    # -----------------------------------------------------------------------
    # BLAST RADIUS
    # -----------------------------------------------------------------------

    blast = stage_evidence.get("blast_radius")

    if blast and blast.blast_radius == "HIGH":

        score += 10

        reasons.append(
            f"Blast radius is HIGH — "
            f"{len(blast.affected_services)} downstream "
            f"service(s) affected."
        )

    # -----------------------------------------------------------------------
    # ROLLBACK
    # -----------------------------------------------------------------------

    rollback = stage_evidence.get("rollback")

    if rollback and rollback.status != "NOT_CONFIGURED":

        previous_version_available = rollback.metrics.get(
            "previous_version_available",
            True,
        )

        if not previous_version_available:
            score += 20

            reasons.append(
                "Rollback is not ready for this release."
            )

    # -----------------------------------------------------------------------
    # Final score cap
    # -----------------------------------------------------------------------

    score = min(score, 100)

    # -----------------------------------------------------------------------
    # Risk level bands
    #
    #   0-24   -> LOW
    #   25-49  -> MEDIUM
    #   50-74  -> HIGH
    #   75-100 -> CRITICAL
    # -----------------------------------------------------------------------

    if score <= 24:
        risk_level = RiskLevel.LOW.value

    elif score <= 49:
        risk_level = RiskLevel.MEDIUM.value

    elif score <= 74:
        risk_level = RiskLevel.HIGH.value

    else:
        risk_level = RiskLevel.CRITICAL.value

    if not reasons:
        reasons.append(
            "No risk factors detected across any evidence source."
        )

    return score, risk_level, reasons