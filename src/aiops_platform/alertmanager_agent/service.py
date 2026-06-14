from __future__ import annotations

import hashlib
import html
import json
import logging
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from aiops_platform.agent.context_bundle import (
    build_incident_context_bundle,
    compact_tool_result,
)
from aiops_platform.agent.dispatcher import McpToolDispatcher, resolve_registered_tool
from aiops_platform.agent.planner import RuleBasedAgentPlanner
from aiops_platform.agent.schemas import AgentToolExecutionResult, AgentToolPlan
from aiops_platform.alertmanager_agent.schemas import (
    AlertmanagerIncidentWindow,
    AlertmanagerSreAlertContext,
    AlertmanagerSreNotificationResult,
    AlertmanagerSrePlanResult,
)
from aiops_platform.alertmanager_agent.slack_delivery import (
    SlackSender,
    SlackWebhookSender,
)
from aiops_platform.core.config import Settings, settings
from aiops_platform.infra_rca.schemas import AlertmanagerAlert, AlertmanagerWebhookRequest
from aiops_platform.llmops.schemas import LlmRunResult
from aiops_platform.llmops.service import LlmOpsService
from aiops_platform.mcp.schemas import McpToolPermission
from aiops_platform.ops_reports.email_delivery import EmailSender, SmtpEmailSender

logger = logging.getLogger(__name__)

LLM_SNAPSHOT_CHAR_BUDGET = 24000
LLM_EVIDENCE_CHAR_BUDGET = 32000
LLM_SECTION_CHAR_BUDGET = 6000
LLM_TOOL_RESULT_LIMIT = 30
LLM_TOPOLOGY_FACT_LIMIT = 10
TOPOLOGY_LLM_TOOLS = {
    "get_topology_snapshot",
    "search_topology_knowledge",
    "get_service_routing_path",
    "get_service_dependency_map",
}
TOPOLOGY_FACT_KEYWORDS = (
    "service-payment",
    "api-payment.dev6.fisa",
    "10.30.2.100",
    "on-prem metallb",
    "onprem metallb",
    "cloudfront",
    "aws alb",
    "aws target group",
    "service-catalog",
    "checkout-requests",
    "primary payment path",
    "direct path",
)
ROUTING_BOUNDARIES = {
    "dns",
    "cloudfront",
    "aws_alb",
    "aws_target_group",
    "vpn_route",
    "onprem_metallb",
    "onprem_ingress",
    "k8s_service",
    "pod",
}
NEXT_INVESTIGATION_PRIORITY = (
    "application logs",
    "distributed traces",
    "recent deployments",
    "DB/HikariCP",
    "downstream dependencies",
)
APPLICATION_SIGNAL_TOOLS = {
    "logs": {"query_multi_cluster_loki", "query_loki", "get_pod_logs"},
    "metrics": {"query_multi_cluster_prometheus", "query_prometheus"},
    "traces": {
        "get_service_trace_summary",
        "search_traces",
        "get_trace_by_id",
        "get_trace_error_spans",
    },
    "deployment_changes": {
        "get_recent_deployments",
        "get_rollout_status",
        "get_argocd_application_status",
        "get_current_image_tags",
    },
    "aws": {"get_sqs_queue_attributes", "get_sqs_dlq_attributes"},
}
APPLICATION_CANDIDATE_LABELS = {
    "postgres_connection_saturation": "PostgreSQL connection saturation",
    "pod_waiting_state": "Kubernetes pod waiting/pending state",
    "db_hikaricp": "DB/HikariCP connection pool issue",
    "sqs_publish": "SQS publish failure",
    "sqs_consume": "SQS consume/DLQ backlog issue",
    "application_error": "Application runtime error or HTTP 5xx",
    "trace_latency": "Downstream latency or trace error",
    "deployment_regression": "Recent deployment regression",
}

SRE_INTENT_BY_ALERT_NAME: dict[str, str] = {
    "checkout500high": "checkout_500",
    "checkout5xxhigh": "checkout_500",
    "checkouthttperrorhigh": "checkout_500",
    "sqsproducererrors": "sqs_publish_failure",
    "sqspublishfailure": "sqs_publish_failure",
    "sqssendmessagefailure": "sqs_publish_failure",
    "sqssendmessageerrors": "sqs_publish_failure",
    "sqsconsumerlaghigh": "sqs_consume_failure",
    "sqsconsumefailure": "sqs_consume_failure",
    "sqsdlqmessagesvisible": "sqs_consume_failure",
    "sqsdlqnotempty": "sqs_consume_failure",
    "pinverificationeventmissing": "pin_verification_missing",
    "pinverificationmissing": "pin_verification_missing",
    "cloudfront5xxhigh": "routing_failure",
    "alb5xxhigh": "routing_failure",
    "albtargetunhealthy": "routing_failure",
    "ingress5xxhigh": "routing_failure",
    "onpremmetallbroutingfailure": "routing_failure",
    "podcrashlooping": "pod_crashloop",
    "podcrashloopbackoff": "pod_crashloop",
    "kubepodcrashlooping": "pod_crashloop",
    "kubepodcontainerwaiting": "pod_crashloop",
    "kubepodcontainerstatuswaitingreason": "pod_crashloop",
    "kubernetespodnothealthy": "pod_crashloop",
    "kubernetespodwaitingproblem": "pod_crashloop",
    "hikaripoolexhausted": "db_hikaricp_issue",
    "hikariconnectionpoolstarvation": "db_hikaricp_issue",
    "dbconnectionfailure": "db_hikaricp_issue",
    "postgresconnectionfailure": "db_hikaricp_issue",
    "postgresqlconnectionsaturationhigh": "db_hikaricp_issue",
    "postgresqldatabasedown": "db_hikaricp_issue",
    "postgresqlexportertargetdown": "db_hikaricp_issue",
    "postgresqlreplicationlaghigh": "db_hikaricp_issue",
    "postgresqllockcounthigh": "db_hikaricp_issue",
    "postgresqlserverhighcpuusage": "db_hikaricp_issue",
    "postgresqlserverrootfilesystemalmostfull": "db_hikaricp_issue",
}

POSTGRES_ALERT_NAMES = {
    "postgresqlconnectionsaturationhigh",
    "postgresqldatabasedown",
    "postgresqlexportertargetdown",
    "postgresqlreplicationlaghigh",
    "postgresqllockcounthigh",
    "postgresqlserverhighcpuusage",
    "postgresqlserverrootfilesystemalmostfull",
    "postgresqlcachehitratiolow",
    "postgresqldeadtupleshigh",
    "postgresqlcheckpointrequestedhigh",
    "postgresqlserverhighmemoryusage",
}
POSTGRES_CONNECTION_SATURATION_ALERT_NAMES = {
    "postgresqlconnectionsaturationhigh",
    "hikaripoolexhausted",
    "hikariconnectionpoolstarvation",
}
KUBERNETES_POD_HEALTH_ALERT_NAMES = {
    "podcrashlooping",
    "podcrashloopbackoff",
    "kubepodcrashlooping",
    "kubepodcontainerwaiting",
    "kubepodcontainerstatuswaitingreason",
    "kubernetespodnothealthy",
    "kubernetespodwaitingproblem",
    "aiopspodpendingtoolong",
    "aiopspodcrashlooping",
}


DEFAULT_INCIDENT_LOOKBACK = timedelta(minutes=15)
LOG_TIME_WINDOW_TOOLS = {
    "query_loki",
    "query_multi_cluster_loki",
}
TRACE_TIME_WINDOW_TOOLS = {
    "search_traces",
    "get_service_trace_summary",
}
OBSERVABILITY_POINT_TIME_TOOLS = {
    "query_prometheus",
    "query_multi_cluster_prometheus",
}


class AlertmanagerSreAgentService:
    def __init__(
        self,
        planner: RuleBasedAgentPlanner | None = None,
        dispatcher: McpToolDispatcher | None = None,
        now_provider: Callable[[], datetime] | None = None,
        llmops_service: LlmOpsService | None = None,
        email_sender: EmailSender | None = None,
        email_recipients: list[str] | None = None,
        slack_sender: SlackSender | None = None,
        app_settings: Settings = settings,
    ) -> None:
        self._planner = planner or RuleBasedAgentPlanner()
        self._dispatcher = dispatcher or McpToolDispatcher()
        self._now_provider = now_provider or (lambda: datetime.now(UTC))
        self._llmops_service = llmops_service
        self._email_sender = email_sender
        self._email_recipients = email_recipients
        self._slack_sender = slack_sender
        self._settings = app_settings

    def plan_from_webhook(
        self,
        request: AlertmanagerWebhookRequest,
        *,
        actor: str = "alertmanager",
    ) -> AlertmanagerSrePlanResult:
        return self.handle_webhook(request, actor=actor, execute=False)

    def handle_webhook(
        self,
        request: AlertmanagerWebhookRequest,
        *,
        actor: str = "alertmanager",
        execute: bool = False,
        notify: bool = False,
    ) -> AlertmanagerSrePlanResult:
        alert = select_firing_alert(request)
        if alert is None:
            return AlertmanagerSrePlanResult(
                status="SKIPPED",
                receiver=request.receiver,
                actor=actor,
                skipped_reason="No firing alerts were included in the Alertmanager webhook.",
            )

        plan_result = self._plan_firing_alert(request=request, alert=alert, actor=actor)
        if not execute:
            return plan_result
        return self._collect_evidence(
            plan_result=plan_result,
            alert=alert,
            actor=actor,
            notify=notify,
        )

    def _plan_firing_alert(
        self,
        *,
        request: AlertmanagerWebhookRequest,
        alert: AlertmanagerAlert,
        actor: str,
    ) -> AlertmanagerSrePlanResult:
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

    def _collect_evidence(
        self,
        *,
        plan_result: AlertmanagerSrePlanResult,
        alert: AlertmanagerAlert,
        actor: str,
        notify: bool,
    ) -> AlertmanagerSrePlanResult:
        if plan_result.alert is None or plan_result.analysis_message is None:
            return plan_result

        now = normalize_datetime(self._now_provider())
        incident_window = build_incident_window(alert=alert, now=now)
        tool_results = []
        deferred_rca_plans: list[AgentToolPlan] = []

        for tool_plan in plan_result.planned_tools:
            if not is_read_tool_plan(tool_plan):
                continue
            enriched_plan = inject_alertmanager_execution_context(
                tool_plan,
                incident_key=plan_result.incident_key,
                incident_window=incident_window,
            )
            if (
                enriched_plan.server_name == "infraops-mcp"
                and enriched_plan.tool_name == "create_rca_snapshot"
            ):
                deferred_rca_plans.append(enriched_plan)
                continue
            tool_results.append(self._dispatcher.execute(enriched_plan))

        context_bundle = build_incident_context_bundle(
            chat_type="sre_copilot",
            message=plan_result.analysis_message,
            capability=plan_result.capability,
            tool_results=tool_results,
        )
        context_bundle["alertmanager"] = {
            "receiver": plan_result.receiver,
            "actor": actor,
            "incident_key": plan_result.incident_key,
            "intent": plan_result.intent,
            "capability": plan_result.capability,
            "alert": plan_result.alert.model_dump(mode="json"),
        }
        context_bundle["incident_window"] = incident_window.model_dump(mode="json")

        rca_snapshot: dict | None = None
        for tool_plan in deferred_rca_plans:
            enriched_payload = {
                **tool_plan.request_payload,
                "context_bundle": context_bundle,
            }
            result = self._dispatcher.execute(
                tool_plan.model_copy(update={"request_payload": enriched_payload})
            )
            tool_results.append(result)
            if tool_plan.tool_name == "create_rca_snapshot":
                rca_snapshot = compact_tool_result(result)

        collected_result = plan_result.model_copy(
            update={
                "dry_run": False,
                "status": "COLLECTED",
                "incident_window": incident_window,
                "executed_tools": tool_results,
                "context_bundle": context_bundle,
                "rca_snapshot": rca_snapshot,
            }
        )
        if not notify:
            return collected_result
        notification_results = self._send_collection_notifications(collected_result)
        rca_analysis = self._run_rca_analysis(collected_result)
        analyzed_result = collected_result.model_copy(
            update={
                "status": "ANALYZED",
                "rca_analysis": rca_analysis,
            }
        )
        notification_results.extend(self._send_analysis_notifications(analyzed_result))
        return analyzed_result.model_copy(
            update={"notification_results": notification_results}
        )

    def _run_rca_analysis(self, result: AlertmanagerSrePlanResult) -> dict[str, Any]:
        try:
            llm_run = self._get_llmops_service().run_rca_completion(
                incident=build_rca_llm_incident_payload(result),
                alert=(
                    result.alert.model_dump(mode="json")
                    if result.alert is not None
                    else {}
                ),
                snapshot=build_rca_llm_snapshot_payload(result),
                evidence=build_rca_llm_evidence(result),
            )
            return build_rca_analysis_payload(llm_run, result=result)
        except Exception as exc:
            error_message = format_delivery_error(exc)
            logger.exception("Alertmanager SRE RCA LLM analysis failed.")
            return {
                "run_status": "FAILED",
                "answer": "",
                "last_error": error_message,
                "validation_errors": [],
            }

    def _send_collection_notifications(
        self,
        result: AlertmanagerSrePlanResult,
    ) -> list[AlertmanagerSreNotificationResult]:
        subject = build_collection_notification_subject(result)
        html_body = build_collection_notification_html(result)
        slack_text = build_collection_notification_text(result)
        payload = build_collection_notification_payload(result)
        notifications = []

        email_recipients = self._resolve_email_recipients()
        if not email_recipients:
            notifications.append(
                AlertmanagerSreNotificationResult(
                    channel="EMAIL",
                    status="SKIPPED",
                    error_message="RCA_EMAIL_RECIPIENTS is empty.",
                )
            )
        for recipient in email_recipients:
            notifications.append(
                self._deliver_email_notification(
                    recipient=recipient,
                    subject=subject,
                    html_body=html_body,
                    payload=payload,
                    result=result,
                )
            )

        notifications.append(
            self._deliver_slack_notification(
                text=slack_text,
                subject=subject,
                payload=payload,
                result=result,
            )
        )
        return notifications

    def _send_analysis_notifications(
        self,
        result: AlertmanagerSrePlanResult,
    ) -> list[AlertmanagerSreNotificationResult]:
        subject = build_analysis_notification_subject(result)
        html_body = build_analysis_notification_html(result)
        slack_text = build_analysis_notification_text(result)
        payload = build_analysis_notification_payload(result)
        notifications = []

        email_recipients = self._resolve_email_recipients()
        if not email_recipients:
            notifications.append(
                AlertmanagerSreNotificationResult(
                    channel="EMAIL",
                    status="SKIPPED",
                    error_message="RCA_EMAIL_RECIPIENTS is empty.",
                )
            )
        for recipient in email_recipients:
            notifications.append(
                self._deliver_email_notification(
                    recipient=recipient,
                    subject=subject,
                    html_body=html_body,
                    payload=payload,
                    result=result,
                    notification_stage="sre_analysis",
                )
            )

        notifications.append(
            self._deliver_slack_notification(
                text=slack_text,
                subject=subject,
                payload=payload,
                result=result,
                notification_stage="sre_analysis",
            )
        )
        return notifications

    def _deliver_email_notification(
        self,
        *,
        recipient: str,
        subject: str,
        html_body: str,
        payload: dict[str, Any],
        result: AlertmanagerSrePlanResult,
        notification_stage: str = "sre_collection",
    ) -> AlertmanagerSreNotificationResult:
        notification = self._create_notification_record(
            channel="email",
            recipient=recipient,
            title=subject,
            content=html_body,
            payload=payload,
            result=result,
            notification_stage=notification_stage,
        )
        if isinstance(notification, AlertmanagerSreNotificationResult):
            return notification
        if notification.notification_status == "SENT":
            return AlertmanagerSreNotificationResult(
                channel="EMAIL",
                recipient=recipient,
                status="SENT",
                notification_id=notification.notification_id,
            )
        try:
            self._get_email_sender().send_html(
                recipient=recipient,
                subject=subject,
                html_body=html_body,
            )
            self._safe_update_notification_status(
                notification.notification_id,
                status="SENT",
                last_error=None,
            )
            return AlertmanagerSreNotificationResult(
                channel="EMAIL",
                recipient=recipient,
                status="SENT",
                notification_id=notification.notification_id,
            )
        except Exception as exc:
            error_message = format_delivery_error(exc)
            logger.warning(
                "Alertmanager SRE RCA email delivery failed for %s: %s",
                recipient,
                error_message,
                exc_info=True,
            )
            self._safe_update_notification_status(
                notification.notification_id,
                status="FAILED",
                last_error=error_message,
            )
            return AlertmanagerSreNotificationResult(
                channel="EMAIL",
                recipient=recipient,
                status="FAILED",
                notification_id=notification.notification_id,
                error_message=error_message,
            )

    def _deliver_slack_notification(
        self,
        *,
        text: str,
        subject: str,
        payload: dict[str, Any],
        result: AlertmanagerSrePlanResult,
        notification_stage: str = "sre_collection",
    ) -> AlertmanagerSreNotificationResult:
        webhook_url = self._settings.rca_slack_webhook_url.strip()
        recipient = self._resolve_slack_recipient()
        if not webhook_url:
            return AlertmanagerSreNotificationResult(
                channel="SLACK",
                recipient=recipient,
                status="SKIPPED",
                error_message="RCA_SLACK_WEBHOOK_URL is empty.",
            )
        notification = self._create_notification_record(
            channel="slack",
            recipient=recipient,
            title=subject,
            content=text,
            payload=payload,
            result=result,
            notification_stage=notification_stage,
        )
        if isinstance(notification, AlertmanagerSreNotificationResult):
            return notification
        if notification.notification_status == "SENT":
            return AlertmanagerSreNotificationResult(
                channel="SLACK",
                recipient=recipient,
                status="SENT",
                notification_id=notification.notification_id,
            )
        try:
            self._get_slack_sender().send_text(
                webhook_url=webhook_url,
                text=text,
                channel=self._settings.rca_slack_channel,
            )
            self._safe_update_notification_status(
                notification.notification_id,
                status="SENT",
                last_error=None,
            )
            return AlertmanagerSreNotificationResult(
                channel="SLACK",
                recipient=recipient,
                status="SENT",
                notification_id=notification.notification_id,
            )
        except Exception as exc:
            error_message = format_delivery_error(exc, secret=webhook_url)
            logger.warning(
                "Alertmanager SRE RCA Slack delivery failed: %s",
                error_message,
                exc_info=True,
            )
            self._safe_update_notification_status(
                notification.notification_id,
                status="FAILED",
                last_error=error_message,
            )
            return AlertmanagerSreNotificationResult(
                channel="SLACK",
                recipient=recipient,
                status="FAILED",
                notification_id=notification.notification_id,
                error_message=error_message,
            )

    def _create_notification_record(
        self,
        *,
        channel: str,
        recipient: str | None,
        title: str,
        content: str,
        payload: dict[str, Any],
        result: AlertmanagerSrePlanResult,
        notification_stage: str = "sre_collection",
    ):
        normalized_channel = channel.strip().upper()
        try:
            return self._get_llmops_service().create_notification(
                channel=channel,
                title=title,
                content=content,
                payload=payload,
                recipient=recipient,
                related_table="alertmanager_sre_incidents",
                related_public_id=None,
                idempotency_key=build_notification_idempotency_key(
                    result=result,
                    channel=normalized_channel,
                    recipient=recipient,
                    stage=notification_stage,
                ),
            )
        except Exception as exc:
            error_message = format_delivery_error(exc)
            logger.warning(
                "Alertmanager SRE RCA %s notification outbox creation failed: %s",
                normalized_channel,
                error_message,
                exc_info=True,
            )
            result_channel = "SLACK" if normalized_channel == "SLACK" else "EMAIL"
            return AlertmanagerSreNotificationResult(
                channel=result_channel,
                recipient=recipient,
                status="FAILED",
                error_message=error_message,
            )

    def _safe_update_notification_status(
        self,
        notification_id: str,
        *,
        status: str,
        last_error: str | None,
    ) -> None:
        try:
            self._get_llmops_service().update_notification_status(
                notification_id,
                status=status,
                last_error=last_error,
            )
        except Exception:
            logger.exception(
                "Failed to update Alertmanager SRE RCA notification status."
            )

    def _resolve_email_recipients(self) -> list[str]:
        if self._email_recipients is not None:
            return self._email_recipients
        configured = (
            self._settings.rca_email_recipients.strip()
            or self._settings.ops_report_email_recipients.strip()
        )
        return parse_recipients(configured)

    def _resolve_slack_recipient(self) -> str:
        return self._settings.rca_slack_channel.strip() or "slack-webhook"

    def _get_llmops_service(self) -> LlmOpsService:
        if self._llmops_service is None:
            self._llmops_service = LlmOpsService()
        return self._llmops_service

    def _get_email_sender(self) -> EmailSender:
        if self._email_sender is None:
            self._email_sender = SmtpEmailSender(self._settings)
        return self._email_sender

    def _get_slack_sender(self) -> SlackSender:
        if self._slack_sender is None:
            self._slack_sender = SlackWebhookSender(self._settings)
        return self._slack_sender


def build_collection_notification_subject(result: AlertmanagerSrePlanResult) -> str:
    alert_name = result.alert.alert_name if result.alert is not None else "Alertmanager alert"
    return f"[AIOps] RCA evidence collected: {alert_name}"


def build_collection_notification_payload(
    result: AlertmanagerSrePlanResult,
) -> dict[str, Any]:
    stats = summarize_tool_execution(result)
    summary = extract_bundle_summary(result)
    return {
        "notification_stage": "sre_collection",
        "trigger_type": result.trigger_type,
        "incident_key": result.incident_key,
        "status": result.status,
        "dry_run": result.dry_run,
        "intent": result.intent,
        "capability": result.capability,
        "alert": result.alert.model_dump(mode="json") if result.alert is not None else None,
        "incident_window": (
            result.incident_window.model_dump(mode="json")
            if result.incident_window is not None
            else None
        ),
        "tool_execution": stats,
        "available_sections": summary.get("available_sections", []),
        "missing_sections": summary.get("missing_sections", []),
        "cross_domain_scenario": summary.get("cross_domain_scenario"),
        "failure_boundary_candidates": trim_boundary_candidates(
            summary.get("failure_boundary_candidates", [])
        ),
        "rca_snapshot_collected": result.rca_snapshot is not None,
    }


def build_collection_notification_text(result: AlertmanagerSrePlanResult) -> str:
    view = build_notification_view(result)
    lines = [
        build_collection_notification_subject(result),
        "",
        "📦 1. 수집 요약",
        f"- 사고 유형: {view['incident_type']}",
        f"- 대상: {view['target']}",
        f"- 상태: {result.status} / intent: {result.intent or 'unknown'}",
        f"- 수집 도구: {view['tool_success']}",
        f"- 시간창: {view['window']}",
        "",
        "🔎 2. 핵심 근거",
        *format_bullets(view["evidence"], empty="수집된 핵심 근거가 없습니다."),
        "",
        "⚠️ 3. 미수집/주의",
        *format_bullets(view["data_limits"], empty="미수집 항목 없음"),
        "",
        "🔒 4. 원문 제한",
        "- raw logs, traces, secrets are not included in this notification.",
    ]
    return "\n".join(lines)


def build_collection_notification_html(result: AlertmanagerSrePlanResult) -> str:
    view = build_notification_view(result)
    rows = [
        ("Incident", result.incident_key or ""),
        ("Alert", result.alert.alert_name if result.alert is not None else ""),
        ("Incident Type", view["incident_type"]),
        ("Target", view["target"]),
        ("Severity", view["severity"]),
        ("Intent", result.intent or ""),
        ("Capability", result.capability or ""),
        ("Window", view["window"]),
        ("Tool Success", view["tool_success"]),
        ("Primary Candidate", view["primary_candidate"]),
        ("Confidence", view["primary_confidence"]),
    ]
    return (
        "<html><body>"
        "<h2>📦 AIOps SRE RCA evidence collected</h2>"
        "<p>Alertmanager triggered read-only RCA evidence collection. "
        "Raw logs, traces, and secret-like values are not included in this email.</p>"
        f"{render_html_table(rows)}"
        f"{render_html_section('🔎 핵심 근거', view['evidence'])}"
        f"{render_html_section('⚠️ 미수집/주의', view['data_limits'])}"
        "</body></html>"
    )


def build_rca_llm_incident_payload(result: AlertmanagerSrePlanResult) -> dict[str, Any]:
    stats = summarize_tool_execution(result)
    return {
        "incident_key": result.incident_key,
        "status": result.status,
        "intent": result.intent,
        "capability": result.capability,
        "target": format_alert_target(result.alert),
        "incident_window": (
            result.incident_window.model_dump(mode="json")
            if result.incident_window is not None
            else None
        ),
        "tool_execution": stats,
    }


def build_rca_llm_snapshot_payload(result: AlertmanagerSrePlanResult) -> dict[str, Any]:
    bundle = result.context_bundle or {}
    application_signals = build_application_signal_summary(result)
    root_cause_candidates = build_application_root_cause_candidates(
        result,
        application_signals=application_signals,
    )
    payload = {
        "analysis_contract": build_rca_analysis_contract(
            result,
            root_cause_candidates=root_cause_candidates,
        ),
        "context_summary": compact_payload_for_llm(
            bundle.get("summary_for_llm"),
            char_budget=4000,
        ),
        "cross_domain": compact_payload_for_llm(
            bundle.get("cross_domain"),
            char_budget=5000,
        ),
        "failure_boundary_candidates": trim_boundary_candidates(
            bundle.get("failure_boundary_candidates"),
            limit=8,
        ),
        "application_signals": compact_payload_for_llm(
            application_signals,
            char_budget=6000,
            max_depth=5,
            list_limit=8,
            string_limit=800,
        ),
        "root_cause_candidates": compact_payload_for_llm(
            root_cause_candidates,
            char_budget=5000,
            max_depth=4,
            list_limit=8,
            string_limit=800,
        ),
        "topology_facts": extract_topology_facts_for_llm(result),
        "rca_snapshot": summarize_rca_snapshot_for_llm(result.rca_snapshot),
    }
    return compact_payload_for_llm(
        payload,
        char_budget=LLM_SNAPSHOT_CHAR_BUDGET,
        max_depth=6,
        list_limit=12,
        string_limit=1600,
    )


def build_rca_llm_evidence(result: AlertmanagerSrePlanResult) -> list[dict[str, Any]]:
    bundle = result.context_bundle or {}
    evidence_sections = [
        ("topology", bundle.get("topology")),
        ("live_state", bundle.get("live_state")),
        ("observability", bundle.get("observability")),
        ("deployment_changes", bundle.get("deployment_changes")),
        ("history", bundle.get("history")),
    ]
    evidence = []
    for section_name, payload in evidence_sections:
        if payload:
            evidence.append(
                {
                    "section": section_name,
                    "payload": compact_payload_for_llm(
                        payload,
                        char_budget=LLM_SECTION_CHAR_BUDGET,
                    ),
                }
            )
    evidence.append(
        {
            "section": "tool_results",
            "payload": summarize_tool_results_for_llm(result),
        }
    )
    return compact_payload_for_llm(
        evidence,
        char_budget=LLM_EVIDENCE_CHAR_BUDGET,
        list_limit=len(evidence),
    )


def build_rca_analysis_contract(
    result: AlertmanagerSrePlanResult,
    *,
    root_cause_candidates: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    boundaries = trim_boundary_candidates(
        (result.context_bundle or {}).get("failure_boundary_candidates"),
        limit=12,
    )
    resolved_root_cause_candidates = (
        root_cause_candidates
        if root_cause_candidates is not None
        else build_application_root_cause_candidates(result)
    )
    healthy_boundaries = boundary_names_by_status(boundaries, "healthy")
    degraded_boundaries = boundary_names_by_status(boundaries, "degraded")
    unknown_boundaries = boundary_names_by_status(boundaries, "unknown")
    synthetic_alert = is_synthetic_sre_alert(result.alert)
    rules = [
        "alertname is only a hypothesis, not root-cause evidence",
        "do not list healthy boundaries as likely root-cause candidates",
        "likely causes require degraded or failed live evidence",
        "unknown boundaries are data gaps, not confirmed root causes",
        (
            "if routing boundaries are healthy and application_root_cause_candidates "
            "exist, use those candidates as the primary cause section"
        ),
        (
            "for synthetic alerts, state that this is a current-state "
            "inspection, not a confirmed outage"
        ),
        (
            "if all checked routing boundaries are healthy, conclude that "
            "current routing-boundary evidence is absent"
        ),
        (
            "when routing boundaries are healthy, prioritize logs, traces, "
            "recent deployments, DB/HikariCP, and downstream dependencies"
        ),
        "do not claim destructive remediation was executed",
    ]
    if is_postgres_sre_alert(result.alert):
        rules.extend(
            [
                (
                    "for PostgreSQL alerts, analyze database capacity, sessions, "
                    "locks, replication, and application pool pressure before "
                    "routing boundaries"
                ),
                (
                    "do not choose DNS, ingress, MetalLB, or k8s_service as the "
                    "primary cause of a PostgreSQL alert unless direct degraded "
                    "boundary evidence exists"
                ),
            ]
        )
    if is_kubernetes_pod_health_alert(result.alert):
        rules.extend(
            [
                (
                    "for Kubernetes pod health alerts, analyze pod lifecycle, "
                    "events, image pull, scheduling, node pressure, and mounted "
                    "configuration before traces or routing boundaries"
                ),
                (
                    "do not choose DNS, ingress, MetalLB, or downstream traces as "
                    "the primary cause of a pod Pending/Waiting alert unless direct "
                    "degraded evidence exists"
                ),
            ]
        )
    return {
        "language": {
            "answer_language": "ko",
            "keep_technical_identifiers_in_english": True,
        },
        "incident_focus": build_incident_focus(result.alert),
        "is_synthetic_alert": synthetic_alert,
        "boundary_verdicts": build_boundary_verdicts(boundaries),
        "ruled_out_boundaries": healthy_boundaries,
        "candidate_boundaries": degraded_boundaries,
        "unknown_boundaries": unknown_boundaries,
        "application_root_cause_candidates": resolved_root_cause_candidates,
        "next_investigation_priority": list(NEXT_INVESTIGATION_PRIORITY),
        "current_state_verdict": build_current_state_verdict(
            synthetic_alert=synthetic_alert,
            healthy_boundaries=healthy_boundaries,
            degraded_boundaries=degraded_boundaries,
            unknown_boundaries=unknown_boundaries,
        ),
        "rules": rules,
    }


def build_application_signal_summary(
    result: AlertmanagerSrePlanResult,
) -> dict[str, Any]:
    sections: dict[str, dict[str, Any]] = {
        section: {
            "status": "unavailable",
            "tools": [],
            "failed_tools": [],
            "findings": [],
        }
        for section in APPLICATION_SIGNAL_TOOLS
    }

    for tool_result in result.executed_tools:
        section = application_signal_section(tool_result.tool_name)
        if section is None:
            continue
        section_summary = sections[section]
        section_summary["tools"].append(tool_result.tool_name)
        if enum_value(tool_result.call_status) != "SUCCESS":
            section_summary["failed_tools"].append(
                {
                    "tool_name": tool_result.tool_name,
                    "error_message": truncate_text(
                        tool_result.error_message or "tool execution failed",
                        limit=300,
                    ),
                }
            )
            continue

        payload = select_tool_response_payload(tool_result)
        detection_payload = strip_signal_detection_noise(payload)
        evidence_text = stringify_signal_payload(detection_payload)
        findings = detect_application_findings(
            section=section,
            tool_name=tool_result.tool_name,
            payload=detection_payload,
            evidence_text=evidence_text,
        )
        section_summary["findings"].extend(findings)

    for section_summary in sections.values():
        section_summary["tools"] = sorted(set(section_summary["tools"]))
        section_summary["findings"] = dedupe_application_findings(
            section_summary["findings"]
        )
        if section_summary["findings"] or section_summary["failed_tools"]:
            section_summary["status"] = "degraded"
        elif section_summary["tools"]:
            section_summary["status"] = "unknown"

    degraded_sections = [
        section
        for section, summary in sections.items()
        if summary["status"] == "degraded"
    ]
    available_sections = [
        section
        for section, summary in sections.items()
        if summary["status"] != "unavailable"
    ]
    return {
        "overall_status": "degraded" if degraded_sections else "unknown",
        "available_sections": available_sections,
        "degraded_sections": degraded_sections,
        "sections": sections,
    }


def application_signal_section(tool_name: str) -> str | None:
    for section, tool_names in APPLICATION_SIGNAL_TOOLS.items():
        if tool_name in tool_names:
            return section
    return None


def detect_application_findings(
    *,
    section: str,
    tool_name: str,
    payload: Any,
    evidence_text: str,
) -> list[dict[str, Any]]:
    findings = []
    text = evidence_text.lower()
    if not text:
        return findings

    has_hikari_context = has_any(
        text,
        ("hikari", "hikaripool", "connection pool", "jdbc", "postgres"),
    )
    has_hikari_error = has_any(
        text,
        (
            "timeout",
            "connection is not available",
            "too many connections",
            "refused",
            "exhaust",
            "failed",
            "error",
        ),
    )
    has_pending_metric = (
        section == "metrics"
        and has_any(text, ("hikaricp_connections_pending", "pending"))
        and has_positive_metric_value(payload)
    )
    if has_hikari_context and (has_hikari_error or has_pending_metric):
        findings.append(
            build_application_finding(
                "db_hikaricp",
                section=section,
                tool_name=tool_name,
                evidence="matched HikariCP/JDBC/PostgreSQL connection error signal",
            )
        )

    if section == "metrics" and (
        has_any(
            text,
            (
                "pg_stat_activity_count",
                "pg_settings_max_connections",
                "max_connections",
                "connection saturation",
                "connection usage",
            ),
        )
        and has_positive_metric_value(payload)
    ):
        findings.append(
            build_application_finding(
                "postgres_connection_saturation",
                section=section,
                tool_name=tool_name,
                evidence="matched PostgreSQL connection usage/max_connections metric signal",
            )
        )

    if (
        "sqs" in text
        and has_any(text, ("sendmessage", "send message", "publish", "producer"))
        and has_any(
            text,
            ("fail", "error", "exception", "denied", "throttl", "timeout"),
        )
    ):
        findings.append(
            build_application_finding(
                "sqs_publish",
                section=section,
                tool_name=tool_name,
                evidence="matched SQS send/publish failure signal",
            )
        )

    if (
        has_any(text, ("sqs", "queue", "dlq"))
        and has_any(text, ("consumer", "listener", "receive", "lag", "backlog", "dlq"))
        and has_any(text, ("fail", "error", "timeout", "notempty", "not empty", "degraded"))
    ) or (
        section == "aws"
        and has_any(text, ("approximatenumberofmessages", "dlq", "deadletter"))
        and has_positive_metric_value(payload)
    ):
        findings.append(
            build_application_finding(
                "sqs_consume",
                section=section,
                tool_name=tool_name,
                evidence="matched SQS consume/DLQ lag or backlog signal",
            )
        )

    if has_any(text, ("5xx", "status=500", "status 500", "http 500", "http_status 500")) or (
        "500" in text and has_any(text, ("error", "exception", "http", "status"))
    ):
        findings.append(
            build_application_finding(
                "application_error",
                section=section,
                tool_name=tool_name,
                evidence="matched HTTP 5xx application error signal",
            )
        )

    if has_any(text, ("exception", "stacktrace", "nullpointer", "illegalstate")):
        findings.append(
            build_application_finding(
                "application_error",
                section=section,
                tool_name=tool_name,
                evidence="matched application exception signal",
            )
        )

    if section == "traces" and has_any(
        text,
        ("error span", "span error", "status_code error", "latency", "duration", "slow", "timeout"),
    ):
        findings.append(
            build_application_finding(
                "trace_latency",
                section=section,
                tool_name=tool_name,
                evidence="matched trace latency/error span signal",
            )
        )

    if section == "deployment_changes" and has_any(
        text,
        (
            "outofsync",
            "degraded",
            "progressing",
            "image changed",
            "image_changed",
            "rollout_status degraded",
            "rollout_status progressing",
        ),
    ):
        findings.append(
            build_application_finding(
                "deployment_regression",
                section=section,
                tool_name=tool_name,
                evidence="matched recent deployment or rollout change signal",
            )
        )

    return findings


def build_application_finding(
    finding_type: str,
    *,
    section: str,
    tool_name: str,
    evidence: str,
) -> dict[str, Any]:
    return {
        "type": finding_type,
        "label": APPLICATION_CANDIDATE_LABELS.get(finding_type, finding_type),
        "section": section,
        "tool_name": tool_name,
        "evidence": evidence,
    }


def dedupe_application_findings(findings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped = []
    seen = set()
    for finding in findings:
        key = (
            finding.get("type"),
            finding.get("section"),
            finding.get("tool_name"),
            finding.get("evidence"),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(finding)
    return deduped


def build_application_root_cause_candidates(
    result: AlertmanagerSrePlanResult,
    *,
    application_signals: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    signals = application_signals or build_application_signal_summary(result)
    findings = flatten_application_findings(signals)
    findings.extend(build_alert_root_cause_findings(result))
    findings_by_type: dict[str, list[dict[str, Any]]] = {}
    for finding in findings:
        findings_by_type.setdefault(str(finding.get("type")), []).append(finding)

    candidates = []
    for finding_type in (
        "postgres_connection_saturation",
        "pod_waiting_state",
        "db_hikaricp",
        "sqs_publish",
        "sqs_consume",
        "application_error",
        "trace_latency",
    ):
        if finding_type in findings_by_type:
            confidence_override = (
                "high"
                if finding_type in {"postgres_connection_saturation", "pod_waiting_state"}
                else None
            )
            candidates.append(
                build_root_cause_candidate(
                    finding_type,
                    findings_by_type[finding_type],
                    confidence_override=confidence_override,
                )
            )

    deployment_findings = findings_by_type.get("deployment_regression", [])
    if deployment_findings and any(
        candidate["candidate_type"]
        in {"application_error", "trace_latency", "db_hikaricp", "sqs_publish", "sqs_consume"}
        for candidate in candidates
    ):
        candidates.append(
            build_root_cause_candidate(
                "deployment_regression",
                deployment_findings,
                supporting_context="deployment change overlaps with application degraded signals",
            )
        )
    elif deployment_findings:
        candidates.append(
            build_root_cause_candidate(
                "deployment_regression",
                deployment_findings,
                confidence_override="low",
                supporting_context=(
                    "deployment change detected without a matching runtime error signal"
                ),
            )
        )

    ranked_candidates = sorted(
        candidates,
        key=lambda candidate: candidate_confidence_rank(candidate["confidence"]),
        reverse=True,
    )
    visible_candidates = [
        candidate
        for candidate in ranked_candidates
        if candidate["confidence"] in {"high", "medium"}
    ]
    return visible_candidates[:3]


def build_alert_root_cause_findings(
    result: AlertmanagerSrePlanResult,
) -> list[dict[str, Any]]:
    alert = result.alert
    if alert is None:
        return []
    if is_kubernetes_pod_health_alert(alert):
        return [
            build_application_finding(
                "pod_waiting_state",
                section="alertmanager",
                tool_name="alert_labels",
                evidence=(
                    "Kubernetes pod health alert fired; investigate pod phase, "
                    "waiting reason, image pull, scheduling, node, and events"
                ),
            )
        ]
    if is_postgres_connection_saturation_alert(alert):
        return [
            build_application_finding(
                "postgres_connection_saturation",
                section="alertmanager",
                tool_name="alert_labels",
                evidence=(
                    "PostgreSQL connection saturation alert fired; "
                    "connection usage exceeded the configured threshold"
                ),
            )
        ]
    if is_postgres_sre_alert(alert):
        return [
            build_application_finding(
                "db_hikaricp",
                section="alertmanager",
                tool_name="alert_labels",
                evidence=(
                    "PostgreSQL database alert fired; investigate DB health "
                    "and application connection pool pressure"
                ),
            )
        ]
    return []


def flatten_application_findings(signals: dict[str, Any]) -> list[dict[str, Any]]:
    sections = signals.get("sections")
    if not isinstance(sections, dict):
        return []
    findings = []
    for section_summary in sections.values():
        if not isinstance(section_summary, dict):
            continue
        section_findings = section_summary.get("findings")
        if isinstance(section_findings, list):
            findings.extend(
                finding for finding in section_findings if isinstance(finding, dict)
            )
    return findings


def build_root_cause_candidate(
    candidate_type: str,
    findings: list[dict[str, Any]],
    *,
    confidence_override: str | None = None,
    supporting_context: str | None = None,
) -> dict[str, Any]:
    sources = sorted(
        {
            str(finding.get("section"))
            for finding in findings
            if finding.get("section")
        }
    )
    evidence = [
        (
            f"{finding.get('section')}/{finding.get('tool_name')}: "
            f"{finding.get('evidence')}"
        )
        for finding in findings[:5]
    ]
    if supporting_context:
        evidence.append(supporting_context)
    confidence = confidence_override or infer_candidate_confidence(sources, findings)
    return {
        "candidate_type": candidate_type,
        "candidate": APPLICATION_CANDIDATE_LABELS.get(candidate_type, candidate_type),
        "confidence": confidence,
        "supporting_evidence": evidence,
        "evidence_sources": sources,
        "next_checks": next_checks_for_candidate(candidate_type),
    }


def infer_candidate_confidence(
    sources: list[str],
    findings: list[dict[str, Any]],
) -> str:
    if len(sources) >= 2:
        return "high"
    if len(findings) >= 2:
        return "medium"
    return "low"


def candidate_confidence_rank(confidence: str) -> int:
    return {"high": 3, "medium": 2, "low": 1}.get(confidence, 0)


def next_checks_for_candidate(candidate_type: str) -> list[str]:
    checks = {
        "postgres_connection_saturation": [
            "check PostgreSQL current sessions versus max_connections",
            "split active and idle sessions by database, user, and client",
            "check application HikariCP active/pending/max connection metrics",
            "review recent scale-out or deployment changes that increased DB sessions",
        ],
        "pod_waiting_state": [
            "check Kubernetes events for image pull, scheduling, and mount errors",
            "describe the affected pod and inspect container waiting reason",
            (
                "verify image tag, registry credentials, ConfigMap/Secret "
                "references, and node pressure"
            ),
            "check whether the workload is a Job/CronJob and compare recent runs",
        ],
        "db_hikaricp": [
            "check HikariCP active/pending/max connection metrics",
            "check PostgreSQL max_connections and current sessions",
            "review recent datasource pool configuration changes",
        ],
        "sqs_publish": [
            "check SQS SendMessage errors and IAM permissions",
            "check queue URL/region configuration",
            "review producer logs around the alert window",
        ],
        "sqs_consume": [
            "check queue visible/not-visible message counts and DLQ depth",
            "check consumer listener errors and processing latency",
            "review visibility timeout and retry policy",
        ],
        "application_error": [
            "inspect top exception patterns in application logs",
            "check HTTP 5xx rate by endpoint",
            "correlate errors with recent deployments",
        ],
        "trace_latency": [
            "inspect slow/error spans by downstream service",
            "check p95/p99 latency around the alert window",
            "compare trace errors with application logs",
        ],
        "deployment_regression": [
            "compare image tag/config before and after deployment",
            "check rollout status and Kubernetes events",
            "review ArgoCD sync and health status",
        ],
    }
    return checks.get(candidate_type, ["review supporting evidence"])


def select_tool_response_payload(tool_result: AgentToolExecutionResult) -> Any:
    if tool_result.masked_response_payload is not None:
        return tool_result.masked_response_payload
    return tool_result.response_payload


def strip_signal_detection_noise(value: Any) -> Any:
    noisy_keys = {
        "query",
        "queries",
        "promql",
        "logql",
        "expression",
        "request",
        "request_payload",
        "masked_request_payload",
    }
    if isinstance(value, dict):
        return {
            str(key): strip_signal_detection_noise(item)
            for key, item in value.items()
            if str(key).lower() not in noisy_keys
        }
    if isinstance(value, list):
        return [strip_signal_detection_noise(item) for item in value]
    return value


def stringify_signal_payload(value: Any) -> str:
    if value is None:
        return ""
    try:
        return json.dumps(
            remove_large_llm_fields(value),
            ensure_ascii=False,
            default=str,
            sort_keys=True,
        )
    except TypeError:
        return str(value)


def has_any(value: str, needles: tuple[str, ...]) -> bool:
    return any(needle in value for needle in needles)


def has_positive_metric_value(value: Any, *, threshold: float = 0.0) -> bool:
    return any(number > threshold for number in iter_metric_values(value))


def iter_metric_values(value: Any):
    if isinstance(value, dict):
        for key, item in value.items():
            key_text = str(key).lower()
            if key_text in {"value", "values", "sample", "samples", "datapoints"}:
                yield from iter_numeric_values(item)
            elif any(token in key_text for token in ("count", "depth", "pending", "visible")):
                yield from iter_numeric_values(item)
            else:
                yield from iter_metric_values(item)
    elif isinstance(value, list):
        if len(value) == 2 and is_numeric_like(value[1]):
            yield float(value[1])
            return
        for item in value:
            yield from iter_metric_values(item)


def iter_numeric_values(value: Any):
    if is_numeric_like(value):
        yield float(value)
    elif isinstance(value, dict):
        for item in value.values():
            yield from iter_numeric_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from iter_numeric_values(item)


def is_numeric_like(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, int | float):
        return True
    if isinstance(value, str):
        try:
            float(value)
        except ValueError:
            return False
        return True
    return False


def build_boundary_verdicts(boundaries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    verdicts = []
    for boundary in boundaries:
        boundary_name = str(boundary.get("boundary") or "").strip()
        if not boundary_name:
            continue
        verdicts.append(
            {
                "boundary": boundary_name,
                "status": boundary.get("status"),
                "confidence": boundary.get("confidence"),
                "reason": boundary.get("reason"),
                "health_evidence_tools": boundary.get("health_evidence_tools", []),
                "context_evidence_tools": boundary.get("context_evidence_tools", []),
            }
        )
    return verdicts


def boundary_names_by_status(
    boundaries: list[dict[str, Any]],
    status: str,
) -> list[str]:
    return [
        str(boundary.get("boundary"))
        for boundary in boundaries
        if str(boundary.get("status") or "").lower() == status
        and str(boundary.get("boundary") or "")
    ]


def build_current_state_verdict(
    *,
    synthetic_alert: bool,
    healthy_boundaries: list[str],
    degraded_boundaries: list[str],
    unknown_boundaries: list[str],
) -> str:
    prefix = "synthetic current-state inspection" if synthetic_alert else "alert-triggered RCA"
    if degraded_boundaries:
        return (
            f"{prefix}: degraded live evidence exists for "
            f"{', '.join(degraded_boundaries)}. Healthy boundaries must be ruled out."
        )
    if healthy_boundaries:
        return (
            f"{prefix}: current routing-boundary evidence is absent; no degraded "
            "live boundary evidence was found among checked boundaries "
            f"({', '.join(healthy_boundaries)}). Treat healthy boundaries as ruled "
            "out and move investigation to application/runtime evidence."
        )
    if unknown_boundaries:
        return (
            f"{prefix}: available boundary evidence is insufficient. Unknown boundaries "
            "are data gaps and must not be stated as confirmed causes."
        )
    return f"{prefix}: no boundary evidence is available."


def build_incident_focus(alert: AlertmanagerSreAlertContext | None) -> dict[str, Any]:
    if alert is None:
        return {
            "category": "unknown",
            "primary_domain": "unknown",
            "routing_boundaries_are_primary": True,
        }
    if is_kubernetes_pod_health_alert(alert):
        return {
            "category": "kubernetes_pod_health",
            "primary_domain": "kubernetes",
            "routing_boundaries_are_primary": False,
            "expected_primary_evidence": [
                "pod phase and container waiting reason",
                "Kubernetes warning events",
                "image pull and registry credentials",
                "ConfigMap/Secret mount references",
                "node scheduling and resource pressure",
            ],
        }
    if is_postgres_connection_saturation_alert(alert):
        return {
            "category": "postgres_connection_saturation",
            "primary_domain": "database",
            "routing_boundaries_are_primary": False,
            "expected_primary_evidence": [
                "PostgreSQL current sessions",
                "PostgreSQL max_connections",
                "active versus idle sessions",
                "application HikariCP pool pressure",
                "recent scale-out or deployment changes",
            ],
        }
    if is_postgres_sre_alert(alert):
        return {
            "category": "postgres_database_alert",
            "primary_domain": "database",
            "routing_boundaries_are_primary": False,
            "expected_primary_evidence": [
                "PostgreSQL exporter metrics",
                "database logs",
                "application pool pressure",
                "recent DB or application changes",
            ],
        }
    return {
        "category": "sre_incident",
        "primary_domain": "service_or_routing",
        "routing_boundaries_are_primary": True,
    }


def apply_rca_answer_guardrails(
    answer: str,
    *,
    result: AlertmanagerSrePlanResult,
) -> str:
    if answer.lstrip().startswith("자동 판정"):
        return answer
    prefix = build_rca_guardrail_prefix(result)
    if not prefix:
        return answer
    return f"{prefix}\n\nLLM 분석\n{answer.strip()}"


def build_rca_guardrail_prefix(result: AlertmanagerSrePlanResult) -> str:
    root_cause_candidates = build_application_root_cause_candidates(result)
    contract = build_rca_analysis_contract(
        result,
        root_cause_candidates=root_cause_candidates,
    )
    healthy_boundaries = [
        boundary
        for boundary in contract["ruled_out_boundaries"]
        if boundary in ROUTING_BOUNDARIES
    ]
    degraded_boundaries = [
        boundary
        for boundary in contract["candidate_boundaries"]
        if boundary in ROUTING_BOUNDARIES
    ]
    unknown_boundaries = [
        boundary
        for boundary in contract["unknown_boundaries"]
        if boundary in ROUTING_BOUNDARIES
    ]
    if is_kubernetes_pod_health_alert(result.alert):
        return build_kubernetes_pod_guardrail_prefix(
            root_cause_candidates=root_cause_candidates,
            healthy_boundaries=healthy_boundaries,
            degraded_boundaries=degraded_boundaries,
            unknown_boundaries=unknown_boundaries,
        )
    if is_postgres_sre_alert(result.alert):
        return build_database_guardrail_prefix(
            root_cause_candidates=root_cause_candidates,
            healthy_boundaries=healthy_boundaries,
            degraded_boundaries=degraded_boundaries,
            unknown_boundaries=unknown_boundaries,
        )
    if not (healthy_boundaries or degraded_boundaries or unknown_boundaries):
        return ""

    lines = ["자동 판정"]
    if contract["is_synthetic_alert"]:
        lines.append(
            "- 이 알림은 synthetic current-state inspection이며, "
            "실제 장애를 유발한 검증이 아닙니다."
        )
    if healthy_boundaries:
        lines.append(
            "- 현재 live check 기준 "
            f"{', '.join(healthy_boundaries)} 경계는 healthy이므로 원인 후보에서 제외합니다."
        )
    if degraded_boundaries:
        lines.append(
            "- 우선 원인 후보는 degraded live evidence가 있는 "
            f"{', '.join(degraded_boundaries)} 경계입니다."
        )
    elif healthy_boundaries:
        lines.append(
            "- degraded/failed live boundary evidence가 없어 "
            "현재 시점의 라우팅 경계 장애 증거는 없습니다."
        )
    if unknown_boundaries:
        lines.append(
            "- "
            f"{', '.join(unknown_boundaries)} 경계는 unknown이므로 "
            "원인 확정이 아니라 데이터 한계로 다룹니다."
        )
    if healthy_boundaries and not degraded_boundaries:
        lines.append(
            "- 실제 사용자 오류가 있다면 application logs, distributed traces, recent deployments, "
            "DB/HikariCP, downstream dependencies를 우선 확인합니다."
        )
    if healthy_boundaries and not degraded_boundaries and root_cause_candidates:
        candidate_summary = ", ".join(
            f"{candidate['candidate']}({candidate['confidence']})"
            for candidate in root_cause_candidates[:3]
        )
        lines.append(
            "- 라우팅 경계보다 application root_cause_candidates를 우선 확인합니다: "
            f"{candidate_summary}"
        )
    return "\n".join(lines)


def build_kubernetes_pod_guardrail_prefix(
    *,
    root_cause_candidates: list[dict[str, Any]],
    healthy_boundaries: list[str],
    degraded_boundaries: list[str],
    unknown_boundaries: list[str],
) -> str:
    lines = [
        "자동 판정",
        (
            "- 이 알림은 Kubernetes Pod 상태 알림이므로 라우팅 경계가 아니라 "
            "Pod lifecycle, image pull, scheduling, node/resource 상태를 "
            "1차 원인 영역으로 분석합니다."
        ),
    ]
    if healthy_boundaries:
        lines.append(
            "- 현재 live check 기준 "
            f"{', '.join(healthy_boundaries)} 경계는 healthy이므로 "
            "Pod Pending/Waiting 알림의 원인 후보에서 제외합니다."
        )
    if degraded_boundaries:
        lines.append(
            "- degraded live boundary evidence가 있는 "
            f"{', '.join(degraded_boundaries)} 경계는 보조 증거로만 검토합니다."
        )
    if unknown_boundaries:
        lines.append(
            "- "
            f"{', '.join(unknown_boundaries)} 경계는 unknown이므로 "
            "원인 확정이 아니라 데이터 한계로 다룹니다."
        )
    if root_cause_candidates:
        candidate_summary = ", ".join(
            f"{candidate['candidate']}({candidate['confidence']})"
            for candidate in root_cause_candidates[:3]
        )
        lines.append(
            "- 우선 확인할 Kubernetes/application root_cause_candidates: "
            f"{candidate_summary}"
        )
    else:
        lines.append(
            "- 우선 확인할 항목: pod describe/events, container waiting reason, "
            "image pull 권한/태그, ConfigMap/Secret 참조, node pressure, "
            "최근 Job/CronJob 실행 이력."
        )
    return "\n".join(lines)


def build_database_guardrail_prefix(
    *,
    root_cause_candidates: list[dict[str, Any]],
    healthy_boundaries: list[str],
    degraded_boundaries: list[str],
    unknown_boundaries: list[str],
) -> str:
    lines = [
        "자동 판정",
        (
            "- 이 알림은 PostgreSQL 계열 DB 알림이므로 라우팅 경계가 아니라 "
            "DB connection/session pressure를 1차 원인 영역으로 분석합니다."
        ),
    ]
    if healthy_boundaries:
        lines.append(
            "- 현재 live check 기준 "
            f"{', '.join(healthy_boundaries)} 경계는 healthy이므로 "
            "DB 알림의 원인 후보에서 제외합니다."
        )
    if degraded_boundaries:
        lines.append(
            "- degraded live boundary evidence가 있는 "
            f"{', '.join(degraded_boundaries)} 경계는 보조 증거로만 검토합니다."
        )
    if unknown_boundaries:
        lines.append(
            "- "
            f"{', '.join(unknown_boundaries)} 경계는 unknown이므로 "
            "원인 확정이 아니라 데이터 한계로 다룹니다."
        )
    if root_cause_candidates:
        candidate_summary = ", ".join(
            f"{candidate['candidate']}({candidate['confidence']})"
            for candidate in root_cause_candidates[:3]
        )
        lines.append(
            "- 우선 확인할 DB/application root_cause_candidates: "
            f"{candidate_summary}"
        )
    else:
        lines.append(
            "- 우선 확인할 항목: PostgreSQL current sessions, max_connections, "
            "active/idle session split, HikariCP active/pending/max metrics, "
            "최근 scale-out 또는 deployment 변경."
        )
    return "\n".join(lines)


def is_synthetic_sre_alert(alert: AlertmanagerSreAlertContext | None) -> bool:
    if alert is None:
        return False
    text = " ".join(
        str(value or "")
        for value in (
            alert.alert_name,
            alert.fingerprint,
            alert.summary,
            alert.description,
        )
    ).lower()
    return "synthetic" in text


def is_kubernetes_pod_health_alert_name(normalized_alert_name: str) -> bool:
    return normalized_alert_name in KUBERNETES_POD_HEALTH_ALERT_NAMES


def is_kubernetes_pod_health_alert(alert: AlertmanagerSreAlertContext | None) -> bool:
    if alert is None:
        return False
    normalized_name = normalize_alert_name(alert.alert_name)
    if is_kubernetes_pod_health_alert_name(normalized_name):
        return True
    text = " ".join(
        str(value or "")
        for value in (
            alert.alert_name,
            alert.service_name,
            alert.workload,
            alert.pod,
            alert.summary,
            alert.description,
        )
    ).lower()
    return "pod" in text and any(
        term in text
        for term in (
            "pending",
            "waiting",
            "imagepullbackoff",
            "errimagepull",
            "crashloop",
            "nothealthy",
            "not healthy",
        )
    )


def is_postgres_sre_alert(alert: AlertmanagerSreAlertContext | None) -> bool:
    if alert is None:
        return False
    normalized_name = normalize_alert_name(alert.alert_name)
    if normalized_name in POSTGRES_ALERT_NAMES:
        return True
    text = " ".join(
        str(value or "")
        for value in (
            alert.alert_name,
            alert.service_name,
            alert.workload,
            alert.summary,
            alert.description,
        )
    ).lower()
    return "postgres" in text or "postgresql" in text


def is_postgres_connection_saturation_alert(
    alert: AlertmanagerSreAlertContext | None,
) -> bool:
    if alert is None:
        return False
    normalized_name = normalize_alert_name(alert.alert_name)
    if normalized_name in POSTGRES_CONNECTION_SATURATION_ALERT_NAMES:
        return True
    text = " ".join(
        str(value or "")
        for value in (
            alert.alert_name,
            alert.summary,
            alert.description,
        )
    ).lower()
    return (
        ("postgres" in text or "postgresql" in text)
        and "connection" in text
        and any(term in text for term in ("saturation", "usage", "80%", "max_connections"))
    )


def build_rca_analysis_payload(
    llm_run: LlmRunResult,
    *,
    result: AlertmanagerSrePlanResult | None = None,
) -> dict[str, Any]:
    answer = str(llm_run.masked_output.get("answer") or "").strip()
    if result is not None and answer:
        answer = apply_rca_answer_guardrails(answer, result=result)
    return {
        "llm_run_id": llm_run.llm_run_id,
        "provider": llm_run.provider,
        "model": llm_run.model,
        "prompt_key": llm_run.prompt_key,
        "run_status": llm_run.run_status,
        "answer": answer,
        "last_error": llm_run.last_error,
        "validation_errors": llm_run.validation_errors,
    }


def build_analysis_notification_subject(result: AlertmanagerSrePlanResult) -> str:
    alert_name = result.alert.alert_name if result.alert is not None else "Alertmanager alert"
    return f"[AIOps] RCA analysis completed: {alert_name}"


def build_analysis_notification_payload(
    result: AlertmanagerSrePlanResult,
) -> dict[str, Any]:
    analysis = result.rca_analysis or {}
    return {
        "notification_stage": "sre_analysis",
        "trigger_type": result.trigger_type,
        "incident_key": result.incident_key,
        "status": result.status,
        "intent": result.intent,
        "capability": result.capability,
        "alert": result.alert.model_dump(mode="json") if result.alert is not None else None,
        "incident_window": (
            result.incident_window.model_dump(mode="json")
            if result.incident_window is not None
            else None
        ),
        "tool_execution": summarize_tool_execution(result),
        "rca_analysis": analysis,
    }


def build_analysis_notification_text(result: AlertmanagerSrePlanResult) -> str:
    analysis = result.rca_analysis or {}
    run_status = str(analysis.get("run_status") or "UNKNOWN")
    answer = build_notification_answer(result, limit=1400)
    view = build_notification_view(result)
    lines = [
        build_analysis_notification_subject(result),
        "",
        "🚦 1. 요약",
        f"- 사고 유형: {view['incident_type']}",
        f"- 대상: {view['target']}",
        f"- 심각도: {view['severity']}",
        f"- 1순위 후보: {view['primary_candidate']}",
        f"- 신뢰도: {view['primary_confidence']}",
        f"- 영향 범위: {view['impact_scope']}",
        f"- LLM 상태: {run_status}",
        "",
        "🧭 2. 자동 판정",
        *format_bullets(view["verdict"], empty="자동 판정 정보 없음"),
        "",
        "🔎 3. 핵심 근거",
        *format_bullets(view["evidence"], empty="수집된 핵심 근거가 없습니다."),
        "",
        "🎯 4. 원인 후보",
        *format_bullets(view["candidate_lines"], empty="명확한 원인 후보 없음"),
        "",
        "🛠 5. 권장 확인/조치",
        *format_bullets(view["next_checks"], empty="추가 확인 항목 없음"),
        "",
        "⚠️ 6. 데이터 한계",
        *format_bullets(view["data_limits"], empty="확인된 데이터 한계 없음"),
        "",
        "🤖 7. 모델 보조 분석",
        answer or "No RCA answer was generated.",
        "",
        "🔒 note: destructive remediation was not executed.",
    ]
    return "\n".join(lines)


def build_analysis_notification_html(result: AlertmanagerSrePlanResult) -> str:
    analysis = result.rca_analysis or {}
    run_status = str(analysis.get("run_status") or "UNKNOWN")
    answer = build_notification_answer(result, limit=8000)
    view = build_notification_view(result)
    rows = [
        ("Incident", result.incident_key or ""),
        ("Alert", result.alert.alert_name if result.alert is not None else ""),
        ("Incident Type", view["incident_type"]),
        ("Target", view["target"]),
        ("Severity", view["severity"]),
        ("Intent", result.intent or ""),
        ("Primary Candidate", view["primary_candidate"]),
        ("Confidence", view["primary_confidence"]),
        ("Impact Scope", view["impact_scope"]),
        ("LLM Status", run_status),
        ("LLM Run", str(analysis.get("llm_run_id") or "")),
        ("Tool Success", view["tool_success"]),
        ("Window", view["window"]),
    ]
    return (
        "<html><body>"
        "<h2>🚦 AIOps SRE RCA analysis completed</h2>"
        f"{render_html_table(rows)}"
        f"{render_html_section('🧭 자동 판정', view['verdict'])}"
        f"{render_html_section('🔎 핵심 근거', view['evidence'])}"
        f"{render_html_section('🎯 원인 후보', view['candidate_lines'])}"
        f"{render_html_section('🛠 권장 확인/조치', view['next_checks'])}"
        f"{render_html_section('⚠️ 데이터 한계', view['data_limits'])}"
        "<h3>🤖 모델 보조 분석</h3>"
        "<pre>"
        f"{html.escape(truncate_text(answer or 'No RCA answer was generated.', limit=8000))}"
        "</pre>"
        "<p>Destructive remediation was not executed.</p>"
        "</body></html>"
    )


def build_notification_view(result: AlertmanagerSrePlanResult) -> dict[str, Any]:
    stats = summarize_tool_execution(result)
    summary = extract_bundle_summary(result)
    candidates = build_application_root_cause_candidates(result)
    alert = result.alert
    primary_candidate = candidates[0] if candidates else {}
    boundaries = notification_boundaries(result, summary=summary)
    window = (
        f"{result.incident_window.start} ~ {result.incident_window.end}"
        if result.incident_window is not None
        else "unknown"
    )
    return {
        "incident_type": determine_incident_type(result),
        "target": format_alert_target(alert),
        "severity": alert.severity if alert is not None and alert.severity else "unknown",
        "primary_candidate": format_candidate_name(primary_candidate),
        "primary_confidence": str(primary_candidate.get("confidence") or "unknown"),
        "impact_scope": determine_impact_scope(result),
        "window": window,
        "tool_success": f"{stats['successful_tools']}/{stats['total_tools']} succeeded",
        "verdict": build_deterministic_verdict_lines(
            result,
            candidates=candidates,
            boundaries=boundaries,
        ),
        "evidence": build_key_evidence_lines(
            result,
            stats=stats,
            summary=summary,
            candidates=candidates,
            boundaries=boundaries,
        ),
        "candidate_lines": build_candidate_lines(candidates),
        "next_checks": build_next_check_lines(result, candidates),
        "data_limits": build_data_limit_lines(
            result,
            stats=stats,
            summary=summary,
            boundaries=boundaries,
        ),
    }


def notification_boundaries(
    result: AlertmanagerSrePlanResult,
    *,
    summary: dict[str, Any],
) -> list[dict[str, Any]]:
    boundaries = trim_boundary_candidates(summary.get("failure_boundary_candidates", []))
    if boundaries:
        return boundaries
    bundle = result.context_bundle or {}
    return trim_boundary_candidates(bundle.get("failure_boundary_candidates", []))


def determine_incident_type(result: AlertmanagerSrePlanResult) -> str:
    if is_kubernetes_pod_health_alert(result.alert):
        return "Kubernetes Pod 상태 이상"
    if is_postgres_connection_saturation_alert(result.alert):
        return "PostgreSQL connection 포화"
    if is_postgres_sre_alert(result.alert):
        return "PostgreSQL/DB 문제"
    if result.intent in {"routing_failure", "checkout_500"}:
        return "Routing/Ingress/MetalLB 문제"
    if result.intent in {"sqs_publish_failure", "sqs_consume_failure", "pin_verification_missing"}:
        return "SQS 메시징 문제"
    if result.intent == "pod_crashloop":
        return "Kubernetes Pod 상태 이상"
    if result.intent == "db_hikaricp_issue":
        return "DB/HikariCP 문제"
    return "일반 application incident"


def determine_impact_scope(result: AlertmanagerSrePlanResult) -> str:
    alert = result.alert
    if alert is None:
        return "unknown"
    if is_kubernetes_pod_health_alert(alert):
        return "/".join(
            part
            for part in (
                alert.namespace,
                alert.workload or alert.service_name,
                alert.pod,
            )
            if part
        )
    if is_postgres_sre_alert(alert):
        return "/".join(
            part for part in (alert.namespace, alert.service_name or alert.workload) if part
        )
    return format_alert_target(alert)


def build_deterministic_verdict_lines(
    result: AlertmanagerSrePlanResult,
    *,
    candidates: list[dict[str, Any]],
    boundaries: list[dict[str, Any]],
) -> list[str]:
    alert = result.alert
    lines = []
    if is_kubernetes_pod_health_alert(alert):
        lines.append(
            "Kubernetes Pod 상태 알림이므로 routing/trace보다 pod lifecycle을 우선 분석합니다."
        )
    elif is_postgres_sre_alert(alert):
        lines.append(
            "PostgreSQL 계열 DB 알림이므로 routing boundary보다 "
            "DB session/connection 압박을 우선 분석합니다."
        )
    elif result.intent == "routing_failure":
        lines.append("Routing/Ingress/MetalLB 경계 상태를 우선 분석합니다.")
    else:
        lines.append(
            "Alertmanager 알림과 수집된 관측 신호를 기준으로 "
            "READ-only RCA를 수행했습니다."
        )

    if is_synthetic_sre_alert(alert):
        lines.append("synthetic current-state inspection이며 실제 장애 유발 검증은 아닙니다.")

    healthy = boundary_names_by_status(boundaries, "healthy")
    degraded = boundary_names_by_status(boundaries, "degraded")
    unknown = boundary_names_by_status(boundaries, "unknown")
    non_routing_focus = is_kubernetes_pod_health_alert(alert) or is_postgres_sre_alert(alert)
    if healthy:
        lines.append(f"healthy 경계는 원인 후보에서 제외합니다: {', '.join(healthy)}")
    if degraded:
        if non_routing_focus:
            lines.append(
                "라우팅 경계 degraded 신호는 보조 신호로만 기록합니다: "
                f"{', '.join(degraded)}"
            )
        else:
            lines.append(f"degraded 경계는 우선 확인 대상입니다: {', '.join(degraded)}")
    if unknown:
        lines.append(
            "unknown 경계는 원인 확정이 아니라 데이터 한계로 둡니다: "
            f"{', '.join(unknown)}"
        )
    if candidates:
        lines.append(
            "우선 원인 후보: "
            + ", ".join(
                f"{format_candidate_name(candidate)}({candidate.get('confidence')})"
                for candidate in candidates[:3]
            )
        )
    return lines


def build_key_evidence_lines(
    result: AlertmanagerSrePlanResult,
    *,
    stats: dict[str, Any],
    summary: dict[str, Any],
    candidates: list[dict[str, Any]],
    boundaries: list[dict[str, Any]],
) -> list[str]:
    alert = result.alert
    lines = []
    if alert is not None:
        lines.append(
            "alert="
            f"{alert.alert_name}, severity={alert.severity or 'unknown'}, "
            f"target={format_alert_target(alert)}"
        )
        if alert.pod:
            lines.append(f"pod={alert.pod}")
        if alert.summary:
            lines.append(f"summary={truncate_text(alert.summary, limit=180)}")
    lines.append(f"tools={stats['successful_tools']}/{stats['total_tools']} succeeded")
    sections = compact_list(summary.get("available_sections", []), limit=6)
    if sections:
        lines.append(f"evidence_sections={sections}")
    boundary_summary = format_boundary_summary(boundaries)
    if boundary_summary:
        lines.append(f"boundaries={boundary_summary}")
    if candidates:
        evidence = candidates[0].get("supporting_evidence")
        if isinstance(evidence, list) and evidence:
            lines.append(f"primary_evidence={truncate_text(str(evidence[0]), limit=220)}")
    return lines


def build_candidate_lines(candidates: list[dict[str, Any]]) -> list[str]:
    lines = []
    for index, candidate in enumerate(candidates[:5], start=1):
        lines.append(
            f"{index}. {format_candidate_name(candidate)} "
            f"({candidate.get('confidence', 'unknown')})"
        )
        evidence = candidate.get("supporting_evidence")
        if isinstance(evidence, list) and evidence:
            lines.append(f"   근거: {truncate_text(str(evidence[0]), limit=180)}")
    return lines


def format_candidate_name(candidate: dict[str, Any]) -> str:
    candidate_type = str(candidate.get("candidate_type") or "")
    fallback = str(candidate.get("candidate") or "unknown")
    names = {
        "pod_waiting_state": "Pod Pending/Waiting 상태",
        "postgres_connection_saturation": "PostgreSQL connection 포화",
        "db_hikaricp": "DB/HikariCP connection pool 압박",
        "sqs_publish": "SQS publish 실패",
        "sqs_consume": "SQS consume/DLQ backlog",
        "application_error": "Application runtime error/HTTP 5xx",
        "trace_latency": "Downstream latency/trace error",
        "deployment_regression": "최근 배포 회귀",
    }
    return names.get(candidate_type, fallback)


def build_next_check_lines(
    result: AlertmanagerSrePlanResult,
    candidates: list[dict[str, Any]],
) -> list[str]:
    checks = []
    for candidate in candidates[:2]:
        next_checks = candidate.get("next_checks")
        if isinstance(next_checks, list):
            checks.extend(str(item) for item in next_checks if str(item).strip())
    if checks:
        return [format_next_check(item) for item in dedupe_strings(checks)[:6]]
    if is_kubernetes_pod_health_alert(result.alert):
        return [format_next_check(item) for item in next_checks_for_candidate("pod_waiting_state")]
    if is_postgres_sre_alert(result.alert):
        return [
            format_next_check(item)
            for item in next_checks_for_candidate("postgres_connection_saturation")
        ]
    if result.intent == "routing_failure":
        return [
            "MetalLB endpoint 도달성을 확인합니다.",
            "Ingress host/path가 올바른 backend service로 연결되는지 확인합니다.",
            "Service endpoint와 pod readiness를 확인합니다.",
            "최근 deployment 또는 ingress 변경 이력을 비교합니다.",
        ]
    return ["logs, metrics, traces, 최근 deployment 변경 이력을 함께 확인합니다."]


def format_next_check(value: str) -> str:
    normalized = value.strip()
    translations = {
        "check Kubernetes events for image pull, scheduling, and mount errors": (
            "Kubernetes events에서 image pull, scheduling, mount 오류를 확인합니다."
        ),
        "describe the affected pod and inspect container waiting reason": (
            "영향받은 pod describe 결과에서 container waiting reason을 확인합니다."
        ),
        (
            "verify image tag, registry credentials, ConfigMap/Secret references, "
            "and node pressure"
        ): (
            "image tag, registry 인증, ConfigMap/Secret 참조, node pressure를 확인합니다."
        ),
        "check whether the workload is a Job/CronJob and compare recent runs": (
            "대상이 Job/CronJob인지 확인하고 최근 실행 이력을 비교합니다."
        ),
        "check PostgreSQL current sessions versus max_connections": (
            "PostgreSQL 현재 session 수와 max_connections를 비교합니다."
        ),
        "split active and idle sessions by database, user, and client": (
            "active/idle session을 database, user, client 기준으로 나눠 확인합니다."
        ),
        "check application HikariCP active/pending/max connection metrics": (
            "애플리케이션 HikariCP active/pending/max connection metric을 확인합니다."
        ),
        "review recent scale-out or deployment changes that increased DB sessions": (
            "DB session 증가를 유발한 최근 scale-out 또는 deployment 변경을 확인합니다."
        ),
    }
    return translations.get(normalized, normalized)


def build_data_limit_lines(
    result: AlertmanagerSrePlanResult,
    *,
    stats: dict[str, Any],
    summary: dict[str, Any],
    boundaries: list[dict[str, Any]],
) -> list[str]:
    lines = []
    for tool_name in stats.get("failed_tools", [])[:8]:
        lines.append(explain_failed_tool(str(tool_name), result=result))
    missing_sections = summary.get("missing_sections")
    if isinstance(missing_sections, list):
        lines.extend(f"missing evidence section: {section}" for section in missing_sections[:5])
    unknown_boundaries = boundary_names_by_status(boundaries, "unknown")
    if unknown_boundaries:
        lines.append(f"unknown boundaries: {', '.join(unknown_boundaries)}")
    return dedupe_strings(lines)


def explain_failed_tool(tool_name: str, *, result: AlertmanagerSrePlanResult) -> str:
    explanations = {
        "get_pod_logs": (
            "pod logs 미수집: 컨테이너가 아직 시작되지 않았거나 대상 pod 로그가 없을 수 있음"
        ),
        "get_rollout_status": (
            "rollout 상태 미수집: 대상이 Deployment가 아니라 Job/CronJob일 수 있음"
        ),
        "get_current_image_tags": (
            "image tag 미수집: 대상 workload의 현재 이미지 정보를 확인하지 못함"
        ),
        "get_k8s_service_endpoints": (
            "service endpoint 미수집: 대상이 Service 뒤의 서버가 아닌 batch/job pod일 수 있음"
        ),
        "get_k8s_ingress_backend_mapping": (
            "ingress mapping 미수집: 대상 workload가 외부 ingress 경로를 갖지 않을 수 있음"
        ),
        "get_service_trace_summary": (
            "trace summary 미수집: Tempo/trace backend 또는 service mapping 확인 필요"
        ),
        "search_traces": (
            "trace 검색 미수집: trace backend 연결 또는 service name mapping 확인 필요"
        ),
    }
    return explanations.get(tool_name, f"{tool_name} 미수집: tool 실행 결과를 확인해야 함")


def build_notification_answer(result: AlertmanagerSrePlanResult, *, limit: int) -> str:
    analysis = result.rca_analysis or {}
    run_status = str(analysis.get("run_status") or "UNKNOWN")
    raw_answer = str(analysis.get("answer") or "").strip()
    last_error = str(analysis.get("last_error") or "").strip()
    if run_status != "SUCCESS":
        return truncate_text(
            last_error or "LLM RCA analysis did not complete successfully.",
            limit=limit,
        )
    if raw_answer:
        raw_answer = apply_rca_answer_guardrails(raw_answer, result=result)
    return normalize_rca_answer_for_notification(raw_answer, limit=limit)


def normalize_rca_answer_for_notification(answer: str, *, limit: int) -> str:
    if not answer:
        return ""
    llm_part = answer
    if "\n\nLLM 분석\n" in answer:
        llm_part = answer.split("\n\nLLM 분석\n", 1)[1].strip()
    parsed = parse_json_object(llm_part)
    if isinstance(parsed, dict):
        lines = []
        for key in ("요약", "관측 근거", "원인 후보", "권장 확인/조치", "데이터 한계"):
            value = parsed.get(key)
            if value:
                lines.append(f"{key}: {value}")
        if lines:
            return truncate_text("\n".join(lines), limit=limit)
    return truncate_text(llm_part, limit=limit)


def parse_json_object(value: str) -> dict[str, Any] | None:
    stripped = value.strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            return None
        stripped = stripped[start : end + 1]
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def format_bullets(items: list[str], *, empty: str) -> list[str]:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        return [f"- {empty}"]
    return [f"- {item}" for item in values]


def dedupe_strings(items: list[str]) -> list[str]:
    deduped = []
    seen = set()
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def summarize_rca_snapshot_for_llm(value: Any) -> Any:
    if not isinstance(value, dict):
        return compact_payload_for_llm(value, char_budget=4000)

    sources = value.get("sources")
    source_summaries = []
    if isinstance(sources, list):
        for source in sources[:12]:
            if not isinstance(source, dict):
                continue
            source_summaries.append(
                {
                    "source": source.get("source"),
                    "status": source.get("status"),
                    "error_message": truncate_text(
                        str(source.get("error_message") or ""),
                        limit=500,
                    ),
                    "summary": compact_payload_for_llm(
                        remove_large_llm_fields(source),
                        char_budget=1800,
                        max_depth=3,
                        list_limit=3,
                        string_limit=400,
                    ),
                }
            )

    return {
        "snapshot_id": value.get("snapshot_id") or value.get("id"),
        "incident_key": value.get("incident_key"),
        "status": value.get("status"),
        "partial": value.get("partial"),
        "created_at": value.get("created_at"),
        "sources": source_summaries,
        "truncated_sources": (
            max(len(sources) - len(source_summaries), 0)
            if isinstance(sources, list)
            else 0
        ),
    }


def summarize_tool_results_for_llm(result: AlertmanagerSrePlanResult) -> list[dict[str, Any]]:
    tool_summaries = []
    for tool_result in result.executed_tools[:LLM_TOOL_RESULT_LIMIT]:
        request_payload = (
            tool_result.masked_request_payload
            if tool_result.masked_request_payload is not None
            else tool_result.request_payload
        )
        response_payload = (
            tool_result.masked_response_payload
            if tool_result.masked_response_payload is not None
            else tool_result.response_payload
        )
        summary = {
            "server_name": tool_result.server_name,
            "tool_name": tool_result.tool_name,
            "call_status": enum_value(tool_result.call_status),
            "will_execute": tool_result.will_execute,
            "request_payload": compact_payload_for_llm(
                remove_large_llm_fields(request_payload),
                char_budget=1200,
                max_depth=3,
                list_limit=3,
                string_limit=300,
            ),
        }
        if tool_result.error_message:
            summary["error_message"] = truncate_text(tool_result.error_message, limit=800)
        response_summary = summarize_tool_response_for_llm(
            response_payload,
            tool_name=tool_result.tool_name,
        )
        if response_summary:
            summary["response_summary"] = response_summary
        tool_summaries.append(summary)

    if len(result.executed_tools) > LLM_TOOL_RESULT_LIMIT:
        tool_summaries.append(
            {"truncated_tools": len(result.executed_tools) - LLM_TOOL_RESULT_LIMIT}
        )
    return tool_summaries


def summarize_tool_response_for_llm(value: Any, *, tool_name: str | None = None) -> Any:
    if not isinstance(value, dict):
        return None
    if tool_name in TOPOLOGY_LLM_TOOLS:
        return summarize_topology_response_for_llm(tool_name, value)

    summary: dict[str, Any] = {}
    for key in (
        "status",
        "source",
        "query",
        "namespace",
        "deployment_name",
        "service_name",
        "resource",
        "partial",
        "target_host",
        "port",
        "url",
        "host_header",
        "path",
        "reachable",
        "healthy",
        "http_status",
        "latency_ms",
        "ready_count",
        "not_ready_count",
        "error_message",
    ):
        if key in value:
            summary[key] = compact_payload_for_llm(
                value.get(key),
                char_budget=500,
                max_depth=2,
                list_limit=3,
                string_limit=300,
            )

    for key in ("items", "sources", "results", "alerts", "events", "data", "matched_rules"):
        if key in value:
            summary[f"{key}_summary"] = summarize_collection_for_llm(value.get(key))
    return summary


def extract_topology_facts_for_llm(
    result: AlertmanagerSrePlanResult,
) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for tool_result in result.executed_tools:
        if tool_result.tool_name not in TOPOLOGY_LLM_TOOLS:
            continue
        response_payload = (
            tool_result.masked_response_payload
            if tool_result.masked_response_payload is not None
            else tool_result.response_payload
        )
        if not isinstance(response_payload, dict):
            continue
        summary = summarize_topology_response_for_llm(
            tool_result.tool_name,
            response_payload,
        )
        if summary:
            facts.append(
                {
                    "tool_name": tool_result.tool_name,
                    "call_status": enum_value(tool_result.call_status),
                    "summary": summary,
                }
            )
    return facts[:LLM_TOPOLOGY_FACT_LIMIT]


def summarize_topology_response_for_llm(
    tool_name: str | None,
    value: dict[str, Any],
) -> dict[str, Any]:
    if tool_name == "search_topology_knowledge":
        return summarize_topology_matches_for_llm(value)
    if tool_name == "get_service_routing_path":
        return summarize_topology_routing_paths_for_llm(value)
    if tool_name == "get_topology_snapshot":
        return summarize_topology_snapshots_for_llm(value)
    if tool_name == "get_service_dependency_map":
        return summarize_topology_dependency_map_for_llm(value)
    return {}


def summarize_topology_matches_for_llm(value: dict[str, Any]) -> dict[str, Any]:
    matches = value.get("matches")
    summarized_matches = []
    if isinstance(matches, list):
        for match in matches[:6]:
            if not isinstance(match, dict):
                continue
            summarized_matches.append(
                {
                    "environment": match.get("environment"),
                    "snapshot_name": match.get("snapshot_name"),
                    "section": match.get("section"),
                    "score": match.get("score"),
                    "excerpt": truncate_text(
                        str(match.get("excerpt") or ""),
                        limit=1600,
                    ),
                }
            )
    return {
        "source": value.get("source"),
        "query": value.get("query"),
        "matches": summarized_matches,
        "match_count": len(matches) if isinstance(matches, list) else 0,
    }


def summarize_topology_routing_paths_for_llm(value: dict[str, Any]) -> dict[str, Any]:
    routing_paths = value.get("routing_paths")
    summarized_paths = []
    if isinstance(routing_paths, list):
        for path in routing_paths[:8]:
            if not isinstance(path, dict):
                continue
            lines = path.get("lines")
            summarized_paths.append(
                {
                    "environment": path.get("environment"),
                    "snapshot_name": path.get("snapshot_name"),
                    "section": path.get("section"),
                    "lines": summarize_topology_lines(lines),
                }
            )
    return {
        "source": value.get("source"),
        "service": value.get("service"),
        "aliases": value.get("aliases"),
        "routing_paths": summarized_paths,
        "path_count": len(routing_paths) if isinstance(routing_paths, list) else 0,
    }


def summarize_topology_snapshots_for_llm(value: dict[str, Any]) -> dict[str, Any]:
    snapshots = value.get("snapshots")
    summarized_snapshots = []
    if isinstance(snapshots, list):
        for snapshot in snapshots[:6]:
            if not isinstance(snapshot, dict):
                continue
            content = str(snapshot.get("content") or "")
            summarized_snapshots.append(
                {
                    "environment": snapshot.get("environment"),
                    "snapshot_name": snapshot.get("snapshot_name"),
                    "collected_date": snapshot.get("collected_date"),
                    "sections": snapshot.get("sections"),
                    "key_facts": extract_topology_key_facts(content),
                }
            )
    return {
        "source": value.get("source"),
        "environment": value.get("environment"),
        "detail": value.get("detail"),
        "snapshots": summarized_snapshots,
        "snapshot_count": len(snapshots) if isinstance(snapshots, list) else 0,
    }


def summarize_topology_dependency_map_for_llm(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "source": value.get("source"),
        "service": value.get("service"),
        "aliases": value.get("aliases"),
        "dependencies": compact_payload_for_llm(
            value.get("dependencies") or value.get("dependency_map") or [],
            char_budget=2500,
            max_depth=3,
            list_limit=6,
            string_limit=600,
        ),
    }


def summarize_topology_lines(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [
        truncate_text(str(line), limit=700)
        for line in value[:12]
        if str(line).strip()
    ]


def extract_topology_key_facts(content: str) -> list[str]:
    if not content:
        return []
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    facts = []
    for line in lines:
        normalized = line.lower()
        if any(keyword in normalized for keyword in TOPOLOGY_FACT_KEYWORDS):
            facts.append(truncate_text(line, limit=900))
        if len(facts) >= 12:
            break
    if facts:
        return facts
    return [truncate_text(content, limit=1800)]


def summarize_collection_for_llm(value: Any) -> Any:
    if isinstance(value, list):
        return {
            "count": len(value),
            "sample": compact_payload_for_llm(
                value[:3],
                char_budget=1600,
                max_depth=3,
                list_limit=3,
                string_limit=300,
            ),
        }
    if isinstance(value, dict):
        return compact_payload_for_llm(
            value,
            char_budget=1600,
            max_depth=3,
            list_limit=3,
            string_limit=300,
        )
    return compact_payload_for_llm(value, char_budget=500)


def compact_payload_for_llm(
    value: Any,
    *,
    char_budget: int,
    max_depth: int = 4,
    list_limit: int = 4,
    string_limit: int = 800,
) -> Any:
    compacted = trim_payload_for_llm(
        remove_large_llm_fields(value),
        max_depth=max_depth,
        list_limit=list_limit,
        string_limit=string_limit,
    )
    if payload_char_size(compacted) <= char_budget:
        return compacted

    smaller = trim_payload_for_llm(
        remove_large_llm_fields(value),
        max_depth=max_depth - 1,
        list_limit=max(1, list_limit // 2),
        string_limit=max(120, string_limit // 2),
    )
    if payload_char_size(smaller) <= char_budget:
        return smaller

    return {
        "truncated": True,
        "excerpt": truncate_text(
            json.dumps(smaller, ensure_ascii=False, default=str),
            limit=char_budget,
        ),
    }


def payload_char_size(value: Any) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str))


def remove_large_llm_fields(value: Any) -> Any:
    if isinstance(value, dict):
        filtered = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text in {
                "context_bundle",
                "raw",
                "raw_tool_results",
                "response_payload",
                "masked_response_payload",
            }:
                filtered[key_text] = summarize_trimmed_value(item)
                continue
            filtered[key_text] = remove_large_llm_fields(item)
        return filtered
    if isinstance(value, list):
        return [remove_large_llm_fields(item) for item in value]
    return value


def trim_payload_for_llm(
    value: Any,
    *,
    max_depth: int = 5,
    list_limit: int = 5,
    string_limit: int = 2000,
) -> Any:
    if max_depth <= 0:
        return summarize_trimmed_value(value)
    if isinstance(value, dict):
        return {
            str(key): trim_payload_for_llm(
                item,
                max_depth=max_depth - 1,
                list_limit=list_limit,
                string_limit=string_limit,
            )
            for key, item in value.items()
            if str(key) != "raw_tool_results"
        }
    if isinstance(value, list):
        trimmed = [
            trim_payload_for_llm(
                item,
                max_depth=max_depth - 1,
                list_limit=list_limit,
                string_limit=string_limit,
            )
            for item in value[:list_limit]
        ]
        if len(value) > list_limit:
            trimmed.append({"truncated_items": len(value) - list_limit})
        return trimmed
    if isinstance(value, str):
        return truncate_text(value, limit=string_limit)
    return value


def summarize_trimmed_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {"trimmed_object_keys": list(value)[:10], "trimmed": True}
    if isinstance(value, list):
        return {"trimmed_list_length": len(value), "trimmed": True}
    if isinstance(value, str):
        return truncate_text(value, limit=300)
    return value


def truncate_text(value: str, *, limit: int) -> str:
    if len(value) <= limit:
        return value
    return f"{value[:limit]}..."


def summarize_tool_execution(result: AlertmanagerSrePlanResult) -> dict[str, Any]:
    failed_tools = [
        tool_result.tool_name
        for tool_result in result.executed_tools
        if enum_value(tool_result.call_status) != "SUCCESS"
    ]
    total_tools = len(result.executed_tools)
    return {
        "total_tools": total_tools,
        "successful_tools": total_tools - len(failed_tools),
        "failed_tools": failed_tools,
    }


def extract_bundle_summary(result: AlertmanagerSrePlanResult) -> dict[str, Any]:
    bundle = result.context_bundle or {}
    summary = bundle.get("summary_for_llm")
    if isinstance(summary, dict):
        return summary
    return {}


def format_alert_target(alert: AlertmanagerSreAlertContext | None) -> str:
    if alert is None:
        return "unknown"
    parts = [
        alert.cluster,
        alert.namespace,
        alert.service_name or alert.workload or alert.pod,
    ]
    return "/".join(part for part in parts if part) or "unknown"


def format_boundary_summary(value: Any) -> str:
    candidates = trim_boundary_candidates(value)
    return ", ".join(
        f"{candidate.get('boundary')}={candidate.get('status')}"
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("boundary")
    )


def trim_boundary_candidates(value: Any, *, limit: int = 6) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    candidates = [candidate for candidate in value if isinstance(candidate, dict)]
    return candidates[:limit]


def compact_list(value: Any, *, limit: int = 8) -> str:
    if not isinstance(value, list):
        return ""
    items = [str(item) for item in value[:limit] if str(item).strip()]
    suffix = " ..." if len(value) > limit else ""
    return ", ".join(items) + suffix


def render_html_table(rows: list[tuple[str, str]]) -> str:
    rendered_rows = "".join(
        "<tr>"
        f"<th>{html.escape(label)}</th>"
        f"<td>{html.escape(value)}</td>"
        "</tr>"
        for label, value in rows
    )
    return (
        "<table border=\"1\" cellpadding=\"6\" cellspacing=\"0\">"
        f"<tbody>{rendered_rows}</tbody>"
        "</table>"
    )


def render_html_section(title: str, items: list[str]) -> str:
    values = [str(item).strip() for item in items if str(item).strip()]
    if not values:
        values = ["none"]
    rendered_items = "".join(f"<li>{html.escape(item)}</li>" for item in values)
    return f"<h3>{html.escape(title)}</h3><ul>{rendered_items}</ul>"


def parse_recipients(value: str) -> list[str]:
    return [recipient.strip() for recipient in value.split(",") if recipient.strip()]


def build_notification_idempotency_key(
    *,
    result: AlertmanagerSrePlanResult,
    channel: str,
    recipient: str | None,
    stage: str = "sre_collection",
) -> str:
    analysis_run_id = ""
    if stage == "sre_analysis":
        analysis = result.rca_analysis or {}
        analysis_run_id = str(analysis.get("llm_run_id") or "")
    seed = "|".join(
        [
            result.incident_key or "unknown-incident",
            (
                result.alert.fingerprint
                if result.alert is not None and result.alert.fingerprint
                else "unknown-fingerprint"
            ),
            channel,
            recipient or "",
            stage,
            analysis_run_id,
        ]
    )
    digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:32]
    return f"{stage}:{digest}"


def format_delivery_error(exc: Exception, *, secret: str | None = None) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    if secret:
        message = message.replace(secret, "[REDACTED]")
    formatted = f"{exc.__class__.__name__}: {message}"
    if len(formatted) <= 500:
        return formatted
    return f"{formatted[:500]}..."


def enum_value(value: object) -> object:
    return getattr(value, "value", value)


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
    pod_name = first_present(labels, "pod", "pod_name")
    service_name = first_present(labels, "service", "service_name", "app", "application")
    workload = first_present(labels, "workload", "deployment", "statefulset", "daemonset", "job")
    normalized_alert_name = normalize_alert_name(alert_name)
    component = first_present(labels, "component", "category", "alert_scope")
    is_k8s_pod_alert = is_kubernetes_pod_health_alert_name(normalized_alert_name) or (
        component is not None and component.lower() in {"pod", "kubernetes", "k8s"}
    )
    if workload is None and pod_name is not None and is_k8s_pod_alert:
        workload = infer_workload_from_pod_name(pod_name)
    if service_name is None and workload is not None and is_k8s_pod_alert:
        service_name = workload
    if service_name is None and (
        normalized_alert_name in POSTGRES_ALERT_NAMES
        or (component is not None and component.lower() in {"database", "postgresql", "postgres"})
    ):
        service_name = "postgresql"
    if workload is None and service_name == "postgresql":
        workload = first_present(labels, "db_role", "db_host") or "postgresql"
    return AlertmanagerSreAlertContext(
        alert_name=alert_name,
        status=alert.status.strip().lower() or "firing",
        severity=first_present(labels, "severity", "priority"),
        cluster=first_present(labels, "cluster", "cluster_name", "source"),
        namespace=resolve_alert_namespace(labels, is_k8s_pod_alert=is_k8s_pod_alert),
        service_name=service_name or workload,
        workload=workload or service_name,
        pod=pod_name,
        fingerprint=normalized_optional(alert.fingerprint) or fingerprint_from_labels(labels),
        starts_at=alert.startsAt,
        ends_at=alert.endsAt,
        summary=first_present(annotations, "summary", "message"),
        description=first_present(annotations, "description", "runbook", "details"),
    )


def resolve_alert_namespace(
    labels: Mapping[str, str],
    *,
    is_k8s_pod_alert: bool,
) -> str | None:
    if is_k8s_pod_alert:
        namespace = first_present(labels, "k8s_namespace", "kubernetes_namespace")
        if namespace is not None:
            return namespace
    return first_present(labels, "namespace", "kubernetes_namespace", "k8s_namespace")


def infer_workload_from_pod_name(pod_name: str) -> str:
    normalized = pod_name.strip()
    deployment_match = re.match(r"^(.+)-[a-f0-9]{8,10}-[a-z0-9]{5}$", normalized)
    if deployment_match is not None:
        return deployment_match.group(1)
    job_match = re.match(r"^(.+)-\d{6,}-[a-z0-9]{5}$", normalized)
    if job_match is not None:
        return job_match.group(1)
    return normalized


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


def normalize_alert_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())


def infer_sre_intent(
    *,
    context: AlertmanagerSreAlertContext,
    labels: Mapping[str, str],
    annotations: Mapping[str, str],
) -> str:
    alert_intent = SRE_INTENT_BY_ALERT_NAME.get(normalize_alert_name(context.alert_name))
    if alert_intent is not None:
        return alert_intent

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

    if any(
        term in signal
        for term in (
            "cloudfront",
            "alb",
            "targetunhealthy",
            "target unhealthy",
            "ingress",
            "metallb",
        )
    ):
        return "routing_failure"
    if "checkout" in signal and any(term in signal for term in ("500", "5xx", "http")):
        return "checkout_500"
    if "sqs" in signal and any(
        term in signal for term in ("publish", "producer", "send", "sendmessage")
    ):
        return "sqs_publish_failure"
    if any(term in signal for term in ("sqs", "queue", "dlq")) and any(
        term in signal
        for term in ("consume", "consumer", "listener", "lag", "dlq", "messagesvisible")
    ):
        return "sqs_consume_failure"
    if "pin" in signal and any(
        term in signal for term in ("verification", "verified", "event", "missing")
    ):
        return "pin_verification_missing"
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
    routing_phrase = build_routing_analysis_phrase(context)
    intent_phrases = {
        "checkout_500": "checkout 500 error analysis",
        "sqs_publish_failure": "SQS publish failure analysis",
        "sqs_consume_failure": "SQS consume failure DLQ lag analysis",
        "pin_verification_missing": "PIN verification event missing analysis",
        "routing_failure": routing_phrase,
        "pod_crashloop": "pod CrashLoopBackOff restart analysis",
        "db_hikaricp_issue": "DB HikariCP connection pool analysis",
        "general_incident": "on-prem AWS Kubernetes SRE general incident analysis",
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


def build_routing_analysis_phrase(context: AlertmanagerSreAlertContext) -> str:
    signal = " ".join(
        value
        for value in [
            context.cluster or "",
            context.service_name or "",
            context.workload or "",
            context.summary or "",
            context.description or "",
        ]
        if value
    ).lower()
    onprem_services = {"service-auth", "service-payment", "service-core", "service-admin"}
    if context.service_name in onprem_services or any(
        term in signal for term in ("on-prem", "onprem", "metallb", "metal lb")
    ):
        return "CloudFront ALB on-prem MetalLB routing failure analysis"
    if any(term in signal for term in ("eks", "aws", "service-catalog", "catalog")):
        return "CloudFront ALB EKS routing failure analysis"
    return "CloudFront ALB routing failure analysis"


def build_incident_window(
    *,
    alert: AlertmanagerAlert,
    now: datetime,
    lookback: timedelta = DEFAULT_INCIDENT_LOOKBACK,
) -> AlertmanagerIncidentWindow:
    anchor_time = parse_alert_datetime(alert.startsAt) or now
    start = anchor_time - lookback
    end = select_incident_end_time(alert=alert, now=now, anchor_time=anchor_time)
    return AlertmanagerIncidentWindow(
        anchor_time=format_datetime(anchor_time),
        start=format_datetime(start),
        end=format_datetime(end),
        lookback_seconds=int(lookback.total_seconds()),
    )


def select_incident_end_time(
    *,
    alert: AlertmanagerAlert,
    now: datetime,
    anchor_time: datetime,
) -> datetime:
    parsed_end = parse_alert_datetime(alert.endsAt)
    if parsed_end is None or parsed_end.year < 2000 or parsed_end < anchor_time:
        return now
    return max(parsed_end, now)


def parse_alert_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    normalized = value.strip()
    if not normalized:
        return None
    if normalized.endswith("Z"):
        normalized = f"{normalized[:-1]}+00:00"
    try:
        return normalize_datetime(datetime.fromisoformat(normalized))
    except ValueError:
        return None


def normalize_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def format_datetime(value: datetime) -> str:
    return normalize_datetime(value).isoformat().replace("+00:00", "Z")


def is_read_tool_plan(tool_plan: AgentToolPlan) -> bool:
    try:
        tool = resolve_registered_tool(
            server_name=tool_plan.server_name,
            tool_name=tool_plan.tool_name,
        )
    except ValueError:
        return False
    return McpToolPermission(tool.tool_permission) == McpToolPermission.READ


def inject_alertmanager_execution_context(
    tool_plan: AgentToolPlan,
    *,
    incident_key: str | None,
    incident_window: AlertmanagerIncidentWindow,
) -> AgentToolPlan:
    payload = dict(tool_plan.request_payload)
    if tool_plan.tool_name in LOG_TIME_WINDOW_TOOLS:
        payload.setdefault("start", incident_window.start)
        payload.setdefault("end", incident_window.end)
    if tool_plan.tool_name in TRACE_TIME_WINDOW_TOOLS:
        payload.setdefault("start", format_epoch_seconds(incident_window.start))
        payload.setdefault("end", format_epoch_seconds(incident_window.end))
    if tool_plan.tool_name in OBSERVABILITY_POINT_TIME_TOOLS:
        payload.setdefault("time", incident_window.end)
    if tool_plan.tool_name == "get_pod_logs":
        payload.setdefault("since_seconds", incident_window.lookback_seconds)
    if tool_plan.tool_name == "create_rca_snapshot" and incident_key is not None:
        payload["incident_key"] = incident_key
    return tool_plan.model_copy(update={"request_payload": payload})


def format_epoch_seconds(value: str) -> str:
    parsed = parse_alert_datetime(value)
    if parsed is None:
        return value
    return str(int(parsed.timestamp()))
