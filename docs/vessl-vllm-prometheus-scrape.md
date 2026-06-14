# VESSL vLLM Prometheus and AWS Grafana Setup

## Goal

Expose VESSL-hosted Qwen3-32B vLLM and H100 GPU metrics to the existing AWS EKS Grafana dashboard without opening VESSL metrics ports publicly.

## Final Architecture

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

## VESSL Components

- vLLM model: `Qwen/Qwen3-32B`
- vLLM metrics endpoint: `127.0.0.1:8000/metrics`
- GPU exporter endpoint: `127.0.0.1:9400/metrics`
- Prometheus config: `infra/vessl/prometheus.yml`
- GPU exporter script: `infra/vessl/nvidia_smi_exporter.py`

Prometheus scrapes both local VESSL endpoints and keeps the metrics private on `127.0.0.1:9090`.

## AWS EKS Components

- Tunnel manifest: `infra/k8s/monitoring/vessl-prometheus-tunnel.yaml`
- Required Secret, created outside Git:

```bash
kubectl create secret generic vessl-llm-ssh-key \
  -n monitoring \
  --from-file=id_ed25519=/path/to/kkpp-llm-server-ver1.pem
```

- Grafana datasource: `infra/grafana/vessl-prometheus-datasource.json`
- Grafana dashboard: `infra/grafana/vessl-vllm-qwen3-dashboard.json`

## Verification

From the VESSL server:

```bash
curl http://127.0.0.1:9090/-/ready
curl 'http://127.0.0.1:9090/api/v1/query?query=vllm%3Anum_requests_running'
curl 'http://127.0.0.1:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL'
```

From the AWS Grafana pod:

```bash
kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- http://vessl-prometheus.monitoring.svc.cluster.local:9090/-/ready

kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- 'http://vessl-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=vllm%3Anum_requests_running'

kubectl exec -n monitoring <grafana-pod> -- \
  wget -qO- 'http://vessl-prometheus.monitoring.svc.cluster.local:9090/api/v1/query?query=DCGM_FI_DEV_GPU_UTIL'
```

Expected:

- Prometheus readiness returns `Prometheus is Ready.`
- `vllm:num_requests_running` returns at least one series.
- `DCGM_FI_DEV_GPU_UTIL` returns at least one series.
- Grafana dashboard `vessl-vllm-qwen3` no longer shows `No data` after refresh.

## Operational Notes

- VESSL SSH host keys may change when the VESSL instance is recreated. The demo tunnel uses `StrictHostKeyChecking=no` for availability. Pin the host key for production.
- VESSL-local Prometheus and the GPU exporter are started inside the VESSL runtime. If the VESSL workspace is recreated, restart them or add equivalent startup commands.
- The SSH private key Secret is intentionally not stored in Git.
