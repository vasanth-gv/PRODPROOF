"""PRODPROOF — Security Evidence API (Phase 5)."""

from fastapi import APIRouter

from schemas.evidence import EvidenceEnvelope
from services.security_service import get_security_evidence

router = APIRouter(prefix="/api/security", tags=["security"])


@router.get("/evidence", response_model=EvidenceEnvelope)
def security_evidence() -> EvidenceEnvelope:
    return get_security_evidence()
