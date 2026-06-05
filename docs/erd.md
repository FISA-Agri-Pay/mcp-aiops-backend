# ERD 요약

이 문서는 `aiops-platform` 데이터 모델의 공개 가능한 요약본입니다.
상세 컬럼, 제약조건, seed data, 실행 가능한 SQL은 내부 공유용으로만 관리합니다.

`aiops-platform`은 KongKongFarm의 기존 `core.*`, `catalog.*` 비즈니스 테이블을 대체하지 않습니다.
AI/LLM/MCP 확장 기능은 별도 `ai` schema에 두고, 기존 도메인 객체는 `*_public_id` 값으로 참조합니다.

## 데이터 도메인

| 도메인 | 목적 |
|---|---|
| 채팅과 LLM 감사 | AI 채팅 세션, 메시지, 프롬프트 버전, LLM 실행, MCP Tool 호출 이력을 추적합니다. |
| MCP Registry | 챗봇, RiskOps, InfraOps, 예측 워크플로우에서 사용하는 MCP Server와 MCP Tool을 관리합니다. |
| Job 오케스트레이션 | RCA, 리포트, 예측 실행, 알림, 승인, BNPL 결제 초안 처리 같은 비동기 작업을 관리합니다. |
| InfraOps와 RCA | incident, alert payload, Prometheus/Loki/ELK/Kubernetes 관측 snapshot, RCA 보고서, RCA 피드백을 관리합니다. |
| 운영 리포트 | 일간/주간/스케일링/RiskOps 리포트와 전처리된 metric summary를 관리합니다. |
| Farmer BNPL checkout | AI 결제 초안, 추천 상품 항목, 결제 요청 발행 이벤트를 관리합니다. 실제 결제 요청은 기존 `catalog.bnpl_payment_requests` 흐름을 사용합니다. |
| 외부 비즈니스 참조 | 기존 KongKongFarm 도메인 엔티티를 직접 재생성하지 않고 `target_table`, `target_public_id`로 연결합니다. |
| 농업 조언 | 농업 조언 case, 작물 일정, 농자재 추천, 리스크/수익 시뮬레이션 결과를 관리합니다. |
| Admin RiskOps | 신용 심사 대기열, 연체 현황, 리스크 분석 보고서, 분석 대상, 재해 리스크 시뮬레이션 결과를 관리합니다. |
| 예측과 스케일링 | 모델 버전, 예측 실행, 예측 metric, 실제 metric, 예측 오차, scaling event, 예측/스케일링 분석 snapshot을 관리합니다. |
| 알림과 승인 | 기존 `core.notifications`와 분리된 AI 운영 알림 outbox와 human-in-the-loop 승인 흐름을 관리합니다. |

## 관계 요약

- 기존 사용자는 `core.users.public_id` 기반으로 AI 채팅 세션, 농업 조언 case, BNPL 결제 초안, 관리자 분석 요청과 연결됩니다.
- 채팅 세션은 여러 메시지를 포함하며, 메시지는 LLM 실행과 MCP Tool 호출 이력에 연결될 수 있습니다.
- MCP Server는 여러 MCP Tool을 제공하고, 모든 Tool 호출은 job, 사용자, 세션, 권한 맥락과 함께 감사 로그로 저장됩니다.
- Prompt version은 LLM 실행과 연결되어 생성 결과의 재현성과 감사 가능성을 높입니다.
- Incident는 alert event를 포함하며, 관측 snapshot과 RCA 보고서 생성의 기준이 됩니다.
- 관측 snapshot item은 `PROMETHEUS`, `LOKI`, `ELASTICSEARCH`, `KIBANA`, `LOGSTASH`, `KUBERNETES` 등 source를 구분해 저장합니다.
- 운영 리포트는 incident 요약과 전처리된 metric summary를 포함할 수 있습니다.
- AI BNPL 결제 초안은 추천 상품 항목을 포함하고, 사용자 명시 승인 이후 기존 BNPL 결제 요청 흐름으로 이벤트를 발행합니다.
- 기존 KongKongFarm 엔티티는 cross-service FK 대신 `*_public_id` 또는 외부 비즈니스 참조로 연결합니다.
- 농업 조언 case는 하나 이상의 조언 결과를 생성할 수 있으며, 추천 결과는 BNPL checkout 초안의 추천 상품 항목으로 이어질 수 있습니다.
- 리스크 분석 보고서는 여러 비즈니스 참조를 분석할 수 있고, 재해 리스크 시뮬레이션과 상환/연체 알림 승인 흐름에 연결될 수 있습니다.
- 예측 실행은 예측 metric을 생성하고, 실제 metric과 비교되어 예측 오차 metric과 예측 분석 snapshot으로 저장될 수 있습니다.
- Scaling event는 KEDA/HPA 분석을 위해 수집되며 예측 metric 또는 스케일링 분석 snapshot과 연결될 수 있습니다.
- 알림과 승인 record는 운영, 리스크, 리포트, RCA, MCP Tool 호출 워크플로우에 연결됩니다.

## 내부 전용 산출물

실행 가능한 PostgreSQL schema는 내부 공유용 파일로 관리합니다.

```text
infra/docker/postgres/init/001_init_schema.sql
```

이 파일은 Git에서 제외됩니다. 내부 schema가 변경되더라도 공개 가능한 도메인 또는 관계 모델이 바뀐 경우에만 이 요약 문서를 갱신합니다.
