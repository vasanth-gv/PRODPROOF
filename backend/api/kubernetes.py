"""PRODPROOF — Kubernetes Readiness API (Phase 7)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import get_db
from models.release import Release
from schemas.evidence import EvidenceEnvelope
from services.kubernetes_service import get_kubernetes_readiness

router = APIRouter(prefix="/api/kubernetes", tags=["kubernetes"])


@router.get("/readiness", response_model=EvidenceEnvelope)
def kubernetes_readiness(release_id: int | None = None, db: Session = Depends(get_db)) -> EvidenceEnvelope:
    release = db.query(Release).filter(Release.id == release_id).first() if release_id else None
    return get_kubernetes_readiness(release)
