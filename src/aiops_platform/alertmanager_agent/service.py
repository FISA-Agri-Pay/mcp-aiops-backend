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
from aiops_platform.agent.schemas import AgentToolPlan
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
    "hikaripoolexhausted": "db_hikaricp_issue",
    "hikariconnectionpoolstarvation": "db_hikaricp_issue",
    "dbconnectionfailure": "db_hikaricp_issue",
    "postgresconnectionfailure": "db_hikaricp_issue",
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
            return build_rca_analysis_payload(llm_run)
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
    stats = summarize_tool_execution(result)
    summary = extract_bundle_summary(result)
    alert = result.alert
    incident_window = result.incident_window
    target = format_alert_target(alert)
    failed_tools = compact_list(stats["failed_tools"])
    sections = compact_list(summary.get("available_sections", []))
    boundaries = format_boundary_summary(
        summary.get("failure_boundary_candidates", [])
    )
    lines = [
        build_collection_notification_subject(result),
        f"- incident: {result.incident_key or 'unknown'}",
        f"- target: {target}",
        f"- status: {result.status} / intent: {result.intent or 'unknown'}",
        (
            "- window: "
            f"{incident_window.start} ~ {incident_window.end}"
            if incident_window is not None
            else "- window: unknown"
        ),
        (
            "- tools: "
            f"{stats['successful_tools']}/{stats['total_tools']} succeeded"
        ),
        f"- failed_tools: {failed_tools or 'none'}",
        f"- evidence_sections: {sections or 'none'}",
        f"- boundaries: {boundaries or 'unknown'}",
        "- note: raw logs, traces, and secrets are not included in this notification.",
    ]
    return "\n".join(lines)


def build_collection_notification_html(result: AlertmanagerSrePlanResult) -> str:
    stats = summarize_tool_execution(result)
    summary = extract_bundle_summary(result)
    alert = result.alert
    incident_window = result.incident_window
    rows = [
        ("Incident", result.incident_key or ""),
        ("Alert", alert.alert_name if alert is not None else ""),
        ("Target", format_alert_target(alert)),
        ("Severity", alert.severity if alert is not None and alert.severity else ""),
        ("Intent", result.intent or ""),
        ("Capability", result.capability or ""),
        (
            "Window",
            (
                f"{incident_window.start} ~ {incident_window.end}"
                if incident_window is not None
                else ""
            ),
        ),
        (
            "Tool Success",
            f"{stats['successful_tools']}/{stats['total_tools']}",
        ),
        ("Failed Tools", compact_list(stats["failed_tools"]) or "none"),
        (
            "Evidence Sections",
            compact_list(summary.get("available_sections", [])) or "none",
        ),
        (
            "Missing Sections",
            compact_list(summary.get("missing_sections", [])) or "none",
        ),
        (
            "Cross Domain",
            str(summary.get("cross_domain_scenario") or ""),
        ),
        (
            "Boundary Candidates",
            format_boundary_summary(summary.get("failure_boundary_candidates", []))
            or "unknown",
        ),
    ]
    return (
        "<html><body>"
        "<h2>AIOps SRE RCA evidence collected</h2>"
        "<p>Alertmanager triggered read-only RCA evidence collection. "
        "Raw logs, traces, and secret-like values are not included in this email.</p>"
        f"{render_html_table(rows)}"
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
    payload = {
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
        "topology_facts": extract_topology_facts_for_llm(result),
        "rca_snapshot": summarize_rca_snapshot_for_llm(result.rca_snapshot),
    }
    return compact_payload_for_llm(
        payload,
        char_budget=LLM_SNAPSHOT_CHAR_BUDGET,
        max_depth=6,
        list_limit=8,
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


def build_rca_analysis_payload(llm_run: LlmRunResult) -> dict[str, Any]:
    answer = str(llm_run.masked_output.get("answer") or "").strip()
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
    answer = str(analysis.get("answer") or "").strip()
    last_error = str(analysis.get("last_error") or "").strip()
    if run_status != "SUCCESS":
        answer = last_error or "LLM RCA analysis did not complete successfully."
    lines = [
        build_analysis_notification_subject(result),
        f"- incident: {result.incident_key or 'unknown'}",
        f"- target: {format_alert_target(result.alert)}",
        f"- llm_status: {run_status}",
        "- answer:",
        truncate_text(answer or "No RCA answer was generated.", limit=3500),
        "- note: destructive remediation was not executed.",
    ]
    return "\n".join(lines)


def build_analysis_notification_html(result: AlertmanagerSrePlanResult) -> str:
    analysis = result.rca_analysis or {}
    run_status = str(analysis.get("run_status") or "UNKNOWN")
    answer = str(analysis.get("answer") or "").strip()
    last_error = str(analysis.get("last_error") or "").strip()
    if run_status != "SUCCESS":
        answer = last_error or "LLM RCA analysis did not complete successfully."
    rows = [
        ("Incident", result.incident_key or ""),
        ("Alert", result.alert.alert_name if result.alert is not None else ""),
        ("Target", format_alert_target(result.alert)),
        ("Intent", result.intent or ""),
        ("LLM Status", run_status),
        ("LLM Run", str(analysis.get("llm_run_id") or "")),
    ]
    return (
        "<html><body>"
        "<h2>AIOps SRE RCA analysis completed</h2>"
        f"{render_html_table(rows)}"
        "<h3>Analysis</h3>"
        "<pre>"
        f"{html.escape(truncate_text(answer or 'No RCA answer was generated.', limit=8000))}"
        "</pre>"
        "<p>Destructive remediation was not executed.</p>"
        "</body></html>"
    )


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
        ends_at=alert.endsAt,
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
