"""
PRODPROOF — Audit event model.

Every important action gets a row here: release submitted, analysis
started/completed, decision generated, override applied. This is what
powers the Audit page, and it's append-only — nothing here is ever
updated or deleted by the application.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g. RELEASE_SUBMITTED, ANALYSIS_STARTED, ANALYSIS_COMPLETED,
    # DECISION_GENERATED, OVERRIDE_APPLIED
    release_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
