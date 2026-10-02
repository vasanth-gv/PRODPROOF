"""
PRODPROOF — Rollback readiness (Phase 10).

Evaluates rollback readiness using the evidence that is actually available.

Current evidence sources:
- Release record (`rollback_version`)
- Live Kubernetes Deployment
- Kubernetes ReplicaSet rollout history

Important:
- A recorded rollback_version alone is NOT treated as proof that a
  rollback artifact/image is available.
- This build has no container registry integration, so image availability
  is not claimed.
- A previous Kubernetes rollout revision is useful evidence, but it does
  not prove that the exact rollback image/version is available.
- Missing live Kubernetes rollback evidence is reported honestly.
"""

from __future__ import annotations

from config import get_settings
from schemas.evidence import EvidenceEnvelope
from utils.status import EvidenceStatus


def _not_configured(
    summary: str,
    findings: list[str],
    metrics: dict | None = None,
) -> EvidenceEnvelope:
    return EvidenceEnvelope(
        status=EvidenceStatus.NOT_CONFIGURED.value,
        summary=summary,
        source="not_configured",
        metrics=metrics or {},
        findings=findings,
    )


def get_rollback_readiness(release=None) -> EvidenceEnvelope:
    settings = get_settings()

    # ------------------------------------------------------------------
    # Release validation
    # ------------------------------------------------------------------

    if release is None:
        return _not_configured(
            summary="No release specified.",
            findings=[
                "A release is required to evaluate rollback readiness."
            ],
        )

    rollback_version = (
        getattr(release, "rollback_version", None)
        or ""
    ).strip()

    # ------------------------------------------------------------------
    # No rollback target recorded
    # ------------------------------------------------------------------

    if not rollback_version:

        if settings.demo_mode:
            return EvidenceEnvelope(
                status=EvidenceStatus.WARNING.value,
                summary="No rollback version recorded for this release.",
                source="demo",
                metrics={
                    "previous_version_available": False,
                    "rollback_version": None,
                    "rollback_artifact_verified": False,
                    "kubernetes_deployment_found": False,
                },
                findings=[
                    "Release has no rollback_version recorded.",
                    "Rollback artifact/image availability is not configured.",
                ],
            )

        return _not_configured(
            summary=(
                "No rollback version recorded and "
                "demo mode is off."
            ),
            findings=[
                "Release has no rollback_version recorded."
            ],
            metrics={
                "previous_version_available": False,
                "rollback_version": None,
                "rollback_artifact_verified": False,
                "kubernetes_deployment_found": False,
            },
        )

    # ------------------------------------------------------------------
    # Kubernetes integration disabled
    # ------------------------------------------------------------------

    if not settings.kubernetes_enabled:
        return EvidenceEnvelope(
            status=EvidenceStatus.WARNING.value,
            summary=(
                f"Rollback target recorded: {rollback_version}, "
                "but live Kubernetes rollback evidence is unavailable."
            ),
            source="live",
            metrics={
                "previous_version_available": True,
                "rollback_version": rollback_version,
                "rollback_artifact_verified": False,
                "kubernetes_deployment_found": False,
                "previous_revision_available": False,
            },
            findings=[
                (
                    f"Rollback target '{rollback_version}' is recorded "
                    "in the release."
                ),
                (
                    "Kubernetes integration is disabled, so live "
                    "rollback history could not be verified."
                ),
                (
                    "Container registry/image availability is not "
                    "configured in this build."
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Live Kubernetes inspection
    # ------------------------------------------------------------------

    try:
        from kubernetes import client, config

        config.load_kube_config(
            config_file=settings.kube_config_path,
            context=settings.kube_context,
        )

        apps_api = client.AppsV1Api()

        deployment_response = (
            apps_api.list_deployment_for_all_namespaces()
        )

        deployments = (
            deployment_response.items
            or []
        )

        # Release application is the Kubernetes workload name we expect.
        application_name = (
            getattr(release, "application", None)
            or ""
        ).strip()

        matched_deployment = None

        for deployment in deployments:

            deployment_name = (
                getattr(
                    deployment.metadata,
                    "name",
                    None,
                )
                or ""
            ).strip()

            labels = (
                getattr(
                    deployment.metadata,
                    "labels",
                    None,
                )
                or {}
            )

            app_label = labels.get(
                "app"
            )

            app_name_label = labels.get(
                "app.kubernetes.io/name"
            )

            if deployment_name == application_name:
                matched_deployment = deployment
                break

            if app_label == application_name:
                matched_deployment = deployment
                break

            if app_name_label == application_name:
                matched_deployment = deployment
                break

        # ------------------------------------------------------------------
        # No Deployment found
        # ------------------------------------------------------------------

        if matched_deployment is None:
            return EvidenceEnvelope(
                status=EvidenceStatus.WARNING.value,
                summary=(
                    f"Rollback target recorded: {rollback_version}, "
                    "but no live Kubernetes Deployment was found "
                    f"for '{application_name}'."
                ),
                source="live",
                metrics={
                    "previous_version_available": True,
                    "rollback_version": rollback_version,
                    "rollback_artifact_verified": False,
                    "kubernetes_deployment_found": False,
                    "deployment_history_available": False,
                    "previous_revision_available": False,
                },
                findings=[
                    (
                        f"Rollback target '{rollback_version}' is "
                        "recorded in the release."
                    ),
                    (
                        f"No Kubernetes Deployment matching "
                        f"'{application_name}' was found."
                    ),
                    (
                        "Container registry/image availability is not "
                        "configured, so the rollback artifact cannot "
                        "be verified."
                    ),
                ],
            )

        deployment_name = (
            matched_deployment.metadata.name
        )

        deployment_namespace = (
            matched_deployment.metadata.namespace
            or "default"
        )

        # ------------------------------------------------------------------
        # Current deployment image evidence
        # ------------------------------------------------------------------

        containers = (
            matched_deployment.spec.template.spec.containers
            or []
        )

        current_images = [
            container.image
            for container in containers
            if getattr(container, "image", None)
        ]

        # ------------------------------------------------------------------
        # Deployment rollout revision
        # ------------------------------------------------------------------

        deployment_annotations = (
            getattr(
                matched_deployment.metadata,
                "annotations",
                None,
            )
            or {}
        )

        current_revision = (
            deployment_annotations.get(
                "deployment.kubernetes.io/revision"
            )
        )

        # ------------------------------------------------------------------
        # ReplicaSet rollout history
        # ------------------------------------------------------------------

        replica_set_response = (
            apps_api.list_namespaced_replica_set(
                namespace=deployment_namespace
            )
        )

        replica_sets = (
            replica_set_response.items
            or []
        )

        deployment_uid = (
            matched_deployment.metadata.uid
        )

        related_replicasets = []

        for replica_set in replica_sets:

            owners = (
                getattr(
                    replica_set.metadata,
                    "owner_references",
                    None,
                )
                or []
            )

            owned_by_deployment = any(
                (
                    owner.kind == "Deployment"
                    and owner.name == deployment_name
                    and owner.uid == deployment_uid
                )
                for owner in owners
            )

            if owned_by_deployment:
                related_replicasets.append(
                    replica_set
                )

        rollout_revisions = []

        for replica_set in related_replicasets:

            annotations = (
                getattr(
                    replica_set.metadata,
                    "annotations",
                    None,
                )
                or {}
            )

            revision = annotations.get(
                "deployment.kubernetes.io/revision"
            )

            if revision:
                try:
                    rollout_revisions.append(
                        int(revision)
                    )
                except (TypeError, ValueError):
                    continue

        rollout_revisions = sorted(
            set(rollout_revisions)
        )

        # ------------------------------------------------------------------
        # Determine whether a previous Kubernetes revision exists
        # ------------------------------------------------------------------

        previous_revision_available = False

        if current_revision is not None:
            try:
                current_revision_int = int(
                    current_revision
                )

                previous_revision_available = any(
                    revision < current_revision_int
                    for revision in rollout_revisions
                )

            except (TypeError, ValueError):
                previous_revision_available = (
                    len(rollout_revisions) >= 2
                )

        else:
            previous_revision_available = (
                len(rollout_revisions) >= 2
            )

        # ------------------------------------------------------------------
        # Registry verification is not available in this build.
        #
        # We therefore NEVER claim that the exact rollback artifact
        # (for example payment-service:v1.3.2) is available.
        # ------------------------------------------------------------------

        registry_verified = False

        metrics = {
            "previous_version_available": True,
            "rollback_version": rollback_version,
            "rollback_artifact_verified": registry_verified,
            "kubernetes_deployment_found": True,
            "deployment_name": deployment_name,
            "deployment_namespace": deployment_namespace,
            "current_revision": current_revision,
            "rollout_revision_count": len(
                rollout_revisions
            ),
            "previous_revision_available": (
                previous_revision_available
            ),
            "current_images": current_images,
        }

        # ------------------------------------------------------------------
        # Previous Kubernetes revision exists.
        #
        # But exact rollback artifact is NOT verified.
        #
        # Therefore WARNING, not PASS.
        # ------------------------------------------------------------------

        if previous_revision_available:

            return EvidenceEnvelope(
                status=EvidenceStatus.WARNING.value,
                summary=(
                    f"Rollback target {rollback_version} is recorded "
                    "and Kubernetes rollout history contains a "
                    "previous deployment revision, but the exact "
                    "rollback artifact is not verified."
                ),
                source="live",
                metrics=metrics,
                findings=[
                    (
                        f"Rollback target '{rollback_version}' is "
                        "recorded in the release."
                    ),
                    (
                        f"Kubernetes Deployment '{deployment_name}' "
                        f"has {len(rollout_revisions)} recorded "
                        "revision(s)."
                    ),
                    (
                        "A previous Kubernetes revision is available "
                        "for rollback history."
                    ),
                    (
                        "Container registry/image availability is not "
                        "verified because no registry integration is "
                        "configured."
                    ),
                ],
            )

        # ------------------------------------------------------------------
        # Deployment exists, but no previous revision evidence
        # ------------------------------------------------------------------

        return EvidenceEnvelope(
            status=EvidenceStatus.WARNING.value,
            summary=(
                f"Rollback target {rollback_version} is recorded, "
                "but no previous Kubernetes rollout revision was "
                "verified."
            ),
            source="live",
            metrics=metrics,
            findings=[
                (
                    f"Rollback target '{rollback_version}' is "
                    "recorded in the release."
                ),
                (
                    f"Kubernetes Deployment '{deployment_name}' "
                    "exists."
                ),
                (
                    "No previous Kubernetes rollout revision was "
                    "verified."
                ),
                (
                    "Container registry/image availability is not "
                    "verified because no registry integration is "
                    "configured."
                ),
            ],
        )

    # ------------------------------------------------------------------
    # Kubernetes/API error
    # ------------------------------------------------------------------

    except Exception as exc:
        return EvidenceEnvelope(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary=(
                "Live rollback readiness evidence could not "
                "be retrieved."
            ),
            source="unavailable",
            metrics={
                "previous_version_available": True,
                "rollback_version": rollback_version,
                "rollback_artifact_verified": False,
                "kubernetes_deployment_found": False,
                "previous_revision_available": False,
            },
            findings=[
                f"Kubernetes rollback inspection failed: {exc}"
            ],
        )