"""
PRODPROOF — Audit Trail API (Phase 13).

Provides a read-only audit trail for important release actions.

Endpoints:

GET /api/audit
    Latest audit events across all releases.

GET /api/audit?release_id=1
    Latest audit events for one release.

Query parameters:
- release_id: optional release filter
- limit: number of records to return, 1-500
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc
from sqlalchemy.orm import Session

from models.audit import AuditEvent
from models.database import get_db
from schemas.evidence import AuditEventResponse


router = APIRouter(
    prefix="/api/audit",
    tags=["audit"],
)


@router.get(
    "",
    response_model=list[AuditEventResponse],
)
def list_audit_events(
    release_id: int | None = Query(
        default=None,
        description="Filter audit events by release ID.",
    ),
    limit: int = Query(
        default=100,
        ge=1,
        le=500,
        description="Maximum number of audit events to return.",
    ),
    db: Session = Depends(get_db),
) -> list[AuditEvent]:

    query = db.query(AuditEvent)

    if release_id is not None:
        query = query.filter(
            AuditEvent.release_id == release_id
        )

    return (
        query
        .order_by(
            desc(AuditEvent.created_at),
            desc(AuditEvent.id),
        )
        .limit(limit)
        .all()
    )