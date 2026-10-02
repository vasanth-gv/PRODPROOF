"""
PRODPROOF — Release model.

Reuses the existing Base from models.database — no second declarative
base is created. Imported by app.py before Base.metadata.create_all() runs.

Release requirements are nullable so older Phase 2 releases continue
working while newer analysis phases consume the additional evidence fields.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from models.database import Base


class Release(Base):
    __tablename__ = "releases"

    id: Mapped[int] = mapped_column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    application: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    version: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    environment: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )

    git_commit: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    release_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="READY_FOR_ANALYSIS",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )

    # ---------------------------------------------------------
    # Release requirements / analysis inputs
    # ---------------------------------------------------------

    docker_image: Mapped[str | None] = mapped_column(
        String(200),
        nullable=True,
    )

    expected_replicas: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    cpu_millicores: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    memory_mb: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    db_connections_required: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    dependency_list: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    rollback_version: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    # ---------------------------------------------------------
    # CI/CD integration
    # ---------------------------------------------------------

    jenkins_job_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )