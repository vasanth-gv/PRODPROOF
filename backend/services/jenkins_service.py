"""
PRODPROOF — Jenkins integration (Phase 4).

Converts raw Jenkins build data into release evidence — not a Jenkins
dashboard. Uses a real HTTP client with a timeout when configured; when
not configured, reports NOT_CONFIGURED (or demo data if DEMO_MODE=true).
On any network/auth failure against a real Jenkins, reports UNAVAILABLE
with the actual error — never a fake PASS.
"""

import httpx

from config import get_settings
from schemas.evidence import EvidenceEnvelope
from utils.logger import get_logger
from utils.status import EvidenceStatus

logger = get_logger("prodproof.services.jenkins")


def get_cicd_evidence(job_name: str | None = None) -> EvidenceEnvelope:
    settings = get_settings()

    if not settings.jenkins_enabled or not settings.jenkins_base_url:
        if settings.demo_mode:
            return EvidenceEnvelope(
                status=EvidenceStatus.PASS.value,
                summary="Demo CI/CD evidence (Jenkins not configured).",
                source="demo",
                metrics={
                    "build_status": "SUCCESS",
                    "test_status": "PASS",
                    "pipeline_status": "PASS",
                    "build_duration_seconds": 184,
                    "failed_stages": [],
                },
                findings=["Build and tests passed (demo data)."],
            )
        return EvidenceEnvelope(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary="Jenkins integration is not configured.",
            source="not_configured",
        )

    job = job_name or "unspecified-job"
    url = f"{settings.jenkins_base_url.rstrip('/')}/job/{job}/lastBuild/api/json"
    auth = (settings.jenkins_user, settings.jenkins_api_token) if settings.jenkins_user else None

    try:
        with httpx.Client(timeout=settings.jenkins_timeout_seconds) as client:
            resp = client.get(url, auth=auth)
            resp.raise_for_status()
            data = resp.json()

        result = data.get("result")  # SUCCESS, FAILURE, UNSTABLE, or None if still building
        building = data.get("building", False)

        if result == "SUCCESS":
            status = EvidenceStatus.PASS.value
        elif result in ("FAILURE", "UNSTABLE"):
            status = EvidenceStatus.FAIL.value
        else:
            status = EvidenceStatus.WARNING.value

        return EvidenceEnvelope(
            status=status,
            summary=f"Jenkins job '{job}' last build: {result or ('BUILDING' if building else 'UNKNOWN')}.",
            source="live",
            metrics={
                "build_status": result,
                "building": building,
                "build_number": data.get("number"),
                "duration_ms": data.get("duration"),
            },
            findings=[] if status == EvidenceStatus.PASS.value else [f"Jenkins reported result: {result}."],
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("Jenkins evidence fetch failed for job '%s': %s", job, exc)
        return EvidenceEnvelope(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary="Jenkins is configured but could not be reached.",
            source="live",
            metrics={},
            findings=[str(exc)],
        )
