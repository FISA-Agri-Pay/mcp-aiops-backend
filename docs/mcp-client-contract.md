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
| Operations report API | `POST /reports/ops`, `GET /reports/ops`, `GET /reports/ops/{report_id}`, `POST /reports/ops/{report_id}/send-email` |
| Farmer chatbot | `POST /farmer/chat/ask` |
| Farmer BNPL delivery API | `GET /farmer/orders/latest/delivery` |
| Admin Copilot | `POST /admin/copilot/sessions`, `GET /admin/copilot/sessions`, `GET /admin/copilot/sessions/{session_id}`, `GET /admin/copilot/sessions/{session_id}/messages`, `POST /admin/copilot/ask` |
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
    "provider": "fake|openai-compatible|anthropic",
    "run_status": "SUCCESS"
  },
  "planned_tools": [],
  "tool_results": [],
  "ui_cards": [],
  "ui_actions": []
}
```

클라이언트는 `planned_tools`로 실행 계획을 먼저 보여주고, `tool_results`로 실제 실행 결과 또는 승인 필요 상태를 표시한다.
LLM 실행 근거와 prompt version은 `llm_run`과 `/llm-runs/{llm_run_id}`에서 확인한다.
Agent 실행 snapshot은 `/agent-snapshots`의 `session_id`, `llm_run_id`, `payload`로 채팅 세션과 LLM 실행 근거를 연결한다.
외부 LLM provider를 사용할 때도 LLM은 DB를 직접 조회하지 않고, MCP tool 실행 결과와 masking된 context만 입력으로 받는다.

Farmer 챗봇은 프론트 카드 UI 렌더링을 위해 `ui_cards`와 `ui_actions`를 함께 반환할 수 있다. 클라이언트는 LLM 답변 문장을 파싱하지 않고 `ui_cards[*].type` 기준으로 카드를 렌더링한다.

지원 Farmer 카드 타입:

| Card Type | 화면 |
| --- | --- |
| `credit-summary` | 외상 한도/사용액/잔여 한도 |
| `repayment-summary` | 다음 상환일/이자/연체 상태 |
| `recommendation` | 추천 농자재/비료/센서 |
| `delivery-status` | 최근 주문 배송 현황 |
| `checkout-confirmation` | 사용자 확인이 필요한 결제 준비 |

## Admin Copilot Session List

프론트의 "최근 대화 더보기"는 서버 기반 세션 목록 API를 사용한다.

### `GET /admin/copilot/sessions`

지원 query:

| Query | 설명 |
| --- | --- |
| `user_id` | 관리자 사용자 ID. 인증 토큰 기반 식별이 가능하면 생략 가능 |
| `status` | `OPEN`, `CLOSED` |
| `limit` | 최대 조회 개수. 기본 20, 최대 100 |

```json
{
  "limit": 20,
  "items": [
    {
      "session_id": "string",
      "chat_type": "admin_copilot",
      "user_id": "admin-1",
      "title": "연체 위험 고객 현황 알려줘",
      "status": "OPEN",
      "created_at": "2026-06-07T10:00:00+09:00",
      "updated_at": "2026-06-07T10:15:00+09:00"
    }
  ]
}
```

이 API는 신규 테이블 없이 `chat_sessions`를 조회한다. 제목은 `context.title`을 우선 사용하고, 없으면 첫 사용자 메시지 또는 기본 제목을 API 계층에서 계산한다.

## Operations Report API Contract

일간/주간 운영 리포트는 대시보드 없이도 API 조회와 이메일 발송으로 소비할 수 있어야 한다.
리포트 생성은 기존 MCP Tool, RCA report, prediction/scaling 데이터를 수집한 뒤 LLM `ops_report` 실행 결과를 `ops_reports`에 저장한다.

### `POST /reports/ops`

일간 또는 주간 운영 리포트를 생성한다.

```json
{
  "report_type": "DAILY",
  "report_date": "2026-06-06",
  "timezone": "Asia/Seoul",
  "namespace": "default",
  "service_name": "api",
  "include_rca": true,
  "include_prediction_scaling": true
}
```

응답은 생성된 리포트와 비동기 처리 추적용 job, LLM 실행 이력을 포함한다.

```json
{
  "report": {
    "report_id": "string",
    "report_type": "DAILY",
    "period_start": "2026-06-06T00:00:00",
    "period_end": "2026-06-07T00:00:00",
    "timezone": "Asia/Seoul",
    "title": "Daily operations report",
    "summary": "string",
    "sections": [],
    "metrics": {},
    "report_status": "COMPLETED"
  },
  "job": {
    "job_id": "string",
    "job_type": "ops_report",
    "status": "SUCCEEDED"
  },
  "llm_run": {
    "llm_run_id": "string",
    "run_status": "SUCCESS"
  },
  "included_incidents": [],
  "included_rca_reports": [],
  "metric_summaries": []
}
```

### `GET /reports/ops`

운영 리포트 목록을 조회한다.

지원 필터:

| Query | 설명 |
| --- | --- |
| `report_type` | `DAILY`, `WEEKLY` |
| `date_from` | 조회 시작일 |
| `date_to` | 조회 종료일 |
| `status` | `DRAFT`, `COMPLETED`, `SENT`, `FAILED` |
| `namespace` | Kubernetes namespace 필터 |
| `service_name` | 서비스/workload 필터 |
| `limit` | 최대 조회 개수 |

### `GET /reports/ops/{report_id}`

운영 리포트 상세를 조회한다.
응답에는 리포트 본문, incident 요약, 포함 RCA report, prediction error summary, scaling event summary, 이메일 발송 상태를 포함한다.
리포트의 서술형 본문은 한국어로 작성하고, metric name, alert name, source type, Kubernetes resource name, identifier는 원문을 유지한다.

### `POST /reports/ops/{report_id}/send-email`

생성된 운영 리포트를 HTML 이메일로 발송 요청한다.

```json
{
  "recipients": ["ops@example.com"],
  "subject": "[AIOps] Daily operations report - 2026-06-06",
  "format": "HTML"
}
```

1차 MVP는 PDF 또는 문서 첨부를 만들지 않는다.
API는 수신자별 `notification_outbox` record를 생성하고 SMTP 발송을 시도한 뒤
`SENT` 또는 `FAILED` 상태로 갱신한다. 응답은 `notification_id` 목록과 전체 발송 상태를 반환한다.

```json
{
  "report_id": "string",
  "channel": "EMAIL",
  "notification_ids": ["string"],
  "status": "SENT"
}
```

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
9. `POST /reports/ops`
   - 일간/주간 운영 리포트가 RCA, prediction/scaling 요약과 함께 생성되는지 확인한다.
10. `POST /reports/ops/{report_id}/send-email`
   - HTML 이메일이 SMTP로 발송되고 `notification_outbox` 상태가 갱신되는지 확인한다.

## Client Implementation Notes

- 채팅 화면은 `assistant_message.content`를 기본 답변으로 렌더링한다.
- tool 결과 상세 패널은 `tool_results[*].response_payload`를 사용한다.
- 승인 필요 CTA는 `requires_approval=true` 또는 `call_status=APPROVAL_REQUIRED` 기준으로 표시한다.
- 차단된 작업은 `is_blocked=true` 또는 `call_status=BLOCKED` 기준으로 표시한다.
- 실행 이력 화면은 `/jobs`와 `/mcp/tool-calls`를 함께 사용한다.
- 감사/근거 화면은 `/llm-runs`, `/prompt-versions`, `/approvals`, `/notifications`, `/agent-snapshots`를 사용한다.
- 운영 리포트 화면 또는 이메일 미리보기는 `/reports/ops/{report_id}`를 사용한다. 별도 대시보드 UI는 1차 MVP 필수 범위가 아니다.
