from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from aiops_platform.core.config import Settings, settings
from aiops_platform.topology_knowledge.schemas import (
    ServiceDependencyMapResult,
    ServiceRoutingPathResult,
    TopologyEnvironment,
    TopologyKnowledgeSearchMatch,
    TopologyKnowledgeSearchResult,
    TopologyKnowledgeSectionMatch,
    TopologyMaskingLevel,
    TopologySnapshotDetail,
    TopologySnapshotItem,
    TopologySnapshotResult,
)

SNAPSHOT_GLOB = "*topology-snapshot-*.md"
MAX_FULL_CONTENT_CHARS = 16_000
MAX_SUMMARY_CONTENT_CHARS = 6_000
MAX_SECTION_LINES = 80

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$", re.MULTILINE)
DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")
TOKEN_PATTERN = re.compile(r"[A-Za-z0-9가-힣_.:/-]+")
SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(password|passwd|secret|token|api[_-]?key|authorization|"
    r"access[_-]?key|private[_-]?key)\b(\s*[:=]\s*)([^\s`|,]+)"
)
IPV4_PATTERN = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?::\d{1,5})?(?:/\d{1,2})?\b")
AWS_ARN_PATTERN = re.compile(r"arn:aws:[^\s`|,)]+")
AWS_ACCOUNT_PATTERN = re.compile(r"\b\d{12}\b")
AWS_DNS_PATTERN = re.compile(
    r"\b[A-Za-z0-9.-]+(?:elb|cloudfront|amazonaws)\.com\b"
)

SERVICE_ALIASES: dict[str, tuple[str, ...]] = {
    "checkout": (
        "checkout",
        "checkout-requests",
        "service-catalog",
        "catalog-api",
        "cart",
    ),
    "service-catalog": (
        "service-catalog",
        "catalog",
        "checkout-requests",
        "products",
        "categories",
        "cart",
    ),
    "catalog": (
        "service-catalog",
        "catalog",
        "checkout-requests",
        "products",
        "categories",
        "cart",
    ),
    "payment": (
        "payment",
        "service-payment",
        "credit-payment",
        "sqs",
        "pin",
    ),
    "pin": (
        "pin",
        "payment-pin",
        "payment-pin-verified",
        "service-payment",
        "sqs",
    ),
    "auth": (
        "auth",
        "service-auth",
        "admin-api",
        "api/v1/auth",
    ),
    "admin": (
        "admin",
        "service-admin",
        "admin-api",
        "api/v1/admin",
    ),
    "core": (
        "core",
        "service-core",
        "admin-api",
        "api/v1/core",
    ),
    "aiops": (
        "aiops",
        "mcp-aiops",
        "mcp",
        "admin/copilot",
    ),
    "loki": ("loki", "logs", "fluent-bit"),
    "tempo": ("tempo", "otel", "trace", "traces"),
}

ROUTING_SECTION_KEYWORDS = (
    "traffic flow",
    "cloudfront",
    "edge routing",
    "load balancers",
    "kubernetes services",
    "ingress",
    "dependency map",
    "incident analysis hints",
)
DEPENDENCY_SECTION_KEYWORDS = (
    "dependency map",
    "observability",
    "sqs",
    "traces",
    "logs",
    "storage",
    "keda",
    "dns",
    "risk findings",
)


@dataclass(frozen=True)
class MarkdownSection:
    title: str
    normalized_title: str
    level: int
    start_line: int
    content: str


@dataclass(frozen=True)
class TopologySnapshotDocument:
    environment: str
    path: Path
    name: str
    collected_date: str | None
    text: str
    sections: tuple[MarkdownSection, ...]


class TopologyKnowledgeService:
    """Read-only topology knowledge facade.

    The first storage adapter is local Markdown so Milestone 3 can ship without
    committing to DB/S3. The MCP tool contract can stay fixed while this reader
    is later swapped for S3 or an internal object store.
    """

    def __init__(self, *, knowledge_dirs: Iterable[str | Path]) -> None:
        self._knowledge_dirs = tuple(Path(path) for path in knowledge_dirs)

    @classmethod
    def from_settings(cls, app_settings: Settings | None = None) -> "TopologyKnowledgeService":
        app_settings = app_settings or settings
        return cls(
            knowledge_dirs=parse_knowledge_dirs(app_settings.topology_knowledge_dirs)
        )

    def get_topology_snapshot(
        self,
        *,
        environment: TopologyEnvironment = "all",
        detail: TopologySnapshotDetail = "summary",
        masking_level: TopologyMaskingLevel = "secrets_only",
    ) -> TopologySnapshotResult:
        documents = self._load_documents(environment)
        max_chars = MAX_FULL_CONTENT_CHARS if detail == "full" else MAX_SUMMARY_CONTENT_CHARS
        snapshots: list[TopologySnapshotItem] = []

        for document in documents:
            content = (
                document.text
                if detail == "full"
                else extract_named_sections(
                    document,
                    ("summary", "coverage check"),
                    fallback_chars=max_chars,
                )
            )
            content, truncated = truncate_text(content, max_chars=max_chars)
            content = mask_text(content, masking_level=masking_level)
            snapshots.append(
                TopologySnapshotItem(
                    environment=document.environment,
                    snapshot_name=document.name,
                    collected_date=document.collected_date,
                    detail=detail,
                    content=content,
                    sections=[section.title for section in document.sections],
                    truncated=truncated,
                )
            )

        return TopologySnapshotResult(
            environment=environment,
            detail=detail,
            masking_level=masking_level,
            masking_applied=True,
            partial=False,
            snapshots=snapshots,
            warnings=build_missing_snapshot_warnings(environment, documents),
        )

    def search_topology_knowledge(
        self,
        *,
        query: str,
        environment: TopologyEnvironment = "all",
        limit: int = 5,
        masking_level: TopologyMaskingLevel = "secrets_only",
    ) -> TopologyKnowledgeSearchResult:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("query must not be blank.")
        resolved_limit = max(1, min(limit, 20))
        terms = tokenize(normalized_query)
        documents = self._load_documents(environment)
        matches: list[TopologyKnowledgeSearchMatch] = []

        for document in documents:
            for section in document.sections:
                score = score_text(section.content, terms) + score_text(section.title, terms)
                if score <= 0:
                    continue
                excerpt = build_excerpt(section.content, terms)
                matches.append(
                    TopologyKnowledgeSearchMatch(
                        environment=document.environment,
                        snapshot_name=document.name,
                        section=section.title,
                        line=section.start_line,
                        score=score,
                        excerpt=mask_text(excerpt, masking_level=masking_level),
                    )
                )

        matches.sort(key=lambda item: (-item.score, item.environment, item.line))
        return TopologyKnowledgeSearchResult(
            environment=environment,
            query=normalized_query,
            limit=resolved_limit,
            masking_level=masking_level,
            masking_applied=True,
            matches=matches[:resolved_limit],
            warnings=build_missing_snapshot_warnings(environment, documents),
        )

    def get_service_routing_path(
        self,
        *,
        service: str,
        environment: TopologyEnvironment = "all",
        masking_level: TopologyMaskingLevel = "secrets_only",
    ) -> ServiceRoutingPathResult:
        aliases = build_aliases(service)
        documents = self._load_documents(environment)
        routing_paths = [
            match
            for document in documents
            for match in extract_service_section_matches(
                document=document,
                aliases=aliases,
                section_keywords=ROUTING_SECTION_KEYWORDS,
                masking_level=masking_level,
            )
        ]
        return ServiceRoutingPathResult(
            environment=environment,
            service=service,
            aliases=aliases,
            masking_level=masking_level,
            masking_applied=True,
            routing_paths=routing_paths,
            warnings=build_missing_snapshot_warnings(environment, documents),
        )

    def get_service_dependency_map(
        self,
        *,
        service: str,
        environment: TopologyEnvironment = "all",
        masking_level: TopologyMaskingLevel = "secrets_only",
    ) -> ServiceDependencyMapResult:
        aliases = build_aliases(service)
        documents = self._load_documents(environment)
        dependencies = [
            match
            for document in documents
            for match in extract_service_section_matches(
                document=document,
                aliases=aliases,
                section_keywords=DEPENDENCY_SECTION_KEYWORDS,
                masking_level=masking_level,
            )
        ]
        return ServiceDependencyMapResult(
            environment=environment,
            service=service,
            aliases=aliases,
            masking_level=masking_level,
            masking_applied=True,
            dependencies=dependencies,
            warnings=build_missing_snapshot_warnings(environment, documents),
        )

    def _load_documents(self, environment: TopologyEnvironment) -> list[TopologySnapshotDocument]:
        paths = {
            path.resolve()
            for directory in self._knowledge_dirs
            for path in resolve_knowledge_dir(directory).glob(SNAPSHOT_GLOB)
            if path.is_file()
        }
        documents = [
            load_markdown_document(path)
            for path in sorted(paths, key=lambda item: item.name, reverse=True)
        ]
        return [
            document
            for document in documents
            if environment == "all" or document.environment == environment
        ]


def parse_knowledge_dirs(value: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in value.split(",") if part.strip())


def resolve_knowledge_dir(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def load_markdown_document(path: Path) -> TopologySnapshotDocument:
    text = path.read_text(encoding="utf-8")
    name = path.name
    return TopologySnapshotDocument(
        environment=infer_environment(name, text),
        path=path,
        name=name,
        collected_date=infer_collected_date(name),
        text=text,
        sections=tuple(split_markdown_sections(text)),
    )


def infer_environment(name: str, text: str) -> str:
    normalized = f"{name}\n{text[:300]}".lower()
    if "onprem" in normalized or "on-prem" in normalized:
        return "onprem"
    if "aws" in normalized or "eks" in normalized:
        return "aws_eks"
    return "unknown"


def infer_collected_date(name: str) -> str | None:
    match = DATE_PATTERN.search(name)
    return match.group(1) if match else None


def split_markdown_sections(text: str) -> list[MarkdownSection]:
    matches = list(HEADING_PATTERN.finditer(text))
    if not matches:
        return [
            MarkdownSection(
                title="Document",
                normalized_title="document",
                level=1,
                start_line=1,
                content=text,
            )
        ]

    sections: list[MarkdownSection] = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        title = match.group(2).strip()
        sections.append(
            MarkdownSection(
                title=title,
                normalized_title=normalize_text(title),
                level=len(match.group(1)),
                start_line=text.count("\n", 0, start) + 1,
                content=text[start:end].strip(),
            )
        )
    return sections


def extract_named_sections(
    document: TopologySnapshotDocument,
    names: tuple[str, ...],
    *,
    fallback_chars: int,
) -> str:
    selected = [
        section.content
        for section in document.sections
        if section.normalized_title in names
    ]
    if selected:
        return "\n\n".join(selected)
    return document.text[:fallback_chars]


def tokenize(value: str) -> list[str]:
    return [token.lower() for token in TOKEN_PATTERN.findall(value) if token.strip()]


def normalize_text(value: str) -> str:
    return " ".join(tokenize(value))


def score_text(value: str, terms: Iterable[str]) -> int:
    normalized = value.lower()
    return sum(normalized.count(term) for term in terms)


def build_excerpt(content: str, terms: list[str], *, radius: int = 280) -> str:
    lowered = content.lower()
    first_index = min(
        (lowered.find(term) for term in terms if lowered.find(term) >= 0),
        default=0,
    )
    start = max(0, first_index - radius)
    end = min(len(content), first_index + radius)
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(content) else ""
    return f"{prefix}{content[start:end].strip()}{suffix}"


def truncate_text(content: str, *, max_chars: int) -> tuple[str, bool]:
    if len(content) <= max_chars:
        return content, False
    return content[:max_chars].rstrip() + "\n\n[truncated]", True


def mask_text(content: str, *, masking_level: TopologyMaskingLevel) -> str:
    masked = SECRET_ASSIGNMENT_PATTERN.sub(r"\1\2***MASKED***", content)
    if masking_level == "infrastructure":
        masked = AWS_ARN_PATTERN.sub("arn:aws:***MASKED***", masked)
        masked = AWS_ACCOUNT_PATTERN.sub("***ACCOUNT_ID***", masked)
        masked = AWS_DNS_PATTERN.sub("***DNS***", masked)
        masked = IPV4_PATTERN.sub("***IP***", masked)
    return masked


def build_aliases(service: str) -> list[str]:
    normalized = service.strip().lower()
    if not normalized:
        raise ValueError("service must not be blank.")
    aliases = {normalized}
    aliases.update(SERVICE_ALIASES.get(normalized, ()))
    return sorted(aliases)


def extract_service_section_matches(
    *,
    document: TopologySnapshotDocument,
    aliases: list[str],
    section_keywords: tuple[str, ...],
    masking_level: TopologyMaskingLevel,
) -> list[TopologyKnowledgeSectionMatch]:
    matches: list[TopologyKnowledgeSectionMatch] = []
    normalized_aliases = tuple(alias.lower() for alias in aliases)
    for section in document.sections:
        if not any(keyword in section.normalized_title for keyword in section_keywords):
            continue
        section_lines = section.content.splitlines()
        matched_lines = [
            line
            for line in section_lines
            if any(alias in line.lower() for alias in normalized_aliases)
        ]
        if not matched_lines:
            continue
        matches.append(
            TopologyKnowledgeSectionMatch(
                environment=document.environment,
                snapshot_name=document.name,
                section=section.title,
                lines=[
                    mask_text(line, masking_level=masking_level)
                    for line in matched_lines[:MAX_SECTION_LINES]
                ],
            )
        )
    return matches


def build_missing_snapshot_warnings(
    environment: TopologyEnvironment,
    documents: list[TopologySnapshotDocument],
) -> list[str]:
    if documents:
        return []
    if environment == "all":
        return ["No topology snapshot markdown files were found."]
    return [f"No topology snapshot markdown files were found for environment={environment}."]
