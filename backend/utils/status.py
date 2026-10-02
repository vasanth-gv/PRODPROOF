"""
PRODPROOF — Shared evidence status vocabulary.

Every integration (Jenkins, Trivy, Terraform, Kubernetes, AWS, production DB,
etc.) must report one of these statuses. Nothing in this system is allowed
to report PASS when an integration was never actually reached.
"""

from enum import Enum


class EvidenceStatus(str, Enum):
    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    UNAVAILABLE = "UNAVAILABLE"          # integration enabled + configured, but call failed/timed out
    NOT_CONFIGURED = "NOT_CONFIGURED"    # integration disabled or missing credentials


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ReleaseDecision(str, Enum):
    APPROVE = "APPROVE"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"
