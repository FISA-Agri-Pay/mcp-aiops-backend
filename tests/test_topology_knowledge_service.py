from aiops_platform.topology_knowledge.service import TopologyKnowledgeService


def test_topology_service_reads_summary_and_masks_secrets(tmp_path) -> None:
    snapshot = tmp_path / "onprem-topology-snapshot-2026-06-11.md"
    snapshot.write_text(
        """# On-Prem Topology Snapshot - 2026-06-11

## Summary

- Ingress path is MetalLB 10.30.2.100 -> ingress-nginx.
- password=do-not-leak

## Dependency Map

| Source | Target |
| --- | --- |
| checkout | service-catalog |
""",
        encoding="utf-8",
    )

    service = TopologyKnowledgeService(knowledge_dirs=(tmp_path,))

    result = service.get_topology_snapshot(environment="onprem", detail="summary")

    assert len(result.snapshots) == 1
    assert result.snapshots[0].environment == "onprem"
    assert "MetalLB 10.30.2.100" in result.snapshots[0].content
    assert "do-not-leak" not in result.snapshots[0].content
    assert "***MASKED***" in result.snapshots[0].content


def test_topology_service_can_mask_infrastructure_identifiers(tmp_path) -> None:
    snapshot = tmp_path / "aws-eks-topology-snapshot-2026-06-11.md"
    snapshot.write_text(
        """# AWS/EKS Topology Snapshot - 2026-06-11

## Summary

- Account 153585581837 routes to 172.20.0.1.
- ALB internal-example.elb.amazonaws.com is healthy.
- Role arn:aws:iam::153585581837:role/example is attached.
""",
        encoding="utf-8",
    )

    service = TopologyKnowledgeService(knowledge_dirs=(tmp_path,))

    result = service.get_topology_snapshot(
        environment="aws_eks",
        detail="summary",
        masking_level="infrastructure",
    )
    content = result.snapshots[0].content

    assert "153585581837" not in content
    assert "172.20.0.1" not in content
    assert "internal-example.elb.amazonaws.com" not in content
    assert "arn:aws:iam" not in content
    assert "***ACCOUNT_ID***" in content
    assert "***IP***" in content
    assert "***DNS***" in content
    assert "arn:aws:***MASKED***" in content


def test_topology_service_search_and_service_maps(tmp_path) -> None:
    snapshot = tmp_path / "aws-eks-topology-snapshot-2026-06-11.md"
    snapshot.write_text(
        """# AWS/EKS Topology Snapshot - 2026-06-11

## CloudFront And Edge Routing

| Path | Origin |
| --- | --- |
| /api/v1/checkout-requests* | catalog-api-alb |

## Dependency Map

| Source | Target | Type |
| --- | --- | --- |
| checkout | service-catalog | edge-to-eks |
| service-catalog | credit-payment-requested.fifo | queue |
""",
        encoding="utf-8",
    )

    service = TopologyKnowledgeService(knowledge_dirs=(tmp_path,))

    search = service.search_topology_knowledge(query="checkout", environment="all")
    routing = service.get_service_routing_path(service="checkout", environment="all")
    dependencies = service.get_service_dependency_map(service="checkout", environment="all")

    assert search.matches
    assert routing.routing_paths
    assert dependencies.dependencies
    assert any("checkout-requests" in line for match in routing.routing_paths for line in match.lines)
    assert any("service-catalog" in line for match in dependencies.dependencies for line in match.lines)


def test_topology_service_maps_ignore_sections_without_service_alias(tmp_path) -> None:
    snapshot = tmp_path / "aws-eks-topology-snapshot-2026-06-11.md"
    snapshot.write_text(
        """# AWS/EKS Topology Snapshot - 2026-06-11

## CloudFront And Edge Routing

| Path | Origin |
| --- | --- |
| /api/v1/checkout-requests* | catalog-api-alb |

## Dependency Map

| Source | Target | Type |
| --- | --- | --- |
| checkout | service-catalog | edge-to-eks |

## Observability

- Tempo traces are exported through the shared collector.
""",
        encoding="utf-8",
    )

    service = TopologyKnowledgeService(knowledge_dirs=(tmp_path,))

    routing = service.get_service_routing_path(service="payment", environment="all")
    dependencies = service.get_service_dependency_map(service="payment", environment="all")

    assert routing.routing_paths == []
    assert dependencies.dependencies == []
