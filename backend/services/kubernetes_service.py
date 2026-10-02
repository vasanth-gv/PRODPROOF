"""
PRODPROOF — Kubernetes Readiness Service (Phase 7).

Live Kubernetes readiness evaluation.

Checks:
- cluster connectivity
- ready / schedulable nodes
- node allocatable CPU and memory
- current pod resource requests
- release requested replicas
- release CPU / memory requirement
- actual Deployment state
- actual resource requests / limits
- readiness probe
- liveness probe

Important:
No deployment/probe success is fabricated.

If the release workload is not deployed in Kubernetes, PRODPROOF reports
that the live workload evidence is not available instead of pretending
probes or limits exist.
"""

from __future__ import annotations

import math
import re
from typing import Any

from config import get_settings
from schemas.evidence import EvidenceEnvelope
from utils.status import EvidenceStatus


# ---------------------------------------------------------------------------
# Quantity parsing
# ---------------------------------------------------------------------------

def _parse_cpu_millicores(value: str | int | float | None) -> float:
    """
    Convert Kubernetes CPU quantity to millicores.

    Examples:
        500m -> 500
        1    -> 1000
        12   -> 12000
    """
    if value is None:
        return 0.0

    text = str(value).strip()

    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(n|u|m)?",
        text,
    )

    if not match:
        raise ValueError(f"Unsupported CPU quantity: {value}")

    number = float(match.group(1))
    suffix = match.group(2) or ""

    if suffix == "n":
        return number / 1_000_000

    if suffix == "u":
        return number / 1_000

    if suffix == "m":
        return number

    return number * 1000


_MEMORY_MULTIPLIERS = {
    "Ki": 1024,
    "Mi": 1024**2,
    "Gi": 1024**3,
    "Ti": 1024**4,
    "Pi": 1024**5,
    "Ei": 1024**6,
    "K": 1000,
    "M": 1000**2,
    "G": 1000**3,
    "T": 1000**4,
    "P": 1000**5,
    "E": 1000**6,
    "": 1,
}


def _parse_memory_bytes(value: str | int | float | None) -> float:
    """
    Convert Kubernetes memory quantity into bytes.
    """
    if value is None:
        return 0.0

    text = str(value).strip()

    match = re.fullmatch(
        r"([0-9]+(?:\.[0-9]+)?)(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?",
        text,
    )

    if not match:
        raise ValueError(f"Unsupported memory quantity: {value}")

    number = float(match.group(1))
    suffix = match.group(2) or ""

    return number * _MEMORY_MULTIPLIERS[suffix]


def _bytes_to_mib(value: float) -> float:
    return value / (1024**2)


# ---------------------------------------------------------------------------
# Node helpers
# ---------------------------------------------------------------------------

def _node_is_ready(node) -> bool:
    conditions = node.status.conditions or []

    for condition in conditions:
        if condition.type == "Ready":
            return condition.status == "True"

    return False


def _node_has_blocking_taint(node) -> bool:
    """
    Exclude nodes with blocking taints for a normal release pod.
    """
    taints = node.spec.taints or []

    for taint in taints:
        if taint.effect in {"NoSchedule", "NoExecute"}:
            return True

    return False


# ---------------------------------------------------------------------------
# Pod resource helpers
# ---------------------------------------------------------------------------

def _container_requests(pod) -> tuple[float, float]:
    """
    Return effective CPU and memory requests for a pod.

    Safely handles resources=None and requests=None.
    """
    regular_cpu = 0.0
    regular_memory = 0.0

    for container in pod.spec.containers or []:
        resources = container.resources

        if resources is None:
            requests = {}
        else:
            requests = resources.requests or {}

        regular_cpu += _parse_cpu_millicores(
            requests.get("cpu")
        )

        regular_memory += _parse_memory_bytes(
            requests.get("memory")
        )

    init_cpu = 0.0
    init_memory = 0.0

    for container in pod.spec.init_containers or []:
        resources = container.resources

        if resources is None:
            requests = {}
        else:
            requests = resources.requests or {}

        init_cpu = max(
            init_cpu,
            _parse_cpu_millicores(
                requests.get("cpu")
            ),
        )

        init_memory = max(
            init_memory,
            _parse_memory_bytes(
                requests.get("memory")
            ),
        )

    cpu_request = max(
        regular_cpu,
        init_cpu,
    )

    memory_request = max(
        regular_memory,
        init_memory,
    )

    overhead = getattr(
        pod.spec,
        "overhead",
        None,
    ) or {}

    cpu_request += _parse_cpu_millicores(
        overhead.get("cpu")
    )

    memory_request += _parse_memory_bytes(
        overhead.get("memory")
    )

    return cpu_request, memory_request


# ---------------------------------------------------------------------------
# Deployment helpers
# ---------------------------------------------------------------------------

def _deployment_matches_release(
    deployment: Any,
    release: Any,
) -> bool:
    """
    Decide whether a Kubernetes Deployment belongs to this release.

    Matching order:
    1. deployment name == release.application
    2. common app labels == release.application
    3. release docker image name appears in a container image
    """
    application = release.application if release else None

    if not application:
        return False

    if deployment.metadata.name == application:
        return True

    labels = deployment.metadata.labels or {}

    label_values = [
        labels.get("app"),
        labels.get("application"),
        labels.get("name"),
        labels.get("app.kubernetes.io/name"),
    ]

    if application in label_values:
        return True

    expected_image = release.docker_image if release else None

    if expected_image:
        expected_image_name = expected_image.split(":")[0]

        for container in deployment.spec.template.spec.containers or []:
            image = container.image or ""
            image_name = image.split(":")[0]

            if image == expected_image or image_name == expected_image_name:
                return True

    return False


def _find_release_deployment(
    deployments: list[Any],
    release: Any,
) -> Any | None:
    matches = [
        deployment
        for deployment in deployments
        if _deployment_matches_release(
            deployment,
            release,
        )
    ]

    if not matches:
        return None

    # Prefer exact deployment name match.
    if release and release.application:
        for deployment in matches:
            if deployment.metadata.name == release.application:
                return deployment

    return matches[0]


def _deployment_resource_summary(
    deployment: Any,
) -> dict[str, float | bool]:
    """
    Aggregate CPU/memory requests and limits across containers.

    Values represent one pod/replica.
    """
    cpu_request = 0.0
    memory_request = 0.0

    cpu_limit = 0.0
    memory_limit = 0.0

    all_cpu_limits = True
    all_memory_limits = True

    containers = deployment.spec.template.spec.containers or []

    if not containers:
        all_cpu_limits = False
        all_memory_limits = False

    for container in containers:
        resources = container.resources

        if resources is None:
            requests = {}
            limits = {}
        else:
            requests = resources.requests or {}
            limits = resources.limits or {}

        cpu_request += _parse_cpu_millicores(
            requests.get("cpu")
        )

        memory_request += _parse_memory_bytes(
            requests.get("memory")
        )

        if limits.get("cpu") is None:
            all_cpu_limits = False
        else:
            cpu_limit += _parse_cpu_millicores(
                limits.get("cpu")
            )

        if limits.get("memory") is None:
            all_memory_limits = False
        else:
            memory_limit += _parse_memory_bytes(
                limits.get("memory")
            )

    return {
        "cpu_request_millicores": cpu_request,
        "memory_request_mib": _bytes_to_mib(
            memory_request
        ),
        "cpu_limit_millicores": cpu_limit,
        "memory_limit_mib": _bytes_to_mib(
            memory_limit
        ),
        "all_cpu_limits_configured": all_cpu_limits,
        "all_memory_limits_configured": all_memory_limits,
    }


def _deployment_probe_summary(
    deployment: Any,
) -> dict[str, bool]:
    """
    Check whether every application container has both probes.
    """
    containers = deployment.spec.template.spec.containers or []

    if not containers:
        return {
            "readiness_probe_configured": False,
            "liveness_probe_configured": False,
        }

    readiness_ok = all(
        container.readiness_probe is not None
        for container in containers
    )

    liveness_ok = all(
        container.liveness_probe is not None
        for container in containers
    )

    return {
        "readiness_probe_configured": readiness_ok,
        "liveness_probe_configured": liveness_ok,
    }


# ---------------------------------------------------------------------------
# Main readiness evaluation
# ---------------------------------------------------------------------------

def get_kubernetes_readiness(release=None) -> EvidenceEnvelope:
    settings = get_settings()

    # -----------------------------------------------------------------------
    # Disabled / demo mode
    # -----------------------------------------------------------------------

    if not settings.kubernetes_enabled or not settings.kube_config_path:
        if settings.demo_mode:
            requested = (
                release.expected_replicas
                if release and release.expected_replicas
                else 5
            )

            available_capacity = 3

            if requested > available_capacity:
                status = EvidenceStatus.FAIL.value

                findings = [
                    (
                        f"Requested replicas ({requested}) exceed "
                        f"available cluster capacity ({available_capacity})."
                    )
                ]
            else:
                status = EvidenceStatus.PASS.value

                findings = [
                    "Cluster has sufficient capacity for the requested replicas."
                ]

            return EvidenceEnvelope(
                status=status,
                summary="Demo Kubernetes readiness (Kubernetes not configured).",
                source="demo",
                metrics={
                    "requested_replicas": requested,
                    "available_capacity": available_capacity,
                    "readiness_probe_configured": True,
                    "liveness_probe_configured": True,
                },
                findings=findings,
            )

        return EvidenceEnvelope(
            status=EvidenceStatus.NOT_CONFIGURED.value,
            summary="Kubernetes integration is not configured.",
            source="not_configured",
            metrics={},
            findings=[],
        )

    try:
        from kubernetes import client, config as kube_config

        kube_config.load_kube_config(
            config_file=settings.kube_config_path,
            context=settings.kube_context,
        )

        core_api = client.CoreV1Api()
        apps_api = client.AppsV1Api()

        nodes = core_api.list_node().items
        pods = core_api.list_pod_for_all_namespaces().items
        deployments = apps_api.list_deployment_for_all_namespaces().items

        # -------------------------------------------------------------------
        # Node accounting
        # -------------------------------------------------------------------

        node_stats: dict[str, dict[str, float]] = {}

        ready_node_count = 0
        schedulable_node_count = 0

        total_allocatable_cpu = 0.0
        total_allocatable_memory = 0.0

        for node in nodes:
            node_name = node.metadata.name

            ready = _node_is_ready(node)

            allocatable = node.status.allocatable or {}

            alloc_cpu = _parse_cpu_millicores(
                allocatable.get("cpu")
            )

            alloc_memory = _parse_memory_bytes(
                allocatable.get("memory")
            )

            if ready:
                ready_node_count += 1

            blocked = (
                node.spec.unschedulable is True
                or _node_has_blocking_taint(node)
            )

            if ready and not blocked:
                schedulable_node_count += 1

            node_stats[node_name] = {
                "allocatable_cpu": alloc_cpu,
                "allocatable_memory": alloc_memory,
                "requested_cpu": 0.0,
                "requested_memory": 0.0,
                "schedulable": (
                    1.0
                    if ready and not blocked
                    else 0.0
                ),
            }

            total_allocatable_cpu += alloc_cpu
            total_allocatable_memory += alloc_memory

        # -------------------------------------------------------------------
        # Existing pod resource requests
        # -------------------------------------------------------------------

        for pod in pods:
            node_name = pod.spec.node_name

            if not node_name:
                continue

            if node_name not in node_stats:
                continue

            if pod.status.phase in {
                "Succeeded",
                "Failed",
            }:
                continue

            cpu_request, memory_request = _container_requests(
                pod
            )

            node_stats[node_name]["requested_cpu"] += cpu_request
            node_stats[node_name]["requested_memory"] += memory_request

        # -------------------------------------------------------------------
        # Release requirements
        # -------------------------------------------------------------------

        requested_replicas = (
            int(release.expected_replicas)
            if release is not None
            and release.expected_replicas
            else None
        )

        requested_cpu_millicores = (
            int(release.cpu_millicores)
            if release is not None
            and release.cpu_millicores
            else None
        )

        requested_memory_mb = (
            int(release.memory_mb)
            if release is not None
            and release.memory_mb
            else None
        )

        requested_memory_mib = (
            float(requested_memory_mb)
            if requested_memory_mb is not None
            else None
        )

        # -------------------------------------------------------------------
        # Capacity calculation
        # -------------------------------------------------------------------

        total_free_schedulable_cpu = 0.0
        total_free_schedulable_memory = 0.0

        schedulable_replica_capacity = 0

        node_capacity_details: list[dict] = []

        for node_name, stats in node_stats.items():
            if not bool(stats["schedulable"]):
                continue

            free_cpu = max(
                stats["allocatable_cpu"]
                - stats["requested_cpu"],
                0.0,
            )

            free_memory = max(
                stats["allocatable_memory"]
                - stats["requested_memory"],
                0.0,
            )

            total_free_schedulable_cpu += free_cpu
            total_free_schedulable_memory += free_memory

            replica_capacity = None

            if (
                requested_cpu_millicores
                and requested_cpu_millicores > 0
                and requested_memory_mib
                and requested_memory_mib > 0
            ):
                cpu_capacity = math.floor(
                    free_cpu
                    / requested_cpu_millicores
                )

                memory_capacity = math.floor(
                    _bytes_to_mib(free_memory)
                    / requested_memory_mib
                )

                replica_capacity = max(
                    min(
                        cpu_capacity,
                        memory_capacity,
                    ),
                    0,
                )

                schedulable_replica_capacity += (
                    replica_capacity
                )

            node_capacity_details.append(
                {
                    "node": node_name,
                    "free_cpu_millicores": round(
                        free_cpu,
                        2,
                    ),
                    "free_memory_mib": round(
                        _bytes_to_mib(free_memory),
                        2,
                    ),
                    "replica_capacity": replica_capacity,
                }
            )

        # -------------------------------------------------------------------
        # Actual Deployment inspection
        # -------------------------------------------------------------------

        deployment = _find_release_deployment(
            deployments,
            release,
        )

        deployment_found = deployment is not None

        actual_desired_replicas = None
        actual_available_replicas = None
        actual_ready_replicas = None
        actual_updated_replicas = None

        actual_cpu_request_millicores = None
        actual_memory_request_mib = None
        actual_cpu_limit_millicores = None
        actual_memory_limit_mib = None

        cpu_limits_configured = False
        memory_limits_configured = False

        readiness_probe_configured = False
        liveness_probe_configured = False

        deployment_namespace = None
        deployment_name = None

        if deployment_found:
            deployment_name = deployment.metadata.name
            deployment_namespace = deployment.metadata.namespace

            status_obj = deployment.status

            actual_desired_replicas = (
                deployment.spec.replicas
            )

            actual_available_replicas = (
                status_obj.available_replicas or 0
            )

            actual_ready_replicas = (
                status_obj.ready_replicas or 0
            )

            actual_updated_replicas = (
                status_obj.updated_replicas or 0
            )

            resource_summary = (
                _deployment_resource_summary(
                    deployment
                )
            )

            actual_cpu_request_millicores = round(
                float(
                    resource_summary[
                        "cpu_request_millicores"
                    ]
                ),
                2,
            )

            actual_memory_request_mib = round(
                float(
                    resource_summary[
                        "memory_request_mib"
                    ]
                ),
                2,
            )

            actual_cpu_limit_millicores = round(
                float(
                    resource_summary[
                        "cpu_limit_millicores"
                    ]
                ),
                2,
            )

            actual_memory_limit_mib = round(
                float(
                    resource_summary[
                        "memory_limit_mib"
                    ]
                ),
                2,
            )

            cpu_limits_configured = bool(
                resource_summary[
                    "all_cpu_limits_configured"
                ]
            )

            memory_limits_configured = bool(
                resource_summary[
                    "all_memory_limits_configured"
                ]
            )

            probe_summary = _deployment_probe_summary(
                deployment
            )

            readiness_probe_configured = probe_summary[
                "readiness_probe_configured"
            ]

            liveness_probe_configured = probe_summary[
                "liveness_probe_configured"
            ]

        # -------------------------------------------------------------------
        # Findings
        # -------------------------------------------------------------------

        findings: list[str] = []

        if requested_replicas is None:
            findings.append(
                "Release replica requirement is not configured."
            )

        if requested_cpu_millicores is None:
            findings.append(
                "Release CPU request is not configured."
            )

        if requested_memory_mb is None:
            findings.append(
                "Release memory request is not configured."
            )

        capacity_ok = (
            requested_replicas is not None
            and schedulable_replica_capacity
            >= requested_replicas
        )

        if capacity_ok:
            findings.append(
                (
                    f"Current schedulable capacity is sufficient "
                    f"for {requested_replicas} requested replica(s)."
                )
            )
        elif requested_replicas is not None:
            findings.append(
                (
                    f"Requested replicas ({requested_replicas}) "
                    f"exceed current schedulable replica capacity "
                    f"({schedulable_replica_capacity})."
                )
            )

        # -------------------------------------------------------------------
        # Deployment evidence
        # -------------------------------------------------------------------

        if not deployment_found:
            findings.append(
                (
                    f"No live Kubernetes Deployment was found for "
                    f"release application '{release.application if release else 'unknown'}'. "
                    "Actual probes and resource limits cannot be verified."
                )
            )

        else:
            if (
                requested_replicas is not None
                and actual_desired_replicas
                != requested_replicas
            ):
                findings.append(
                    (
                        f"Deployment replicas ({actual_desired_replicas}) "
                        f"do not match release requirement "
                        f"({requested_replicas})."
                    )
                )

            if actual_available_replicas < (
                requested_replicas or 0
            ):
                findings.append(
                    (
                        f"Deployment currently has "
                        f"{actual_available_replicas} available "
                        f"replica(s) out of {requested_replicas} required."
                    )
                )

            if not readiness_probe_configured:
                findings.append(
                    "Readiness probe is not configured on the live Deployment."
                )

            if not liveness_probe_configured:
                findings.append(
                    "Liveness probe is not configured on the live Deployment."
                )

            if not cpu_limits_configured:
                findings.append(
                    "CPU limits are not configured on all live Deployment containers."
                )

            if not memory_limits_configured:
                findings.append(
                    "Memory limits are not configured on all live Deployment containers."
                )

        # -------------------------------------------------------------------
        # Final status
        # -------------------------------------------------------------------

        requirements_complete = (
            requested_replicas is not None
            and requested_cpu_millicores is not None
            and requested_memory_mb is not None
        )

        if requirements_complete and not capacity_ok:
            status = EvidenceStatus.FAIL.value

        elif (
            requirements_complete
            and capacity_ok
            and deployment_found
            and actual_available_replicas is not None
            and actual_available_replicas
            >= requested_replicas
            and actual_desired_replicas
            == requested_replicas
            and readiness_probe_configured
            and liveness_probe_configured
            and cpu_limits_configured
            and memory_limits_configured
        ):
            status = EvidenceStatus.PASS.value

        else:
            status = EvidenceStatus.WARNING.value

        return EvidenceEnvelope(
            status=status,
            summary=(
                "Live Kubernetes readiness evaluated from cluster capacity "
                "and workload deployment evidence."
            ),
            source="live",
            metrics={
                "node_count": len(nodes),
                "ready_node_count": ready_node_count,
                "schedulable_node_count": schedulable_node_count,
                "total_allocatable_cpu_millicores": round(
                    total_allocatable_cpu,
                    2,
                ),
                "total_allocatable_memory_mib": round(
                    _bytes_to_mib(
                        total_allocatable_memory
                    ),
                    2,
                ),
                "free_schedulable_cpu_millicores": round(
                    total_free_schedulable_cpu,
                    2,
                ),
                "free_schedulable_memory_mib": round(
                    _bytes_to_mib(
                        total_free_schedulable_memory
                    ),
                    2,
                ),
                "requested_replicas": requested_replicas,
                "requested_cpu_millicores": requested_cpu_millicores,
                "requested_memory_mb": requested_memory_mb,
                "schedulable_replica_capacity": (
                    schedulable_replica_capacity
                ),
                "deployment_found": deployment_found,
                "deployment_name": deployment_name,
                "deployment_namespace": deployment_namespace,
                "actual_desired_replicas": (
                    actual_desired_replicas
                ),
                "actual_available_replicas": (
                    actual_available_replicas
                ),
                "actual_ready_replicas": (
                    actual_ready_replicas
                ),
                "actual_updated_replicas": (
                    actual_updated_replicas
                ),
                "actual_cpu_request_millicores": (
                    actual_cpu_request_millicores
                ),
                "actual_memory_request_mib": (
                    actual_memory_request_mib
                ),
                "actual_cpu_limit_millicores": (
                    actual_cpu_limit_millicores
                ),
                "actual_memory_limit_mib": (
                    actual_memory_limit_mib
                ),
                "cpu_limits_configured": (
                    cpu_limits_configured
                ),
                "memory_limits_configured": (
                    memory_limits_configured
                ),
                "readiness_probe_configured": (
                    readiness_probe_configured
                ),
                "liveness_probe_configured": (
                    liveness_probe_configured
                ),
                "node_capacity_details": (
                    node_capacity_details
                ),
            },
            findings=findings,
        )

    except Exception as exc:
        return EvidenceEnvelope(
            status=EvidenceStatus.UNAVAILABLE.value,
            summary=(
                "Kubernetes is configured but could not be evaluated."
            ),
            source="live",
            metrics={},
            findings=[str(exc)],
        )