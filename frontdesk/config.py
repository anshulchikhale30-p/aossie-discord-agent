"""Configuration and organization catalog for the AI Front Desk."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().casefold() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_int_set(name: str) -> set[int]:
    result: set[int] = set()
    for chunk in os.getenv(name, "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.add(int(chunk))
        except ValueError:
            continue
    return result


def _env_int_list(name: str, default: list[int]) -> list[int]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    result: list[int] = []
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            result.append(int(chunk))
        except ValueError:
            continue
    return result or list(default)


def _env_list(name: str, default: list[str]) -> list[str]:
    raw = os.getenv(name)
    if not raw:
        return list(default)
    return [item.strip() for item in raw.split(",") if item.strip()] or list(default)


def _path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default))
    return value if value.is_absolute() else ROOT / value


@dataclass(frozen=True)
class RepoDefinition:
    name: str
    url: str
    description: str
    default_branch: str
    docs: tuple[str, ...]
    keywords: tuple[str, ...]


@dataclass(frozen=True)
class OrgDefinition:
    key: str
    display_name: str
    github_org: str
    website: str
    description: str
    timezone: str
    default_repo: str
    repos: dict[str, RepoDefinition] = field(default_factory=dict)


@dataclass(frozen=True)
class Settings:
    token: str
    database_path: Path
    docs_dir: Path
    audit_log: Path
    catalog_path: Path
    default_org: str
    use_ollama: bool
    ollama_base_url: str
    ollama_model: str
    docs_cache_ttl_hours: int
    repo_docs_enabled: bool
    demo_mode: bool
    demo_allowed_user_ids: set[int]
    command_sync_guild_ids: list[int]
    log_level: str
    support_channel_words: list[str]
    staff_channel_words: list[str]
    staff_role_names: list[str]
    default_reminder_offsets: list[int]
    booking_lead_minutes: int
    slot_lookahead_days: int
    max_context_chars: int
    legacy_channel_id: int | None

    @classmethod
    def from_env(cls) -> "Settings":
        legacy_channel = os.getenv("DISCORD_CHANNEL_ID", "").strip()
        return cls(
            token=os.getenv("DISCORD_TOKEN", "").strip(),
            database_path=_path("DATABASE_PATH", "./data/frontdesk.db"),
            docs_dir=_path("DOCS_DIR", "./data/docs"),
            audit_log=_path("AUDIT_LOG", "./data/audit.jsonl"),
            catalog_path=_path("ORG_CATALOG", "./config/orgs.json"),
            default_org=os.getenv("DEFAULT_ORG", "aossie").strip().casefold() or "aossie",
            use_ollama=_env_bool("USE_OLLAMA", False),
            ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/"),
            ollama_model=os.getenv("OLLAMA_MODEL", "llama3.2"),
            docs_cache_ttl_hours=_env_int("DOCS_CACHE_TTL_HOURS", 24),
            repo_docs_enabled=_env_bool("REPO_DOCS_ENABLED", True),
            demo_mode=_env_bool("DEMO_MODE", False),
            demo_allowed_user_ids=_env_int_set("DEMO_ALLOWED_USER_IDS"),
            command_sync_guild_ids=_env_int_list("COMMAND_SYNC_GUILD_IDS", []),
            log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
            support_channel_words=_env_list(
                "SUPPORT_CHANNEL_WORDS",
                ["agent", "support", "help", "ask", "questions", "gsoc", "frontdesk", "front-desk"],
            ),
            staff_channel_words=_env_list(
                "STAFF_CHANNEL_WORDS",
                ["staff", "maintainer", "maintainers", "admin", "moderator", "mods"],
            ),
            staff_role_names=_env_list(
                "STAFF_ROLE_NAMES",
                ["admin", "administrator", "maintainer", "maintainers", "core team", "staff", "moderator", "owner"],
            ),
            default_reminder_offsets=_env_int_list("REMINDER_OFFSETS_MINUTES", [1440, 60, 10]),
            booking_lead_minutes=_env_int("BOOKING_LEAD_MINUTES", 30),
            slot_lookahead_days=_env_int("SLOT_LOOKAHEAD_DAYS", 14),
            max_context_chars=_env_int("MAX_CONTEXT_CHARS", 6000),
            legacy_channel_id=int(legacy_channel) if legacy_channel.isdigit() else None,
        )


class OrgCatalog:
    """The two provider organizations and their public repository catalog."""

    def __init__(self, orgs: dict[str, OrgDefinition]) -> None:
        if not orgs:
            raise ValueError("The organization catalog is empty.")
        self.orgs = orgs

    @classmethod
    def load(cls, path: Path) -> "OrgCatalog":
        raw: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        orgs: dict[str, OrgDefinition] = {}
        for key, data in raw.items():
            repos: dict[str, RepoDefinition] = {}
            for name, repo in (data.get("repos") or {}).items():
                repos[name] = RepoDefinition(
                    name=name,
                    url=repo["url"],
                    description=repo.get("description") or "",
                    default_branch=repo.get("default_branch") or "main",
                    docs=tuple(repo.get("docs") or ("README.md",)),
                    keywords=tuple(repo.get("keywords") or ()),
                )
            orgs[key.casefold()] = OrgDefinition(
                key=key.casefold(),
                display_name=data.get("display_name") or key,
                github_org=data.get("github_org") or key,
                website=data.get("website") or "",
                description=data.get("description") or "",
                timezone=data.get("timezone") or "UTC",
                default_repo=data.get("default_repo") or "Info",
                repos=repos,
            )
        return cls(orgs)

    def get(self, key: str) -> OrgDefinition:
        return self.orgs.get(key.casefold()) or self.orgs[self.default_key]

    @property
    def default_key(self) -> str:
        return next(iter(self.orgs))

    def infer(self, guild_name: str, fallback: str | None = None) -> str:
        name = guild_name.casefold()
        if "stability" in name or "stabilitynexus" in name:
            return "stability" if "stability" in self.orgs else self.default_key
        if "aossie" in name:
            return "aossie" if "aossie" in self.orgs else self.default_key
        candidate = (fallback or "").casefold()
        return candidate if candidate in self.orgs else self.default_key

    def choices(self) -> list[tuple[str, str]]:
        return [(key, org.display_name) for key, org in self.orgs.items()]

    def repo(self, org_key: str, repo_name: str) -> RepoDefinition | None:
        return self.get(org_key).repos.get(repo_name)
