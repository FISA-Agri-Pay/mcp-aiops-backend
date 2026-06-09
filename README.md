# mcp-aiops-backend

MCP 기반 농업 BNPL AIOps 백엔드입니다.

## 로컬 개발환경

### 1. 환경변수 준비

```powershell
Copy-Item .env.example .env
```

실제 secret, 운영 URL, 내부 schema SQL은 Git에 올리지 않습니다.

### 2. PostgreSQL 확인

```powershell
docker ps --filter name=kkpp-postgres
```

이 프로젝트는 별도 PostgreSQL을 띄우지 않고 기존 KongKongFarm PostgreSQL을 사용합니다.

기본 로컬 연결 정보:

```text
DATABASE_URL=postgresql+psycopg://kkpp:kkpp@localhost:5432/kkpp
```

내부 DB schema SQL은 아래 위치에 둡니다.

```text
infra/docker/postgres/init/001_init_schema.sql
```

이 SQL은 내부 공유용이므로 `.gitignore`에 의해 제외됩니다.
실제 적용은 기존 KongKongFarm DB에 `ai` schema를 추가하는 방식으로 진행합니다.

### 3. API 실행

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
uvicorn aiops_platform.main:app --reload
```

Health Check:

```text
GET http://localhost:8000/health
```

### 4. LLM Provider 설정

기본값은 로컬 테스트용 `fake` provider입니다. 외부 Chat Completions 호환 API를 사용할 때는 `.env`에 아래 값을 설정합니다.

```text
LLM_PROVIDER=openai
LLM_MODEL=gpt-4o-mini
LLM_API_KEY=...
LLM_API_BASE_URL=https://api.openai.com/v1
```

Claude/Anthropic 계열은 아래처럼 설정합니다.

```text
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet-latest
LLM_API_KEY=...
```

GPU Pod에서 vLLM OpenAI-compatible server를 외부 노출할 때는 API key 없이도 연결할 수 있습니다.

```text
LLM_PROVIDER=openai-compatible
LLM_MODEL=Qwen/Qwen3-32B
LLM_API_BASE_URL=http://gpu-pod-host:8000/v1
LLM_API_KEY=
LLM_REQUIRE_API_KEY=false
```

`LLM_MODEL`은 vLLM server의 served model 이름과 맞춰야 합니다. `--served-model-name`을 별도로 지정했다면 그 값을 사용합니다.

`LLM_API_KEY`가 비어 있으면 외부 호출 대신 fake provider로 fallback합니다.
단, `LLM_REQUIRE_API_KEY=false`이고 `LLM_PROVIDER=openai-compatible`이면 keyless vLLM endpoint를 호출합니다.

## 클라이언트 연동 기준

클라이언트 앱은 `docs/mcp-client-contract.md`를 기준으로 MCP 서버, Agent API, job/tool-call history 응답을 연동합니다.

주요 확인 endpoint:

```text
GET /mcp/servers
GET /mcp/tools
POST /farmer/chat/ask
POST /admin/copilot/ask
GET /jobs
GET /mcp/tool-calls
GET /llm-runs
GET /approvals
GET /notifications
GET /agent-snapshots
```

FastMCP transport는 `/mcp-server/mcp`에 mount됩니다.

## AWS EKS 배포 및 운영 인프라 연동

이 프로젝트는 EKS 배포 시 로컬 개발용 `localhost` 주소를 그대로 사용하지 않습니다.
MCP Tool이 바라보는 운영 인프라 주소는 Kubernetes `ConfigMap`과 `Secret`으로 주입합니다.

### MCP Tool별 운영 인프라 환경변수

| MCP 영역 | 연동 인프라 | 환경변수 |
| --- | --- | --- |
| `farmer-bnpl-mcp` | PostgreSQL/RDS | `DATABASE_URL` |
| `farm-advisory-mcp` | PostgreSQL/RDS 상품 카탈로그 | `DATABASE_URL` |
| `admin-riskops-mcp` | PostgreSQL/RDS | `DATABASE_URL` |
| `prediction-scaling-mcp` | PostgreSQL/RDS 예측/스케일링 테이블 | `DATABASE_URL` |
| `infraops-mcp` | Prometheus | `PROMETHEUS_BASE_URL`, `PROMETHEUS_SOURCE_URLS` |
| `infraops-mcp` | Loki | `LOKI_BASE_URL`, `LOKI_SOURCE_URLS` |
| `infraops-mcp` | EKS Kubernetes API | `KUBERNETES_API_BASE_URL`, `KUBERNETES_BEARER_TOKEN_FILE`, `KUBERNETES_CA_CERT_FILE`, `KUBERNETES_NAMESPACE_ALLOWLIST` |
| `infraops-mcp` | Kafka Admin API | `KAFKA_ADMIN_BASE_URL` |
| `infraops-mcp` | Batch/Job API | `BATCH_API_BASE_URL` |
| `infraops-mcp` | Elasticsearch/OpenSearch | `ELASTICSEARCH_BASE_URL`, `ELASTICSEARCH_USERNAME`, `ELASTICSEARCH_PASSWORD`, `ELASTICSEARCH_INDEX_ALLOWLIST` |
| `infraops-mcp` | Kibana/OpenSearch Dashboards | `KIBANA_BASE_URL` |
| Agent/Copilot | LLM endpoint | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_REQUIRE_API_KEY` |
| Ops report | SMTP | `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM`, `SMTP_USE_TLS` |

### Kubernetes 매니페스트

EKS 배포용 기본 파일은 `infra/k8s`에 있습니다.

```text
infra/k8s/serviceaccount.yaml
infra/k8s/rbac.yaml
infra/k8s/configmap.yaml
infra/k8s/secret.example.yaml
infra/k8s/deployment.yaml
infra/k8s/service.yaml
infra/k8s/rca-due-job-cronjob.yaml
infra/k8s/kustomization.yaml
```

`secret.example.yaml`은 예시 파일입니다. 실제 운영 secret은 Git에 커밋하지 않고,
GitHub Actions 또는 `kubectl create secret`으로 생성합니다.

`infra/k8s/ingress.yaml`은 기존 `default/service-catalog-ingress`에 MCP 경로를 추가합니다.
MCP는 `default` namespace의 `ClusterIP` Service로 배포되고, 기존 `kkpp-catalog-api`
ALB가 path rule로 catalog pod와 MCP pod를 구분합니다.

Kubernetes 조회 MCP Tool은 EKS 내부 service account를 사용합니다. 기본 운영 설정은 다음과 같습니다.

```text
KUBERNETES_API_BASE_URL=https://kubernetes.default.svc
KUBERNETES_BEARER_TOKEN_FILE=/var/run/secrets/kubernetes.io/serviceaccount/token
KUBERNETES_CA_CERT_FILE=/var/run/secrets/kubernetes.io/serviceaccount/ca.crt
```

### GitHub Actions 배포 파이프라인

`.github/workflows/deploy.yml`은 `main` 브랜치 push 또는 수동 실행 시 아래 순서로 동작합니다.

```text
pytest
Docker image build
Amazon ECR push
EKS kubeconfig 설정
ConfigMap/Secret/Manifest 적용
Deployment rollout 확인
서비스 내부 /health smoke test
```

GitHub Actions에 필요한 값은 아래처럼 설정합니다.

| 이름 | 위치 | 설명 |
| --- | --- | --- |
| `AWS_ROLE_TO_ASSUME` | Secret | GitHub OIDC가 assume할 AWS IAM Role ARN |
| `AWS_REGION` | Variable 또는 Secret | 기본값: `ap-northeast-2` |
| `ECR_REPOSITORY` | Variable 또는 Secret | 기본값: `kkpp/mcp-aiops-backend` |
| `EKS_CLUSTER_NAME` | Variable 또는 Secret | 기본값: `kkpp-eks` |
| `DATABASE_URL` | Secret | 운영 PostgreSQL/RDS 연결 문자열 |
| `LLM_API_KEY` | Secret | Groq 외부 LLM API key. `infra/k8s/configmap.yaml`은 `LLM_PROVIDER=groq`, `LLM_MODEL=qwen/qwen3-32b`, `LLM_API_BASE_URL=https://api.groq.com/openai/v1` 기준 |
| `ELASTICSEARCH_USERNAME` | Secret | Elasticsearch/OpenSearch 사용자명 |
| `ELASTICSEARCH_PASSWORD` | Secret | Elasticsearch/OpenSearch 비밀번호 |
| `SMTP_HOST` | Secret | SMTP host |
| `SMTP_USERNAME` | Secret | SMTP 사용자명 |
| `SMTP_PASSWORD` | Secret | SMTP 비밀번호 |
| `SMTP_FROM` | Secret | 발신자 이메일 |
| `OPS_REPORT_EMAIL_RECIPIENTS` | Secret | 운영 리포트 수신자 목록, 쉼표 구분 |
| `RCA_EMAIL_RECIPIENTS` | Secret | Alertmanager 기반 preliminary/final RCA 이메일 수신자 목록, 쉼표 구분. 비워두면 `OPS_REPORT_EMAIL_RECIPIENTS`를 사용 |

선택적으로 아래 Variables를 바꿀 수 있습니다.

```text
K8S_NAMESPACE=default
K8S_DEPLOYMENT=mcp-aiops-backend
K8S_SERVICE=mcp-aiops-backend
K8S_SECRET_NAME=mcp-aiops-backend-secret
```

배포 후 기본 확인 endpoint:

```text
GET /health
GET /mcp/servers
GET /mcp/tools
POST /mcp-server/mcp
GET /api/v1/mcp/servers
GET /api/v1/mcp/tools
POST /api/v1/mcp-server/mcp
```

Alertmanager webhook은 `POST /api/alerts`로 수신합니다. 신규 firing alert는 즉시 preliminary RCA email을 만들고,
최종 RCA는 alert `startsAt` 기준 `10분 전 ~ 5분 후` 증거 윈도우가 닫힌 뒤 생성됩니다.
EKS에서는 `mcp-aiops-rca-due-job-runner` CronJob이 1분마다 `POST /rca/jobs/run-due`를 호출해
`scheduled_at`이 지난 RCA job만 처리합니다.

CloudFront에서 MCP 외부 접근이 필요하면 `/api/v1/mcp*`, `/api/v1/mcp-server*`
behavior를 기존 `catalog-api-alb` origin으로 추가합니다.

## 문서 관리 원칙

- 원본 기획서와 실제 DB schema SQL은 내부 공유용으로 관리합니다.
- 공개 가능한 ERD 요약은 `docs/erd.md`에만 작성합니다.
- API, MCP, ERD 구조 변경 시 공개 docs와 로컬 기획서를 함께 갱신합니다.

## 하드코딩 제거 방향

- production 서비스 코드는 샘플 농가, 샘플 상품, 샘플 예측 실행값을 fallback으로 사용하지 않습니다.
- 관리자 Copilot, RiskOps, BNPL, 예측/스케일링 조회는 Docker PostgreSQL의 `core`, `catalog`, `ai` schema를 기준으로 동작합니다.
- DB에 데이터가 없으면 빈 목록 또는 domain not-found 오류를 반환합니다. 샘플 데이터가 필요하면 production 코드가 아니라 테스트 fixture 또는 seed SQL에 둡니다.
- 테스트는 `tests/seed/local_dummy.sql`을 pytest session fixture에서 실행한 뒤 로컬 Docker PostgreSQL을 기준으로 검증합니다.
- 수동으로 seed를 다시 적용해야 할 때는 `python -m pytest`를 실행하거나, 같은 SQL을 로컬 DB에 직접 실행하면 됩니다.
