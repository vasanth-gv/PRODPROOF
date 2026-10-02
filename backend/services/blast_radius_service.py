"""
PRODPROOF — Blast radius analysis (Phase 9).

Determines what would be affected if this release's application fails.

Blast-radius evidence is collected from live Kubernetes workload metadata.

Supported dependency declarations:

1. Deployment metadata labels / annotations
2. Pod template labels / annotations
3. Container environment variable:
       PRODPROOF_DEPENDS_ON

Example:

spec:
  template:
    metadata:
      labels:
        prodproof.io/depends-on: payment-service

or:

env:
  - name: PRODPROOF_DEPENDS_ON
    value: payment-service,auth-service

Important:
- No hard-coded downstream map.
- Missing dependency metadata is NOT_CONFIGURED.
- Confirmed downstream workloads are reported from live Kubernetes.
- Kubernetes/API errors are UNAVAILABLE.
"""

from __future__ import annotations

from typing import Any

from config import get_settings
from schemas.evidence import BlastRadiusEvidence
from utils.status import EvidenceStatus


DEPENDENCY_LABEL = "prodproof.io/depends-on"
DEPENDENCY_ENV = "PRODPROOF_DEPENDS_ON"


def _parse_dependency_values(value: str | None) -> list[str]:
    """
    Parse comma-separated dependency declarations.

    Example:
        "payment-service,auth-service"
        ->
        ["payment-service", "auth-service"]
    """

    if not value:
        return []

    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def _read_metadata_dependencies(
    metadata: Any,
) -> tuple[list[str], bool]:
    """
    Read dependency declarations from Kubernetes metadata.

    Returns:
        dependencies, metadata_present
    """

    if metadata is None:
        return [], False

    dependencies: list[str] = []
    metadata_present = False

    labels = getattr(metadata, "labels", None) or {}
    annotations = getattr(metadata, "annotations", None) or {}

    # ------------------------------------------------------------
    # Labels
    # ------------------------------------------------------------

    if DEPENDENCY_LABEL in labels:
        metadata_present = True

        dependencies.extend(
            _parse_dependency_values(
                labels.get(DEPENDENCY_LABEL)
            )
        )

    # ------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------

    if DEPENDENCY_LABEL in annotations:
        metadata_present = True

        dependencies.extend(
            _parse_dependency_values(
                annotations.get(DEPENDENCY_LABEL)
            )
        )

    return dependencies, metadata_present


def _get_deployment_dependencies(
    deployment: Any,
) -> tuple[list[str], bool]:
    """
    Extract downstream dependency declarations from a Deployment.

    Checks BOTH:

        deployment.metadata
        deployment.spec.template.metadata

    The pod-template metadata is especially important because application
    dependency labels are commonly attached to the pods created by the
    Deployment.
    """

    dependencies: list[str] = []
    metadata_present = False

    # ------------------------------------------------------------
    # 1. Deployment metadata
    # ------------------------------------------------------------

    deployment_metadata = getattr(
        deployment,
        "metadata",
        None,
    )

    deployment_dependencies, deployment_metadata_present = (
        _read_metadata_dependencies(
            deployment_metadata
        )
    )

    dependencies.extend(
        deployment_dependencies
    )

    if deployment_metadata_present:
        metadata_present = True

    # ------------------------------------------------------------
    # 2. Pod template metadata
    #
    # This is where our current test workloads place:
    #
    # prodproof.io/depends-on: payment-service
    # ------------------------------------------------------------

    spec = getattr(
        deployment,
        "spec",
        None,
    )

    template = getattr(
        spec,
        "template",
        None,
    ) if spec else None

    template_metadata = getattr(
        template,
        "metadata",
        None,
    ) if template else None

    template_dependencies, template_metadata_present = (
        _read_metadata_dependencies(
            template_metadata
        )
    )

    dependencies.extend(
        template_dependencies
    )

    if template_metadata_present:
        metadata_present = True

    # ------------------------------------------------------------
    # 3. Container environment variable
    # ------------------------------------------------------------

    pod_spec = getattr(
        template,
        "spec",
        None,
    ) if template else None

    containers = (
        getattr(
            pod_spec,
            "containers",
            None,
        )
        or []
    )

    for container in containers:

        env_list = (
            getattr(
                container,
                "env",
                None,
            )
            or []
        )

        for env in env_list:

            if getattr(
                env,
                "name",
                None,
            ) != DEPENDENCY_ENV:
                continue

            metadata_present = True

            value = getattr(
                env,
                "value",
                None,
            )

            dependencies.extend(
                _parse_dependency_values(
                    value
                )
            )

    # ------------------------------------------------------------
    # Deduplicate while preserving order
    # ------------------------------------------------------------

    unique_dependencies: list[str] = []

    for dependency in dependencies:

        normalized = dependency.strip()

        if (
            normalized
            and normalized not in unique_dependencies
        ):
            unique_dependencies.append(
                normalized
            )

    return (
        unique_dependencies,
        metadata_present,
    )


def _deployment_identity(
    deployment: Any,
) -> str:
    """
    Get the best human-readable workload name.
    """

    metadata = getattr(
        deployment,
        "metadata",
        None,
    )

    if metadata is None:
        return "unknown-service"

    labels = (
        getattr(
            metadata,
            "labels",
            None,
        )
        or {}
    )

    return (
        labels.get("app")
        or labels.get("app.kubernetes.io/name")
        or getattr(
            metadata,
            "name",
            None,
        )
        or "unknown-service"
    )


def _matches_target(
    dependency_name: str,
    application_name: str,
) -> bool:
    """
    Match a declared dependency against the release application.
    """

    left = dependency_name.strip().lower()
    right = application_name.strip().lower()

    if left == right:
        return True

    normalized_left = (
        left
        .replace("_", "-")
        .replace(" ", "-")
    )

    normalized_right = (
        right
        .replace("_", "-")
        .replace(" ", "-")
    )

    return normalized_left == normalized_right


def compute_blast_radius(
    release=None,
) -> BlastRadiusEvidence:
    """
    Evaluate live downstream dependency evidence from Kubernetes.
    """

    settings = get_settings()

    # ============================================================
    # Release validation
    # ============================================================

    if (
        release is None
        or not release.application
    ):
        return BlastRadiusEvidence(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary="No release application specified.",
            source="not_configured",
            blast_radius="LOW",
            affected_services=[],
            findings=[
                "A release application is required to evaluate blast radius."
            ],
        )

    application = release.application

    # ============================================================
    # Kubernetes integration validation
    # ============================================================

    if not settings.kubernetes_enabled:
        return BlastRadiusEvidence(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary=(
                "Live Kubernetes blast-radius integration is disabled."
            ),
            source="not_configured",
            blast_radius="LOW",
            affected_services=[],
            findings=[
                "Kubernetes integration is disabled; downstream "
                "dependency evidence cannot be evaluated."
            ],
        )

    # ============================================================
    # Live Kubernetes inspection
    # ============================================================

    try:
        from kubernetes import client, config

        config.load_kube_config(
            config_file=settings.kube_config_path,
            context=settings.kube_context,
        )

        apps_api = client.AppsV1Api()

        deployments_response = (
            apps_api.list_deployment_for_all_namespaces()
        )

        deployments = (
            deployments_response.items
            or []
        )

        discovered_dependency_metadata = False
        affected_services: list[str] = []

        # ========================================================
        # Inspect every live Deployment
        # ========================================================

        for deployment in deployments:

            (
                dependencies,
                metadata_present,
            ) = _get_deployment_dependencies(
                deployment
            )

            if metadata_present:
                discovered_dependency_metadata = True

            if not dependencies:
                continue

            depends_on_application = any(
                _matches_target(
                    dependency,
                    application,
                )
                for dependency in dependencies
            )

            if not depends_on_application:
                continue

            service_name = _deployment_identity(
                deployment
            )

            if service_name not in affected_services:
                affected_services.append(
                    service_name
                )

        # ========================================================
        # No dependency metadata anywhere
        # ========================================================

        if not discovered_dependency_metadata:
            return BlastRadiusEvidence(
                status=EvidenceStatus.NOT_CONFIGURED.value,
                summary=(
                    "Live Kubernetes workloads do not expose "
                    "downstream dependency metadata."
                ),
                source="live",
                blast_radius="LOW",
                affected_services=[],
                findings=[
                    (
                        f"No downstream dependency evidence was found "
                        f"for '{application}'. Workloads need the "
                        f"'{DEPENDENCY_LABEL}' label/annotation or "
                        f"'{DEPENDENCY_ENV}' environment variable."
                    )
                ],
            )

        # ========================================================
        # Metadata exists but no workload depends on this app
        # ========================================================

        if not affected_services:
            return BlastRadiusEvidence(
                status=EvidenceStatus.PASS.value,
                summary=(
                    f"No downstream dependents of '{application}' "
                    f"were found in live Kubernetes dependency metadata."
                ),
                source="live",
                blast_radius="LOW",
                affected_services=[],
                findings=[
                    (
                        f"No live downstream workload declares "
                        f"'{application}' as a dependency."
                    )
                ],
            )

        # ========================================================
        # Calculate blast radius
        # ========================================================

        count = len(
            affected_services
        )

        if count >= 3:
            radius = "HIGH"
            status = EvidenceStatus.WARNING.value

        elif count >= 1:
            radius = "MEDIUM"
            status = EvidenceStatus.PASS.value

        else:
            radius = "LOW"
            status = EvidenceStatus.PASS.value

        findings = [
            (
                f"{count} downstream service(s) would be affected "
                f"if {application} fails: "
                f"{', '.join(affected_services)}."
            )
        ]

        return BlastRadiusEvidence(
            status=status,
            summary=f"Live blast radius: {radius}.",
            source="live",
            blast_radius=radius,
            affected_services=affected_services,
            findings=findings,
        )

    # ============================================================
    # Kubernetes API/configuration error
    # ============================================================

    except Exception as exc:
        return BlastRadiusEvidence(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary=(
                "Live Kubernetes blast-radius evidence "
                "could not be retrieved."
            ),
            source="unavailable",
            blast_radius="LOW",
            affected_services=[],
            findings=[
                f"Kubernetes dependency inspection failed: {exc}"
            ],
        )