# SRE Agent Security, Permission, Audit Policy

## Scope

This policy fixes the Milestone 7 contract for the SRE Agent.

The SRE Agent can be triggered by either:

- user chat follow-up in `sre_copilot`
- Alertmanager firing alerts that start a proactive RCA workflow

Both paths must use the same permission, masking, and audit rules.

## Permission Model

| Tool group | Permission | Execution policy |
| --- | --- | --- |
| Topology knowledge tools | `READ` | Automatically executable |
| Live observability tools | `READ` | Automatically executable |
| Kubernetes/AWS/GitOps read tools | `READ` | Automatically executable |
| RCA snapshot/search tools | `READ` | Automatically executable |
| Operational mutation tools | `OPS_WRITE` | Excluded from SRE Agent auto execution |
| Destructive tools | `DESTRUCTIVE` | Excluded from SRE Agent auto execution |

SRE Agent automatic execution must only plan and dispatch `READ` tools.

The following tools remain outside the automatic SRE RCA flow:

- `scale_deployment`
- `restart_pod`
- `delete_pod`
- `run_kubectl_exec`

They may exist in the registry for future approval-based workflows, but they are not part of Milestone 7 auto analysis.

## Audit Policy

Every SRE-related tool execution must produce an audit record with:

- caller or triggering actor, for example user id or Alertmanager webhook actor
- trigger type, for example `CHAT` or `ALERTMANAGER`
- incident key when available
- server name
- tool name
- permission
- call status
- masked request payload
- masked response payload
- latency
- error message when failed

Topology knowledge reads must be auditable at the tool-call level:

- `get_topology_snapshot`
- `search_topology_knowledge`
- `get_service_routing_path`
- `get_service_dependency_map`

For future Alertmanager-triggered RCA, the audit chain should connect:

1. Alertmanager webhook payload
2. generated incident key
3. SRE Agent plan
4. MCP tool calls
5. RCA snapshot
6. LLM RCA run
7. Slack/Email notification outbox record

## Masking Policy

Secret-like values are always forbidden in stored or LLM-visible payloads.

Always mask keys containing:

- `password`
- `passwd`
- `secret`
- `token`
- `api_key`
- `apikey`
- `authorization`
- `access_key`
- `refresh_key`
- `private_key`

Topology knowledge supports two masking levels:

| Level | Behavior |
| --- | --- |
| `secrets_only` | Masks secret-like assignments only |
| `infrastructure` | Masks secrets plus IP, CIDR, AWS account id, AWS ARN, and AWS DNS identifiers |

Use `infrastructure` when topology snapshots may be shown outside the on-call/SRE boundary.
Use `secrets_only` for internal RCA where concrete routing evidence is needed.

Alertmanager-triggered Slack/Email notifications must not include raw secrets. If a notification is sent to a wider audience, it should use infrastructure-level masking for topology evidence.

## Alertmanager Extension

Milestone 7 changes slightly because Alertmanager can become the trigger.

The policy now also covers:

- Alertmanager webhook payload masking
- incident dedup/idempotency key audit
- proactive RCA job execution audit
- notification outbox audit
- Slack/Email body masking

The SRE Agent still remains read-only. Alertmanager firing alerts must not cause automatic restarts, scaling, pod deletion, or exec.

The first Alertmanager-triggered SRE Agent endpoint starts as a dry-run planning API:

- `POST /infra-rca/alertmanager/webhook`
- `POST /api/v1/infra-rca/alertmanager/webhook`

This endpoint receives a standard Alertmanager webhook payload, derives an incident key,
maps the alert to an SRE intent, and returns the MCP tool plan without executing tools by default.
With `execute=true`, it runs READ-only evidence collection and builds an incident context bundle.
With `execute=true&notify=true`, it also records Slack/Email notification outbox entries and
delivers a masked RCA evidence summary. Actual remediation remains disabled.

## Required Validation

Milestone 7 is considered satisfied when:

- SRE Agent allowed tool set contains only registry tools with `READ` permission
- knowledge tools are registered as `READ`
- live observability tools are registered as `READ`
- mutation tools are not allowed in SRE auto execution
- MCP audit stores masked payloads by default
- empty masked payloads are preserved and do not fall back to raw payloads
- topology `infrastructure` masking hides IP/CIDR/ARN/DNS/account identifiers
- representative Alertmanager RCA dry-runs do not plan `OPS_WRITE` or `DESTRUCTIVE` tools
