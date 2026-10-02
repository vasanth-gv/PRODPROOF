"""
PRODPROOF — Decision Engine (Phase 12).

Turns the Risk Engine's risk_level into a baseline decision, then applies
any policy violations from the Policy Engine — policies can only escalate
(REVIEW -> BLOCK, APPROVE -> REVIEW/BLOCK), never downgrade. Every escalation
is recorded so the final decision is fully explainable: never a black box.
"""

from utils.status import ReleaseDecision, RiskLevel

_DECISION_RANK = {
    ReleaseDecision.APPROVE.value: 0,
    ReleaseDecision.REVIEW.value: 1,
    ReleaseDecision.BLOCK.value: 2,
}

_BASELINE_BY_RISK = {
    RiskLevel.LOW.value: ReleaseDecision.APPROVE.value,
    RiskLevel.MEDIUM.value: ReleaseDecision.REVIEW.value,
    RiskLevel.HIGH.value: ReleaseDecision.REVIEW.value,
    RiskLevel.CRITICAL.value: ReleaseDecision.BLOCK.value,
}


def decide(risk_level: str, policy_violations: list[tuple]) -> tuple[str, list[str]]:
    """
    Returns (final_decision, policy_override_messages).
    policy_violations: list of (Policy, message) from policy_engine.evaluate_policies().
    """
    decision = _BASELINE_BY_RISK.get(risk_level, ReleaseDecision.REVIEW.value)
    override_messages: list[str] = []

    for policy, message in policy_violations:
        candidate = policy.action  # "BLOCK" or "REVIEW"
        if _DECISION_RANK.get(candidate, 0) > _DECISION_RANK.get(decision, 0):
            decision = candidate
            override_messages.append(message)
        elif candidate == decision:
            # Same severity — still record why, for the audit trail.
            override_messages.append(message)

    return decision, override_messages
