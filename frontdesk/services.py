"""Shared application services."""

from __future__ import annotations

from dataclasses import dataclass

from .agent import AnswerEngine
from .config import OrgCatalog, Settings
from .db import Database
from .docs import DocsService
from .knowledge import KnowledgeService
from .notifications import NotificationService
from .scheduling import SchedulingService


@dataclass
class Services:
    settings: Settings
    catalog: OrgCatalog
    db: Database
    docs: DocsService
    knowledge: KnowledgeService
    scheduling: SchedulingService
    notifications: NotificationService
    agent: AnswerEngine

    @classmethod
    def build(cls, settings: Settings) -> "Services":
        catalog = OrgCatalog.load(settings.catalog_path)
        db = Database(settings.database_path)
        docs = DocsService(settings)
        knowledge = KnowledgeService(db)
        scheduling = SchedulingService(settings, db)
        notifications = NotificationService(db)
        agent = AnswerEngine(settings, db, docs, knowledge)
        return cls(settings, catalog, db, docs, knowledge, scheduling, notifications, agent)

    async def close(self) -> None:
        await self.docs.close()
        self.db.close()
