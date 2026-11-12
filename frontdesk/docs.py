"""Public documentation retrieval and markdown chunking.

The product specification treats arbitrary repository ingestion as out of
scope. This connector is an explicit, administrator-enabled convenience for
these two open-source organizations: only the configured public repositories
and their README/CONTRIBUTING files are read. Provider-entered text remains the
authoritative knowledge source.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path

import httpx

from .config import OrgDefinition, RepoDefinition, Settings
from .routing import RepoRoute
from .text import excerpt, score_text, token_set
from .timeutil import utc_now


@dataclass(frozen=True)
class DocChunk:
    repo_name: str
    doc: str
    heading: str
    text: str
    url: str
    score: float
    coverage: float

    @property
    def citation(self) -> str:
        label = f"{self.repo_name}/{self.doc}"
        if self.heading:
            label = f"{label} § {self.heading}"
        return label


def _safe_part(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def chunk_markdown(text: str, max_chars: int = 1400) -> list[tuple[str, str]]:
    """Split markdown into (heading, chunk) pairs."""
    chunks: list[tuple[str, str]] = []
    heading = ""
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        body = "\n".join(buffer).strip()
        if body:
            chunks.append((heading, body))
        buffer = []

    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            flush()
            heading = stripped.lstrip("#").strip()[:120]
            continue
        if not stripped:
            flush()
            continue
        buffer.append(line)
        if sum(len(item) + 1 for item in buffer) >= max_chars:
            flush()
    flush()
    return chunks


class DocsService:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.cache_dir = settings.docs_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.client = httpx.AsyncClient(
            timeout=httpx.Timeout(12.0, connect=6.0),
            follow_redirects=True,
            headers={"User-Agent": "aossie-stability-frontdesk/1.0"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    def _cache_path(self, org: OrgDefinition, repo: RepoDefinition, doc: str) -> Path:
        path = self.cache_dir / org.key / _safe_part(repo.name) / _safe_part(doc)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def _fresh(self, path: Path) -> bool:
        if not path.exists():
            return False
        age = utc_now().timestamp() - path.stat().st_mtime
        return age < self.settings.docs_cache_ttl_hours * 3600

    async def fetch_doc(self, org: OrgDefinition, repo: RepoDefinition, doc: str) -> str | None:
        cache_path = self._cache_path(org, repo, doc)
        if self._fresh(cache_path):
            return cache_path.read_text(encoding="utf-8", errors="ignore")

        branches = [repo.default_branch, "main", "master", "dev", "develop"]
        seen: set[str] = set()
        for branch in branches:
            if branch in seen:
                continue
            seen.add(branch)
            url = f"https://raw.githubusercontent.com/{org.github_org}/{repo.name}/{branch}/{doc}"
            try:
                response = await self.client.get(url)
            except httpx.HTTPError:
                continue
            if response.status_code == 200 and response.text.strip():
                text = response.text[:120_000]
                cache_path.write_text(text, encoding="utf-8")
                return text
            if response.status_code not in {404, 403, 429}:
                continue
        if cache_path.exists():
            # Serve stale documentation rather than failing the conversation.
            return cache_path.read_text(encoding="utf-8", errors="ignore")
        return None

    async def retrieve(
        self,
        org: OrgDefinition,
        routes: list[RepoRoute],
        question: str,
        max_chunks: int = 4,
    ) -> list[DocChunk]:
        if not self.settings.repo_docs_enabled or not routes:
            return []

        tasks: list[asyncio.Task[tuple[RepoRoute, str, str | None]]] = []
        for route in routes[:2]:
            repo = org.repos.get(route.name)
            if repo is None:
                continue
            for doc in route.docs[:2]:
                tasks.append(asyncio.create_task(self._fetch_task(org, repo, doc, route)))
        if not tasks:
            return []
        results = await asyncio.gather(*tasks, return_exceptions=True)

        chunks: list[DocChunk] = []
        for result in results:
            if isinstance(result, BaseException):
                continue
            route, doc, text = result
            if not text:
                continue
            repo = org.repos.get(route.name)
            if repo is None:
                continue
            url = f"{repo.url}/blob/{repo.default_branch}/{doc}"
            for heading, body in chunk_markdown(text):
                score, cov = score_text(
                    question,
                    body,
                    title=heading,
                    description=repo.description,
                )
                if score <= 0:
                    continue
                chunks.append(
                    DocChunk(
                        repo_name=route.name,
                        doc=doc,
                        heading=heading,
                        text=excerpt(body, 1200),
                        url=url,
                        score=score,
                        coverage=cov,
                    )
                )
        chunks.sort(key=lambda item: (-item.score, -item.coverage, item.repo_name))
        selected: list[DocChunk] = []
        seen_text: set[str] = set()
        for chunk in chunks:
            fingerprint = chunk.text[:160].casefold()
            if fingerprint in seen_text:
                continue
            seen_text.add(fingerprint)
            selected.append(chunk)
            if len(selected) >= max_chunks:
                break
        return selected

    async def _fetch_task(
        self,
        org: OrgDefinition,
        repo: RepoDefinition,
        doc: str,
        route: RepoRoute,
    ) -> tuple[RepoRoute, str, str | None]:
        return route, doc, await self.fetch_doc(org, repo, doc)


def relevant_terms(question: str, text: str) -> set[str]:
    return token_set(question) & token_set(text)
