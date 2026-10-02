"""
PRODPROOF — Policy Engine (Phase 13).

Evaluates configurable Policy rows (stored in MySQL, editable via
GET/POST /api/policies) against a flattened evidence dict. Policies can
only ESCALATE a decision (force REVIEW or BLOCK) — they never downgrade
a decision the Risk Engine already flagged as risky. This keeps the
policy layer additive and auditable rather than a second, conflicting
source of truth.
"""

from sqlalchemy.orm import Session

from models.policy import Policy

DEFAULT_POLICIES = [
    {
        "name": "Block on critical vulnerabilities",
        "field": "security.critical_vulnerabilities",
        "operator": "gt",
        "threshold": 0,
        "action": "BLOCK",
    },
    {
        "name": "Block when rollback is not ready",
        "field": "rollback.previous_version_available",
        "operator": "is_false",
        "threshold": None,
        "action": "BLOCK",
    },
    {
        "name": "Review when production CPU exceeds 80%",
        "field": "production.cpu_utilization_pct",
        "operator": "gt",
        "threshold": 80,
        "action": "REVIEW",
    },
    {
        "name": "Block when infrastructure has an open security group",
        "field": "infrastructure.security_group_changes",
        "operator": "gt",
        "threshold": 0,
        "action": "BLOCK",
    },
    {
        "name": "Block when a critical dependency is unavailable",
        "field": "dependencies.has_critical_failure",
        "operator": "is_true",
        "threshold": None,
        "action": "BLOCK",
    },
]


def seed_default_policies(db: Session) -> None:
    """Idempotent: only seeds if the policies table is empty."""
    if db.query(Policy).count() > 0:
        return
    for p in DEFAULT_POLICIES:
        db.add(Policy(**p, enabled=True))
    db.commit()


def _get(flat: dict, dotted: str):
    node = flat
    for part in dotted.split("."):
        if isinstance(node, dict) and part in node:
            node = node[part]
        else:
            return None
    return node


def evaluate_policies(db: Session, evidence_flat: dict) -> list[tuple[Policy, str]]:
    """Returns (policy, message) for every enabled policy that is violated."""
    violations: list[tuple[Policy, str]] = []
    policies = db.query(Policy).filter(Policy.enabled.is_(True)).all()

    for p in policies:
        value = _get(evidence_flat, p.field)
        if value is None:
            continue
        triggered = False
        try:
            if p.operator == "gt" and p.threshold is not None:
                triggered = float(value) > p.threshold
            elif p.operator == "gte" and p.threshold is not None:
                triggered = float(value) >= p.threshold
            elif p.operator == "lt" and p.threshold is not None:
                triggered = float(value) < p.threshold
            elif p.operator == "lte" and p.threshold is not None:
                triggered = float(value) <= p.threshold
            elif p.operator == "eq" and p.threshold is not None:
                triggered = float(value) == p.threshold
            elif p.operator == "is_true":
                triggered = value is True
            elif p.operator == "is_false":
                triggered = value is False
        except (TypeError, ValueError):
            continue

        if triggered:
            violations.append((p, f"Policy '{p.name}' triggered ({p.field} = {value})."))

    return violations
