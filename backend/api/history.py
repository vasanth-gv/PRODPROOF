"""PRODPROOF — Release History API (Phase 12)."""

from fastapi import APIRouter, Depends
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.database import get_db
from models.decision import Decision
from models.release import Release
from schemas.evidence import DecisionHistoryItem

router = APIRouter(prefix="/api/history", tags=["history"])


@router.get("", response_model=list[DecisionHistoryItem])
def history(db: Session = Depends(get_db)) -> list[DecisionHistoryItem]:
    rows = (
        db.query(Decision, Release)
        .join(Release, Decision.release_id == Release.id)
        .order_by(desc(Decision.created_at), desc(Decision.id))
        .all()
    )
    return [
        DecisionHistoryItem(
            release_id=release.id,
            application=release.application,
            version=release.version,
            environment=release.environment,
            risk_score=decision.risk_score,
            risk_level=decision.risk_level,
            decision=decision.decision,
            primary_reason=decision.primary_reason,
            overridden=decision.overridden,
            created_at=decision.created_at,
        )
        for decision, release in rows
    ]
