# mcp-aiops-backend

MCP 기반 농업 BNPL AIOps 백엔드입니다.

## 로컬 개발환경

### 1. 환경변수 준비

```powershell
Copy-Item .env.example .env
```

실제 secret, 운영 URL, 내부 schema SQL은 Git에 올리지 않습니다.

### 2. PostgreSQL 실행

```powershell
docker compose up -d postgres
```

기본 로컬 포트는 기존 KongKongFarm PostgreSQL과 충돌하지 않도록 `55432`를 사용합니다.

내부 DB schema SQL은 아래 위치에 둡니다.

```text
infra/docker/postgres/init/001_init_schema.sql
```

이 SQL은 내부 공유용이므로 `.gitignore`에 의해 제외됩니다.

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

## 문서 관리 원칙

- 원본 기획서와 실제 DB schema SQL은 내부 공유용으로 관리합니다.
- 공개 가능한 ERD 요약은 `docs/erd.md`에만 작성합니다.
- API, MCP, ERD 구조 변경 시 공개 docs와 로컬 기획서를 함께 갱신합니다.
