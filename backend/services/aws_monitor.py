"""
PRODPROOF — AWS production monitoring.

Reads live EC2 and CloudWatch evidence for the production context engine.
Only reports metrics that AWS can actually provide.
"""

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Any

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from config import get_settings


def _clients():
    settings = get_settings()

    if not settings.aws_enabled:
        raise RuntimeError("AWS integration is disabled.")

    if not settings.aws_region:
        raise RuntimeError("AWS_REGION is not configured.")

    session_kwargs: dict[str, Any] = {
        "region_name": settings.aws_region,
    }

    if settings.aws_access_key_id and settings.aws_secret_access_key:
        session_kwargs["aws_access_key_id"] = settings.aws_access_key_id
        session_kwargs["aws_secret_access_key"] = settings.aws_secret_access_key

    session = boto3.Session(**session_kwargs)

    return (
        session.client("ec2"),
        session.client("cloudwatch"),
    )


def _get_running_instances(ec2_client) -> list[dict[str, Any]]:
    response = ec2_client.describe_instances(
        Filters=[
            {
                "Name": "instance-state-name",
                "Values": ["running"],
            }
        ]
    )

    instances: list[dict[str, Any]] = []

    for reservation in response.get("Reservations", []):
        for instance in reservation.get("Instances", []):
            instances.append(
                {
                    "instance_id": instance.get("InstanceId"),
                    "instance_type": instance.get("InstanceType"),
                    "private_ip": instance.get("PrivateIpAddress"),
                    "availability_zone": (
                        instance.get("Placement", {}).get("AvailabilityZone")
                    ),
                }
            )

    return instances


def _get_cpu_utilization(
    cloudwatch_client,
    instance_ids: list[str],
) -> float | None:
    if not instance_ids:
        return None

    end_time = datetime.now(timezone.utc)
    start_time = end_time - timedelta(minutes=15)

    values: list[float] = []

    for instance_id in instance_ids:
        response = cloudwatch_client.get_metric_statistics(
            Namespace="AWS/EC2",
            MetricName="CPUUtilization",
            Dimensions=[
                {
                    "Name": "InstanceId",
                    "Value": instance_id,
                }
            ],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=["Average"],
            Unit="Percent",
        )

        datapoints = response.get("Datapoints", [])

        for datapoint in datapoints:
            average_value = datapoint.get("Average")
            if average_value is not None:
                values.append(float(average_value))

    if not values:
        return None

    return round(mean(values), 2)


def get_aws_production_context() -> dict[str, Any]:
    """
    Return live EC2 + CloudWatch production evidence.

    The function deliberately does not invent memory, DB, disk, or traffic
    values because those metrics require additional monitoring sources.
    """

    try:
        ec2_client, cloudwatch_client = _clients()

        instances = _get_running_instances(ec2_client)

        instance_ids = [
            item["instance_id"]
            for item in instances
            if item.get("instance_id")
        ]

        cpu_utilization = _get_cpu_utilization(
            cloudwatch_client,
            instance_ids,
        )

        metrics: dict[str, Any] = {
            "ec2_instance_count": len(instances),
            "running_instance_count": len(instances),
            "instance_ids": instance_ids,
        }

        findings: list[str] = []

        if not instances:
            findings.append("No running EC2 instances were found.")

        if cpu_utilization is not None:
            metrics["cpu_utilization_pct"] = cpu_utilization

            if cpu_utilization >= 85:
                findings.append(
                    f"Average EC2 CPU utilization is high: {cpu_utilization}%."
                )
            elif cpu_utilization >= 70:
                findings.append(
                    f"Average EC2 CPU utilization is elevated: {cpu_utilization}%."
                )
        else:
            findings.append(
                "CloudWatch returned no recent EC2 CPU datapoints."
            )

        return {
            "status": "WARNING" if findings else "PASS",
            "summary": (
                "Live AWS EC2 production context collected from EC2 and "
                "CloudWatch."
            ),
            "source": "live",
            "metrics": metrics,
            "findings": findings
            or ["AWS production metrics are within the configured thresholds."],
        }

    except (ClientError, BotoCoreError) as exc:
        return {
            "status": "UNAVAILABLE",
            "summary": "AWS production context could not be retrieved.",
            "source": "live",
            "metrics": {},
            "findings": [f"AWS API error: {exc}"],
        }
    except Exception as exc:
        return {
            "status": "UNAVAILABLE",
            "summary": "AWS production context could not be retrieved.",
            "source": "live",
            "metrics": {},
            "findings": [f"AWS integration error: {exc}"],
        }