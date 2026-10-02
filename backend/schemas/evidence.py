"""
PRODPROOF — Evidence schemas.

Every evidence source (production context, Jenkins, security, Terraform,
Kubernetes, dependencies, blast radius, rollback) returns the same shape:
a top-level status (the shared EvidenceStatus vocabulary), a short
human-readable summary, and a metrics/details payload specific to that
domain. This consistency is what lets the Release Analysis page render
any stage the same way.
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel


class EvidenceEnvelope(BaseModel):
    status: str  # PASS / WARNING / FAIL / UNAVAILABLE / NOT_CONFIGURED
    summary: str
    source: str  # "demo" | "live" | "not_configured"
    metrics: dict[str, Any] = {}
    findings: list[str] = []  # human-readable notes, e.g. specific warnings


class DependencyNode(BaseModel):
    name: str
    status: str  # PASS / WARNING / FAIL / UNAVAILABLE
    criticality: str  # LOW / MEDIUM / HIGH / CRITICAL
    note: Optional[str] = None


class DependencyEvidence(EvidenceEnvelope):
    graph: list[DependencyNode] = []


class BlastRadiusEvidence(EvidenceEnvelope):
    blast_radius: str = "UNKNOWN"  # LOW / MEDIUM / HIGH
    affected_services: list[str] = []


class AnalysisStage(BaseModel):
    name: str
    evidence: EvidenceEnvelope


class AnalysisBundle(BaseModel):
    release_id: int
    application: str
    version: str
    environment: str
    stages: list[AnalysisStage]
    risk_score: int
    risk_level: str
    decision: str
    primary_reason: str
    reasons: list[str]
    policy_overrides: list[str] = []
    analyzed_at: datetime


class OverrideRequest(BaseModel):
    reason: str
    user: str


class PolicyCreateRequest(BaseModel):
    name: str
    field: str
    operator: str  # gt, gte, lt, lte, eq, is_true, is_false
    threshold: Optional[float] = None
    action: str  # BLOCK or REVIEW
    enabled: bool = True


class PolicyResponse(BaseModel):
    id: int
    name: str
    field: str
    operator: str
    threshold: Optional[float]
    action: str
    enabled: bool
    created_at: datetime

    class Config:
        from_attributes = True


class AuditEventResponse(BaseModel):
    id: int
    event_type: str
    release_id: Optional[int]
    actor: str
    detail: str
    created_at: datetime

    class Config:
        from_attributes = True


class DecisionHistoryItem(BaseModel):
    release_id: int
    application: str
    version: str
    environment: str
    risk_score: int
    risk_level: str
    decision: str
    primary_reason: str
    overridden: bool
    created_at: datetime
