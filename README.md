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
