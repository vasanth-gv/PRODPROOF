"""PRODPROOF — Dependency Analysis API (Phase 8)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import get_db
from models.release import Release
from schemas.evidence import DependencyEvidence
from services.dependency_service import get_dependency_evidence

router = APIRouter(prefix="/api/dependencies", tags=["dependencies"])


@router.get("", response_model=DependencyEvidence)
def dependencies(release_id: int | None = None, db: Session = Depends(get_db)) -> DependencyEvidence:
    release = db.query(Release).filter(Release.id == release_id).first() if release_id else None
    return get_dependency_evidence(release)
