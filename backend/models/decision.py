"""
PRODPROOF — Decision model.

One row per analysis run (POST /api/releases/{id}/analyze). A release can
be analyzed more than once (e.g. after production context changes), so
this is a history table, not a single column on Release — it's what
powers the History page and release comparison over time.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class Decision(Base):
    __tablename__ = "decisions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    release_id: Mapped[int] = mapped_column(ForeignKey("releases.id"), nullable=False, index=True)
    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    risk_level: Mapped[str] = mapped_column(String(20), nullable=False)  # LOW/MEDIUM/HIGH/CRITICAL
    decision: Mapped[str] = mapped_column(String(20), nullable=False)  # APPROVE/REVIEW/BLOCK
    primary_reason: Mapped[str] = mapped_column(String(300), nullable=False)
    reasons_json: Mapped[str] = mapped_column(Text, nullable=False)  # full evidence bundle, JSON-encoded
    overridden: Mapped[bool] = mapped_column(default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=lambda: datetime.now(timezone.utc)
    )
