"""
PRODPROOF — Security evidence ingestion (Phase 5).

Consumes and interprets Trivy/Gitleaks report output — does not scan
anything itself. Reads local JSON report files when configured (path in
TRIVY_REPORT_SOURCE / GITLEAKS_REPORT_SOURCE); reports UNAVAILABLE if a
configured source can't be read, NOT_CONFIGURED if nothing is set up
(or demo data if DEMO_MODE=true).
"""

import json
import os

from config import get_settings
from schemas.evidence import EvidenceEnvelope
from utils.status import EvidenceStatus


def get_security_evidence() -> EvidenceEnvelope:
    settings = get_settings()
    trivy_on = settings.trivy_enabled and bool(settings.trivy_report_source)
    gitleaks_on = settings.gitleaks_enabled and bool(settings.gitleaks_report_source)

    if not trivy_on and not gitleaks_on:
        if settings.demo_mode:
            return EvidenceEnvelope(
                status=EvidenceStatus.WARNING.value,
                summary="Demo security evidence (Trivy/Gitleaks not configured).",
                source="demo",
                metrics={
                    "critical_vulnerabilities": 0,
                    "high_vulnerabilities": 2,
                    "secret_findings": 0,
                    "dependency_findings": 1,
                },
                findings=[
                    "2 high-severity vulnerabilities found (demo data).",
                    "1 outdated dependency flagged (demo data).",
                ],
            )
        return EvidenceEnvelope(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary="No security scanners configured.",
            source="not_configured",
        )

    metrics = {
        "critical_vulnerabilities": 0,
        "high_vulnerabilities": 0,
        "secret_findings": 0,
        "dependency_findings": 0,
    }
    findings: list[str] = []
    status = EvidenceStatus.PASS.value

    if trivy_on:
        try:
            if os.path.isfile(settings.trivy_report_source):
                with open(settings.trivy_report_source) as f:
                    report = json.load(f)
                for result in report.get("Results", []):
                    for vuln in result.get("Vulnerabilities", []) or []:
                        sev = (vuln.get("Severity") or "").upper()
                        if sev == "CRITICAL":
                            metrics["critical_vulnerabilities"] += 1
                        elif sev == "HIGH":
                            metrics["high_vulnerabilities"] += 1
            else:
                findings.append(f"Trivy report source not found: {settings.trivy_report_source}")
                status = EvidenceStatus.UNAVAILABLE.value
        except Exception as exc:  # noqa: BLE001
            findings.append(f"Failed to read Trivy report: {exc}")
            status = EvidenceStatus.UNAVAILABLE.value

    if gitleaks_on:
        try:
            if os.path.isfile(settings.gitleaks_report_source):
                with open(settings.gitleaks_report_source) as f:
                    report = json.load(f)
                metrics["secret_findings"] = len(report) if isinstance(report, list) else 0
            else:
                findings.append(f"Gitleaks report source not found: {settings.gitleaks_report_source}")
                status = EvidenceStatus.UNAVAILABLE.value
        except Exception as exc:  # noqa: BLE001
            findings.append(f"Failed to read Gitleaks report: {exc}")
            status = EvidenceStatus.UNAVAILABLE.value

    if status != EvidenceStatus.UNAVAILABLE.value:
        if metrics["critical_vulnerabilities"] > 0 or metrics["secret_findings"] > 0:
            status = EvidenceStatus.FAIL.value
        elif metrics["high_vulnerabilities"] > 0:
            status = EvidenceStatus.WARNING.value

    if not findings:
        findings.append(
            "No critical vulnerabilities or secret findings detected."
            if status == EvidenceStatus.PASS.value
            else "See metrics for details."
        )

    return EvidenceEnvelope(
        status=status,
        summary="Security evidence from configured scanners.",
        source="live",
        metrics=metrics,
        findings=findings,
    )
