# Deployment

이 문서는 `mcp-aiops-backend`의 컨테이너 실행, Kubernetes 배포, GitHub Actions 배포 흐름을 정리합니다.

## Docker

```powershell
docker build -t mcp-aiops-backend .
docker run --env-file .env -p 8000:8000 mcp-aiops-backend
```

런타임 이미지는 distroless nonroot 기반이며 기본 command는 다음과 같습니다.

```text
python -m uvicorn aiops_platform.main:app --host 0.0.0.0 --port 8000
```

## Kubernetes Manifests

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

`secret.example.yaml`은 예시 파일입니다. 실제 운영 secret은 Git에 커밋하지 않고 Kubernetes Secret 또는 GitHub Secrets로 주입합니다.

공용 Ingress는 service-catalog 또는 infra IaC에서 단일 소유로 관리합니다. `infra/k8s/ingress.yaml`은 service-catalog Ingress에 합쳐야 하는 MCP 경로 참고본입니다.

대표 외부 경로:

```text
/api/alerts
/alerts/webhook
/reports/ops
/api/v1/mcp
/api/v1/mcp-server
```

## GitHub Actions

`.github/workflows/deploy.yml`은 branch push와 수동 실행에서 다음 순서로 동작합니다.

```text
pytest
Docker image build
Amazon ECR push
EKS kubeconfig 설정
ConfigMap / Secret / Manifest 적용
Deployment rollout 확인
서비스 내부 /health smoke test
```

필수 GitHub Actions 입력값:

| 이름 | 위치 | 설명 |
| --- | --- | --- |
| `AWS_ROLE_ARN` | Variable 또는 Secret | GitHub OIDC가 assume할 AWS IAM Role 전체 ARN |
| `AWS_REGION` | Variable 또는 Secret | AWS 리전 |
| `ECR_REPOSITORY` | Variable 또는 Secret | ECR 리포지토리 이름 |
| `EKS_CLUSTER_NAME` | Variable 또는 Secret | EKS 클러스터 이름 |
| `DATABASE_URL` | Secret | 운영 PostgreSQL/RDS 연결 문자열 |
| `LLM_API_KEY` | Secret | 외부 LLM API key |
| `SMTP_HOST`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_FROM` | Secret | 운영 리포트/RCA 이메일 발송 설정 |
| `OPS_REPORT_EMAIL_RECIPIENTS` | Secret | 운영 리포트 수신자 목록 |
| `RCA_SLACK_WEBHOOK_URL` | Secret | RCA evidence/analysis Slack 알림 webhook |

선택적으로 아래 Variables를 바꿀 수 있습니다.

```text
K8S_NAMESPACE=aiops
K8S_DEPLOYMENT=mcp-aiops-backend
K8S_SERVICE=mcp-aiops-backend
K8S_SECRET_NAME=mcp-aiops-backend-secret
```

## Smoke Test

배포 후 확인할 대표 endpoint:

```text
GET /health
GET /mcp/servers
GET /mcp/tools
POST /mcp-server/mcp
GET /api/v1/mcp/servers
POST /api/v1/mcp-server/mcp
```

Alertmanager webhook은 `POST /api/alerts`로 수신합니다. 신규 firing alert는 preliminary RCA 알림과 최종 RCA 흐름으로 이어지고, due RCA job은 `POST /rca/jobs/run-due`를 통해 처리됩니다.
