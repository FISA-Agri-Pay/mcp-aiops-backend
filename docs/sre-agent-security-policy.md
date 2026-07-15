# SRE Agent 보안·권한·감사 정책

## 범위

이 정책은 SRE Agent에 대한 Milestone 7 계약을 확정합니다.

SRE Agent는 다음 두 가지 경로로 트리거될 수 있습니다.

- `sre_copilot`에서의 사용자 채팅 후속 질문
- proactive RCA 워크플로우를 시작하는 Alertmanager firing alert

두 경로 모두 동일한 권한, masking, 감사 규칙을 사용해야 합니다.

## 권한 모델

| Tool 그룹 | 권한 | 실행 정책 |
| --- | --- | --- |
| Topology knowledge tools | `READ` | 자동 실행 가능 |
| Live observability tools | `READ` | 자동 실행 가능 |
| Kubernetes/AWS/GitOps read tools | `READ` | 자동 실행 가능 |
| RCA snapshot/search tools | `READ` | 자동 실행 가능 |
| 운영 변경(mutation) tools | `OPS_WRITE` | SRE Agent 자동 실행에서 제외 |
| 파괴적(destructive) tools | `DESTRUCTIVE` | SRE Agent 자동 실행에서 제외 |

SRE Agent 자동 실행은 `READ` Tool만 계획하고 실행해야 합니다.

다음 Tool은 자동 SRE RCA 흐름에서 항상 제외됩니다.

- `scale_deployment`
- `restart_pod`
- `delete_pod`
- `run_kubectl_exec`

이 Tool들은 향후 승인 기반 워크플로우를 위해 registry에 남아 있을 수 있지만, Milestone 7 자동 분석 범위에는 포함되지 않습니다.

## 감사 정책

SRE 관련 Tool 실행은 모두 다음 항목을 포함한 감사 기록을 생성해야 합니다.

- 호출자 또는 트리거 주체 (예: user id 또는 Alertmanager webhook actor)
- 트리거 유형 (예: `CHAT` 또는 `ALERTMANAGER`)
- 가능한 경우 incident key
- server name
- tool name
- permission
- call status
- masked request payload
- masked response payload
- latency
- 실패 시 error message

Topology knowledge 조회는 Tool 호출 단위로 감사 가능해야 합니다.

- `get_topology_snapshot`
- `search_topology_knowledge`
- `get_service_routing_path`
- `get_service_dependency_map`

향후 Alertmanager 기반 RCA에서는 감사 체인이 다음을 연결하는 것이 좋습니다.

1. Alertmanager webhook payload
2. 생성된 incident key
3. SRE Agent plan
4. MCP tool calls
5. RCA snapshot
6. LLM RCA run
7. Slack/Email notification outbox record

## Masking 정책

secret 성격의 값은 저장되거나 LLM에 노출되는 payload에 절대 포함되어서는 안 됩니다.

다음 키워드가 포함된 키는 항상 마스킹합니다.

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

Topology knowledge는 두 가지 masking 레벨을 지원합니다.

| Level | 동작 |
| --- | --- |
| `secrets_only` | secret 성격의 값만 마스킹 |
| `infrastructure` | secret에 더해 IP, CIDR, AWS 계정 ID, AWS ARN, AWS DNS 식별자까지 마스킹 |

Topology snapshot을 on-call/SRE 경계 밖에 노출할 수 있는 경우에는 `infrastructure`를 사용합니다.
구체적인 라우팅 근거가 필요한 내부 RCA에서는 `secrets_only`를 사용합니다.

Alertmanager 기반 Slack/Email 알림에는 원문 secret이 포함되어서는 안 됩니다. 더 넓은 대상에게 알림을 보낼 때는 topology 근거에 infrastructure 수준 masking을 사용하는 것이 좋습니다.

## Alertmanager 확장

Alertmanager가 트리거가 될 수 있어 Milestone 7 범위가 일부 확장됩니다.

이 정책은 이제 다음도 다룹니다.

- Alertmanager webhook payload masking
- incident dedup/idempotency key 감사
- proactive RCA job 실행 감사
- notification outbox 감사
- Slack/Email 본문 masking

SRE Agent는 여전히 읽기 전용입니다. Alertmanager firing alert가 자동 재시작, 스케일링, pod 삭제, exec 실행을 유발해서는 안 됩니다.

Alertmanager 기반 SRE Agent의 첫 endpoint는 dry-run 계획 API로 시작합니다.

- `POST /infra-rca/alertmanager/webhook`
- `POST /api/v1/infra-rca/alertmanager/webhook`

이 endpoint는 표준 Alertmanager webhook payload를 수신해 incident key를 도출하고, alert를 SRE intent로 매핑하며, 기본적으로 Tool을 실행하지 않고 MCP tool plan을 반환합니다.
`execute=true`이면 READ 전용 증거 수집을 실행하고 incident context bundle을 구성합니다.
`execute=true&notify=true`이면 Slack/Email notification outbox 기록도 남기고 masked RCA 증거 요약을 발송합니다. 실제 조치(remediation)는 계속 비활성화 상태입니다.

## 필수 검증 항목

Milestone 7은 다음을 만족할 때 완료된 것으로 봅니다.

- SRE Agent가 허용하는 Tool 집합이 `READ` 권한의 registry Tool만 포함
- knowledge tools가 `READ`로 등록됨
- live observability tools가 `READ`로 등록됨
- mutation tools는 SRE 자동 실행에서 허용되지 않음
- MCP 감사가 기본적으로 masked payload를 저장함
- 빈 masked payload가 그대로 보존되고 원본 payload로 대체되지 않음
- topology `infrastructure` masking이 IP/CIDR/ARN/DNS/계정 식별자를 가림
- 대표 Alertmanager RCA dry-run이 `OPS_WRITE` 또는 `DESTRUCTIVE` Tool을 계획하지 않음
