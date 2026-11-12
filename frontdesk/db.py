"""SQLite persistence for the front desk.

SQLite keeps the MVP self-contained while preserving the business-state
boundaries the product specification requires. Every read and mutation is
scoped by tenant (one Discord server = one provider account) in the service
layer; the database enforces uniqueness and booking conflicts.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from .timeutil import now_iso, parse_iso

SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    guild_id TEXT NOT NULL UNIQUE,
    org_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    timezone TEXT NOT NULL,
    staff_role_ids TEXT NOT NULL DEFAULT '[]',
    support_channel_ids TEXT NOT NULL DEFAULT '[]',
    staff_channel_id TEXT,
    reminder_offsets TEXT NOT NULL DEFAULT '[1440,60,10]',
    settings TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS customers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform_user_id TEXT NOT NULL,
    username TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    verified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL,
    UNIQUE (tenant_id, platform_user_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    channel_id TEXT NOT NULL,
    thread_id TEXT,
    parent_channel_id TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conversations_thread ON conversations(thread_id);
CREATE INDEX IF NOT EXISTS idx_conversations_customer ON conversations(tenant_id, customer_id, status);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
    author_id TEXT,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_conversation ON messages(conversation_id, id);

CREATE TABLE IF NOT EXISTS knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    scope TEXT NOT NULL CHECK (scope IN ('org', 'customer')),
    customer_id INTEGER REFERENCES customers(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    tags TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    effective_at TEXT,
    expires_at TEXT,
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'cancelled', 'superseded')),
    supersedes_id INTEGER,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_knowledge_tenant ON knowledge(tenant_id, status, scope);
CREATE INDEX IF NOT EXISTS idx_knowledge_customer ON knowledge(tenant_id, customer_id, status);

CREATE TABLE IF NOT EXISTS pending_questions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER REFERENCES customers(id) ON DELETE SET NULL,
    conversation_id INTEGER REFERENCES conversations(id) ON DELETE SET NULL,
    question TEXT NOT NULL,
    answer_given TEXT NOT NULL DEFAULT '',
    clarification TEXT NOT NULL DEFAULT '',
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('normal', 'high', 'urgent')),
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'resolved', 'dismissed')),
    summary TEXT NOT NULL DEFAULT '',
    staff_message_id TEXT,
    staff_channel_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    resolved_at TEXT,
    resolved_by TEXT,
    resolution TEXT
);
CREATE INDEX IF NOT EXISTS idx_pending_tenant ON pending_questions(tenant_id, status, created_at);

CREATE TABLE IF NOT EXISTS availability (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    weekday INTEGER NOT NULL CHECK (weekday BETWEEN 0 AND 6),
    start_time TEXT NOT NULL,
    end_time TEXT NOT NULL,
    slot_minutes INTEGER NOT NULL DEFAULT 30,
    timezone TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_availability_tenant ON availability(tenant_id, staff_id, active);

CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    customer_id INTEGER NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
    staff_id TEXT NOT NULL,
    service TEXT NOT NULL,
    start_ts TEXT NOT NULL,
    end_ts TEXT NOT NULL,
    timezone TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'confirmed' CHECK (status IN ('confirmed', 'cancelled', 'completed')),
    attendance TEXT NOT NULL DEFAULT 'unknown' CHECK (attendance IN ('unknown', 'attending', 'declined')),
    source_channel_id TEXT,
    source_thread_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_bookings_tenant_time ON bookings(tenant_id, start_ts, status);
CREATE INDEX IF NOT EXISTS idx_bookings_customer ON bookings(tenant_id, customer_id, status);
CREATE INDEX IF NOT EXISTS idx_bookings_staff ON bookings(tenant_id, staff_id, start_ts, status);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    recipient_kind TEXT NOT NULL CHECK (recipient_kind IN ('user', 'channel')),
    recipient_id TEXT NOT NULL,
    channel_id TEXT,
    kind TEXT NOT NULL,
    booking_id INTEGER REFERENCES bookings(id) ON DELETE CASCADE,
    payload TEXT NOT NULL DEFAULT '{}',
    due_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed', 'cancelled')),
    attempts INTEGER NOT NULL DEFAULT 0,
    last_error TEXT,
    created_at TEXT NOT NULL,
    sent_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_notifications_due ON notifications(status, due_at);
CREATE INDEX IF NOT EXISTS idx_notifications_booking ON notifications(booking_id, status);

CREATE TABLE IF NOT EXISTS spam (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    platform_user_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (tenant_id, platform_user_id)
);

CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id INTEGER,
    actor TEXT NOT NULL DEFAULT '',
    event TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_tenant ON audit(tenant_id, created_at);
"""


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


class Database:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute("PRAGMA busy_timeout=5000")
        self.conn.executescript(SCHEMA)

    def close(self) -> None:
        self.conn.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        self.conn.execute("BEGIN IMMEDIATE")
        try:
            yield self.conn
        except Exception:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        return self.conn.execute(sql, params).fetchone()

    def _all(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        return list(self.conn.execute(sql, params).fetchall())

    # Tenants -----------------------------------------------------------------
    def get_tenant(self, tenant_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM tenants WHERE id = ?", (tenant_id,))

    def get_tenant_by_guild(self, guild_id: int | str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM tenants WHERE guild_id = ?", (str(guild_id),))

    def list_tenants(self) -> list[sqlite3.Row]:
        return self._all("SELECT * FROM tenants ORDER BY id")

    def create_tenant(
        self,
        guild_id: int | str,
        org_key: str,
        display_name: str,
        timezone: str,
        staff_role_ids: list[int] | None = None,
        support_channel_ids: list[int] | None = None,
        staff_channel_id: int | str | None = None,
        reminder_offsets: list[int] | None = None,
    ) -> sqlite3.Row:
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO tenants
                (guild_id, org_key, display_name, timezone, staff_role_ids,
                 support_channel_ids, staff_channel_id, reminder_offsets, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(guild_id) DO NOTHING
            """,
            (
                str(guild_id),
                org_key,
                display_name,
                timezone,
                _json([str(value) for value in (staff_role_ids or [])]),
                _json([str(value) for value in (support_channel_ids or [])]),
                str(staff_channel_id) if staff_channel_id else None,
                _json(reminder_offsets or [1440, 60, 10]),
                timestamp,
                timestamp,
            ),
        )
        row = self.get_tenant_by_guild(guild_id)
        if row is None:
            raise RuntimeError("Could not create the tenant.")
        return row

    def update_tenant(self, tenant_id: int, **fields: Any) -> sqlite3.Row:
        allowed = {
            "org_key", "display_name", "timezone", "staff_role_ids",
            "support_channel_ids", "staff_channel_id", "reminder_offsets", "settings",
        }
        values: list[Any] = []
        assignments: list[str] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            if key in {"staff_role_ids", "support_channel_ids", "reminder_offsets", "settings"}:
                value = _json(value) if not isinstance(value, str) else value
            if key == "staff_channel_id" and value is not None:
                value = str(value)
            assignments.append(f"{key} = ?")
            values.append(value)
        if assignments:
            assignments.append("updated_at = ?")
            values.append(now_iso())
            values.append(tenant_id)
            self.conn.execute(f"UPDATE tenants SET {', '.join(assignments)} WHERE id = ?", tuple(values))
        row = self.get_tenant(tenant_id)
        if row is None:
            raise RuntimeError("Tenant not found.")
        return row

    # Customers ---------------------------------------------------------------
    def upsert_customer(
        self,
        tenant_id: int,
        platform_user_id: int | str,
        username: str = "",
        display_name: str = "",
    ) -> sqlite3.Row:
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO customers
                (tenant_id, platform_user_id, username, display_name, created_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, platform_user_id) DO UPDATE SET
                username = excluded.username,
                display_name = excluded.display_name,
                last_seen_at = excluded.last_seen_at
            """,
            (tenant_id, str(platform_user_id), username, display_name, timestamp, timestamp),
        )
        row = self.get_customer_by_platform_id(tenant_id, platform_user_id)
        if row is None:
            raise RuntimeError("Could not store the customer.")
        return row

    def get_customer(self, customer_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM customers WHERE id = ?", (customer_id,))

    def get_customer_by_platform_id(self, tenant_id: int, platform_user_id: int | str) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM customers WHERE tenant_id = ? AND platform_user_id = ?",
            (tenant_id, str(platform_user_id)),
        )

    def list_customers(self, tenant_id: int, limit: int = 500) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM customers WHERE tenant_id = ? ORDER BY last_seen_at DESC LIMIT ?",
            (tenant_id, limit),
        )

    def customer_tenants(self, platform_user_id: int | str) -> list[sqlite3.Row]:
        return self._all(
            """
            SELECT c.*, t.guild_id, t.org_key, t.display_name AS tenant_name, t.timezone
            FROM customers c JOIN tenants t ON t.id = c.tenant_id
            WHERE c.platform_user_id = ?
            ORDER BY c.last_seen_at DESC
            """,
            (str(platform_user_id),),
        )

    # Conversations and messages ---------------------------------------------
    def create_conversation(
        self,
        tenant_id: int,
        customer_id: int,
        channel_id: int | str,
        thread_id: int | str | None = None,
        parent_channel_id: int | str | None = None,
    ) -> sqlite3.Row:
        if thread_id:
            existing = self.get_conversation_by_thread(thread_id)
            if existing:
                return existing
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO conversations
                (tenant_id, customer_id, channel_id, thread_id, parent_channel_id, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                customer_id,
                str(channel_id),
                str(thread_id) if thread_id else None,
                str(parent_channel_id) if parent_channel_id else None,
                timestamp,
                timestamp,
            ),
        )
        row = self._one("SELECT * FROM conversations WHERE id = last_insert_rowid()")
        if row is None:
            raise RuntimeError("Could not create the conversation.")
        return row

    def get_conversation(self, conversation_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM conversations WHERE id = ?", (conversation_id,))

    def get_conversation_by_thread(self, thread_id: int | str) -> sqlite3.Row | None:
        return self._one("SELECT * FROM conversations WHERE thread_id = ?", (str(thread_id),))

    def get_dm_conversation(self, tenant_id: int, customer_id: int, channel_id: int | str) -> sqlite3.Row | None:
        return self._one(
            """
            SELECT * FROM conversations
            WHERE tenant_id = ? AND customer_id = ? AND channel_id = ? AND thread_id IS NULL
            ORDER BY id DESC LIMIT 1
            """,
            (tenant_id, customer_id, str(channel_id)),
        )

    def touch_conversation(self, conversation_id: int) -> None:
        self.conn.execute(
            "UPDATE conversations SET updated_at = ? WHERE id = ?",
            (now_iso(), conversation_id),
        )

    def close_conversation(self, conversation_id: int) -> None:
        self.conn.execute(
            "UPDATE conversations SET status = 'closed', updated_at = ? WHERE id = ?",
            (now_iso(), conversation_id),
        )

    def add_message(self, conversation_id: int, author_id: int | str | None, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages (conversation_id, author_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
            (conversation_id, str(author_id) if author_id else None, role, content, now_iso()),
        )

    def recent_messages(self, conversation_id: int, limit: int = 8) -> list[sqlite3.Row]:
        rows = self._all(
            "SELECT * FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        )
        return list(reversed(rows))

    # Knowledge ---------------------------------------------------------------
    def add_knowledge(
        self,
        tenant_id: int,
        scope: str,
        title: str,
        content: str,
        *,
        customer_id: int | None = None,
        tags: str = "",
        source: str = "",
        effective_at: str | None = None,
        expires_at: str | None = None,
        created_by: str = "",
        supersedes_id: int | None = None,
    ) -> sqlite3.Row:
        if scope not in {"org", "customer"}:
            raise ValueError("Knowledge scope must be 'org' or 'customer'.")
        if scope == "customer" and not customer_id:
            raise ValueError("Customer-specific knowledge requires a customer.")
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO knowledge
                (tenant_id, scope, customer_id, title, content, tags, source,
                 effective_at, expires_at, supersedes_id, created_by, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                scope,
                customer_id if scope == "customer" else None,
                title.strip() or "Maintainer note",
                content.strip(),
                tags.strip(),
                source.strip(),
                effective_at,
                expires_at,
                supersedes_id,
                created_by,
                timestamp,
                timestamp,
            ),
        )
        row = self._one("SELECT * FROM knowledge WHERE id = last_insert_rowid()")
        if row is None:
            raise RuntimeError("Could not store the knowledge entry.")
        return row

    def get_knowledge(self, knowledge_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM knowledge WHERE id = ?", (knowledge_id,))

    def list_knowledge(
        self,
        tenant_id: int,
        *,
        scope: str | None = None,
        customer_id: int | None = None,
        status: str | None = "active",
        limit: int = 100,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if scope:
            clauses.append("scope = ?")
            params.append(scope)
        if customer_id is not None:
            clauses.append("customer_id = ?")
            params.append(customer_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        params.append(limit)
        return self._all(
            f"SELECT * FROM knowledge WHERE {' AND '.join(clauses)} ORDER BY id DESC LIMIT ?",
            tuple(params),
        )

    def current_knowledge(self, tenant_id: int, customer_id: int | None) -> list[sqlite3.Row]:
        timestamp = now_iso()
        return self._all(
            """
            SELECT * FROM knowledge
            WHERE tenant_id = ?
              AND status = 'active'
              AND (scope = 'org' OR (scope = 'customer' AND customer_id = ?))
              AND (effective_at IS NULL OR effective_at <= ?)
              AND (expires_at IS NULL OR expires_at > ?)
            ORDER BY id DESC
            """,
            (tenant_id, customer_id, timestamp, timestamp),
        )

    def expired_knowledge(self, tenant_id: int, customer_id: int | None) -> list[sqlite3.Row]:
        timestamp = now_iso()
        return self._all(
            """
            SELECT * FROM knowledge
            WHERE tenant_id = ?
              AND status = 'active'
              AND (scope = 'org' OR (scope = 'customer' AND customer_id = ?))
              AND expires_at IS NOT NULL AND expires_at <= ?
            ORDER BY id DESC
            """,
            (tenant_id, customer_id, timestamp),
        )

    def cancel_knowledge(self, knowledge_id: int, tenant_id: int) -> bool:
        cursor = self.conn.execute(
            "UPDATE knowledge SET status = 'cancelled', updated_at = ? WHERE id = ? AND tenant_id = ?",
            (now_iso(), knowledge_id, tenant_id),
        )
        return cursor.rowcount > 0

    def update_knowledge(
        self,
        knowledge_id: int,
        tenant_id: int,
        *,
        title: str | None = None,
        content: str | None = None,
        tags: str | None = None,
        source: str | None = None,
        effective_at: str | None = None,
        expires_at: str | None = None,
    ) -> sqlite3.Row | None:
        fields: list[str] = []
        values: list[Any] = []
        for key, value in (
            ("title", title),
            ("content", content),
            ("tags", tags),
            ("source", source),
            ("effective_at", effective_at),
            ("expires_at", expires_at),
        ):
            if value is not None:
                fields.append(f"{key} = ?")
                values.append(value)
        if not fields:
            return self.get_knowledge(knowledge_id)
        fields.append("updated_at = ?")
        values.extend([now_iso(), knowledge_id, tenant_id])
        self.conn.execute(
            f"UPDATE knowledge SET {', '.join(fields)} WHERE id = ? AND tenant_id = ?",
            tuple(values),
        )
        return self.get_knowledge(knowledge_id)

    # Pending questions -------------------------------------------------------
    def create_pending(
        self,
        tenant_id: int,
        question: str,
        *,
        customer_id: int | None = None,
        conversation_id: int | None = None,
        answer_given: str = "",
        clarification: str = "",
        priority: str = "normal",
        summary: str = "",
    ) -> sqlite3.Row:
        if priority not in {"normal", "high", "urgent"}:
            priority = "normal"
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO pending_questions
                (tenant_id, customer_id, conversation_id, question, answer_given,
                 clarification, priority, summary, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                customer_id,
                conversation_id,
                question.strip(),
                answer_given.strip(),
                clarification.strip(),
                priority,
                summary.strip(),
                timestamp,
                timestamp,
            ),
        )
        row = self._one("SELECT * FROM pending_questions WHERE id = last_insert_rowid()")
        if row is None:
            raise RuntimeError("Could not create the pending question.")
        return row

    def get_pending(self, pending_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM pending_questions WHERE id = ?", (pending_id,))

    def list_pending(
        self,
        tenant_id: int,
        *,
        status: str | None = "open",
        priority: str | None = None,
        limit: int = 25,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if status:
            clauses.append("status = ?")
            params.append(status)
        if priority:
            clauses.append("priority = ?")
            params.append(priority)
        params.append(limit)
        return self._all(
            f"""
            SELECT * FROM pending_questions
            WHERE {' AND '.join(clauses)}
            ORDER BY CASE priority WHEN 'urgent' THEN 0 WHEN 'high' THEN 1 ELSE 2 END, created_at
            LIMIT ?
            """,
            tuple(params),
        )

    def open_pending_for_tenant(self, tenant_id: int) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM pending_questions WHERE tenant_id = ? AND status = 'open' ORDER BY created_at",
            (tenant_id,),
        )

    def set_pending_staff_message(self, pending_id: int, message_id: int | str, channel_id: int | str) -> None:
        self.conn.execute(
            "UPDATE pending_questions SET staff_message_id = ?, staff_channel_id = ?, updated_at = ? WHERE id = ?",
            (str(message_id), str(channel_id), now_iso(), pending_id),
        )

    def get_pending_by_staff_message(self, tenant_id: int, message_id: int | str) -> sqlite3.Row | None:
        return self._one(
            "SELECT * FROM pending_questions WHERE tenant_id = ? AND staff_message_id = ? AND status = 'open'",
            (tenant_id, str(message_id)),
        )

    def resolve_pending(self, pending_id: int, resolution: str, resolved_by: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE pending_questions
            SET status = 'resolved', resolution = ?, resolved_by = ?, resolved_at = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (resolution.strip(), resolved_by, now_iso(), now_iso(), pending_id),
        )
        return cursor.rowcount > 0

    def dismiss_pending(self, pending_id: int, reason: str, resolved_by: str) -> bool:
        cursor = self.conn.execute(
            """
            UPDATE pending_questions
            SET status = 'dismissed', resolution = ?, resolved_by = ?, resolved_at = ?, updated_at = ?
            WHERE id = ? AND status = 'open'
            """,
            (reason.strip(), resolved_by, now_iso(), now_iso(), pending_id),
        )
        return cursor.rowcount > 0

    # Availability ------------------------------------------------------------
    def add_availability(
        self,
        tenant_id: int,
        staff_id: int | str,
        weekday: int,
        start_time: str,
        end_time: str,
        slot_minutes: int,
        timezone_name: str,
    ) -> sqlite3.Row:
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO availability
                (tenant_id, staff_id, weekday, start_time, end_time, slot_minutes, timezone, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (tenant_id, str(staff_id), weekday, start_time, end_time, slot_minutes, timezone_name, timestamp, timestamp),
        )
        row = self._one("SELECT * FROM availability WHERE id = last_insert_rowid()")
        if row is None:
            raise RuntimeError("Could not store availability.")
        return row

    def get_availability(self, availability_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM availability WHERE id = ?", (availability_id,))

    def list_availability(
        self,
        tenant_id: int,
        *,
        staff_id: int | str | None = None,
        active_only: bool = True,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?"]
        params: list[Any] = [tenant_id]
        if staff_id is not None:
            clauses.append("staff_id = ?")
            params.append(str(staff_id))
        if active_only:
            clauses.append("active = 1")
        return self._all(
            f"SELECT * FROM availability WHERE {' AND '.join(clauses)} ORDER BY weekday, start_time",
            tuple(params),
        )

    def deactivate_availability(self, availability_id: int, tenant_id: int) -> bool:
        cursor = self.conn.execute(
            "UPDATE availability SET active = 0, updated_at = ? WHERE id = ? AND tenant_id = ?",
            (now_iso(), availability_id, tenant_id),
        )
        return cursor.rowcount > 0

    # Bookings ----------------------------------------------------------------
    def bookings_overlapping(
        self,
        tenant_id: int,
        staff_id: int | str,
        start_ts: str,
        end_ts: str,
        *,
        exclude_booking_id: int | None = None,
    ) -> list[sqlite3.Row]:
        clauses = [
            "tenant_id = ?",
            "staff_id = ?",
            "status = 'confirmed'",
            "start_ts < ?",
            "end_ts > ?",
        ]
        params: list[Any] = [tenant_id, str(staff_id), end_ts, start_ts]
        if exclude_booking_id:
            clauses.append("id != ?")
            params.append(exclude_booking_id)
        return self._all(
            f"SELECT * FROM bookings WHERE {' AND '.join(clauses)} ORDER BY start_ts",
            tuple(params),
        )

    def create_booking(
        self,
        tenant_id: int,
        customer_id: int,
        staff_id: int | str,
        service: str,
        start_ts: str,
        end_ts: str,
        timezone_name: str,
        *,
        location: str = "",
        notes: str = "",
        source_channel_id: int | str | None = None,
        source_thread_id: int | str | None = None,
    ) -> sqlite3.Row | None:
        """Create a booking atomically. Returns None if the slot was taken."""
        timestamp = now_iso()
        try:
            with self.transaction() as conn:
                conflict = conn.execute(
                    """
                    SELECT id FROM bookings
                    WHERE tenant_id = ? AND staff_id = ? AND status = 'confirmed'
                      AND start_ts < ? AND end_ts > ?
                    LIMIT 1
                    """,
                    (tenant_id, str(staff_id), end_ts, start_ts),
                ).fetchone()
                if conflict:
                    return None
                cursor = conn.execute(
                    """
                    INSERT INTO bookings
                        (tenant_id, customer_id, staff_id, service, start_ts, end_ts, timezone,
                         location, notes, source_channel_id, source_thread_id, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        tenant_id,
                        customer_id,
                        str(staff_id),
                        service.strip() or "Meeting",
                        start_ts,
                        end_ts,
                        timezone_name,
                        location.strip(),
                        notes.strip(),
                        str(source_channel_id) if source_channel_id else None,
                        str(source_thread_id) if source_thread_id else None,
                        timestamp,
                        timestamp,
                    ),
                )
                booking_id = cursor.lastrowid
        except sqlite3.IntegrityError:
            return None
        if booking_id is None:
            return None
        return self.get_booking(int(booking_id))

    def get_booking(self, booking_id: int) -> sqlite3.Row | None:
        return self._one("SELECT * FROM bookings WHERE id = ?", (booking_id,))

    def list_customer_bookings(
        self,
        tenant_id: int,
        customer_id: int,
        *,
        include_cancelled: bool = False,
        limit: int = 20,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?", "customer_id = ?"]
        params: list[Any] = [tenant_id, customer_id]
        if not include_cancelled:
            clauses.append("status = 'confirmed'")
        clauses.append("start_ts >= ?")
        params.append(now_iso())
        params.append(limit)
        return self._all(
            f"SELECT * FROM bookings WHERE {' AND '.join(clauses)} ORDER BY start_ts LIMIT ?",
            tuple(params),
        )

    def list_staff_bookings(
        self,
        tenant_id: int,
        *,
        staff_id: int | str | None = None,
        from_ts: str | None = None,
        limit: int = 50,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?", "status = 'confirmed'"]
        params: list[Any] = [tenant_id]
        if staff_id is not None:
            clauses.append("staff_id = ?")
            params.append(str(staff_id))
        if from_ts:
            clauses.append("start_ts >= ?")
            params.append(from_ts)
        params.append(limit)
        return self._all(
            f"SELECT * FROM bookings WHERE {' AND '.join(clauses)} ORDER BY start_ts LIMIT ?",
            tuple(params),
        )

    def bookings_in_range(
        self,
        tenant_id: int,
        start_ts: str,
        end_ts: str,
        *,
        staff_id: int | str | None = None,
    ) -> list[sqlite3.Row]:
        clauses = ["tenant_id = ?", "status = 'confirmed'", "start_ts >= ?", "start_ts < ?"]
        params: list[Any] = [tenant_id, start_ts, end_ts]
        if staff_id is not None:
            clauses.append("staff_id = ?")
            params.append(str(staff_id))
        return self._all(
            f"SELECT * FROM bookings WHERE {' AND '.join(clauses)} ORDER BY start_ts",
            tuple(params),
        )

    def update_booking_time(
        self,
        booking_id: int,
        tenant_id: int,
        start_ts: str,
        end_ts: str,
    ) -> bool:
        """Move a booking atomically. Returns False if the new slot is taken."""
        try:
            with self.transaction() as conn:
                booking = conn.execute(
                    "SELECT * FROM bookings WHERE id = ? AND tenant_id = ? AND status = 'confirmed'",
                    (booking_id, tenant_id),
                ).fetchone()
                if booking is None:
                    return False
                conflict = conn.execute(
                    """
                    SELECT id FROM bookings
                    WHERE tenant_id = ? AND staff_id = ? AND status = 'confirmed'
                      AND id != ? AND start_ts < ? AND end_ts > ?
                    LIMIT 1
                    """,
                    (tenant_id, booking["staff_id"], booking_id, end_ts, start_ts),
                ).fetchone()
                if conflict:
                    return False
                conn.execute(
                    "UPDATE bookings SET start_ts = ?, end_ts = ?, updated_at = ? WHERE id = ?",
                    (start_ts, end_ts, now_iso(), booking_id),
                )
        except sqlite3.IntegrityError:
            return False
        return True

    def cancel_booking(self, booking_id: int, tenant_id: int) -> bool:
        cursor = self.conn.execute(
            "UPDATE bookings SET status = 'cancelled', updated_at = ? WHERE id = ? AND tenant_id = ? AND status = 'confirmed'",
            (now_iso(), booking_id, tenant_id),
        )
        return cursor.rowcount > 0

    def set_attendance(self, booking_id: int, tenant_id: int, attendance: str) -> bool:
        if attendance not in {"attending", "declined"}:
            return False
        cursor = self.conn.execute(
            "UPDATE bookings SET attendance = ?, updated_at = ? WHERE id = ? AND tenant_id = ? AND status = 'confirmed'",
            (attendance, now_iso(), booking_id, tenant_id),
        )
        return cursor.rowcount > 0

    # Notifications -----------------------------------------------------------
    def create_notification(
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
        if recipient_kind not in {"user", "channel"}:
            raise ValueError("recipient_kind must be 'user' or 'channel'.")
        timestamp = now_iso()
        self.conn.execute(
            """
            INSERT INTO notifications
                (tenant_id, recipient_kind, recipient_id, channel_id, kind, booking_id, payload,
                 due_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                recipient_kind,
                str(recipient_id),
                str(channel_id) if channel_id else None,
                kind,
                booking_id,
                _json(payload or {}),
                due_at or timestamp,
                timestamp,
            ),
        )
        row = self._one("SELECT * FROM notifications WHERE id = last_insert_rowid()")
        if row is None:
            raise RuntimeError("Could not create the notification.")
        return row

    def due_notifications(self, limit: int = 50) -> list[sqlite3.Row]:
        return self._all(
            """
            SELECT * FROM notifications
            WHERE status = 'pending' AND due_at <= ?
            ORDER BY due_at LIMIT ?
            """,
            (now_iso(), limit),
        )

    def mark_notification_sent(self, notification_id: int) -> None:
        self.conn.execute(
            "UPDATE notifications SET status = 'sent', sent_at = ?, attempts = attempts + 1 WHERE id = ?",
            (now_iso(), notification_id),
        )

    def mark_notification_failed(
        self,
        notification_id: int,
        error: str,
        *,
        retry_at: str | None = None,
    ) -> None:
        row = self._one("SELECT attempts FROM notifications WHERE id = ?", (notification_id,))
        attempts = (row["attempts"] if row else 0) + 1
        if retry_at and attempts < 3:
            self.conn.execute(
                """
                UPDATE notifications
                SET attempts = ?, last_error = ?, due_at = ?
                WHERE id = ?
                """,
                (attempts, error[:500], retry_at, notification_id),
            )
        else:
            self.conn.execute(
                "UPDATE notifications SET status = 'failed', attempts = ?, last_error = ? WHERE id = ?",
                (attempts, error[:500], notification_id),
            )

    def cancel_notifications_for_booking(self, booking_id: int, *, kinds: list[str] | None = None) -> int:
        clauses = ["booking_id = ?", "status = 'pending'"]
        params: list[Any] = [booking_id]
        if kinds:
            clauses.append(f"kind IN ({', '.join('?' for _ in kinds)})")
            params.extend(kinds)
        cursor = self.conn.execute(
            f"UPDATE notifications SET status = 'cancelled' WHERE {' AND '.join(clauses)}",
            tuple(params),
        )
        return cursor.rowcount

    def pending_notification_count(self, tenant_id: int) -> int:
        row = self._one(
            "SELECT COUNT(*) AS count FROM notifications WHERE tenant_id = ? AND status = 'pending'",
            (tenant_id,),
        )
        return int(row["count"]) if row else 0

    # Spam --------------------------------------------------------------------
    def add_spam(self, tenant_id: int, platform_user_id: int | str, reason: str, created_by: str) -> None:
        self.conn.execute(
            """
            INSERT INTO spam (tenant_id, platform_user_id, reason, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(tenant_id, platform_user_id) DO UPDATE SET
                reason = excluded.reason,
                created_by = excluded.created_by,
                created_at = excluded.created_at
            """,
            (tenant_id, str(platform_user_id), reason.strip(), created_by, now_iso()),
        )

    def remove_spam(self, tenant_id: int, platform_user_id: int | str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM spam WHERE tenant_id = ? AND platform_user_id = ?",
            (tenant_id, str(platform_user_id)),
        )
        return cursor.rowcount > 0

    def is_spam(self, tenant_id: int, platform_user_id: int | str) -> bool:
        row = self._one(
            "SELECT id FROM spam WHERE tenant_id = ? AND platform_user_id = ?",
            (tenant_id, str(platform_user_id)),
        )
        return row is not None

    def list_spam(self, tenant_id: int, limit: int = 100) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM spam WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
            (tenant_id, limit),
        )

    # Audit -------------------------------------------------------------------
    def audit(self, tenant_id: int | None, actor: str, event: str, detail: dict[str, Any] | None = None) -> None:
        self.conn.execute(
            "INSERT INTO audit (tenant_id, actor, event, detail, created_at) VALUES (?, ?, ?, ?, ?)",
            (tenant_id, actor, event, _json(detail or {}), now_iso()),
        )

    def recent_audit(self, tenant_id: int, limit: int = 50) -> list[sqlite3.Row]:
        return self._all(
            "SELECT * FROM audit WHERE tenant_id = ? ORDER BY id DESC LIMIT ?",
            (tenant_id, limit),
        )

    def tenant_counts(self, tenant_id: int) -> dict[str, int]:
        result: dict[str, int] = {}
        for table in ("customers", "knowledge", "pending_questions", "bookings", "spam"):
            row = self._one(f"SELECT COUNT(*) AS count FROM {table} WHERE tenant_id = ?", (tenant_id,))
            result[table] = int(row["count"]) if row else 0
        row = self._one(
            "SELECT COUNT(*) AS count FROM pending_questions WHERE tenant_id = ? AND status = 'open'",
            (tenant_id,),
        )
        result["open_pending"] = int(row["count"]) if row else 0
        return result

    def cleanup_past(self) -> None:
        """Mark past confirmed bookings completed and cancel stale reminders."""
        timestamp = now_iso()
        self.conn.execute(
            "UPDATE bookings SET status = 'completed', updated_at = ? WHERE status = 'confirmed' AND end_ts < ?",
            (timestamp, timestamp),
        )
        self.conn.execute(
            "UPDATE notifications SET status = 'cancelled' WHERE status = 'pending' AND booking_id IN (SELECT id FROM bookings WHERE status != 'confirmed')",
        )

    def booking_age_days(self, booking: sqlite3.Row) -> float:
        start = parse_iso(booking["start_ts"])
        if start is None:
            return 0.0
        from .timeutil import utc_now

        return (start - utc_now()).total_seconds() / 86400
