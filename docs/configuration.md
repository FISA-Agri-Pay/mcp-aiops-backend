# Configuration

이 문서는 `mcp-aiops-backend`의 환경변수와 LLM provider 설정을 정리합니다. 전체 예시는 루트의 `.env.example`을 기준으로 관리합니다.

## 기본 설정

로컬 개발에서는 `.env.example`을 복사해 시작합니다.

```powershell
Copy-Item .env.example .env
```

기본 로컬 DB 연결값은 다음과 같습니다. 실제 환경에서는 사용하는 PostgreSQL/RDS/Patroni 구성에 맞게 `DATABASE_URL`을 바꿉니다.

```text
DATABASE_URL=postgresql+psycopg://kkpp:kkpp@localhost:5432/kkpp
```

## LLM Provider

기본값은 로컬 개발용 `fake` provider입니다. 외부 LLM key 없이 planner, orchestration, API 응답 형태를 검증할 수 있습니다.

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

## 환경변수 그룹

| 구분 | 환경변수 |
| --- | --- |
| App | `APP_ENV`, `APP_NAME`, `APP_VERSION`, `APP_TIMEZONE`, `CORS_ALLOW_ORIGINS` |
| Database | `DATABASE_URL` |
| LLM | `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_BASE_URL`, `LLM_API_KEY`, `LLM_REQUIRE_API_KEY`, `LLM_MAX_TOKENS`, `LLM_TIMEOUT_SECONDS`, `LLM_TEMPERATURE` |
| Observability | `PROMETHEUS_BASE_URL`, `PROMETHEUS_SOURCE_URLS`, `LOKI_BASE_URL`, `LOKI_SOURCE_URLS`, `TEMPO_BASE_URL` |
| Kubernetes | `KUBERNETES_API_BASE_URL`, `KUBERNETES_BEARER_TOKEN_FILE`, `KUBERNETES_CA_CERT_FILE`, `KUBERNETES_NAMESPACE_ALLOWLIST` |
| On-prem Kubernetes | `ONPREM_KUBERNETES_API_BASE_URL`, `ONPREM_KUBERNETES_BEARER_TOKEN`, `ONPREM_KUBERNETES_CA_CERT`, `ONPREM_KUBERNETES_NAMESPACE_ALLOWLIST` |
| Infra optional tools | `INFRAOPS_ELK_ENABLED`, `INFRAOPS_KAFKA_ENABLED`, `INFRAOPS_BATCH_ENABLED` |
| Prediction scaling | `PREDICTION_SCALING_*` |
| RCA / report notification | `EMAIL_PROVIDER`, `SMTP_*`, `OPS_REPORT_EMAIL_RECIPIENTS`, `RCA_EMAIL_RECIPIENTS`, `RCA_SLACK_WEBHOOK_URL`, `RCA_SLACK_CHANNEL` |
| Watchers | `PREDICTION_SCALING_WATCHER_ENABLED`, `SRE_INSPECTION_WATCHER_ENABLED` |

## 운영 Secret

운영 secret은 Git에 커밋하지 않고 Kubernetes Secret 또는 GitHub Secrets로 주입합니다.

대표 secret:

- `DATABASE_URL`
- `LLM_API_KEY`
- `ONPREM_KUBERNETES_BEARER_TOKEN`
- `ONPREM_KUBERNETES_CA_CERT`
- `ELASTICSEARCH_USERNAME`
- `ELASTICSEARCH_PASSWORD`
- `SMTP_HOST`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`
- `SMTP_FROM`
- `OPS_REPORT_EMAIL_RECIPIENTS`
- `RCA_EMAIL_RECIPIENTS`
- `RCA_SLACK_WEBHOOK_URL`
- `PREDICTION_SCALING_SLACK_WEBHOOK_URL`

## 테스트 Seed

기본 테스트는 seed 적용 없이 실행됩니다.

```powershell
python -m pytest
```

로컬 DB fixture seed까지 적용해야 하는 테스트를 돌릴 때는 로컬 DB 스키마가 준비된 상태에서 opt-in 합니다.

```powershell
$env:RUN_TEST_SEEDS = "true"
python -m pytest
```
