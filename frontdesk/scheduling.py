"""Availability, booking, and reminder rules."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .config import Settings
from .db import Database
from .timeutil import format_dt, iso, now_iso, parse_iso, utc_now, zone


@dataclass(frozen=True)
class Slot:
    staff_id: str
    rule_id: int
    start_utc: datetime
    end_utc: datetime

    @property
    def start_iso(self) -> str:
        return iso(self.start_utc)

    @property
    def end_iso(self) -> str:
        return iso(self.end_utc)

    def label(self, timezone_name: str) -> str:
        return format_dt(self.start_utc, timezone_name)


@dataclass(frozen=True)
class SlotValidation:
    slot: Slot | None
    error: str = ""


class SchedulingService:
    def __init__(self, settings: Settings, db: Database) -> None:
        self.settings = settings
        self.db = db

    # Helpers -----------------------------------------------------------------
    @staticmethod
    def _local_datetime(day: date, clock: str, timezone_name: str) -> datetime | None:
        try:
            parsed = time.fromisoformat(clock)
        except ValueError:
            return None
        local = datetime.combine(day, parsed).replace(tzinfo=zone(timezone_name))
        # Skip nonexistent local times around a DST jump.
        if local.astimezone(zone(timezone_name)).replace(tzinfo=zone(timezone_name)) != local:
            return None
        return local.astimezone(zone("UTC"))

    @staticmethod
    def _minutes(clock: str) -> int:
        try:
            parsed = time.fromisoformat(clock)
        except ValueError:
            return -1
        return parsed.hour * 60 + parsed.minute

    def validate_availability(
        self,
        weekday: int,
        start_time: str,
        end_time: str,
        slot_minutes: int,
    ) -> str:
        if weekday not in range(0, 7):
            return "Weekday must be Monday through Sunday."
        start_minutes = self._minutes(start_time)
        end_minutes = self._minutes(end_time)
        if start_minutes < 0 or end_minutes < 0:
            return "Times must use HH:MM (24-hour)."
        if end_minutes <= start_minutes:
            return "End time must be after start time."
        if slot_minutes < 10 or slot_minutes > 240:
            return "Slot length must be between 10 and 240 minutes."
        if (end_minutes - start_minutes) % slot_minutes != 0:
            return "The availability window must divide evenly into slots."
        return ""

    def _rule_for_local(
        self,
        rules: list[sqlite3.Row],
        local_start: datetime,
        local_end: datetime,
    ) -> sqlite3.Row | None:
        for rule in rules:
            if int(rule["weekday"]) != local_start.weekday():
                continue
            if not (self._minutes(rule["start_time"]) <= local_start.hour * 60 + local_start.minute):
                continue
            if not (local_end.hour * 60 + local_end.minute <= self._minutes(rule["end_time"])):
                continue
            return rule
        return None

    def validate_slot(
        self,
        tenant: sqlite3.Row,
        staff_id: int | str,
        date_text: str,
        time_text: str,
    ) -> SlotValidation:
        timezone_name = tenant["timezone"]
        try:
            local_day = date.fromisoformat(date_text.strip())
        except ValueError:
            return SlotValidation(None, "Date must use YYYY-MM-DD.")
        local_start = self._local_datetime(local_day, time_text.strip(), timezone_name)
        if local_start is None:
            return SlotValidation(None, "That local time does not exist on this date.")
        if local_start < utc_now() + timedelta(minutes=self.settings.booking_lead_minutes):
            return SlotValidation(None, "That time is too soon. Please choose a later slot.")
        rules = self.db.list_availability(int(tenant["id"]), staff_id=staff_id)
        if not rules:
            return SlotValidation(None, "That maintainer has not published availability yet.")
        local_start_view = local_start.astimezone(zone(timezone_name))
        # Use the first rule that can contain a full slot.
        for rule in rules:
            slot_minutes = int(rule["slot_minutes"])
            local_end = local_start_view + timedelta(minutes=slot_minutes)
            matched = self._rule_for_local([rule], local_start_view, local_end)
            if matched is None:
                continue
            end_utc = local_start + timedelta(minutes=slot_minutes)
            conflicts = self.db.bookings_overlapping(
                int(tenant["id"]),
                staff_id,
                iso(local_start),
                iso(end_utc),
            )
            if conflicts:
                return SlotValidation(None, "That slot was just taken. Please choose another one.")
            return SlotValidation(
                Slot(
                    staff_id=str(staff_id),
                    rule_id=int(rule["id"]),
                    start_utc=local_start,
                    end_utc=end_utc,
                )
            )
        return SlotValidation(None, "That time is outside the maintainer's published availability.")

    def generate_slots(
        self,
        tenant: sqlite3.Row,
        staff_id: int | str,
        *,
        days: int | None = None,
        limit: int = 10,
        after: datetime | None = None,
    ) -> list[Slot]:
        timezone_name = tenant["timezone"]
        rules = self.db.list_availability(int(tenant["id"]), staff_id=staff_id)
        if not rules:
            return []
        days = max(1, min(days or self.settings.slot_lookahead_days, 60))
        earliest = (after or utc_now()) + timedelta(minutes=self.settings.booking_lead_minutes)
        today = utc_now().astimezone(zone(timezone_name)).date()
        slots: list[Slot] = []
        for offset in range(days):
            local_day = today + timedelta(days=offset)
            for rule in rules:
                if int(rule["weekday"]) != local_day.weekday():
                    continue
                slot_minutes = int(rule["slot_minutes"])
                start_minutes = self._minutes(rule["start_time"])
                end_minutes = self._minutes(rule["end_time"])
                for minutes in range(start_minutes, end_minutes, slot_minutes):
                    clock = f"{minutes // 60:02d}:{minutes % 60:02d}"
                    start = self._local_datetime(local_day, clock, timezone_name)
                    if start is None or start < earliest:
                        continue
                    end = start + timedelta(minutes=slot_minutes)
                    if self.db.bookings_overlapping(
                        int(tenant["id"]),
                        staff_id,
                        iso(start),
                        iso(end),
                    ):
                        continue
                    slots.append(
                        Slot(
                            staff_id=str(staff_id),
                            rule_id=int(rule["id"]),
                            start_utc=start,
                            end_utc=end,
                        )
                    )
                    if len(slots) >= limit:
                        return slots
        return slots

    def staff_with_availability(self, tenant_id: int) -> list[str]:
        rows = self.db.list_availability(tenant_id)
        return list(dict.fromkeys(str(row["staff_id"]) for row in rows))

    # Booking operations ------------------------------------------------------
    def _reminder_offsets(self, tenant: sqlite3.Row) -> list[int]:
        try:
            values = json.loads(tenant["reminder_offsets"] or "[]")
        except (TypeError, ValueError):
            values = []
        return [int(value) for value in values if isinstance(value, int) and value > 0]

    def _queue_booking_confirmation(self, tenant: sqlite3.Row, booking: sqlite3.Row, actor: str) -> None:
        payload = {"booking_id": int(booking["id"])}
        customer = self.db.get_customer(int(booking["customer_id"]))
        if customer:
            self.db.create_notification(
                int(tenant["id"]),
                "user",
                customer["platform_user_id"],
                "booking_confirmed",
                booking_id=int(booking["id"]),
                payload=payload,
                channel_id=booking["source_channel_id"],
            )
        self.db.create_notification(
            int(tenant["id"]),
            "user",
            booking["staff_id"],
            "booking_confirmed_staff",
            booking_id=int(booking["id"]),
            payload=payload,
            channel_id=tenant["staff_channel_id"],
        )
        self.db.audit(int(tenant["id"]), actor, "booking_confirmed", payload)

    def _queue_reminders(self, tenant: sqlite3.Row, booking: sqlite3.Row) -> None:
        start = parse_iso(booking["start_ts"])
        if start is None:
            return
        now = utc_now()
        offsets = self._reminder_offsets(tenant)
        for minutes in offsets:
            due = start - timedelta(minutes=minutes)
            if due <= now:
                continue
            self.db.create_notification(
                int(tenant["id"]),
                "user",
                booking["staff_id"],
                "booking_reminder_staff",
                booking_id=int(booking["id"]),
                payload={"booking_id": int(booking["id"]), "offset_minutes": minutes},
                due_at=iso(due),
                channel_id=tenant["staff_channel_id"],
            )
            customer = self.db.get_customer(int(booking["customer_id"]))
            if customer:
                self.db.create_notification(
                    int(tenant["id"]),
                    "user",
                    customer["platform_user_id"],
                    "booking_reminder",
                    booking_id=int(booking["id"]),
                    payload={"booking_id": int(booking["id"]), "offset_minutes": minutes},
                    due_at=iso(due),
                    channel_id=booking["source_channel_id"],
                )

    def create_booking(
        self,
        tenant: sqlite3.Row,
        customer: sqlite3.Row,
        staff_id: int | str,
        service: str,
        date_text: str,
        time_text: str,
        *,
        location: str = "",
        notes: str = "",
        source_channel_id: int | str | None = None,
        source_thread_id: int | str | None = None,
        actor: str = "",
    ) -> tuple[sqlite3.Row | None, str]:
        validation = self.validate_slot(tenant, staff_id, date_text, time_text)
        if validation.slot is None:
            return None, validation.error
        slot = validation.slot
        booking = self.db.create_booking(
            int(tenant["id"]),
            int(customer["id"]),
            staff_id,
            service,
            slot.start_iso,
            slot.end_iso,
            tenant["timezone"],
            location=location,
            notes=notes,
            source_channel_id=source_channel_id,
            source_thread_id=source_thread_id,
        )
        if booking is None:
            return None, "That slot was just taken. Please choose another one."
        self._queue_booking_confirmation(tenant, booking, actor or "customer")
        self._queue_reminders(tenant, booking)
        return booking, ""

    def reschedule_booking(
        self,
        tenant: sqlite3.Row,
        booking: sqlite3.Row,
        date_text: str,
        time_text: str,
        *,
        actor: str = "",
    ) -> tuple[sqlite3.Row | None, str]:
        validation = self.validate_slot(tenant, booking["staff_id"], date_text, time_text)
        if validation.slot is None:
            return None, validation.error
        slot = validation.slot
        moved = self.db.update_booking_time(
            int(booking["id"]),
            int(tenant["id"]),
            slot.start_iso,
            slot.end_iso,
        )
        if not moved:
            return None, "That slot was just taken. Please choose another one."
        self.db.cancel_notifications_for_booking(int(booking["id"]))
        updated = self.db.get_booking(int(booking["id"]))
        if updated is None:
            return None, "The booking could not be reloaded."
        payload = {"booking_id": int(updated["id"])}
        customer = self.db.get_customer(int(updated["customer_id"]))
        if customer:
            self.db.create_notification(
                int(tenant["id"]),
                "user",
                customer["platform_user_id"],
                "booking_rescheduled",
                booking_id=int(updated["id"]),
                payload=payload,
                channel_id=updated["source_channel_id"],
            )
        self.db.create_notification(
            int(tenant["id"]),
            "user",
            updated["staff_id"],
            "booking_rescheduled_staff",
            booking_id=int(updated["id"]),
            payload=payload,
            channel_id=tenant["staff_channel_id"],
        )
        self._queue_reminders(tenant, updated)
        self.db.audit(
            int(tenant["id"]),
            actor,
            "booking_rescheduled",
            {"booking_id": int(updated["id"]), "start_ts": updated["start_ts"]},
        )
        return updated, ""

    def cancel_booking(self, tenant: sqlite3.Row, booking: sqlite3.Row, actor: str) -> None:
        self.db.cancel_booking(int(booking["id"]), int(tenant["id"]))
        self.db.cancel_notifications_for_booking(int(booking["id"]))
        payload = {"booking_id": int(booking["id"])}
        customer = self.db.get_customer(int(booking["customer_id"]))
        if customer:
            self.db.create_notification(
                int(tenant["id"]),
                "user",
                customer["platform_user_id"],
                "booking_cancelled",
                booking_id=int(booking["id"]),
                payload=payload,
                channel_id=booking["source_channel_id"],
            )
        self.db.create_notification(
            int(tenant["id"]),
            "user",
            booking["staff_id"],
            "booking_cancelled_staff",
            booking_id=int(booking["id"]),
            payload=payload,
            channel_id=tenant["staff_channel_id"],
        )
        self.db.audit(int(tenant["id"]), actor, "booking_cancelled", payload)

    def alternatives(
        self,
        tenant: sqlite3.Row,
        staff_id: int | str,
        *,
        after: datetime | None = None,
        limit: int = 3,
    ) -> list[Slot]:
        return self.generate_slots(tenant, staff_id, limit=limit, after=after)

    def availability_affected_bookings(
        self,
        tenant: sqlite3.Row,
        staff_id: int | str,
    ) -> list[sqlite3.Row]:
        rules = self.db.list_availability(int(tenant["id"]), staff_id=staff_id)
        affected: list[sqlite3.Row] = []
        timezone_name = tenant["timezone"]
        for booking in self.db.list_staff_bookings(
            int(tenant["id"]),
            staff_id=staff_id,
            from_ts=now_iso(),
        ):
            start = parse_iso(booking["start_ts"])
            end = parse_iso(booking["end_ts"])
            if start is None or end is None:
                continue
            local_start = start.astimezone(zone(timezone_name))
            local_end = end.astimezone(zone(timezone_name))
            if self._rule_for_local(rules, local_start, local_end) is None:
                affected.append(booking)
        return affected

    def remove_availability(
        self,
        tenant: sqlite3.Row,
        availability_id: int,
        actor: str,
    ) -> tuple[bool, list[sqlite3.Row]]:
        rule = self.db.get_availability(availability_id)
        if rule is None or int(rule["tenant_id"]) != int(tenant["id"]):
            return False, []
        staff_id = rule["staff_id"]
        if not self.db.deactivate_availability(availability_id, int(tenant["id"])):
            return False, []
        affected = self.availability_affected_bookings(tenant, staff_id)
        for booking in affected:
            customer = self.db.get_customer(int(booking["customer_id"]))
            if customer is None:
                continue
            self.db.create_notification(
                int(tenant["id"]),
                "user",
                customer["platform_user_id"],
                "availability_changed",
                booking_id=int(booking["id"]),
                payload={"booking_id": int(booking["id"])},
                channel_id=booking["source_channel_id"],
            )
        self.db.audit(
            int(tenant["id"]),
            actor,
            "availability_removed",
            {"availability_id": availability_id, "affected_bookings": [int(row["id"]) for row in affected]},
        )
        return True, affected

    def set_attendance(
        self,
        tenant: sqlite3.Row,
        booking: sqlite3.Row,
        attendance: str,
        actor: str,
    ) -> bool:
        changed = self.db.set_attendance(int(booking["id"]), int(tenant["id"]), attendance)
        if changed:
            self.db.audit(
                int(tenant["id"]),
                actor,
                "attendance_updated",
                {"booking_id": int(booking["id"]), "attendance": attendance},
            )
            if attendance == "declined":
                self.db.create_notification(
                    int(tenant["id"]),
                    "channel",
                    tenant["staff_channel_id"] or "",
                    "attendance_declined_staff",
                    booking_id=int(booking["id"]),
                    payload={"booking_id": int(booking["id"])},
                    channel_id=tenant["staff_channel_id"],
                )
        return changed
