from __future__ import annotations

import logging
import math
from datetime import UTC, datetime
from typing import Protocol

from aiops_platform.core.config import Settings, settings
from aiops_platform.infraops.clients import KubernetesClient

logger = logging.getLogger(__name__)


class RcaJobRunner(Protocol):
    def schedule_due_rca_job(self, *, job_id: str, scheduled_at: datetime) -> None:
        pass


class NoopRcaJobRunner:
    def schedule_due_rca_job(self, *, job_id: str, scheduled_at: datetime) -> None:
        return None


class KubernetesRcaJobRunner:
    def __init__(
        self,
        *,
        kubernetes_client: KubernetesClient,
        namespace: str,
        image: str,
        service_name: str,
        limit: int,
        ttl_seconds_after_finished: int,
        active_deadline_buffer_seconds: int,
    ) -> None:
        if not image.strip():
            raise ValueError("RCA job runner image is required.")
        self._kubernetes_client = kubernetes_client
        self._namespace = namespace
        self._image = image
        self._service_name = service_name
        self._limit = limit
        self._ttl_seconds_after_finished = ttl_seconds_after_finished
        self._active_deadline_buffer_seconds = active_deadline_buffer_seconds

    def schedule_due_rca_job(self, *, job_id: str, scheduled_at: datetime) -> None:
        manifest = build_rca_job_manifest(
            job_id=job_id,
            scheduled_at=scheduled_at,
            namespace=self._namespace,
            image=self._image,
            service_name=self._service_name,
            limit=self._limit,
            ttl_seconds_after_finished=self._ttl_seconds_after_finished,
            active_deadline_buffer_seconds=self._active_deadline_buffer_seconds,
        )
        self._kubernetes_client.create_job(self._namespace, manifest)
        logger.info("Scheduled RCA Kubernetes Job for job_id=%s.", job_id)


def create_rca_job_runner(
    current_settings: Settings = settings,
) -> RcaJobRunner:
    if not current_settings.rca_job_runner_enabled:
        return NoopRcaJobRunner()
    return KubernetesRcaJobRunner(
        kubernetes_client=KubernetesClient(
            current_settings.kubernetes_api_base_url,
            bearer_token=current_settings.kubernetes_bearer_token,
            bearer_token_file=current_settings.kubernetes_bearer_token_file,
            ca_cert_file=current_settings.kubernetes_ca_cert_file,
            timeout_seconds=current_settings.kubernetes_timeout_seconds,
        ),
        namespace=current_settings.rca_job_runner_namespace,
        image=current_settings.rca_job_runner_image,
        service_name=current_settings.rca_job_runner_service_name,
        limit=current_settings.rca_job_runner_limit,
        ttl_seconds_after_finished=current_settings.rca_job_runner_ttl_seconds_after_finished,
        active_deadline_buffer_seconds=(
            current_settings.rca_job_runner_active_deadline_buffer_seconds
        ),
    )


def build_rca_job_manifest(
    *,
    job_id: str,
    scheduled_at: datetime,
    namespace: str,
    image: str,
    service_name: str,
    limit: int,
    ttl_seconds_after_finished: int,
    active_deadline_buffer_seconds: int,
) -> dict[str, object]:
    scheduled_at_utc = normalize_utc(scheduled_at)
    delay_seconds = max(0, (scheduled_at_utc - datetime.now(UTC)).total_seconds())
    active_deadline_seconds = max(60, math.ceil(delay_seconds) + active_deadline_buffer_seconds)
    endpoint = (
        f"http://{service_name}.{namespace}.svc.cluster.local"
        f"/rca/jobs/run-due?limit={limit}"
    )
    script = build_runner_script(
        scheduled_at=scheduled_at_utc.isoformat(),
        endpoint=endpoint,
    )
    return {
        "apiVersion": "batch/v1",
        "kind": "Job",
        "metadata": {
            "name": build_job_name(job_id),
            "namespace": namespace,
            "labels": {
                "app.kubernetes.io/name": "mcp-aiops-rca-due-job-runner",
                "app.kubernetes.io/part-of": "aiops-platform",
                "aiops.platform/rca-job-id": job_id,
            },
        },
        "spec": {
            "backoffLimit": 1,
            "ttlSecondsAfterFinished": ttl_seconds_after_finished,
            "activeDeadlineSeconds": active_deadline_seconds,
            "template": {
                "metadata": {
                    "labels": {
                        "app.kubernetes.io/name": "mcp-aiops-rca-due-job-runner",
                        "app.kubernetes.io/part-of": "aiops-platform",
                        "aiops.platform/rca-job-id": job_id,
                    },
                },
                "spec": {
                    "restartPolicy": "Never",
                    "automountServiceAccountToken": False,
                    "securityContext": {
                        "runAsNonRoot": True,
                        "runAsUser": 10001,
                        "runAsGroup": 10001,
                        "fsGroup": 10001,
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [
                        {
                            "name": "runner",
                            "image": image,
                            "imagePullPolicy": "IfNotPresent",
                            "securityContext": {
                                "allowPrivilegeEscalation": False,
                                "readOnlyRootFilesystem": True,
                                "capabilities": {"drop": ["ALL"]},
                            },
                            "resources": {
                                "requests": {"cpu": "100m", "memory": "128Mi"},
                                "limits": {"cpu": "250m", "memory": "256Mi"},
                            },
                            "command": ["python", "-c", script],
                            "volumeMounts": [{"name": "tmp", "mountPath": "/tmp"}],
                        }
                    ],
                    "volumes": [{"name": "tmp", "emptyDir": {}}],
                },
            },
        },
    }


def build_runner_script(*, scheduled_at: str, endpoint: str) -> str:
    return f"""import datetime
import time
import urllib.request

scheduled_at = datetime.datetime.fromisoformat({scheduled_at!r})
if scheduled_at.tzinfo is None:
    scheduled_at = scheduled_at.replace(tzinfo=datetime.timezone.utc)
delay_seconds = max(
    0,
    (scheduled_at - datetime.datetime.now(datetime.timezone.utc)).total_seconds(),
)
if delay_seconds:
    time.sleep(delay_seconds)
request = urllib.request.Request({endpoint!r}, method="POST")
with urllib.request.urlopen(request, timeout=120) as response:
    print(response.read().decode("utf-8"))
"""


def build_job_name(job_id: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character == "-" else "-"
        for character in job_id.lower()
    ).strip("-")
    return f"mcp-aiops-rca-run-{normalized}"[:63].rstrip("-")


def normalize_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)
