from __future__ import annotations

import re
from typing import Any

from aiops_platform.agent.schemas import AgentToolExecutionResult

TOPOLOGY_TOOLS = {
    "get_topology_snapshot": "snapshots",
    "search_topology_knowledge": "search_matches",
    "get_service_routing_path": "routing_paths",
    "get_service_dependency_map": "dependency_map",
}
METRIC_TOOLS = {
    "query_prometheus": "prometheus",
    "query_multi_cluster_prometheus": "multi_cluster_prometheus",
}
LOG_TOOLS = {
    "query_loki": "loki",
    "query_multi_cluster_loki": "multi_cluster_loki",
    "get_pod_logs": "pod_logs",
    "query_elasticsearch": "elasticsearch",
    "search_elasticsearch_logs": "elasticsearch_logs",
}
TRACE_TOOLS = {
    "search_traces": "trace_search",
    "get_trace_by_id": "trace_detail",
    "get_service_trace_summary": "service_trace_summary",
    "get_trace_error_spans": "trace_error_spans",
}
ALERT_TOOLS = {"get_alertmanager_alerts": "alertmanager"}
KUBERNETES_TOOLS = {
    "get_k8s_pods": "pods",
    "get_k8s_events": "events",
    "get_k8s_deployments": "deployments",
    "get_k8s_hpa": "hpa",
    "get_rollout_status": "rollout_status",
}
AWS_TOOLS = {
    "get_sqs_queue_attributes": "sqs_queue",
    "get_sqs_dlq_attributes": "sqs_dlq",
    "get_alb_target_health": "alb_target_health",
    "get_cloudfront_origin_mapping": "cloudfront_origin_mapping",
    "get_cloudfront_distribution_status": "cloudfront_distribution_status",
}
DEPLOYMENT_CHANGE_TOOLS = {
    "get_argocd_application_status": "argocd_application",
    "get_current_image_tags": "current_image_tags",
    "get_recent_deployments": "recent_deployments",
}
HISTORY_TOOLS = {
    "search_incidents": "similar_incidents",
    "search_rca_history": "rca_history",
}
CROSS_DOMAIN_SCENARIOS = {
    "direct_onprem_ingress_routing": {
        "description": "DNS -> on-prem MetalLB -> ingress -> service -> pod routing.",
        "path": [
            "dns",
            "onprem_metallb",
            "onprem_ingress",
            "k8s_service",
            "pod_application",
        ],
    },
    "edge_to_eks_routing": {
        "description": "CloudFront -> AWS ALB -> EKS service/pod routing.",
        "path": [
            "cloudfront",
            "aws_alb",
            "aws_target_group",
            "eks_ingress",
            "k8s_service",
            "pod_application",
        ],
    },
    "edge_to_onprem_routing": {
        "description": "CloudFront -> AWS ALB -> VPN/on-prem MetalLB -> ingress -> pod.",
        "path": [
            "cloudfront",
            "aws_alb",
            "aws_target_group",
            "vpn_route",
            "onprem_metallb",
            "onprem_ingress",
            "pod_application",
        ],
    },
    "onprem_to_sqs": {
        "description": "On-prem service -> DNS/network/VPN -> AWS SQS.",
        "path": ["pod_application", "dns", "vpn_route", "aws_sqs"],
    },
    "onprem_to_tempo": {
        "description": "On-prem OTel Java Agent/Collector -> AWS ELB -> Tempo.",
        "path": ["pod_application", "onprem_otel_collector", "vpn_route", "aws_tempo"],
    },
    "onprem_to_loki": {
        "description": "On-prem Fluent Bit/app logs -> AWS/EKS Loki.",
        "path": ["pod_application", "onprem_fluent_bit", "vpn_route", "aws_loki"],
    },
    "general_cross_domain": {
        "description": "General on-prem/AWS SRE path with insufficient scenario signal.",
        "path": ["topology", "pod_application", "network", "aws_service"],
    },
}
BOUNDARY_TOOL_MAP = {
    "cloudfront": {"get_cloudfront_origin_mapping", "get_cloudfront_distribution_status"},
    "aws_alb": {"get_alb_target_health"},
    "aws_target_group": {"get_alb_target_health"},
    "vpn_route": {"get_topology_snapshot", "search_topology_knowledge", "get_service_routing_path"},
    "onprem_metallb": {"get_topology_snapshot", "get_service_routing_path"},
    "onprem_ingress": {"get_service_routing_path", "get_k8s_events", "query_multi_cluster_loki"},
    "eks_ingress": {"get_service_routing_path", "get_alb_target_health", "get_k8s_events"},
    "k8s_service": {"get_k8s_pods", "get_k8s_events", "get_k8s_deployments"},
    "pod_application": {
        "query_multi_cluster_loki",
        "query_loki",
        "get_pod_logs",
        "search_traces",
        "get_service_trace_summary",
        "get_trace_error_spans",
    },
    "dns": {"query_multi_cluster_loki", "query_loki", "get_k8s_events", "get_service_routing_path"},
    "aws_sqs": {"get_sqs_queue_attributes", "get_sqs_dlq_attributes"},
    "onprem_otel_collector": {
        "get_topology_snapshot",
        "search_topology_knowledge",
        "search_traces",
        "get_service_trace_summary",
    },
    "aws_tempo": {"search_traces", "get_service_trace_summary", "get_trace_error_spans"},
    "onprem_fluent_bit": {
        "get_topology_snapshot",
        "search_topology_knowledge",
        "query_multi_cluster_loki",
        "query_loki",
    },
    "aws_loki": {"query_multi_cluster_loki", "query_loki"},
    "topology": set(TOPOLOGY_TOOLS),
    "network": {"get_topology_snapshot", "search_topology_knowledge", "get_service_routing_path"},
    "aws_service": set(AWS_TOOLS),
}
BOUNDARY_EXPECTED_SIGNALS = {
    "cloudfront": "Distribution deployed and origin mapping points to expected ALB.",
    "aws_alb": "ALB listener/rule and load balancer are reachable.",
    "aws_target_group": "Target group reports healthy targets.",
    "vpn_route": "AWS route/VPN path to on-prem CIDR is present.",
    "onprem_metallb": "MetalLB entrypoint exists and target IP is reachable.",
    "onprem_ingress": "Ingress routes traffic to the expected ClusterIP/service.",
    "eks_ingress": "EKS ALB/Ingress routes to expected service target group.",
    "k8s_service": "Service endpoints and pods are ready.",
    "pod_application": "Application logs/traces do not show request handling errors.",
    "dns": "Pod DNS resolution does not show SERVFAIL/lookup failures.",
    "aws_sqs": "Queue and DLQ attributes show no backlog or permission failure.",
    "onprem_otel_collector": "OTel collector receives and forwards spans.",
    "aws_tempo": "Tempo query/search returns expected traces.",
    "onprem_fluent_bit": "Fluent Bit forwards logs to the configured Loki endpoint.",
    "aws_loki": "Loki query returns expected logs.",
    "topology": "Topology knowledge contains the expected path.",
    "network": "Network route between domains is known and observable.",
    "aws_service": "AWS managed service status is readable and healthy.",
}
DEGRADED_PATTERNS = (
    re.compile(r"\bnot[\s_-]*ready\b"),
    re.compile(r"\bnot[\s_-]*healthy\b"),
    re.compile(r"\bunhealthy\b"),
    re.compile(r"\bdegraded\b"),
    re.compile(r"\bfailed\b"),
    re.compile(r"\bfailure\b"),
    re.compile(r"\bdown\b"),
    re.compile(r"\bcrashloop\b"),
    re.compile(r"\bcrashloopbackoff\b"),
    re.compile(r"\bimagepullbackoff\b"),
    re.compile(r"\boomkilled\b"),
    re.compile(r"\bservfail\b"),
    re.compile(r"\btimeout\b"),
    re.compile(r"\bexception\b"),
    re.compile(r"\berror\b"),
    re.compile(r"\b5\d\d\b"),
    re.compile(r"\b5xx\b"),
)
BOUNDARY_DEGRADED_PATTERNS = {
    "dns": (
        re.compile(r"\bservfail\b"),
        re.compile(r"\bnxdomain\b"),
        re.compile(r"\btemporary failure in name resolution\b"),
        re.compile(r"\bno such host\b"),
        re.compile(r"\bcould not resolve\b"),
        re.compile(r"\bdns\b.{0,80}\b(fail|error|timeout)\b"),
        re.compile(r"\blookup\b.{0,80}\b(fail|error|timeout)\b"),
    ),
    "onprem_metallb": (
        re.compile(r"\bmetallb\b.{0,80}\b(fail|error|timeout|unavailable|down)\b"),
        re.compile(r"\bspeaker\b.{0,80}\b(fail|error|timeout|unavailable|down)\b"),
        re.compile(r"\barp\b.{0,80}\b(fail|timeout|unreachable)\b"),
        re.compile(r"\b10\.30\.2\.100\b.{0,80}\b(timeout|unreachable|no route)\b"),
        re.compile(r"\bno route to host\b"),
    ),
    "onprem_ingress": (
        re.compile(r"\bingress\b.{0,80}\b(5xx|500|502|503|504|error|timeout|fail)\b"),
        re.compile(r"\bupstream\b.{0,80}\b(unavailable|timeout|timed out|connect.*failed)\b"),
        re.compile(r"\bdefault backend\b"),
        re.compile(r"\bno ingress rule\b"),
    ),
    "k8s_service": (
        re.compile(r"\bno endpoints\b"),
        re.compile(r"\bempty endpoints\b"),
        re.compile(r"\bendpoint(slice)?\b.{0,80}\b(empty|missing|not ready)\b"),
        re.compile(r"\bselector mismatch\b"),
        re.compile(r"\bnot[\s_-]*ready\b"),
        re.compile(r"\bunavailable\b"),
        re.compile(r"\bcrashloop(backoff)?\b"),
        re.compile(r"\bimagepullbackoff\b"),
        re.compile(r"\boomkilled\b"),
    ),
}
HEALTHY_PATTERNS = (
    re.compile(r"\bhealthy\b"),
    re.compile(r"\brunning\b"),
    re.compile(r"\bready\b"),
    re.compile(r"\bactive\b"),
    re.compile(r"\bdeployed\b"),
    re.compile(r"\bsynced\b"),
    re.compile(r"\bsuccess\b"),
    re.compile(r"\bsucceeded\b"),
)
IGNORED_EVIDENCE_KEYS = {
    "query",
    "request",
    "request_payload",
    "masked_request_payload",
}


def build_incident_context_bundle(
    *,
    chat_type: str,
    message: str,
    capability: str | None,
    tool_results: list[AgentToolExecutionResult],
) -> dict[str, Any]:
    bundle: dict[str, Any] = {
        "schema_version": "incident_context_bundle.v1",
        "chat_type": chat_type,
        "message": message,
        "capability": capability,
        "topology": {},
        "live_state": {
            "kubernetes": {},
            "aws": {},
            "gitops": {},
        },
        "observability": {
            "metrics": {},
            "logs": {},
            "traces": {},
            "alerts": {},
        },
        "deployment_changes": {},
        "history": {},
        "rca_snapshot": {},
        "cross_domain": {},
        "failure_boundary_candidates": [],
        "raw_tool_results": [],
        "summary_for_llm": {},
    }

    for result in tool_results:
        entry = compact_tool_result(result)
        bundle["raw_tool_results"].append(
            compact_tool_result(result, include_response=False)
        )
        tool_name = result.tool_name
        if tool_name in TOPOLOGY_TOOLS:
            append_entry(bundle["topology"], TOPOLOGY_TOOLS[tool_name], entry)
        elif tool_name in METRIC_TOOLS:
            append_entry(bundle["observability"]["metrics"], METRIC_TOOLS[tool_name], entry)
        elif tool_name in LOG_TOOLS:
            append_entry(bundle["observability"]["logs"], LOG_TOOLS[tool_name], entry)
        elif tool_name in TRACE_TOOLS:
            append_entry(bundle["observability"]["traces"], TRACE_TOOLS[tool_name], entry)
        elif tool_name in ALERT_TOOLS:
            append_entry(bundle["observability"]["alerts"], ALERT_TOOLS[tool_name], entry)
        elif tool_name in KUBERNETES_TOOLS:
            append_entry(bundle["live_state"]["kubernetes"], KUBERNETES_TOOLS[tool_name], entry)
        elif tool_name in AWS_TOOLS:
            append_entry(bundle["live_state"]["aws"], AWS_TOOLS[tool_name], entry)
        elif tool_name in DEPLOYMENT_CHANGE_TOOLS:
            append_entry(
                bundle["deployment_changes"],
                DEPLOYMENT_CHANGE_TOOLS[tool_name],
                entry,
            )
            append_entry(
                bundle["live_state"]["gitops"],
                DEPLOYMENT_CHANGE_TOOLS[tool_name],
                entry,
            )
        elif tool_name in HISTORY_TOOLS:
            append_entry(bundle["history"], HISTORY_TOOLS[tool_name], entry)
        elif tool_name == "create_rca_snapshot":
            append_entry(bundle["rca_snapshot"], "created_snapshots", entry)

    scenario = infer_cross_domain_scenario(
        message=message,
        capability=capability,
        tool_results=tool_results,
    )
    target_workloads = extract_target_workloads(message=message, tool_results=tool_results)
    boundary_candidates = build_failure_boundary_candidates(
        scenario=scenario,
        tool_results=tool_results,
        target_workloads=target_workloads,
    )
    scenario_definition = CROSS_DOMAIN_SCENARIOS[scenario]
    bundle["cross_domain"] = {
        "scenario": scenario,
        "description": scenario_definition["description"],
        "path": scenario_definition["path"],
        "boundary_candidates": boundary_candidates,
    }
    bundle["failure_boundary_candidates"] = boundary_candidates
    bundle["summary_for_llm"] = summarize_bundle(tool_results=tool_results, bundle=bundle)
    return bundle


def compact_tool_result(
    result: AgentToolExecutionResult,
    *,
    include_response: bool = True,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "server_name": result.server_name,
        "tool_name": result.tool_name,
        "call_status": enum_value(result.call_status),
        "will_execute": result.will_execute,
        "request_payload": prefer_masked_payload(
            result.masked_request_payload,
            result.request_payload,
        ),
    }
    if result.error_message:
        entry["error_message"] = result.error_message
    if include_response:
        entry["response_payload"] = prefer_masked_payload(
            result.masked_response_payload,
            result.response_payload,
        )
    return entry


def prefer_masked_payload(masked_payload: Any, original_payload: Any) -> Any:
    if masked_payload is not None:
        return masked_payload
    return original_payload


def append_entry(target: dict[str, Any], key: str, entry: dict[str, Any]) -> None:
    target.setdefault(key, []).append(entry)


def summarize_bundle(
    *,
    tool_results: list[AgentToolExecutionResult],
    bundle: dict[str, Any],
) -> dict[str, Any]:
    failed_tools = [
        result.tool_name
        for result in tool_results
        if enum_value(result.call_status) != "SUCCESS"
    ]
    available_sections = [
        section
        for section, present in {
            "topology": bool(bundle["topology"]),
            "metrics": bool(bundle["observability"]["metrics"]),
            "logs": bool(bundle["observability"]["logs"]),
            "traces": bool(bundle["observability"]["traces"]),
            "alerts": bool(bundle["observability"]["alerts"]),
            "kubernetes": bool(bundle["live_state"]["kubernetes"]),
            "aws": bool(bundle["live_state"]["aws"]),
            "deployment_changes": bool(bundle["deployment_changes"]),
            "history": bool(bundle["history"]),
            "rca_snapshot": bool(bundle["rca_snapshot"]),
            "cross_domain": bool(bundle["cross_domain"]),
        }.items()
        if present
    ]
    missing_sections = [
        section
        for section in (
            "topology",
            "metrics",
            "logs",
            "traces",
            "kubernetes",
            "deployment_changes",
        )
        if section not in available_sections
    ]
    return {
        "total_tools": len(tool_results),
        "successful_tools": len(tool_results) - len(failed_tools),
        "failed_tools": failed_tools,
        "available_sections": available_sections,
        "missing_sections": missing_sections,
        "cross_domain_scenario": bundle["cross_domain"].get("scenario"),
        "failure_boundary_candidates": [
            {
                "boundary": candidate["boundary"],
                "status": candidate["status"],
                "confidence": candidate["confidence"],
            }
            for candidate in bundle["failure_boundary_candidates"]
        ],
        "analysis_contract": (
            "Use topology for routing context, live_state for current infrastructure "
            "state, observability for metrics/logs/traces/alerts, deployment_changes "
            "for recent rollout correlation, history for prior incident comparison, "
            "and failure_boundary_candidates to decide where the cross-domain path breaks."
        ),
    }


def enum_value(value: object) -> object:
    return getattr(value, "value", value)


def infer_cross_domain_scenario(
    *,
    message: str,
    capability: str | None,
    tool_results: list[AgentToolExecutionResult],
) -> str:
    normalized = f"{message} {capability or ''}".lower()
    tool_names = {result.tool_name for result in tool_results}
    if topology_indicates_direct_onprem_entrypoint(tool_results):
        return "direct_onprem_ingress_routing"
    if any(keyword in normalized for keyword in ("sqs", "queue", "dlq", "pin")):
        return "onprem_to_sqs"
    if any(keyword in normalized for keyword in ("fluent", "fluent-bit", "loki")):
        return "onprem_to_loki"
    if any(keyword in normalized for keyword in ("tempo", "otel")):
        return "onprem_to_tempo"
    if any(keyword in normalized for keyword in ("metallb", "on-prem", "onprem")):
        return "edge_to_onprem_routing"
    if (
        "get_cloudfront_origin_mapping" in tool_names
        or "get_alb_target_health" in tool_names
        or any(keyword in normalized for keyword in ("cloudfront", "alb", "eks", "checkout"))
    ):
        if any(keyword in normalized for keyword in ("auth", "admin", "core", "service-auth")):
            return "edge_to_onprem_routing"
        return "edge_to_eks_routing"
    return "general_cross_domain"


def topology_indicates_direct_onprem_entrypoint(
    tool_results: list[AgentToolExecutionResult],
) -> bool:
    topology_payloads = [
        empty_payload_if_none(
            prefer_masked_payload(
                result.masked_response_payload,
                result.response_payload,
            )
        )
        for result in tool_results
        if result.tool_name in TOPOLOGY_TOOLS
    ]
    if not topology_payloads:
        return False

    evidence_text = " ".join(
        stringify_evidence_payload(payload) for payload in topology_payloads
    ).lower()
    has_service = "service-payment" in evidence_text or "api-payment" in evidence_text
    has_onprem_entrypoint = (
        ("api-payment.dev6.fisa" in evidence_text and "10.30.2.100" in evidence_text)
        or ("on-prem metallb" in evidence_text and "direct" in evidence_text)
        or ("onprem metallb" in evidence_text and "direct" in evidence_text)
    )
    cloudfront_is_not_primary = any(
        phrase in evidence_text
        for phrase in (
            "not visible cloudfront",
            "not the current direct path",
            "not visible aws cloudfront",
            "not aws eks",
            "not an aws eks workload",
            "not a visible cloudfront",
            "cloudfront is not",
        )
    )
    return has_service and has_onprem_entrypoint and cloudfront_is_not_primary


def build_failure_boundary_candidates(
    *,
    scenario: str,
    tool_results: list[AgentToolExecutionResult],
    target_workloads: set[str] | None = None,
) -> list[dict[str, Any]]:
    candidates = []
    for boundary in CROSS_DOMAIN_SCENARIOS[scenario]["path"]:
        evidence_results = [
            result
            for result in tool_results
            if result.tool_name in BOUNDARY_TOOL_MAP.get(boundary, set())
        ]
        status, confidence, reason = assess_boundary_evidence(
            boundary=boundary,
            evidence_results=evidence_results,
            target_workloads=target_workloads or set(),
        )
        context_evidence_tools = sorted(
            {result.tool_name for result in evidence_results if is_topology_tool(result)}
        )
        health_evidence_tools = sorted(
            {result.tool_name for result in evidence_results if not is_topology_tool(result)}
        )
        candidates.append(
            {
                "boundary": boundary,
                "status": status,
                "confidence": confidence,
                "expected_signal": BOUNDARY_EXPECTED_SIGNALS.get(boundary),
                "evidence_tools": sorted({result.tool_name for result in evidence_results}),
                "context_evidence_tools": context_evidence_tools,
                "health_evidence_tools": health_evidence_tools,
                "evidence_count": len(evidence_results),
                "reason": reason,
            }
        )
    return candidates


def assess_boundary_evidence(
    *,
    boundary: str,
    evidence_results: list[AgentToolExecutionResult],
    target_workloads: set[str],
) -> tuple[str, str, str]:
    if not evidence_results:
        return "unknown", "low", "No direct evidence tool result is available for this boundary."

    context_results = [result for result in evidence_results if is_topology_tool(result)]
    health_results = [result for result in evidence_results if not is_topology_tool(result)]
    if health_results:
        return assess_health_evidence(
            boundary=boundary,
            evidence_results=health_results,
            target_workloads=target_workloads,
        )

    if any(enum_value(result.call_status) != "SUCCESS" for result in context_results):
        return "unknown", "medium", "At least one evidence tool did not complete successfully."

    if context_results:
        return (
            "known_path",
            "low",
            "Topology knowledge describes this boundary/path; "
            "no live health evidence was evaluated.",
        )
    return "unknown", "low", "Evidence exists but no live health signal is available."


def assess_health_evidence(
    *,
    boundary: str,
    evidence_results: list[AgentToolExecutionResult],
    target_workloads: set[str],
) -> tuple[str, str, str]:
    if any(enum_value(result.call_status) != "SUCCESS" for result in evidence_results):
        return "unknown", "medium", "At least one live evidence tool did not complete successfully."

    evidence_text = " ".join(
        stringify_evidence_payload(
            evidence_payload_for_boundary(
                result=result,
                boundary=boundary,
                target_workloads=target_workloads,
            )
        )
        for result in evidence_results
    )
    if contains_degraded_signal(evidence_text, boundary=boundary):
        return (
            "degraded",
            "medium",
            "Live evidence payload contains boundary-specific degraded/error markers.",
        )
    if contains_healthy_signal(evidence_text):
        confidence = "high" if len(evidence_results) >= 2 else "medium"
        return "healthy", confidence, "Live evidence payload contains healthy/ready markers."
    return "unknown", "low", "Live evidence exists but does not contain clear health markers."


def is_topology_tool(result: AgentToolExecutionResult) -> bool:
    return result.tool_name in TOPOLOGY_TOOLS


def evidence_payload_for_boundary(
    *,
    result: AgentToolExecutionResult,
    boundary: str,
    target_workloads: set[str],
) -> Any:
    payload = empty_payload_if_none(
        prefer_masked_payload(
            result.masked_response_payload,
            result.response_payload,
        )
    )
    if boundary != "k8s_service" or result.tool_name not in KUBERNETES_TOOLS:
        return payload
    filtered_payload = filter_kubernetes_payload_to_workloads(payload, target_workloads)
    return summarize_kubernetes_health_payload(filtered_payload)


def extract_target_workloads(
    *,
    message: str,
    tool_results: list[AgentToolExecutionResult],
) -> set[str]:
    workloads: set[str] = set()
    for pattern in (
        r"\b(?:service|service_name|deployment|workload|app)[=:]\s*([a-z0-9][a-z0-9-]{1,80})\b",
        r"\b(service-[a-z0-9-]{1,80})\b",
    ):
        workloads.update(match.group(1) for match in re.finditer(pattern, message.lower()))

    for result in tool_results:
        request_payload = prefer_masked_payload(
            result.masked_request_payload,
            result.request_payload,
        )
        if isinstance(request_payload, dict):
            for key in ("service", "service_name", "deployment_name", "workload", "app"):
                value = request_payload.get(key)
                if isinstance(value, str) and is_workload_like(value):
                    workloads.add(value.lower())
    return workloads


def is_workload_like(value: str) -> bool:
    return bool(re.fullmatch(r"[a-z0-9][a-z0-9-]{1,80}", value.lower()))


def filter_kubernetes_payload_to_workloads(payload: Any, workloads: set[str]) -> Any:
    if not workloads:
        return payload
    if isinstance(payload, dict):
        filtered_payload = dict(payload)
        items = payload.get("items")
        if isinstance(items, list):
            filtered_payload["items"] = [
                item for item in items if kubernetes_item_matches_workload(item, workloads)
            ]
        return filtered_payload
    if isinstance(payload, list):
        return [
            item for item in payload if kubernetes_item_matches_workload(item, workloads)
        ]
    return payload


def summarize_kubernetes_health_payload(payload: Any) -> Any:
    if isinstance(payload, dict):
        summarized_payload = dict(payload)
        items = payload.get("items")
        if isinstance(items, list):
            summarized_payload["items"] = [
                summarize_kubernetes_health_item(item) for item in items
            ]
        return summarized_payload
    if isinstance(payload, list):
        return [summarize_kubernetes_health_item(item) for item in payload]
    return payload


def summarize_kubernetes_health_item(item: Any) -> Any:
    if not isinstance(item, dict):
        return item
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    status = item.get("status") if isinstance(item.get("status"), dict) else {}
    involved_object = item.get("involvedObject") or item.get("regarding")

    summary: dict[str, Any] = {
        "name": metadata.get("name"),
        "labels": metadata.get("labels"),
        "phase": status.get("phase"),
        "ready_replicas": status.get("readyReplicas"),
        "available_replicas": status.get("availableReplicas"),
        "updated_replicas": status.get("updatedReplicas"),
        "unavailable_replicas": status.get("unavailableReplicas"),
        "conditions": summarize_kubernetes_conditions(status.get("conditions")),
        "container_statuses": summarize_container_statuses(
            status.get("containerStatuses")
        ),
    }
    if isinstance(involved_object, dict):
        summary["involved_object"] = {
            "kind": involved_object.get("kind"),
            "name": involved_object.get("name"),
        }
    for key in ("type", "reason", "message", "note"):
        value = item.get(key)
        if value is not None:
            summary[key] = value
    return {key: value for key, value in summary.items() if value not in (None, [], {})}


def summarize_kubernetes_conditions(conditions: Any) -> list[dict[str, Any]]:
    if not isinstance(conditions, list):
        return []
    return [
        {
            key: condition.get(key)
            for key in ("type", "status", "reason", "message")
            if condition.get(key) is not None
        }
        for condition in conditions
        if isinstance(condition, dict)
    ]


def summarize_container_statuses(container_statuses: Any) -> list[dict[str, Any]]:
    if not isinstance(container_statuses, list):
        return []
    summaries = []
    for status in container_statuses:
        if not isinstance(status, dict):
            continue
        state = status.get("state") if isinstance(status.get("state"), dict) else {}
        waiting = state.get("waiting") if isinstance(state.get("waiting"), dict) else {}
        terminated = (
            state.get("terminated") if isinstance(state.get("terminated"), dict) else {}
        )
        summaries.append(
            {
                key: value
                for key, value in {
                    "name": status.get("name"),
                    "ready": status.get("ready"),
                    "restart_count": status.get("restartCount"),
                    "waiting_reason": waiting.get("reason"),
                    "terminated_reason": terminated.get("reason"),
                    "terminated_exit_code": terminated.get("exitCode"),
                }.items()
                if value is not None
            }
        )
    return summaries


def kubernetes_item_matches_workload(item: Any, workloads: set[str]) -> bool:
    if not isinstance(item, dict):
        return False
    metadata = item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
    searchable_values: list[str] = []

    name = metadata.get("name")
    if isinstance(name, str):
        searchable_values.append(name)

    labels = metadata.get("labels")
    if isinstance(labels, dict):
        for key in ("app", "app.kubernetes.io/name", "deployment", "service", "workload"):
            value = labels.get(key)
            if isinstance(value, str):
                searchable_values.append(value)

    owner_references = metadata.get("ownerReferences")
    if isinstance(owner_references, list):
        searchable_values.extend(
            owner.get("name", "")
            for owner in owner_references
            if isinstance(owner, dict)
        )

    for object_key in ("involvedObject", "regarding"):
        involved_object = item.get(object_key)
        if isinstance(involved_object, dict):
            object_name = involved_object.get("name")
            if isinstance(object_name, str):
                searchable_values.append(object_name)

    for key in ("message", "note", "reason"):
        value = item.get(key)
        if isinstance(value, str):
            searchable_values.append(value)

    haystack = " ".join(searchable_values).lower()
    return any(workload in haystack for workload in workloads)


def stringify_evidence_payload(payload: Any) -> str:
    if isinstance(payload, dict):
        parts = []
        for key, value in payload.items():
            if str(key).lower() in IGNORED_EVIDENCE_KEYS:
                continue
            parts.append(stringify_evidence_payload(value))
        return " ".join(part for part in parts if part).lower()
    if isinstance(payload, list):
        return " ".join(stringify_evidence_payload(item) for item in payload).lower()
    return str(payload).lower()


def empty_payload_if_none(payload: Any) -> Any:
    if payload is None:
        return {}
    return payload


def contains_degraded_signal(evidence_text: str, *, boundary: str | None = None) -> bool:
    boundary_patterns = BOUNDARY_DEGRADED_PATTERNS.get(boundary or "")
    if boundary_patterns is not None:
        return any(pattern.search(evidence_text) for pattern in boundary_patterns)
    return any(pattern.search(evidence_text) for pattern in DEGRADED_PATTERNS)


def contains_healthy_signal(evidence_text: str) -> bool:
    return any(pattern.search(evidence_text) for pattern in HEALTHY_PATTERNS)
