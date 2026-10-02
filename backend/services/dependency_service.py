"""
PRODPROOF — Dependency analysis (Phase 8).

Evaluates release dependencies against live Kubernetes workload/service
evidence when Kubernetes integration is enabled.

Important:
- Never reports PASS merely because a dependency is listed.
- Missing live evidence is reported as NOT_CONFIGURED.
- Partial health is WARNING.
- Explicitly unhealthy dependencies are FAIL.
- Kubernetes/API failures are reported as UNAVAILABLE.
"""

from __future__ import annotations

from typing import Any

from config import get_settings
from schemas.evidence import DependencyEvidence, DependencyNode
from utils.status import EvidenceStatus


CRITICALITY_MAP = {
    "payment-db": "CRITICAL",
    "redis": "HIGH",
    "auth-service": "HIGH",
    "external-payment-api": "CRITICAL",
    "notification-service": "LOW",
    "order-service": "MEDIUM",
    "checkout": "HIGH",
}


def _dependency_names(release: Any) -> list[str]:
    if not release or not release.dependency_list:
        return []

    return [
        name.strip()
        for name in release.dependency_list.split(",")
        if name.strip()
    ]


def _matches_name(obj: Any, dependency_name: str) -> bool:
    metadata = getattr(obj, "metadata", None)

    if not metadata:
        return False

    object_name = getattr(metadata, "name", None)

    if object_name == dependency_name:
        return True

    labels = getattr(metadata, "labels", None) or {}

    interesting_labels = {
        labels.get("app"),
        labels.get("app.kubernetes.io/name"),
        labels.get("app.kubernetes.io/instance"),
        labels.get("component"),
        labels.get("name"),
    }

    return dependency_name in interesting_labels


def _deployment_health(deployment: Any) -> tuple[str, str]:
    desired = deployment.spec.replicas or 0
    available = deployment.status.available_replicas or 0
    ready = deployment.status.ready_replicas or 0
    updated = deployment.status.updated_replicas or 0

    if desired > 0 and available == desired and ready == desired:
        return (
            EvidenceStatus.PASS.value,
            (
                f"Deployment '{deployment.metadata.name}' is healthy "
                f"({ready}/{desired} ready, {updated}/{desired} updated)."
            ),
        )

    if ready > 0 or available > 0:
        return (
            EvidenceStatus.WARNING.value,
            (
                f"Deployment '{deployment.metadata.name}' is partially healthy "
                f"({ready}/{desired} ready, {available}/{desired} available)."
            ),
        )

    return (
        EvidenceStatus.FAIL.value,
        (
            f"Deployment '{deployment.metadata.name}' has no ready replicas "
            f"({ready}/{desired} ready)."
        ),
    )


def _service_endpoint_health(endpoints: Any) -> tuple[str, str]:
    ready_addresses = 0
    not_ready_addresses = 0

    for subset in endpoints.subsets or []:
        ready_addresses += len(subset.addresses or [])
        not_ready_addresses += len(subset.not_ready_addresses or [])

    if ready_addresses > 0:
        return (
            EvidenceStatus.PASS.value,
            (
                f"Service '{endpoints.metadata.name}' has "
                f"{ready_addresses} ready endpoint(s)."
            ),
        )

    if not_ready_addresses > 0:
        return (
            EvidenceStatus.FAIL.value,
            (
                f"Service '{endpoints.metadata.name}' has no ready endpoints; "
                f"{not_ready_addresses} endpoint(s) are not ready."
            ),
        )

    return (
        EvidenceStatus.FAIL.value,
        f"Service '{endpoints.metadata.name}' has no ready endpoints.",
    )


def _build_demo_evidence() -> DependencyEvidence:
    graph = [
        DependencyNode(
            name="payment-db",
            status=EvidenceStatus.WARNING.value,
            criticality="CRITICAL",
            note="Demo dependency evidence only; live health is not configured.",
        ),
        DependencyNode(
            name="redis",
            status=EvidenceStatus.WARNING.value,
            criticality="HIGH",
            note="Demo dependency evidence only; live health is not configured.",
        ),
        DependencyNode(
            name="auth-service",
            status=EvidenceStatus.WARNING.value,
            criticality="HIGH",
            note="Demo dependency evidence only; live health is not configured.",
        ),
        DependencyNode(
            name="external-payment-api",
            status=EvidenceStatus.WARNING.value,
            criticality="CRITICAL",
            note="Demo dependency evidence only; live health is not configured.",
        ),
    ]

    return DependencyEvidence(
        status=EvidenceStatus.WARNING.value,
        summary="Dependency evidence is running in explicit demo mode.",
        source="demo",
        graph=graph,
        findings=[
            "Live dependency health is not configured; demo evidence is shown."
        ],
    )


def get_dependency_evidence(release=None) -> DependencyEvidence:
    settings = get_settings()

    names = _dependency_names(release)

    # ---------------------------------------------------------
    # No dependency list
    # ---------------------------------------------------------
    if not names:
        if not settings.demo_mode:
            return DependencyEvidence(
                status=EvidenceStatus.NOT_CONFIGURED.value,
                summary="No dependency list provided for this release.",
                source="not_configured",
                graph=[],
                findings=[
                    "Release dependency_list is empty or not configured."
                ],
            )

        return _build_demo_evidence()

    # ---------------------------------------------------------
    # Dependencies exist, but Kubernetes integration is disabled
    # ---------------------------------------------------------
    if not settings.kubernetes_enabled:
        graph = [
            DependencyNode(
                name=name,
                status=EvidenceStatus.NOT_CONFIGURED.value,
                criticality=CRITICALITY_MAP.get(name, "MEDIUM"),
                note="Kubernetes dependency health integration is disabled.",
            )
            for name in names
        ]

        return DependencyEvidence(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary=(
                f"Live dependency health cannot be evaluated for "
                f"{len(graph)} dependency service(s)."
            ),
            source="not_configured",
            graph=graph,
            findings=[
                f"{node.name}: {node.status} — {node.note}"
                for node in graph
            ],
        )

    # ---------------------------------------------------------
    # Live Kubernetes inspection
    # ---------------------------------------------------------
    try:
        from kubernetes import client, config

        config.load_kube_config(
            config_file=settings.kube_config_path,
            context=settings.kube_context,
        )

        apps_api = client.AppsV1Api()
        core_api = client.CoreV1Api()

        deployment_response = apps_api.list_deployment_for_all_namespaces()
        service_response = core_api.list_service_for_all_namespaces()
        endpoint_response = core_api.list_endpoints_for_all_namespaces()

        deployments = deployment_response.items or []
        services = service_response.items or []
        endpoints = endpoint_response.items or []

        graph: list[DependencyNode] = []

        for name in names:
            criticality = CRITICALITY_MAP.get(name, "MEDIUM")

            matched_deployment = next(
                (
                    deployment
                    for deployment in deployments
                    if _matches_name(deployment, name)
                ),
                None,
            )

            if matched_deployment is not None:
                status, note = _deployment_health(matched_deployment)

                graph.append(
                    DependencyNode(
                        name=name,
                        status=status,
                        criticality=criticality,
                        note=note,
                    )
                )

                continue

            matched_service = next(
                (
                    service
                    for service in services
                    if _matches_name(service, name)
                ),
                None,
            )

            if matched_service is not None:
                matched_endpoint = next(
                    (
                        endpoint
                        for endpoint in endpoints
                        if endpoint.metadata.name == matched_service.metadata.name
                        and endpoint.metadata.namespace
                        == matched_service.metadata.namespace
                    ),
                    None,
                )

                if matched_endpoint is None:
                    graph.append(
                        DependencyNode(
                            name=name,
                            status=EvidenceStatus.FAIL.value,
                            criticality=criticality,
                            note=(
                                f"Service '{matched_service.metadata.name}' "
                                "exists but endpoint evidence is missing."
                            ),
                        )
                    )
                else:
                    status, note = _service_endpoint_health(
                        matched_endpoint
                    )

                    graph.append(
                        DependencyNode(
                            name=name,
                            status=status,
                            criticality=criticality,
                            note=note,
                        )
                    )

                continue

            # No live workload/service found.
            graph.append(
                DependencyNode(
                    name=name,
                    status=EvidenceStatus.NOT_CONFIGURED.value,
                    criticality=criticality,
                    note=(
                        "No matching Kubernetes Deployment or Service "
                        "was found in the cluster."
                    ),
                )
            )

        # -----------------------------------------------------
        # Calculate overall dependency status
        # -----------------------------------------------------
        has_fail = any(
            node.status == EvidenceStatus.FAIL.value
            for node in graph
        )

        has_warning = any(
            node.status == EvidenceStatus.WARNING.value
            for node in graph
        )

        has_not_configured = any(
            node.status == EvidenceStatus.NOT_CONFIGURED.value
            for node in graph
        )

        if has_fail:
            overall_status = EvidenceStatus.FAIL.value
        elif has_warning or has_not_configured:
            overall_status = EvidenceStatus.WARNING.value
        else:
            overall_status = EvidenceStatus.PASS.value

        findings = [
            (
                f"{node.name}: {node.status}"
                + (f" — {node.note}" if node.note else "")
            )
            for node in graph
            if node.status != EvidenceStatus.PASS.value
        ]

        if not findings:
            findings = ["All configured dependencies are healthy."]

        return DependencyEvidence(
            status=overall_status,
            summary=f"Live dependency map for {len(graph)} service(s).",
            source="live",
            graph=graph,
            findings=findings,
        )

    except Exception as exc:
        graph = [
            DependencyNode(
                name=name,
                status=EvidenceStatus.UNAVAILABLE.value,
                criticality=CRITICALITY_MAP.get(name, "MEDIUM"),
                note=f"Live dependency check failed: {exc}",
            )
            for name in names
        ]

        return DependencyEvidence(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary="Live dependency health could not be evaluated.",
            source="unavailable",
            graph=graph,
            findings=[
                f"{node.name}: {node.status} — {node.note}"
                for node in graph
            ],
        )