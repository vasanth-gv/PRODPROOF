"""PRODPROOF — Policies API (Phase 13)."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from models.database import get_db
from models.policy import Policy
from schemas.evidence import PolicyCreateRequest, PolicyResponse
from services.policy_engine import seed_default_policies

router = APIRouter(prefix="/api/policies", tags=["policies"])


@router.get("", response_model=list[PolicyResponse])
def list_policies(db: Session = Depends(get_db)) -> list[Policy]:
    seed_default_policies(db)
    return db.query(Policy).order_by(Policy.id).all()


@router.post("", response_model=PolicyResponse, status_code=201)
def create_policy(payload: PolicyCreateRequest, db: Session = Depends(get_db)) -> Policy:
    policy = Policy(
        name=payload.name,
        field=payload.field,
        operator=payload.operator,
        threshold=payload.threshold,
        action=payload.action,
        enabled=payload.enabled,
    )
    db.add(policy)
    db.commit()
    db.refresh(policy)
    return policy
