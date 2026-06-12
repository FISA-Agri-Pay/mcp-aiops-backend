from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping

from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.alertmanager_agent.schemas import (
    AlertmanagerSreAlertContext,
    AlertmanagerSrePlanResult,
)
from aiops_platform.infra_rca.schemas import AlertmanagerAlert, AlertmanagerWebhookRequest


class AlertmanagerSreAgentService:
    def __init__(self, planner: RuleBasedAgentPlanner | None = None) -> None:
        self._planner = planner or RuleBasedAgentPlanner()

    def plan_from_webhook(
        self,
        request: AlertmanagerWebhookRequest,
        *,
        actor: str = "alertmanager",
    ) -> AlertmanagerSrePlanResult:
        alert = select_firing_alert(request)
        if alert is None:
            return AlertmanagerSrePlanResult(
                status="SKIPPED",
                receiver=request.receiver,
                actor=actor,
                skipped_reason="No firing alerts were included in the Alertmanager webhook.",
            )

        labels = merge_values(request.commonLabels, alert.labels)
        annotations = merge_values(request.commonAnnotations, alert.annotations)
        context = build_alert_context(alert=alert, labels=labels, annotations=annotations)
        incident_key = build_incident_key(context)
        intent = infer_sre_intent(context=context, labels=labels, annotations=annotations)
        message = build_sre_analysis_message(intent=intent, context=context)
        plan = self._planner.plan(
            chat_type="sre_copilot",
            message=message,
            user_id=actor,
        )

        return AlertmanagerSrePlanResult(
            status="PLANNED",
            receiver=request.receiver,
            actor=actor,
            incident_key=incident_key,
            intent=plan.intent,
            capability=plan.capability,
            analysis_message=message,
            alert=context,
            planned_tools=plan.tool_plans,
        )


def select_firing_alert(request: AlertmanagerWebhookRequest) -> AlertmanagerAlert | None:
    for alert in request.alerts:
        if alert.status.strip().lower() == "firing":
            return alert
    if request.status == "firing":
        return request.alerts[0]
    return None


def merge_values(
    base: Mapping[str, str],
    override: Mapping[str, str],
) -> dict[str, str]:
    merged = {str(key): str(value) for key, value in base.items()}
    merged.update({str(key): str(value) for key, value in override.items()})
    return merged


def build_alert_context(
    *,
    alert: AlertmanagerAlert,
    labels: Mapping[str, str],
    annotations: Mapping[str, str],
) -> AlertmanagerSreAlertContext:
    alert_name = first_present(labels, "alertname", "alert", "name") or "unknown_alert"
    service_name = first_present(labels, "service", "service_name", "app", "application")
    workload = first_present(labels, "workload", "deployment", "statefulset", "daemonset", "job")
    return AlertmanagerSreAlertContext(
        alert_name=alert_name,
        status=alert.status.strip().lower() or "firing",
        severity=first_present(labels, "severity", "priority"),
        cluster=first_present(labels, "cluster", "cluster_name", "source"),
        namespace=first_present(labels, "namespace", "kubernetes_namespace"),
        service_name=service_name or workload,
        workload=workload or service_name,
        pod=first_present(labels, "pod", "pod_name"),
        fingerprint=normalized_optional(alert.fingerprint) or fingerprint_from_labels(labels),
        starts_at=alert.startsAt,
        summary=first_present(annotations, "summary", "message"),
        description=first_present(annotations, "description", "runbook", "details"),
    )


def first_present(values: Mapping[str, str], *keys: str) -> str | None:
    lowered = {key.lower(): value for key, value in values.items()}
    for key in keys:
        value = normalized_optional(lowered.get(key.lower()))
        if value is not None:
            return value
    return None


def normalized_optional(value: object) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def fingerprint_from_labels(labels: Mapping[str, str]) -> str:
    stable = "|".join(f"{key}={labels[key]}" for key in sorted(labels))
    return hashlib.sha256(stable.encode("utf-8")).hexdigest()[:16]


def build_incident_key(context: AlertmanagerSreAlertContext) -> str:
    parts = [
        "alertmanager",
        context.alert_name,
        context.cluster or "unknown-cluster",
        context.namespace or "unknown-namespace",
        context.service_name or context.workload or context.pod or "unknown-service",
        context.severity or "unknown-severity",
    ]
    return ":".join(slugify(part) for part in parts)


def slugify(value: str) -> str:
    lowered = value.strip().lower()
    slug = re.sub(r"[^a-z0-9_.-]+", "-", lowered)
    return slug.strip("-") or "unknown"


def infer_sre_intent(
    *,
    context: AlertmanagerSreAlertContext,
    labels: Mapping[str, str],
    annotations: Mapping[str, str],
) -> str:
    signal = " ".join(
        value
        for value in [
            context.alert_name,
            context.service_name or "",
            context.workload or "",
            context.pod or "",
            context.summary or "",
            context.description or "",
            " ".join(labels.values()),
            " ".join(annotations.values()),
        ]
        if value
    ).lower()

    if "checkout" in signal and any(term in signal for term in ("500", "5xx", "http")):
        return "checkout_500"
    if "sqs" in signal and any(
        term in signal for term in ("publish", "producer", "send", "발행")
    ):
        return "sqs_publish_failure"
    if any(term in signal for term in ("sqs", "queue", "dlq")) and any(
        term in signal
        for term in ("consume", "consumer", "listener", "lag", "dlq", "messagesvisible", "소비")
    ):
        return "sqs_consume_failure"
    if any(term in signal for term in ("pin", "핀")) and any(
        term in signal for term in ("verification", "verified", "event", "missing", "미반영", "검증")
    ):
        return "pin_verification_missing"
    if any(
        term in signal
        for term in ("cloudfront", "alb", "targetunhealthy", "target unhealthy", "ingress", "metallb")
    ):
        return "routing_failure"
    if any(
        term in signal
        for term in ("crashloop", "crash loop", "imagepullbackoff", "oomkilled", "pod")
    ):
        return "pod_crashloop"
    if any(
        term in signal
        for term in ("hikari", "hikaricp", "jdbc", "postgres", "database", "connection pool")
    ):
        return "db_hikaricp_issue"
    return "general_incident"


def build_sre_analysis_message(*, intent: str, context: AlertmanagerSreAlertContext) -> str:
    intent_phrases = {
        "checkout_500": "checkout 500 장애 분석",
        "sqs_publish_failure": "SQS 발행 실패 장애 분석",
        "sqs_consume_failure": "SQS 소비 실패 DLQ lag 장애 분석",
        "pin_verification_missing": "PIN 검증 이벤트 미반영 장애 분석",
        "routing_failure": "CloudFront ALB EKS on-prem MetalLB 라우팅 실패 분석",
        "pod_crashloop": "pod CrashLoopBackOff 재시작 장애 분석",
        "db_hikaricp_issue": "DB HikariCP connection pool 장애 분석",
        "general_incident": "on-prem AWS Kubernetes SRE 일반 장애 분석",
    }
    details = [
        intent_phrases.get(intent, intent_phrases["general_incident"]),
        f"alertname={context.alert_name}",
    ]
    for key, value in (
        ("cluster", context.cluster),
        ("namespace", context.namespace),
        ("service", context.service_name),
        ("workload", context.workload),
        ("severity", context.severity),
    ):
        if value:
            details.append(f"{key}={value}")
    if context.pod:
        details.append(f"pod {context.pod}")
    if context.summary:
        details.append(f"summary={context.summary}")
    return " ".join(details)
