# mcp-aiops-backend

KongKongFarm 서비스에 붙는 MCP 기반 AIOps 백엔드입니다. 농민 BNPL 업무, 관리자 리스크 운영, SRE 장애 분석을 하나의 Agent/MCP 계층으로 연결해 챗봇, Copilot, RCA, 예측 기반 스케일링 점검, 운영 리포트를 제공합니다.

이 프로젝트는 단순한 BNPL API 서버가 아니라, 농업 BNPL 플랫폼을 운영하면서 생기는 사용자 문의, 관리자 의사결정, 장애 조사, 운영 보고를 AI Agent가 도와주는 백엔드입니다.

## 프로젝트 목적

| 사용자/상황 | 이 프로젝트가 지원하는 흐름 |
| --- | --- |
| 농민 사용자 | BNPL 한도, 상환, 배송, 농자재 추천, 농업 조언을 챗봇으로 안내합니다. |
| 관리자 | 신용 심사, 연체, 재해 리스크, 고객 위험도를 Copilot으로 조회하고 요약합니다. |
| SRE/운영자 | Prometheus, Loki, Kubernetes, Alertmanager 데이터를 모아 장애 원인 분석과 운영 리포트를 만듭니다. |
| LLM Agent | DB나 인프라를 직접 만지지 않고, 권한이 정해진 MCP Tool만 호출해 답변과 실행 이력을 남깁니다. |

즉, 비즈니스 도메인인 **농업 BNPL**과 운영 도메인인 **AIOps/SRE**를 함께 다루는 프로젝트입니다.

## 대표 시나리오

### 1. 농민 BNPL 상담

농민 사용자가 “이번 달 상환해야 할 금액과 남은 한도를 알려줘”라고 물으면 Farmer 챗봇은 사용자 프로필, 신용 한도, 상환 일정, 연체 여부를 MCP Tool로 조회합니다. LLM은 조회 결과를 바탕으로 쉬운 문장으로 답변하고, 필요한 경우 배송 상태나 농자재 추천 카드까지 함께 반환합니다.

```text
사용자 질문
  -> Farmer BNPL Agent
  -> credit / repayment / product MCP Tool 조회
  -> 답변, UI card, tool-call history 저장
```

### 2. 관리자 리스크 운영

관리자가 “연체 위험이 높은 고객과 재해 리스크 영향도를 요약해줘”라고 요청하면 Admin Copilot은 심사 큐, BNPL 요약, 연체 요약, BSS 이력, 재해 시뮬레이션 도구를 조합합니다. 결과는 관리자 화면에서 바로 확인할 수 있는 요약과 근거 데이터로 남습니다.

```text
관리자 질문
  -> Admin Copilot
  -> RiskOps / BNPL / overdue MCP Tool 조회
  -> 위험 요약, 근거 payload, LLM run 저장
```

### 3. SRE 장애 분석과 RCA

SRE가 “결제 서비스 5xx 원인 봐줘”라고 묻거나 Alertmanager가 firing alert를 보내면 SRE Agent는 서비스, namespace, alert 유형을 추론합니다. 이후 Prometheus metric, Loki log, Kubernetes event, service endpoint, topology knowledge, 이전 RCA 이력을 READ-only Tool로 수집하고 RCA 초안을 생성합니다.

```text
SRE 질문 또는 Alertmanager alert
  -> 장애 의도와 대상 서비스 추론
  -> READ-only InfraOps Tool 계획
  -> metric / log / trace / Kubernetes / topology 증거 수집
  -> incident context bundle 및 RCA snapshot 생성
  -> LLM RCA 분석
  -> Slack / Email 알림 및 audit 기록
```

SRE Agent 자동 실행은 읽기 전용입니다. `scale_deployment`, `restart_pod`, `delete_pod`, `run_kubectl_exec`처럼 운영 상태를 바꾸거나 파괴적인 Tool은 자동 RCA 흐름에서 제외합니다.

## 핵심 구성

| 구성 | 역할 |
| --- | --- |
| FastAPI API | Farmer/Admin/SRE Copilot, MCP registry, job/history, report endpoint를 제공합니다. |
| Agent planner | 사용자 질문을 도메인별 의도로 분류하고 필요한 MCP Tool 실행 계획을 만듭니다. |
| MCP registry/policy | 사용할 수 있는 Tool 목록과 권한을 관리하고 자동 실행 가능 여부를 판단합니다. |
| MCP dispatcher | Tool 이름을 실제 Python service 함수로 연결해 실행합니다. |
| LLMOps/Audit | LLM run, prompt version, MCP tool call, approval, notification 이력을 저장합니다. |
| InfraOps/SRE | Prometheus, Loki, Tempo, Kubernetes, topology knowledge, RCA history를 조회합니다. |
| Ops Reports | RCA, 예측/스케일링, 운영 metric을 모아 일간/주간 리포트와 이메일 발송을 처리합니다. |

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
MCP registry / policy / masking
  |
  v
MCP dispatcher
  |---> PostgreSQL
  |---> Prometheus / Loki / Tempo
  |---> Kubernetes / Infra APIs
  |---> Topology knowledge
```

## MCP 용어 정리

LLM Agent가 데이터베이스나 인프라 API를 직접 호출하면 실행 범위를 통제하기 어렵습니다. 이 프로젝트는 모든 외부 동작을 MCP Tool로 감싸고, registry와 policy를 통해 “어떤 도구를, 어떤 권한으로, 어떤 입력에 대해 실행했는지”를 남깁니다.

| 용어 | 의미 |
| --- | --- |
| MCP Server | 비슷한 역할의 Tool 묶음입니다. 예: `farmer-bnpl-mcp`, `infraops-mcp` |
| MCP Tool | Agent가 호출할 수 있는 단일 기능입니다. 예: `get_credit_limit_status`, `query_prometheus` |
| Registry | MCP Server와 Tool의 이름, 설명, 권한을 등록해 둔 목록입니다. |
| Policy | Tool을 자동 실행할지, 승인이 필요한지, 차단할지 판단하는 규칙입니다. |
| Dispatcher | Tool 이름을 실제 service 함수로 연결해 실행하는 계층입니다. |
| Audit | Tool 호출 요청/응답, LLM 실행, 승인 필요 상태를 저장하는 이력입니다. |

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
|-- docs/
|   |-- mcp-client-contract.md    프론트엔드/API/MCP 연동 계약
|   |-- erd.md                    공개 가능한 ERD 요약
|   |-- configuration.md          환경변수와 LLM provider 설정
|   |-- deployment.md             Docker/Kubernetes/GitHub Actions 배포
|   `-- sre-agent-security-policy.md
|-- infra/
|   |-- k8s/                      EKS/Kubernetes manifests
|   |-- docker/                   로컬 보조 인프라 예시
|   `-- grafana/                  Grafana datasource/dashboard json
`-- tests/                        unit/integration tests and seed fixtures
```

## 빠른 시작

요구사항:

- Python 3.11+
- PostgreSQL 접속 정보
- PowerShell 기준 예시입니다.

```powershell
Copy-Item .env.example .env
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn aiops_platform.main:app --reload
```

확인:

```text
GET http://localhost:8000/health
GET http://localhost:8000/docs
```

테스트:

```powershell
python -m pytest
```

환경변수, LLM provider, 테스트 seed 설정은 `docs/configuration.md`를 참고합니다.

## 관련 문서

| 문서 | 내용 |
| --- | --- |
| `docs/mcp-client-contract.md` | 프론트엔드/API/MCP 연동 계약 |
| `docs/erd.md` | 공개 가능한 ERD와 데이터 관계 요약 |
| `docs/configuration.md` | 로컬/운영 환경변수와 LLM provider 설정 |
| `docs/deployment.md` | Docker, Kubernetes, GitHub Actions 배포 흐름 |
| `docs/sre-agent-security-policy.md` | SRE Agent 권한, masking, audit 정책 |
| `docs/vessl-vllm-prometheus-scrape.md` | VESSL/vLLM Prometheus scrape 메모 |
| `infra/docker/postgres/init/README.md` | 로컬 PostgreSQL init script 관리 원칙 |

## 개발 원칙

- production 코드는 샘플 농가, 샘플 상품, 샘플 예측 실행값을 fallback으로 사용하지 않습니다.
- 데이터가 없으면 빈 목록 또는 domain not-found 오류를 반환합니다.
- 샘플 데이터는 production 코드가 아니라 test fixture 또는 seed data에 둡니다.
- API, MCP, ERD, 권한 정책이 바뀌면 README와 `docs/` 계약 문서를 함께 갱신합니다.
- secret, 운영 URL, 내부 전용 산출물은 Git에 커밋하지 않습니다.
