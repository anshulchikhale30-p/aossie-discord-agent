"""Answer composition from scoped knowledge and approved public docs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import httpx

from .config import OrgDefinition, Settings
from .db import Database
from .docs import DocChunk, DocsService
from .knowledge import KnowledgeHit, KnowledgeService
from .routing import RepoRoute, route_question
from .text import excerpt, score_text
from .timeutil import format_dt, now_iso

INSUFFICIENT = "INSUFFICIENT_CONTEXT"


@dataclass
class AnswerResult:
    text: str
    sources: list[str] = field(default_factory=list)
    should_escalate: bool = False
    confidence: str = "low"
    knowledge_hits: list[KnowledgeHit] = field(default_factory=list)
    doc_chunks: list[DocChunk] = field(default_factory=list)
    routes: list[RepoRoute] = field(default_factory=list)
    expired_hits: list[KnowledgeHit] = field(default_factory=list)
    reason: str = ""

    @property
    def route_names(self) -> list[str]:
        return [route.name for route in self.routes if not route.general]


class AnswerEngine:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        docs: DocsService,
        knowledge: KnowledgeService,
    ) -> None:
        self.settings = settings
        self.db = db
        self.docs = docs
        self.knowledge = knowledge

    async def answer(
        self,
        org: OrgDefinition,
        tenant: sqlite3.Row,
        customer: sqlite3.Row,
        conversation: sqlite3.Row,
        question: str,
        *,
        history: list[sqlite3.Row] | None = None,
    ) -> AnswerResult:
        routes = route_question(org, question)
        hits = self.knowledge.search(int(tenant["id"]), int(customer["id"]), question)
        expired = self.knowledge.expired_matches(int(tenant["id"]), int(customer["id"]), question)
        chunks = await self.docs.retrieve(org, routes, question)

        confidence, reason = self._confidence(hits, chunks)
        if confidence == "low":
            return self._escalation_result(
                org=org,
                tenant=tenant,
                question=question,
                hits=hits,
                chunks=chunks,
                routes=routes,
                expired=expired,
                reason=reason,
            )

        context = self._build_context(org, hits, chunks)
        if self.settings.use_ollama:
            generated = await self._ollama_answer(org, question, context, history or [])
            if generated:
                return AnswerResult(
                    text=generated,
                    sources=self._sources(hits, chunks),
                    should_escalate=False,
                    confidence=confidence,
                    knowledge_hits=hits,
                    doc_chunks=chunks,
                    routes=routes,
                    expired_hits=expired,
                    reason="ollama",
                )

        text = self._compose(org, hits, chunks)
        return AnswerResult(
            text=text,
            sources=self._sources(hits, chunks),
            should_escalate=False,
            confidence=confidence,
            knowledge_hits=hits,
            doc_chunks=chunks,
            routes=routes,
            expired_hits=expired,
            reason=reason,
        )

    def _confidence(self, hits: list[KnowledgeHit], chunks: list[DocChunk]) -> tuple[str, str]:
        if hits:
            best = hits[0]
            if best.score >= 5.0 and best.coverage >= 0.3:
                return "high", f"knowledge:{best.id}"
            if best.score >= 3.0:
                return "medium", f"knowledge:{best.id}"
        if chunks:
            best = chunks[0]
            if best.score >= 4.0 and best.coverage >= 0.25:
                return "medium", f"docs:{best.repo_name}/{best.doc}"
        return "low", "no reliable context"

    def _escalation_result(
        self,
        *,
        org: OrgDefinition,
        tenant: sqlite3.Row,
        question: str,
        hits: list[KnowledgeHit],
        chunks: list[DocChunk],
        routes: list[RepoRoute],
        expired: list[KnowledgeHit],
        reason: str,
    ) -> AnswerResult:
        if expired:
            expiry = expired[0].expires_at
            when = format_dt(expiry, tenant["timezone"]) if expiry else "previously"
            text = (
                f"The note I have on that expired on {when}, so I won’t treat it as current. "
                "I’ve asked a maintainer to confirm the latest details."
            )
        else:
            text = (
                "I don’t have verified information about that yet, so I’ve asked a maintainer to check. "
                "You can keep asking other questions in the meantime."
            )
        return AnswerResult(
            text=text,
            sources=self._sources(hits, chunks),
            should_escalate=True,
            confidence="low",
            knowledge_hits=hits,
            doc_chunks=chunks,
            routes=routes,
            expired_hits=expired,
            reason=reason,
        )

    def _compose(self, org: OrgDefinition, hits: list[KnowledgeHit], chunks: list[DocChunk]) -> str:
        parts: list[str] = []
        if hits:
            for hit in hits[:2]:
                parts.append(f"**{hit.title}**\n{excerpt(hit.content, 700)}")
        if chunks and (not hits or len(parts) < 2):
            for chunk in chunks[:2]:
                heading = f" — {chunk.heading}" if chunk.heading else ""
                parts.append(
                    f"From the **{chunk.repo_name}** documentation{heading}:\n"
                    f"{excerpt(chunk.text, 700)}"
                )
        if not parts:
            return (
                "I found the organization, but I couldn’t retrieve a matching document. "
                "I’ve flagged this for maintainer review."
            )
        text = "\n\n".join(parts)
        if len(text) > 1700:
            text = text[:1690].rsplit(" ", 1)[0] + "…"
        return text

    def _sources(self, hits: list[KnowledgeHit], chunks: list[DocChunk]) -> list[str]:
        sources: list[str] = []
        for hit in hits[:2]:
            if hit.source:
                sources.append(hit.source)
            else:
                sources.append(f"Maintainer knowledge #{hit.id}")
        for chunk in chunks[:3]:
            label = f"[{chunk.repo_name}/{chunk.doc}]({chunk.url})"
            if chunk.heading:
                label += f" § {chunk.heading}"
            sources.append(label)
        return list(dict.fromkeys(sources))[:5]

    def _build_context(
        self,
        org: OrgDefinition,
        hits: list[KnowledgeHit],
        chunks: list[DocChunk],
    ) -> str:
        blocks: list[str] = []
        for hit in hits[:4]:
            blocks.append(f"[Knowledge #{hit.id}: {hit.title}]\n{hit.content}")
        for chunk in chunks[:4]:
            blocks.append(f"[Docs {chunk.repo_name}/{chunk.doc} § {chunk.heading}]\n{chunk.text}")
        context = "\n\n".join(blocks)
        return context[: self.settings.max_context_chars]

    async def _ollama_answer(
        self,
        org: OrgDefinition,
        question: str,
        context: str,
        history: list[sqlite3.Row],
    ) -> str | None:
        history_text = "\n".join(
            f"{row['role']}: {row['content']}" for row in history[-6:]
        )
        prompt = (
            f"You are the AI front desk for {org.display_name}, an open-source organization. "
            "Answer the contributor or member question using only the supplied context. "
            "Be concise, friendly, and concrete. Do not invent steps, policies, links, or dates. "
            f"If the context does not answer the question, reply with exactly {INSUFFICIENT}.\n\n"
            f"Context:\n{context}\n\n"
            f"Recent conversation:\n{history_text or '(none)'}\n\n"
            f"Question: {question}"
        )
        try:
            async with httpx.AsyncClient(timeout=45.0) as client:
                response = await client.post(
                    f"{self.settings.ollama_base_url}/api/generate",
                    json={"model": self.settings.ollama_model, "prompt": prompt, "stream": False},
                )
                response.raise_for_status()
                answer = str(response.json().get("response", "")).strip()
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None
        if not answer or INSUFFICIENT in answer:
            return None
        return answer[:1800]

    def summarize(self, history: list[sqlite3.Row], question: str) -> str:
        lines: list[str] = []
        for row in history[-8:]:
            role = "Member" if row["role"] == "user" else "Front desk"
            content = " ".join(str(row["content"]).split())[:220]
            lines.append(f"{role}: {content}")
        lines.append(f"Current question: {' '.join(question.split())[:300]}")
        return "\n".join(lines)[:1800]

    def context_score(self, question: str, text: str) -> tuple[float, float]:
        return score_text(question, text)
