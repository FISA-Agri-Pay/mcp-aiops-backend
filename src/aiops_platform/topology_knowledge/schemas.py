from typing import Literal

from pydantic import BaseModel, Field

TopologyEnvironment = Literal["onprem", "aws_eks", "all"]
TopologySnapshotDetail = Literal["summary", "full"]
TopologyMaskingLevel = Literal["secrets_only", "infrastructure"]


class TopologySnapshotItem(BaseModel):
    environment: str
    snapshot_name: str
    collected_date: str | None = None
    detail: TopologySnapshotDetail
    content: str
    sections: list[str] = Field(default_factory=list)
    truncated: bool = False


class TopologySnapshotResult(BaseModel):
    source: str = "topology_knowledge"
    storage_backend: str = "local_markdown"
    environment: TopologyEnvironment
    detail: TopologySnapshotDetail
    masking_level: TopologyMaskingLevel
    masking_applied: bool
    partial: bool
    snapshots: list[TopologySnapshotItem]
    warnings: list[str] = Field(default_factory=list)


class TopologyKnowledgeSearchMatch(BaseModel):
    environment: str
    snapshot_name: str
    section: str
    line: int
    score: int
    excerpt: str


class TopologyKnowledgeSearchResult(BaseModel):
    source: str = "topology_knowledge"
    storage_backend: str = "local_markdown"
    environment: TopologyEnvironment
    query: str
    limit: int
    masking_level: TopologyMaskingLevel
    masking_applied: bool
    matches: list[TopologyKnowledgeSearchMatch]
    warnings: list[str] = Field(default_factory=list)


class TopologyKnowledgeSectionMatch(BaseModel):
    environment: str
    snapshot_name: str
    section: str
    lines: list[str]


class ServiceRoutingPathResult(BaseModel):
    source: str = "topology_knowledge"
    storage_backend: str = "local_markdown"
    environment: TopologyEnvironment
    service: str
    aliases: list[str]
    masking_level: TopologyMaskingLevel
    masking_applied: bool
    routing_paths: list[TopologyKnowledgeSectionMatch]
    warnings: list[str] = Field(default_factory=list)


class ServiceDependencyMapResult(BaseModel):
    source: str = "topology_knowledge"
    storage_backend: str = "local_markdown"
    environment: TopologyEnvironment
    service: str
    aliases: list[str]
    masking_level: TopologyMaskingLevel
    masking_applied: bool
    dependencies: list[TopologyKnowledgeSectionMatch]
    warnings: list[str] = Field(default_factory=list)
