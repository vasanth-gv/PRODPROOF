"""
PRODPROOF — Analysis API.

POST /api/releases/{id}/analyze   run the full evidence + risk + decision pipeline
GET  /api/releases/{id}/analysis  fetch the latest analysis bundle
GET  /api/releases/{id}/decision  fetch just the latest decision (lightweight)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.database import get_db
from models.release import Release
from schemas.evidence import AnalysisBundle
from services.analysis_service import get_latest_analysis, run_analysis
from services.policy_engine import seed_default_policies

router = APIRouter(prefix="/api/releases", tags=["analysis"])


def _require_release(db: Session, release_id: int) -> Release:
    release = db.query(Release).filter(Release.id == release_id).first()
    if release is None:
        raise HTTPException(status_code=404, detail=f"Release {release_id} not found.")
    return release


@router.post("/{release_id}/analyze", response_model=AnalysisBundle)
def analyze_release(release_id: int, db: Session = Depends(get_db)) -> AnalysisBundle:
    _require_release(db, release_id)
    seed_default_policies(db)
    try:
        return run_analysis(db, release_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/{release_id}/analysis", response_model=AnalysisBundle)
def get_analysis(release_id: int, db: Session = Depends(get_db)) -> AnalysisBundle:
    _require_release(db, release_id)
    bundle = get_latest_analysis(db, release_id)
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail=f"Release {release_id} has not been analyzed yet. POST to /api/releases/{release_id}/analyze first.",
        )
    return bundle


@router.get("/{release_id}/decision")
def get_decision(release_id: int, db: Session = Depends(get_db)) -> dict:
    _require_release(db, release_id)
    bundle = get_latest_analysis(db, release_id)
    if bundle is None:
        raise HTTPException(
            status_code=404,
            detail=f"Release {release_id} has not been analyzed yet.",
        )
    return {
        "release_id": bundle.release_id,
        "decision": bundle.decision,
        "risk_level": bundle.risk_level,
        "risk_score": bundle.risk_score,
        "primary_reason": bundle.primary_reason,
        "analyzed_at": bundle.analyzed_at,
    }
