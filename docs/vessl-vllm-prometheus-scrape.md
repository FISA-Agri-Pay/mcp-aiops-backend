# VESSL vLLM Prometheus와 AWS Grafana 연동

## 목표

VESSL metrics 포트를 외부에 공개하지 않으면서, VESSL에서 호스팅하는 Qwen3-32B vLLM과 H100 GPU metric을 기존 AWS EKS Grafana 대시보드에 노출합니다.

## 최종 아키텍처

```text
VESSL AI
  vLLM metrics       http://127.0.0.1:8000/metrics
  GPU metrics        http://127.0.0.1:9400/metrics
  Prometheus         http://127.0.0.1:9090

AWS EKS monitoring namespace
  vessl-prometheus-tunnel Deployment
    -> SSH local forward to VESSL localhost:9090
  vessl-prometheus Service
    -> http://vessl-prometheus.monitoring.svc.cluster.local:9090

AWS Grafana
  datasource uid     vessl-prometheus
  dashboard uid      vessl-vllm-qwen3
```

## VESSL 구성 요소

- vLLM 모델: `Qwen/Qwen3-32B`
- vLLM metrics endpoint: `127.0.0.1:8000/metrics`
- GPU exporter endpoint: `127.0.0.1:9400/metrics`
- Prometheus 설정: `infra/vessl/prometheus.yml`
- GPU exporter 스크립트: `infra/vessl/nvidia_smi_exporter.py`

Prometheus는 두 VESSL 로컬 endpoint를 스크랩하며, metric을 `127.0.0.1:9090`에만 비공개로 유지합니다.

## AWS EKS 구성 요소

- 터널 manifest: `infra/k8s/monitoring/vessl-prometheus-tunnel.yaml`
- Git 밖에서 생성하는 필수 Secret:

```bash
kubectl create secret generic vessl-llm-ssh-key \
  -n monitoring \
  --from-file=id_ed25519=/path/to/kkpp-llm-server-ver1.pem
```

- Grafana datasource: `infra/grafana/vessl-prometheus-datasource.json`
- Grafana dashboard: `infra/grafana/vessl-vllm-qwen3-dashboard.json`

## 검증

VESSL 서버에서:

```bash
curl http://127.0.0.1:9090/-/ready
curl 'http://127.0.0.1:9090/api/v1/query?query=vllm%3Anum_requests_running'
curl 'http://127.0.0.1:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL'
```

AWS Grafana pod에서:

```bash
kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- http://vessl-prometheus.monitoring.svc.cluster.local:9090/-/ready

kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- 'http://vessl-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=vllm%3Anum_requests_running'

kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- 'http://vessl-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL'
```

기대 결과:

- Prometheus readiness가 `Prometheus is Ready.`를 반환합니다.
- `vllm:num_requests_running`이 최소 1개 이상의 series를 반환합니다.
- `DCGM_FI_DEV_GPU_UTIL`이 최소 1개 이상의 series를 반환합니다.
- Grafana 대시보드 `vessl-vllm-qwen3`가 새로고침 후 더 이상 `No data`를 표시하지 않습니다.

## 운영 참고 사항

- VESSL 인스턴스가 재생성되면 VESSL SSH host key가 바뀔 수 있습니다. 데모용 터널은 가용성을 위해 `StrictHostKeyChecking=no`를 사용합니다. 운영 환경에서는 host key를 고정합니다.
- VESSL 로컬 Prometheus와 GPU exporter는 VESSL runtime 내부에서 시작됩니다. VESSL workspace가 재생성되면 재시작하거나 동일한 시작 명령을 다시 추가해야 합니다.
- SSH private key Secret은 의도적으로 Git에 저장하지 않습니다.
