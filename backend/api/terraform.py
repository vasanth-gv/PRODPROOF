"""PRODPROOF — Infrastructure Analysis API (Phase 6, Terraform)."""

from fastapi import APIRouter

from schemas.evidence import EvidenceEnvelope
from services.terraform_service import get_infrastructure_changes

router = APIRouter(prefix="/api/infrastructure", tags=["infrastructure"])


@router.get("/changes", response_model=EvidenceEnvelope)
def infrastructure_changes() -> EvidenceEnvelope:
    return get_infrastructure_changes()
