# MCP Client Integration Contract

클라이언트 앱은 이 문서를 기준으로 MCP 서버 목록, Agent 실행 응답, 승인 필요 상태, job/tool-call 이력을 표시한다.

## Base URLs

| 용도 | Endpoint |
| --- | --- |
| Swagger | `GET /docs` |
| MCP registry API | `GET /mcp/servers`, `GET /mcp/tools` |
| MCP tool-call history | `GET /mcp/tool-calls` |
| LLM run history | `GET /llm-runs` |
| Approval queue | `GET /approvals` |
| Notification outbox | `GET /notifications` |
| Agent snapshots | `GET /agent-snapshots` |
| Farmer chatbot | `POST /farmer/chat/ask` |
| Admin Copilot | `POST /admin/copilot/ask` |
| Job history | `GET /jobs` |
| FastMCP transport | `/mcp-server/mcp` |

## MCP Servers

| Server | Client Surface | 주요 역할 |
| --- | --- | --- |
| `farmer-bnpl-mcp` | 농민 BNPL 챗봇 | 신용 신청, 한도 조회, 상품 탐색, 장바구니, checkout preview |
| `farm-advisory-mcp` | 농민 BNPL 챗봇 | 작물 일정, 비료/농자재 추천, 날씨/질병/수익성 advisory |
| `admin-riskops-mcp` | 관리자 Copilot | 심사 큐, 연체/위험 사용자 조회, 알림 preview |
| `infraops-mcp` | 관리자 Copilot | Prometheus/Loki/ELK/Kubernetes/Kafka/RCA 관측 및 운영 preview |
| `prediction-scaling-mcp` | 관리자 Copilot | 예측 실행, 실측 metric, 오차, scaling event 조회 |

## Permission Display Rules

| Permission | Client 처리 |
| --- | --- |
| `READ` | 자동 실행 결과를 바로 표시한다. |
| `WRITE` | `APPROVAL_REQUIRED`이면 사용자 확인 UI를 표시한다. |
| `USER_CONFIRMED_WRITE` | 농민 사용자 명시 확인이 필요한 행동으로 표시한다. |
| `OPS_WRITE` | 운영자 승인 필요 상태로 표시한다. |
| `DESTRUCTIVE` | 기본 차단 상태로 표시하고 실행 버튼을 비활성화한다. |

## Agent Response Contract

`POST /farmer/chat/ask`와 `POST /admin/copilot/ask`는 같은 응답 구조를 사용한다.

```json
{
  "session": {},
  "user_message": {},
  "assistant_message": {},
  "job": {
    "job_id": "string",
    "job_type": "farmer_chat",
    "status": "SUCCEEDED"
  },
  "llm_run": {
    "llm_run_id": "string",
    "provider": "fake",
    "run_status": "SUCCESS"
  },
  "planned_tools": [],
  "tool_results": []
}
```

클라이언트는 `planned_tools`로 실행 계획을 먼저 보여주고, `tool_results`로 실제 실행 결과 또는 승인 필요 상태를 표시한다.
LLM 실행 근거와 prompt version은 `llm_run`과 `/llm-runs/{llm_run_id}`에서 확인한다.
Agent 실행 snapshot은 `/agent-snapshots`의 `session_id`, `llm_run_id`, `payload`로 채팅 세션과 LLM 실행 근거를 연결한다.

## Tool Result States

| Field | 의미 |
| --- | --- |
| `call_status` | `SUCCESS`, `FAILED`, `APPROVAL_REQUIRED`, `BLOCKED` |
| `will_execute` | 실제 실행 여부 |
| `requires_approval` | 승인 UI 표시 여부 |
| `is_blocked` | 차단 UI 표시 여부 |
| `request_payload` | 민감 정보가 제거된 요청 payload |
| `masked_request_payload` | history/audit 조회용 masked payload |

## Recommended Swagger Checks

1. `GET /mcp/servers`
   - 5개 MCP 서버가 보이는지 확인한다.
2. `GET /mcp/tools?server_name=farmer-bnpl-mcp`
   - Farmer 챗봇용 tool 목록이 보이는지 확인한다.
3. `POST /farmer/chat/ask`
   - `tool_results`에 `SUCCESS` 또는 `APPROVAL_REQUIRED`가 포함되는지 확인한다.
4. `POST /admin/copilot/ask`
   - RiskOps, InfraOps, Prediction Scaling tool 결과가 함께 반환되는지 확인한다.
5. `GET /jobs`
   - Agent 실행 job이 조회되는지 확인한다.
6. `GET /mcp/tool-calls`
   - tool-call history에 민감 payload가 노출되지 않는지 확인한다.
7. `GET /llm-runs`
   - Agent 답변을 생성한 LLM run history가 조회되는지 확인한다.
8. `GET /approvals`
   - 승인 필요 tool 실행이 approval queue에 기록되는지 확인한다.

## Client Implementation Notes

- 채팅 화면은 `assistant_message.content`를 기본 답변으로 렌더링한다.
- tool 결과 상세 패널은 `tool_results[*].response_payload`를 사용한다.
- 승인 필요 CTA는 `requires_approval=true` 또는 `call_status=APPROVAL_REQUIRED` 기준으로 표시한다.
- 차단된 작업은 `is_blocked=true` 또는 `call_status=BLOCKED` 기준으로 표시한다.
- 실행 이력 화면은 `/jobs`와 `/mcp/tool-calls`를 함께 사용한다.
- 감사/근거 화면은 `/llm-runs`, `/prompt-versions`, `/approvals`, `/notifications`, `/agent-snapshots`를 사용한다.
