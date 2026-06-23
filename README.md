# mcp-aiops-backend

MCP 기반 농업 BNPL AIOps 백엔드입니다. 농민용 BNPL/농업 조언 챗봇, 관리자 RiskOps Copilot, SRE Copilot, Alertmanager 기반 RCA, 예측 기반 스케일링 점검, 운영 리포트 생성을 하나의 FastAPI 서비스와 MCP Tool 계층으로 연결합니다.

## 주요 기능

| 영역 | 주요 역할 | 대표 API / MCP |
| --- | --- | --- |
| Farmer BNPL | 신용 신청, 한도 조회, 상환/연체 조회, 상품 탐색, 장바구니, BNPL checkout 초안 | `POST /farmer/chat/ask`, `GET /farmer/orders/latest/delivery`, `farmer-bnpl-mcp` |
| Farm Advisory | 작물 일정, 농자재/비료 추천, 날씨/질병 리스크, 수익/현금흐름 시뮬레이션 | `farm-advisory-mcp` |
| Admin RiskOps | 신용 심사 큐, BNPL/연체 요약, BSS 이력, 재해 리스크 시뮬레이션, 알림 preview | `POST /admin/copilot/ask`, `GET /admin/risk/*`, `admin-riskops-mcp` |
| SRE / InfraOps | 관측 데이터 조회, Kubernetes 상태 조회, topology knowledge 검색, RCA evidence 수집 | `POST /sre/copilot/ask`, `infraops-mcp` |
| Alertmanager RCA | firing alert 수신, preliminary/final RCA 알림, due RCA job 실행 | `POST /api/alerts`, `POST /rca/jobs/run-due` |
| Prediction Scaling | 예측 run/metric, 실측 metric, 예측 오차, scaling event, Slack/RCA trigger | `POST /prediction-scaling/slack-agent/run`, `prediction-scaling-mcp` |
| Ops Reports | 일간/주간 운영 리포트 생성, RCA/예측/스케일링 요약 포함, SMTP 발송 | `POST /reports/ops`, `POST /reports/ops/{report_id}/send-email` |
| LLMOps / Audit | prompt version, LLM run, MCP tool-call history, approval queue, notification outbox | `GET /llm-runs`, `GET /mcp/tool-calls`, `GET /approvals`, `GET /notifications` |

## 아키텍처 흐름

```text
Frontend / Operator
  |
  v
FastAPI API
  |---> Jobs / LLM runs / tool calls / approvals
  |
  v
Agent planner / orchestrator
  |---> LLM provider
  |
  v
MCP 도구 목록 / 권한 정책
  |
  v
MCP 도구 실행 계층
  |---> PostgreSQL
  |---> Prometheus / Loki / Tempo
  |---> Kubernetes / Infra APIs
```

## MCP 구조

이 프로젝트에서 MCP는 LLM Agent가 외부 시스템을 직접 만지지 않고, 정해진 도구만 호출하도록 만드는 도구 실행 계층입니다.

| 용어 | 이 프로젝트에서의 의미 |
| --- | --- |
| MCP Server | 비슷한 역할의 도구 묶음입니다. 예: `farmer-bnpl-mcp`, `infraops-mcp` |
| MCP Tool | Agent가 호출할 수 있는 단일 기능입니다. 예: `get_credit_limit_status`, `query_prometheus` |
| Registry | 어떤 MCP Server와 Tool이 있는지 등록해 둔 목록입니다. Tool 이름, 설명, 권한을 관리합니다. |
| Policy | Tool을 자동 실행할 수 있는지, 승인이 필요한지, 차단해야 하는지 판단하는 규칙입니다. |
| Dispatcher | 실제 Tool 이름을 Python service 함수에 연결해 실행하는 계층입니다. |
| Audit | Tool 호출 요청/응답, LLM 실행, 승인 필요 상태를 저장하는 이력입니다. |

흐름은 다음처럼 이해하면 됩니다.

```text
사용자 질문
  -> Agent가 필요한 MCP Tool 계획
  -> Registry에서 Tool 존재 여부와 권한 확인
  -> Policy로 자동 실행/승인 필요/차단 판단
  -> Dispatcher가 실제 service 함수 실행
  -> 결과와 감사 이력을 DB에 저장
  -> Agent가 사용자 답변 생성
```

## 저장소 구조

```text
mcp-aiops-backend/
|-- src/
|   `-- aiops_platform/
|       |-- api/                  FastAPI router
|       |-- agent/                planner, orchestrator, dispatcher
|       |-- mcp/                  MCP registry, policy, masking, audit, FastMCP server
|       |-- farmer_bnpl/          농민 BNPL service/repository/schema
|       |-- farm_advisory/        농업 조언 service/schema
|       |-- admin_riskops/        관리자 RiskOps service/repository/schema
|       |-- infraops/             observability/Kubernetes/infra client tools
|       |-- infra_rca/            incident, RCA report, RCA job runner
|       |-- prediction_scaling/   예측 metric, actual metric, scaling event, Slack watcher
|       |-- ops_reports/          운영 리포트 생성, 조회, 이메일 발송
|       |-- llmops/               LLM provider client, run history, prompt/audit
|       `-- core/                 config, database, metrics
|-- docs/                         클라이언트 계약, ERD 요약, SRE 보안 정책
|-- infra/
|   |-- k8s/                      EKS/Kubernetes manifests
|   |-- docker/                   로컬 보조 인프라 예시
|   `-- grafana/                  Grafana datasource/dashboard json
`-- tests/                        unit/integration tests and seed fixtures
```

## 빠른 시작

### 요구사항

- Python 3.11+
- PostgreSQL 접속 정보
- PowerShell 기준 예시입니다.

### 1. 환경변수 준비

```powershell
Copy-Item .env.example .env
```

기본 로컬 DB 연결값은 다음과 같습니다. 실제 환경에서는 `.env`의 `DATABASE_URL`을 사용하는 DB에 맞게 바꿉니다.

```text
DATABASE_URL=postgresql+psycopg://kkpp:kkpp@localhost:5432/kkpp
```

### 2. 패키지 설치

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
```

### 3. API 실행

```powershell
uvicorn aiops_platform.main:app --reload
```

확인:

```text
GET http://localhost:8000/health
GET http://localhost:8000/docs
```

### 4. 테스트

```powershell
python -m pytest
```

로컬 DB fixture seed까지 적용해야 하는 테스트를 돌릴 때는 로컬 DB 스키마가 준비된 상태에서 opt-in 합니다.

```powershell
$env:RUN_TEST_SEEDS = "true"
python -m pytest
```

## LLM 설정

기본값은 로컬 개발용 `fake` provider입니다. 이 상태에서는 외부 LLM key 없이 planner와 API 흐름을 검증할 수 있습니다.

```text
LLM_PROVIDER=fake
LLM_MODEL=fake-agentic-planner
LLM_API_KEY=
```

OpenAI 호환 API를 사용할 때:

```text
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_BASE_URL=https://api.openai.com/v1
LLM_API_KEY=replace-with-api-key
LLM_REQUIRE_API_KEY=true
```

vLLM 같은 keyless OpenAI-compatible endpoint를 사용할 때:

```text
LLM_PROVIDER=openai-compatible
LLM_MODEL=Qwen/Qwen3-32B
LLM_API_BASE_URL=http://gpu-pod-host:8000/v1
LLM_API_KEY=
LLM_REQUIRE_API_KEY=false
```

`LLM_MODEL`은 provider 또는 vLLM server의 served model name과 맞아야 합니다.

## 주요 환경변수

전체 예시는 `.env.example`을 기준으로 봅니다. README에는 자주 바꾸는 값만 요약합니다.

| 구분 | 환경변수 |
| --- | --- |
| App | `APP_ENV`, `APP_NAME`, `APP_VERSION`, `APP_TIMEZONE`, `CORS_ALLOW_ORIGINS` |
| Database | `DATABASE_URL` |
| LLM | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_REQUIRE_API_KEY`, `LLM_MAX_TOKENS` |
| Observability | `PROMETHEUS_BASE_URL`, `PROMETHEUS_SOURCE_URLS`, `LOKI_BASE_URL`, `LOKI_SOURCE_URLS`, `TEMPO_BASE_URL` |
| Kubernetes | `KUBERNETES_API_BASE_URL`, `KUBERNETES_BEARER_TOKEN_FILE`, `KUBERNETES_CA_CERT_FILE`, `KUBERNETES_NAMESPACE_ALLOWLIST` |
| On-prem Kubernetes | `ONPREM_KUBERNETES_API_BASE_URL`, `ONPREM_KUBERNETES_BEARER_TOKEN`, `ONPREM_KUBERNETES_CA_CERT` |
| Infra optional tools | `INFRAOPS_ELK_ENABLED`, `INFRAOPS_KAFKA_ENABLED`, `INFRAOPS_BATCH_ENABLED` |
| Prediction scaling | `PREDICTION_SCALING_*` |
| RCA / report notification | `SMTP_*`, `OPS_REPORT_EMAIL_RECIPIENTS`, `RCA_EMAIL_RECIPIENTS`, `RCA_SLACK_WEBHOOK_URL` |
| Watchers | `PREDICTION_SCALING_WATCHER_ENABLED`, `SRE_INSPECTION_WATCHER_ENABLED` |

## API 표면

CloudFront/ALB 외부 경로는 `/api/v1` prefix도 함께 제공합니다. 예를 들어 `/mcp/servers`는 `/api/v1/mcp/servers`로도 접근할 수 있습니다.

| 용도 | Endpoint |
| --- | --- |
| Health | `GET /health` |
| Swagger | `GET /docs` |
| Prometheus metrics | `GET /metrics` |
| MCP registry | `GET /mcp/servers`, `GET /mcp/tools` |
| FastMCP transport | `POST /mcp-server/mcp`, `POST /api/v1/mcp-server/mcp` |
| Farmer chatbot | `POST /farmer/chat/ask` |
| Admin Copilot | `POST /admin/copilot/ask` |
| SRE Copilot | `POST /sre/copilot/ask` |
| Alertmanager webhook | `POST /api/alerts`, `POST /alerts/webhook` |
| Alertmanager SRE dry-run/execute | `POST /infra-rca/alertmanager/webhook` |
| Ops report | `POST /reports/ops`, `GET /reports/ops`, `GET /reports/ops/{report_id}` |
| Report email | `POST /reports/ops/{report_id}/send-email` |
| Job history | `GET /jobs`, `GET /jobs/{job_id}` |
| Audit/history | `GET /mcp/tool-calls`, `GET /llm-runs`, `GET /approvals`, `GET /notifications`, `GET /agent-snapshots` |

프론트엔드 연동 계약은 `docs/mcp-client-contract.md`를 기준으로 관리합니다.

## MCP 서버와 권한

| MCP server | 역할 |
| --- | --- |
| `farmer-bnpl-mcp` | 농민 신용/상품/장바구니/checkout 도구 |
| `farm-advisory-mcp` | 작물 일정, 농자재 추천, 농업 리스크 도구 |
| `admin-riskops-mcp` | 관리자 심사/연체/재해 리스크 도구 |
| `infraops-mcp` | 관측, Kubernetes, Kafka, RCA evidence, topology 도구 |
| `prediction-scaling-mcp` | 예측 metric, 실측 metric, 예측 오차, scaling event 도구 |

| Permission | 실행 정책 |
| --- | --- |
| `READ` | 자동 실행 가능 |
| `WRITE` | 승인 필요 상태로 기록 가능 |
| `USER_CONFIRMED_WRITE` | 농민 사용자 명시 확인 필요 |
| `OPS_WRITE` | 운영자 승인 필요 |
| `DESTRUCTIVE` | 기본 차단 대상 |

SRE Agent 자동 실행은 `READ` tool만 사용합니다. 운영 변경이나 파괴적 명령은 자동 RCA 흐름에서 제외합니다. 자세한 정책은 `docs/sre-agent-security-policy.md`를 봅니다.

## 데이터와 감사

- 기존 KongKongFarm 비즈니스 테이블은 `core.*`, `catalog.*`를 기준으로 참조합니다.
- AI/LLM/MCP 확장 데이터는 `ai` schema에 저장합니다.
- LLM run, MCP tool call, approval, notification, job history는 감사와 재현성을 위해 별도 조회 API를 제공합니다.
- LLM은 DB에 직접 접근하지 않고 MCP tool 결과와 masking된 context만 입력으로 받습니다.

데이터 모델 요약은 `docs/erd.md`에 있습니다.

## Docker

```powershell
docker build -t mcp-aiops-backend .
docker run --env-file .env -p 8000:8000 mcp-aiops-backend
```

런타임 이미지는 distroless nonroot 기반이며 기본 command는 다음과 같습니다.

```text
python -m uvicorn aiops_platform.main:app --host 0.0.0.0 --port 8000
```

## 배포와 운영

Kubernetes manifest는 `infra/k8s`에 있습니다.

```text
infra/k8s/serviceaccount.yaml
infra/k8s/rbac.yaml
infra/k8s/configmap.yaml
infra/k8s/secret.example.yaml
infra/k8s/deployment.yaml
infra/k8s/service.yaml
infra/k8s/ops-report-cronjobs.yaml
infra/k8s/kustomization.yaml
```

운영 secret은 Git에 커밋하지 않고 Kubernetes Secret 또는 GitHub Secrets로 주입합니다. `infra/k8s/ingress.yaml`은 공용 service-catalog Ingress에 합칠 MCP 경로 참고본으로 유지합니다.

`.github/workflows/deploy.yml`은 현재 branch push와 수동 실행에서 다음 순서로 동작합니다.

```text
pytest
Docker image build
Amazon ECR push
EKS kubeconfig 설정
ConfigMap / Secret / Manifest 적용
Deployment rollout 확인
서비스 내부 /health smoke test
```

배포 후 확인할 대표 endpoint:

```text
GET /health
GET /mcp/servers
GET /mcp/tools
POST /mcp-server/mcp
GET /api/v1/mcp/servers
POST /api/v1/mcp-server/mcp
```

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| `docs/mcp-client-contract.md` | 프론트엔드/API/MCP 연동 계약 |
| `docs/erd.md` | 공개 가능한 ERD와 데이터 관계 요약 |
| `docs/sre-agent-security-policy.md` | SRE Agent 권한, masking, audit 정책 |
| `docs/vessl-vllm-prometheus-scrape.md` | VESSL/vLLM Prometheus scrape 메모 |
| `infra/docker/postgres/init/README.md` | 로컬 PostgreSQL init script 관리 원칙 |

## 개발 원칙

- production 코드는 샘플 농가, 샘플 상품, 샘플 예측 실행값을 fallback으로 사용하지 않습니다.
- 데이터가 없으면 빈 목록 또는 domain not-found 오류를 반환합니다.
- 샘플 데이터는 production 코드가 아니라 test fixture 또는 seed data에 둡니다.
- API, MCP, ERD, 권한 정책이 바뀌면 README와 `docs/` 계약 문서를 함께 갱신합니다.
- secret, 운영 URL, 내부 전용 산출물은 Git에 커밋하지 않습니다.
