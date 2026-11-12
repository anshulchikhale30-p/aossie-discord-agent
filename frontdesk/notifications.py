"""Durable outbound notification queue."""

from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from .db import Database
from .timeutil import iso, now_iso, utc_now


class NotificationService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def enqueue(
        self,
        tenant_id: int,
        recipient_kind: str,
        recipient_id: int | str,
        kind: str,
        *,
        channel_id: int | str | None = None,
        booking_id: int | None = None,
        payload: dict[str, Any] | None = None,
        due_at: str | None = None,
    ) -> sqlite3.Row:
        return self.db.create_notification(
            tenant_id,
            recipient_kind,
            recipient_id,
            kind,
            channel_id=channel_id,
            booking_id=booking_id,
            payload=payload,
            due_at=due_at or now_iso(),
        )

    def due(self, limit: int = 50) -> list[sqlite3.Row]:
        return self.db.due_notifications(limit)

    def mark_sent(self, notification_id: int) -> None:
        self.db.mark_notification_sent(notification_id)

    def mark_failed(self, notification_id: int, error: str) -> None:
        # Retry after five minutes, up to three attempts.
        retry_at = iso(utc_now() + timedelta(minutes=5))
        self.db.mark_notification_failed(notification_id, error, retry_at=retry_at)

    def cancel_for_booking(self, booking_id: int) -> int:
        return self.db.cancel_notifications_for_booking(booking_id)
