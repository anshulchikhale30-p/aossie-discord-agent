"""Discord authorization helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Iterable

import discord

from .config import Settings


def parse_id_list(value: str | None) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def is_guild_admin(member: discord.Member) -> bool:
    if member.id == member.guild.owner_id:
        return True
    return bool(member.guild_permissions.administrator or member.guild_permissions.manage_guild)


def is_staff_member(
    member: discord.Member,
    tenant: sqlite3.Row,
    settings: Settings,
) -> bool:
    if is_guild_admin(member):
        return True
    role_ids = set(parse_id_list(tenant["staff_role_ids"]))
    if any(str(role.id) in role_ids for role in member.roles):
        return True
    allowed_names = {name.casefold() for name in settings.staff_role_names}
    return any(role.name.casefold() in allowed_names for role in member.roles)


def is_demo_allowed(user_id: int, settings: Settings) -> bool:
    if not settings.demo_mode:
        return True
    return int(user_id) in settings.demo_allowed_user_ids


def channel_ids(value: str | None) -> set[int]:
    result: set[int] = set()
    for item in parse_id_list(value):
        try:
            result.add(int(item))
        except ValueError:
            continue
    return result


def _name_matches(channel: discord.abc.GuildChannel | discord.Thread, words: Iterable[str]) -> bool:
    name = channel.name.casefold()
    if any(word.casefold() in name for word in words):
        return True
    parent = getattr(channel, "parent", None)
    if parent is not None:
        parent_name = getattr(parent, "name", "").casefold()
        return any(word.casefold() in parent_name for word in words)
    return False


def is_support_channel(
    tenant: sqlite3.Row,
    channel: discord.abc.GuildChannel | discord.Thread,
    settings: Settings,
) -> bool:
    configured = channel_ids(tenant["support_channel_ids"])
    if int(channel.id) in configured:
        return True
    parent_id = getattr(channel, "parent_id", None)
    if parent_id and int(parent_id) in configured:
        return True
    return _name_matches(channel, settings.support_channel_words)


def is_staff_channel(
    tenant: sqlite3.Row,
    channel: discord.abc.GuildChannel | discord.Thread,
    settings: Settings,
) -> bool:
    if tenant["staff_channel_id"] and str(channel.id) == str(tenant["staff_channel_id"]):
        return True
    parent_id = getattr(channel, "parent_id", None)
    if parent_id and tenant["staff_channel_id"] and str(parent_id) == str(tenant["staff_channel_id"]):
        return True
    return _name_matches(channel, settings.staff_channel_words)


def channel_link(guild_id: int | str | None, channel_id: int | str | None) -> str:
    if not guild_id or not channel_id:
        return ""
    return f"https://discord.com/channels/{guild_id}/{channel_id}"


def member_label(member: discord.abc.User) -> str:
    if getattr(member, "display_name", None):
        return f"{member.display_name} ({member})"
    return str(member)
