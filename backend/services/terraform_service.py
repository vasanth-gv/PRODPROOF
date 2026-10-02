"""
PRODPROOF — Terraform infrastructure change evidence service.

Reads a Terraform JSON plan and converts infrastructure changes
into explainable evidence for the risk engine.

Security-group risk is counted only when a public ingress rule
is detected. A normal/restricted security-group change should not
trigger the "open security group" blocking policy.
"""

import json
import os

from config import get_settings
from schemas.evidence import EvidenceEnvelope


def _is_public_cidr(value: object) -> bool:
    """Return True when a CIDR value exposes the resource publicly."""
    if value is None:
        return False

    if isinstance(value, list):
        return any(_is_public_cidr(item) for item in value)

    if isinstance(value, dict):
        return any(_is_public_cidr(item) for item in value.values())

    return str(value).strip() in {"0.0.0.0/0", "::/0"}


def _collect_security_group_findings(resource: dict) -> list[str]:
    """
    Inspect Terraform security-group ingress rules.

    A security-group is considered risky only when an ingress rule
    exposes it publicly through 0.0.0.0/0 or ::/0.
    """
    findings: list[str] = []

    change = resource.get("change", {}) or {}
    after = change.get("after") or {}

    ingress_rules = after.get("ingress") or []

    if isinstance(ingress_rules, dict):
        ingress_rules = [ingress_rules]

    for rule in ingress_rules:
        if not isinstance(rule, dict):
            continue

        cidr_blocks = rule.get("cidr_blocks") or []
        ipv6_cidr_blocks = rule.get("ipv6_cidr_blocks") or []

        public_ipv4 = _is_public_cidr(cidr_blocks)
        public_ipv6 = _is_public_cidr(ipv6_cidr_blocks)

        if not public_ipv4 and not public_ipv6:
            continue

        from_port = rule.get("from_port")
        to_port = rule.get("to_port")
        protocol = rule.get("protocol", "unknown")
        address = resource.get("address", "unknown-resource")

        if from_port == to_port and from_port is not None:
            port_text = f"port {from_port}"
        elif from_port is not None or to_port is not None:
            port_text = f"ports {from_port}-{to_port}"
        else:
            port_text = "all ports"

        if public_ipv4:
            findings.append(
                f"Open security group rule detected on resource "
                f"{address}: 0.0.0.0/0 → {port_text} ({protocol})."
            )

        if public_ipv6:
            findings.append(
                f"Open IPv6 security group rule detected on resource "
                f"{address}: ::/0 → {port_text} ({protocol})."
            )

    return findings


def get_infrastructure_changes() -> EvidenceEnvelope:
    settings = get_settings()

    if not settings.terraform_enabled or not settings.terraform_plan_source:
        if settings.demo_mode:
            return EvidenceEnvelope(
                status="WARNING",
                summary="Demo infrastructure plan (Terraform not configured).",
                source="demo",
                metrics={
                    "resources_added": 2,
                    "resources_changed": 1,
                    "resources_destroyed": 0,
                    "security_group_changes": 1,
                    "iam_changes": 0,
                },
                findings=[
                    "Open security group rule detected: "
                    "0.0.0.0/0 → port 8080 (demo data)."
                ],
            )

        return EvidenceEnvelope(
            status="NOT_CONFIGURED",
            summary="Terraform integration is not configured.",
            source="not_configured",
        )

    try:
        plan_path = settings.terraform_plan_source

        if not os.path.isfile(plan_path):
            return EvidenceEnvelope(
                status="UNAVAILABLE",
                summary="Terraform plan source not found.",
                source="live",
                findings=[f"Path not found: {plan_path}"],
            )

        with open(plan_path, "r", encoding="utf-8-sig") as file:
            plan = json.load(file)

        resource_changes = plan.get("resource_changes", []) or []

        resources_added = 0
        resources_changed = 0
        resources_destroyed = 0

        # IMPORTANT:
        # This metric represents risky/public security-group changes,
        # because policy #4 uses this field to block open SG access.
        security_group_changes = 0
        iam_changes = 0

        findings: list[str] = []

        for resource in resource_changes:
            change = resource.get("change", {}) or {}
            actions = change.get("actions", []) or []

            if "create" in actions:
                resources_added += 1

            if "update" in actions:
                resources_changed += 1

            if "delete" in actions:
                resources_destroyed += 1

            resource_type = str(resource.get("type", ""))
            address = str(resource.get("address", ""))

            is_security_group = (
                resource_type in {
                    "aws_security_group",
                    "aws_security_group_rule",
                }
                or "security_group" in resource_type
                or "security_group" in address
            )

            if is_security_group and actions and actions != ["no-op"]:
                sg_findings = _collect_security_group_findings(resource)

                if sg_findings:
                    # Count only risky/public SG changes.
                    security_group_changes += 1
                    findings.extend(sg_findings)

            if resource_type.startswith("aws_iam_") and actions:
                iam_changes += 1

        if findings:
            status = "FAIL"
        elif resources_destroyed > 0:
            status = "WARNING"
        else:
            status = "PASS"

        if not findings:
            findings.append(
                "No high-risk infrastructure changes detected."
            )

        return EvidenceEnvelope(
            status=status,
            summary="Infrastructure change evidence from the Terraform plan.",
            source="live",
            metrics={
                "resources_added": resources_added,
                "resources_changed": resources_changed,
                "resources_destroyed": resources_destroyed,
                "security_group_changes": security_group_changes,
                "iam_changes": iam_changes,
            },
            findings=findings,
        )

    except Exception as exc:
        return EvidenceEnvelope(
            status="UNAVAILABLE",
            summary="Failed to read the Terraform plan.",
            source="live",
            findings=[str(exc)],
        )