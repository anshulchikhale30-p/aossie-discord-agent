"""Provider-entered operational knowledge and scoped retrieval."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .db import Database
from .text import score_text


@dataclass(frozen=True)
class KnowledgeHit:
    row: sqlite3.Row
    score: float
    coverage: float
    expired: bool = False

    @property
    def id(self) -> int:
        return int(self.row["id"])

    @property
    def title(self) -> str:
        return str(self.row["title"])

    @property
    def content(self) -> str:
        return str(self.row["content"])

    @property
    def scope(self) -> str:
        return str(self.row["scope"])

    @property
    def source(self) -> str:
        return str(self.row["source"] or "")

    @property
    def expires_at(self) -> str | None:
        return self.row["expires_at"]


class KnowledgeService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def search(
        self,
        tenant_id: int,
        customer_id: int | None,
        question: str,
        *,
        limit: int = 4,
    ) -> list[KnowledgeHit]:
        hits: list[KnowledgeHit] = []
        for row in self.db.current_knowledge(tenant_id, customer_id):
            score, coverage = score_text(
                question,
                row["content"],
                title=row["title"],
                tags=row["tags"],
            )
            if score <= 0:
                continue
            if row["scope"] == "customer":
                score += 0.75
            if score < 2.0 or coverage < 0.2:
                continue
            hits.append(KnowledgeHit(row=row, score=score, coverage=coverage))
        hits.sort(key=lambda item: (-item.score, -item.coverage, -item.id))
        return hits[:limit]

    def expired_matches(
        self,
        tenant_id: int,
        customer_id: int | None,
        question: str,
        *,
        limit: int = 2,
    ) -> list[KnowledgeHit]:
        hits: list[KnowledgeHit] = []
        for row in self.db.expired_knowledge(tenant_id, customer_id):
            score, coverage = score_text(
                question,
                row["content"],
                title=row["title"],
                tags=row["tags"],
            )
            if score >= 2.0 and coverage >= 0.2:
                hits.append(KnowledgeHit(row=row, score=score, coverage=coverage, expired=True))
        hits.sort(key=lambda item: (-item.score, -item.id))
        return hits[:limit]

    def add(
        self,
        tenant_id: int,
        *,
        scope: str,
        title: str,
        content: str,
        actor: str,
        customer_id: int | None = None,
        tags: str = "",
        source: str = "",
        effective_at: str | None = None,
        expires_at: str | None = None,
        supersedes_id: int | None = None,
    ) -> sqlite3.Row:
        row = self.db.add_knowledge(
            tenant_id,
            scope,
            title,
            content,
            customer_id=customer_id,
            tags=tags,
            source=source,
            effective_at=effective_at,
            expires_at=expires_at,
            created_by=actor,
            supersedes_id=supersedes_id,
        )
        self.db.audit(
            tenant_id,
            actor,
            "knowledge_added",
            {
                "knowledge_id": int(row["id"]),
                "scope": scope,
                "customer_id": customer_id,
                "title": title,
                "expires_at": expires_at,
            },
        )
        return row

    def cancel(self, tenant_id: int, knowledge_id: int, actor: str) -> bool:
        cancelled = self.db.cancel_knowledge(knowledge_id, tenant_id)
        if cancelled:
            self.db.audit(tenant_id, actor, "knowledge_cancelled", {"knowledge_id": knowledge_id})
        return cancelled

    def list(
        self,
        tenant_id: int,
        *,
        scope: str | None = None,
        customer_id: int | None = None,
        status: str | None = "active",
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        return self.db.list_knowledge(
            tenant_id,
            scope=scope,
            customer_id=customer_id,
            status=status,
            limit=limit,
        )
