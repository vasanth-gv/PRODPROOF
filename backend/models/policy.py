"""
PRODPROOF — Policy model.

Configurable rules the Policy Engine evaluates against an analysis's
evidence bundle. Seeded with a few sensible defaults on first startup
(see services/policy_engine.py: seed_default_policies), but fully
editable via GET/POST /api/policies — nothing here is hardcoded into the
decision logic itself.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class Policy(Base):
    __tablename__ = "policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    # Dotted path into the evidence bundle, e.g. "security.critical_vulnerabilities"
    field: Mapped[str] = mapped_column(String(150), nullable=False)
    operator: Mapped[str] = mapped_column(String(10), nullable=False)  # gt, gte, lt, lte, eq, is_true, is_false
    threshold: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # BLOCK or REVIEW
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
