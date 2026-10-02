"""PRODPROOF — Production Context API (Phase 3)."""

from fastapi import APIRouter

from schemas.evidence import EvidenceEnvelope
from services.production_context_service import get_capacity_summary, get_production_context

router = APIRouter(prefix="/api/production", tags=["production"])


@router.get("/context", response_model=EvidenceEnvelope)
def production_context() -> EvidenceEnvelope:
    return get_production_context()


@router.get("/capacity", response_model=EvidenceEnvelope)
def production_capacity() -> EvidenceEnvelope:
    return get_capacity_summary()
