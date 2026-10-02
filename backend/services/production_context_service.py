"""
PRODPROOF — Production Context Engine (Phase 3).

Collects the CURRENT production state and returns honest evidence.

Supported live source:
- AWS EC2 + CloudWatch

Other production metrics such as database connections, memory, disk,
traffic, and Kubernetes replicas are only reported when a dedicated
monitoring integration is implemented.
"""

import random

from config import get_settings
from schemas.evidence import EvidenceEnvelope
from services.aws_monitor import get_aws_production_context
from utils.status import EvidenceStatus


CAPACITY_TILES = (
    "cpu_utilization_pct",
    "memory_utilization_pct",
    "db_connections_used",
    "db_connections_max",
    "replica_count",
)


def _demo_context() -> EvidenceEnvelope:
    cpu_pct = 52 + random.randint(-4, 4)
    memory_pct = 68 + random.randint(-3, 3)
    db_conn_used = 47
    db_conn_max = 50
    pod_count = 6
    replica_count = 6
    disk_pct = 61 + random.randint(-2, 2)
    error_rate_pct = round(0.4 + random.uniform(-0.1, 0.2), 2)
    traffic_rps = 420 + random.randint(-30, 30)

    findings: list[str] = []
    status = EvidenceStatus.PASS.value

    utilization = db_conn_used / db_conn_max

    if utilization >= 0.9:
        findings.append(
            f"Database connections near capacity: {db_conn_used}/{db_conn_max}."
        )
        status = EvidenceStatus.WARNING.value
    elif utilization >= 0.8:
        findings.append(
            f"Database connections elevated: {db_conn_used}/{db_conn_max}."
        )
        status = EvidenceStatus.WARNING.value

    if memory_pct >= 85:
        findings.append(f"Memory utilization high: {memory_pct}%.")
        status = EvidenceStatus.WARNING.value

    if cpu_pct >= 85:
        findings.append(f"CPU utilization high: {cpu_pct}%.")
        status = EvidenceStatus.WARNING.value

    return EvidenceEnvelope(
        status=status,
        summary=(
            "Demo production snapshot "
            "(AWS / Kubernetes / production DB monitor not configured)."
        ),
        source="demo",
        metrics={
            "cpu_utilization_pct": cpu_pct,
            "memory_utilization_pct": memory_pct,
            "pod_count": pod_count,
            "replica_count": replica_count,
            "db_connections_used": db_conn_used,
            "db_connections_max": db_conn_max,
            "disk_utilization_pct": disk_pct,
            "error_rate_pct": error_rate_pct,
            "traffic_rps": traffic_rps,
        },
        findings=findings or ["All production metrics within normal range."],
    )


def get_production_context() -> EvidenceEnvelope:
    settings = get_settings()

    # Real AWS production context.
    if settings.aws_enabled:
        result = get_aws_production_context()

        return EvidenceEnvelope(
            status=result["status"],
            summary=result["summary"],
            source=result["source"],
            metrics=result["metrics"],
            findings=result["findings"],
        )

    # Other live integrations are not implemented yet.
    if settings.prod_db_monitor_enabled or settings.kubernetes_enabled:
        return EvidenceEnvelope(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary=(
                "A production context integration is configured, "
                "but its live client is not connected yet."
            ),
            source="live",
            metrics={},
            findings=[
                "AWS is disabled and the configured production "
                "DB/Kubernetes client is not implemented yet."
            ],
        )

    # Demo mode remains available when nothing live is configured.
    if settings.demo_mode:
        return _demo_context()

    return EvidenceEnvelope(
        status=EvidenceStatus.NOT_CONFIGURED.value,
        summary="No production context source configured and demo mode is off.",
        source="not_configured",
        metrics={},
        findings=[],
    )


def get_capacity_summary() -> EvidenceEnvelope:
    ctx = get_production_context()

    if ctx.source == "not_configured":
        return ctx

    return EvidenceEnvelope(
        status=ctx.status,
        summary="Capacity subset of the current production context.",
        source=ctx.source,
        metrics={
            key: value
            for key, value in ctx.metrics.items()
            if key in CAPACITY_TILES
        },
        findings=ctx.findings,
    )