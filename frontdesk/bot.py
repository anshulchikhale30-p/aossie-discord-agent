"""Discord application for the AI Front Desk."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .config import OrgDefinition, Settings
from .permissions import (
    channel_ids,
    channel_link,
    is_guild_admin,
    is_staff_channel,
    is_staff_member,
)
from .services import Services
from .text import (
    looks_like_dissatisfaction,
    looks_like_greeting,
    looks_like_human_request,
    looks_like_codebase_change_request,
    looks_like_thanks,
    looks_urgent,
    split_message,
)
from .timeutil import format_dt, humanize_delta, parse_iso
from .views import AttendanceView, TenantSelectView
from .codebase_quiz import CodebaseQuizView

logger = logging.getLogger("frontdesk")

QUESTION_STARTERS = re.compile(
    r"^(how|where|what|when|why|can|could|is|are|does|do|which|who|should|would)\b",
    re.IGNORECASE,
)


class DeliveryBlocked(RuntimeError):
    pass


@dataclass
class PendingResolution:
    resolved_ids: list[int] = field(default_factory=list)
    delivered: int = 0
    skipped: list[str] = field(default_factory=list)

    @property
    def summary(self) -> str:
        text = f"Resolved {len(self.resolved_ids)} question(s); delivered {self.delivered} message(s)."
        if self.skipped:
            text += " Skipped: " + "; ".join(self.skipped[:4])
        return text


class FrontDeskBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)
        self.settings = settings
        self.services = Services.build(settings)
        self.logger = logger
        self._synced = False

    async def setup_hook(self) -> None:
        from .cogs.general import GeneralCog
        from .cogs.knowledge_cog import KnowledgeCog
        from .cogs.meeting_cog import MeetingCog
        from .cogs.pending_cog import PendingCog
        from .cogs.setup_cog import SetupCog
        from .cogs.staff_cog import StaffCog

        for cog in (GeneralCog, SetupCog, KnowledgeCog, PendingCog, StaffCog, MeetingCog):
            await self.add_cog(cog(self))
        self.tree.on_error = self.on_tree_error
        self.notification_loop.start()

    async def on_ready(self) -> None:
        self.logger.info("Front desk online as %s", self.user)
        for guild in self.guilds:
            try:
                self.ensure_tenant(guild)
            except Exception:
                self.logger.exception("Could not provision tenant for guild %s", guild.id)
        if not self._synced:
            await self.sync_commands()
            self._synced = True

    async def close(self) -> None:
        if self.notification_loop.is_running():
            self.notification_loop.cancel()
        await self.services.close()
        await super().close()

    async def sync_commands(self) -> None:
        try:
            if self.settings.command_sync_guild_ids:
                for guild_id in self.settings.command_sync_guild_ids:
                    guild = self.get_guild(guild_id)
                    if guild:
                        await self.tree.sync(guild=guild)
            else:
                for guild in self.guilds:
                    try:
                        await self.tree.sync(guild=guild)
                    except discord.HTTPException:
                        self.logger.exception("Could not sync commands to guild %s", guild.id)
            # Global commands make /ask and /human usable in DMs. Guild copies
            # override these and appear immediately.
            try:
                await self.tree.sync()
            except discord.HTTPException:
                self.logger.warning("Global command sync was rate limited or failed; guild commands still work.")
        except Exception:
            self.logger.exception("Command sync failed")

    # Tenant and authorization helpers ---------------------------------------
    def ensure_tenant(self, guild: discord.Guild) -> sqlite3.Row:
        existing = self.services.db.get_tenant_by_guild(guild.id)
        if existing is not None:
            configured = channel_ids(existing["support_channel_ids"])
            if self.settings.legacy_channel_id and self.settings.legacy_channel_id not in configured:
                if guild.get_channel(self.settings.legacy_channel_id):
                    configured.add(self.settings.legacy_channel_id)
                    existing = self.services.db.update_tenant(
                        int(existing["id"]),
                        support_channel_ids=sorted(configured),
                    )
            return existing

        org_key = self.services.catalog.infer(guild.name, self.settings.default_org)
        org = self.services.catalog.get(org_key)
        support_channels = [
            channel.id
            for channel in guild.text_channels
            if any(word.casefold() in channel.name.casefold() for word in self.settings.support_channel_words)
        ]
        if self.settings.legacy_channel_id and guild.get_channel(self.settings.legacy_channel_id):
            if self.settings.legacy_channel_id not in support_channels:
                support_channels.append(self.settings.legacy_channel_id)
        staff_channel = next(
            (
                channel
                for channel in guild.text_channels
                if any(word.casefold() in channel.name.casefold() for word in self.settings.staff_channel_words)
            ),
            None,
        )
        staff_roles = [
            role.id
            for role in guild.roles
            if role.name.casefold() in {name.casefold() for name in self.settings.staff_role_names}
        ]
        tenant = self.services.db.create_tenant(
            guild.id,
            org.key,
            org.display_name,
            org.timezone,
            staff_role_ids=staff_roles,
            support_channel_ids=support_channels,
            staff_channel_id=staff_channel.id if staff_channel else None,
            reminder_offsets=self.settings.default_reminder_offsets,
        )
        self.services.db.audit(
            int(tenant["id"]),
            "system",
            "tenant_provisioned",
            {"guild": guild.name, "org": org.key, "support_channels": support_channels},
        )
        self.logger.info("Provisioned %s for guild %s (%s)", org.display_name, guild.name, guild.id)
        return tenant

    def ensure_dm_tenant(self, user: discord.abc.User) -> sqlite3.Row:
        """Create a private default-organization boundary for first-contact DMs."""
        guild_key = f"dm:{user.id}"
        existing = self.services.db.get_tenant_by_guild(guild_key)
        if existing is not None:
            return existing
        org = self.services.catalog.get(self.settings.default_org)
        tenant = self.services.db.create_tenant(
            guild_key,
            org.key,
            org.display_name,
            org.timezone,
            staff_role_ids=[],
            support_channel_ids=[],
            staff_channel_id=None,
            reminder_offsets=self.settings.default_reminder_offsets,
        )
        self.resolve_customer(tenant, user)
        return tenant

    def org_for(self, tenant: sqlite3.Row) -> OrgDefinition:
        return self.services.catalog.get(tenant["org_key"])

    def is_staff(self, member: discord.Member, tenant: sqlite3.Row) -> bool:
        return is_staff_member(member, tenant, self.settings)

    def resolve_customer(self, tenant: sqlite3.Row, user: discord.abc.User) -> sqlite3.Row:
        return self.services.db.upsert_customer(
            int(tenant["id"]),
            user.id,
            getattr(user, "name", str(user)),
            getattr(user, "display_name", getattr(user, "name", str(user))),
        )

    async def guard_staff(self, interaction: discord.Interaction) -> tuple[sqlite3.Row, discord.Member] | None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Staff commands must be used in a server.", ephemeral=True)
            return None
        tenant = self.ensure_tenant(interaction.guild)
        if not self.is_staff(interaction.user, tenant):
            await interaction.response.send_message(
                "You need a maintainer or administrator role to use that command.",
                ephemeral=True,
            )
            return None
        return tenant, interaction.user

    async def guard_admin(self, interaction: discord.Interaction) -> tuple[sqlite3.Row, discord.Member] | None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This command must be used in a server.", ephemeral=True)
            return None
        if not is_guild_admin(interaction.user):
            await interaction.response.send_message(
                "Only a server administrator can use that command.",
                ephemeral=True,
            )
            return None
        tenant = self.ensure_tenant(interaction.guild)
        return tenant, interaction.user

    async def guard_customer(self, interaction: discord.Interaction) -> tuple[sqlite3.Row, discord.abc.User] | None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("Use this command in one of the organization servers.", ephemeral=True)
            return None
        tenant = self.ensure_tenant(interaction.guild)
        if self.services.db.is_spam(int(tenant["id"]), interaction.user.id):
            await interaction.response.send_message("I can’t process that request.", ephemeral=True)
            return None
        return tenant, interaction.user

    # Message handling --------------------------------------------------------
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content.strip():
            return
        try:
            if isinstance(message.channel, discord.DMChannel):
                await self.handle_dm(message)
                return
            if message.guild is None:
                return

            mentioned = self.bot_mentioned(message)
            # A contributor should not need to know the bot's mention for an
            # issue/PR request. These requests start the codebase check even
            # when posted as ordinary text. Unrelated public conversation is
            # still ignored unless the bot is explicitly mentioned.
            change_request = looks_like_codebase_change_request(message.content)
            natural_request = self.likely_question(message) or looks_like_greeting(message.content)
            # Do this before tenant/database/channel checks. If this message is
            # visible to the Gateway and the bot can send in the channel, the
            # user must see an acknowledgement even if later processing fails.
            if not mentioned and not change_request and not natural_request:
                return
            should_handle = mentioned or change_request or natural_request
            # Do this before tenant/database/channel checks. If this message is
            # visible to the Gateway and the bot can send in the channel, the
            # user must see an acknowledgement even if later processing fails.
            if should_handle:
                try:
                    await message.channel.send(
                        "I received your message — checking the approved project information now…",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    self.logger.exception("Could not acknowledge message %s", message.id)

            tenant = self.ensure_tenant(message.guild)
            if self.services.db.is_spam(int(tenant["id"]), message.author.id):
                return

            if is_staff_channel(tenant, message.channel, self.settings) and not mentioned:
                await self.handle_staff_reply(message, tenant)
                return

            conversation = self.services.db.get_conversation_by_thread(message.channel.id)
            if conversation is not None:
                await self.handle_follow_up(message, conversation)
                return

            # Normal channel messages are intentionally mention-driven. This lets
            # the bot work in any public/private channel where it has permission,
            # without replying to every conversation in the server.
            if should_handle:
                customer = self.resolve_customer(tenant, message.author)
                conversation = self.services.db.get_channel_conversation(
                    int(tenant["id"]), int(customer["id"]), message.channel.id
                )
                if conversation is not None:
                    if should_handle:
                        await self.handle_follow_up(message, conversation)
                    return
                await self.handle_new_question(message, tenant)
        except Exception:
            self.logger.exception("Message handling failed for message %s", message.id)
            if message.guild is not None:
                try:
                    await message.channel.send(
                        "I received your message, but I hit a temporary processing error. "
                        "Please try tagging me again in a moment; a maintainer can check the Render logs if it continues.",
                        allowed_mentions=discord.AllowedMentions.none(),
                    )
                except discord.HTTPException:
                    self.logger.exception("Could not send fallback error for message %s", message.id)

    def bot_mentioned(self, message: discord.Message) -> bool:
        if self.user is None:
            return False
        return (
            self.user in message.mentions
            or self.user.id in message.raw_mentions
            or f"<@{self.user.id}>" in message.content
            or f"<@!{self.user.id}>" in message.content
        )

    def likely_question(self, message: discord.Message) -> bool:
        content = message.content.strip()
        return (
            "?" in content
            or bool(QUESTION_STARTERS.match(content))
            or self.bot_mentioned(message)
            or looks_like_human_request(content)
        )

    @staticmethod
    def clean_question(content: str, bot_id: int | None = None) -> str:
        text = content.strip()
        if bot_id:
            text = text.replace(f"<@{bot_id}>", "").replace(f"<@!{bot_id}>", "").strip()
        return text

    async def handle_new_question(
        self,
        message: discord.Message,
        tenant: sqlite3.Row,
        *,
        existing_thread: discord.Thread | None = None,
    ) -> None:
        customer = self.resolve_customer(tenant, message.author)
        # Keep ordinary tagged conversations in the channel. Threads are only
        # used when a user or maintainer explicitly creates one, or when an
        # existing thread is already the conversation surface.
        thread = existing_thread
        conversation = self.services.db.create_conversation(
            int(tenant["id"]),
            int(customer["id"]),
            message.channel.id,
            thread_id=thread.id if thread else None,
            parent_channel_id=message.channel.id if thread else None,
        )
        target = thread or message.channel
        await self.process_question(
            tenant,
            customer,
            conversation,
            self.clean_question(message.content, self.user.id if self.user else None),
            target,
            message.author.id,
            str(message.author),
        )

    async def handle_follow_up(self, message: discord.Message, conversation: sqlite3.Row) -> None:
        tenant = self.services.db.get_tenant(int(conversation["tenant_id"]))
        customer = self.services.db.get_customer(int(conversation["customer_id"]))
        if tenant is None or customer is None:
            return
        if isinstance(message.author, discord.Member) and self.is_staff(message.author, tenant):
            if str(message.author.id) != str(customer["platform_user_id"]):
                # A maintainer has joined the customer thread; let the human
                # conversation continue without the bot talking over them.
                return
        content = self.clean_question(message.content, self.user.id if self.user else None)
        if not content:
            return
        if looks_like_greeting(content):
            reply = "Hi! Ask me anything about the organization, its projects, or scheduling."
            await self.send_to_conversation(conversation, reply)
            self.services.db.add_message(int(conversation["id"]), self.user.id if self.user else None, "assistant", reply)
            return
        if looks_like_thanks(content):
            reply = "You’re welcome. If anything else comes up, ask here and I’ll help or route it to a maintainer."
            await self.send_to_conversation(conversation, reply)
            self.services.db.add_message(int(conversation["id"]), self.user.id if self.user else None, "assistant", reply)
            return
        if looks_like_dissatisfaction(content):
            history = self.services.db.recent_messages(int(conversation["id"]), 10)
            previous = next(
                (str(row["content"]) for row in reversed(history) if row["role"] == "assistant"),
                "",
            )
            summary = self.services.agent.summarize(history, content)
            pending = self.services.db.create_pending(
                int(tenant["id"]),
                question=self.clean_question(history[0]["content"], self.user.id if self.user else None) if history else content,
                customer_id=int(customer["id"]),
                conversation_id=int(conversation["id"]),
                answer_given=previous,
                clarification=content,
                priority="high" if looks_urgent(content) else "normal",
                summary=summary,
            )
            reply = (
                "Thanks for flagging that. I’ve passed your clarification and the earlier answer "
                "to a maintainer so they can check it."
            )
            await self.send_to_conversation(conversation, reply)
            self.services.db.add_message(int(conversation["id"]), self.user.id if self.user else None, "assistant", reply)
            await self.notify_pending_staff(tenant, pending, customer, conversation, content, previous, summary)
            self.services.db.audit(
                int(tenant["id"]),
                str(message.author),
                "clarification_escalated",
                {"pending_id": int(pending["id"]), "question": content},
            )
            return
        await self.process_question(
            tenant,
            customer,
            conversation,
            content,
            message.channel,
            message.author.id,
            str(message.author),
        )

    async def process_question(
        self,
        tenant: sqlite3.Row,
        customer: sqlite3.Row,
        conversation: sqlite3.Row,
        question: str,
        target: discord.abc.Messageable,
        author_id: int | str,
        author_label: str,
        skip_codebase_check: bool = False,
    ):
        question = question.strip()
        if not question:
            return None
        org = self.org_for(tenant)
        if not skip_codebase_check and looks_like_codebase_change_request(question):
            existing_check = self.services.db.get_codebase_check(
                int(tenant["id"]), int(customer["id"]), org.default_repo
            )
            if existing_check is None or existing_check["status"] != "passed":
                self.services.db.save_codebase_check(
                    int(tenant["id"]), int(customer["id"]), org.default_repo, "in_progress", 0, 3
                )
                view = CodebaseQuizView(
                    self,
                    int(tenant["id"]),
                    int(customer["id"]),
                    org.default_repo,
                    question,
                    target,
                    conversation,
                    author_id,
                    author_label,
                )
                prompt = view.prompt()
                await target.send(
                    f"Before I help you create an issue or PR, I want to check your understanding of the codebase.\n\n{prompt}",
                    view=view,
                )
                self.services.db.add_message(
                    int(conversation["id"]), self.user.id if self.user else None, "assistant", prompt
                )
                self.services.db.audit(
                    int(tenant["id"]),
                    author_label,
                    "codebase_check_started",
                    {"repository": org.default_repo, "question": question},
                )
                return None
        self.services.db.add_message(int(conversation["id"]), author_id, "user", question)
        self.services.db.touch_conversation(int(conversation["id"]))
        history = self.services.db.recent_messages(int(conversation["id"]), 10)
        result = await self.services.agent.answer(
            org,
            tenant,
            customer,
            conversation,
            question,
            history=history,
        )
        if result.should_escalate:
            priority = "urgent" if looks_urgent(question) else "high" if looks_like_human_request(question) else "normal"
            summary = self.services.agent.summarize(history, question)
            pending = self.services.db.create_pending(
                int(tenant["id"]),
                question=question,
                customer_id=int(customer["id"]),
                conversation_id=int(conversation["id"]),
                answer_given=result.text,
                priority=priority,
                summary=summary,
            )
            await self.send_long(target, result.text)
            self.services.db.add_message(
                int(conversation["id"]),
                self.user.id if self.user else None,
                "assistant",
                result.text,
            )
            await self.notify_pending_staff(tenant, pending, customer, conversation, question, result.text, summary)
            self.services.db.audit(
                int(tenant["id"]),
                author_label,
                "question_escalated",
                {
                    "pending_id": int(pending["id"]),
                    "question": question,
                    "routes": result.route_names,
                    "reason": result.reason,
                },
            )
            return result

        text = result.text
        if result.sources:
            text += "\n\n**Sources**\n" + "\n".join(f"• {source}" for source in result.sources)
        await self.send_long(target, text)
        self.services.db.add_message(
            int(conversation["id"]),
            self.user.id if self.user else None,
            "assistant",
            text,
        )
        self.services.db.audit(
            int(tenant["id"]),
            author_label,
            "answer_sent",
            {
                "question": question,
                "confidence": result.confidence,
                "routes": result.route_names,
                "sources": result.sources,
                "knowledge_ids": [hit.id for hit in result.knowledge_hits],
            },
        )
        return result

    async def notify_pending_staff(
        self,
        tenant: sqlite3.Row,
        pending: sqlite3.Row,
        customer: sqlite3.Row | None,
        conversation: sqlite3.Row | None,
        question: str,
        answer_given: str,
        summary: str,
    ) -> None:
        guild = self.get_guild(int(tenant["guild_id"])) if tenant["guild_id"] else None
        link = ""
        if conversation is not None and guild is not None:
            link = channel_link(guild.id, conversation["thread_id"] or conversation["channel_id"])
        embed = discord.Embed(
            title=f"Pending question #{int(pending['id'])} · {pending['priority']}",
            description=question[:1800],
            color=discord.Color.orange() if pending["priority"] == "normal" else discord.Color.red(),
        )
        embed.add_field(name="Organization", value=tenant["display_name"], inline=True)
        if customer is not None:
            embed.add_field(
                name="Member",
                value=f"<@{customer['platform_user_id']}> ({customer['username']})",
                inline=True,
            )
        if link:
            embed.add_field(name="Conversation", value=f"[Open thread]({link})", inline=False)
        if answer_given:
            embed.add_field(name="What the bot said", value=answer_given[:1000], inline=False)
        if summary:
            embed.add_field(name="Context", value=summary[:1000], inline=False)
        embed.set_footer(text="Reply to this message with the answer, or use /pending answer.")
        message = await self.notify_staff(tenant, guild, embed=embed)
        if message is not None:
            self.services.db.set_pending_staff_message(int(pending["id"]), message.id, message.channel.id)

    async def notify_staff(
        self,
        tenant: sqlite3.Row,
        guild: discord.Guild | None,
        *,
        content: str | None = None,
        embed: discord.Embed | None = None,
    ) -> discord.Message | None:
        channel = None
        if tenant["staff_channel_id"]:
            channel = self.get_channel(int(tenant["staff_channel_id"]))
            if channel is None:
                try:
                    channel = await self.fetch_channel(int(tenant["staff_channel_id"]))
                except discord.HTTPException:
                    channel = None
        if channel is None and guild is not None:
            channel = next(
                (
                    item
                    for item in guild.text_channels
                    if any(word.casefold() in item.name.casefold() for word in self.settings.staff_channel_words)
                ),
                None,
            )
            if channel is not None:
                self.services.db.update_tenant(int(tenant["id"]), staff_channel_id=channel.id)
        if channel is not None:
            try:
                return await channel.send(content=content, embed=embed, allowed_mentions=discord.AllowedMentions.none())
            except discord.HTTPException:
                self.logger.exception("Could not send staff notification")
        if guild is not None:
            try:
                owner = guild.owner or await guild.fetch_member(guild.owner_id)
                if owner is not None:
                    return await owner.send(content=content, embed=embed)
            except discord.HTTPException:
                self.logger.exception("Could not DM the guild owner")
        self.logger.warning("No staff channel or owner available for tenant %s", tenant["id"])
        return None

    async def handle_staff_reply(self, message: discord.Message, tenant: sqlite3.Row) -> None:
        if message.reference is None or not isinstance(message.author, discord.Member):
            return
        if not self.is_staff(message.author, tenant):
            return
        pending = self.services.db.get_pending_by_staff_message(
            int(tenant["id"]),
            message.reference.message_id,
        )
        if pending is None:
            return
        resolution = await self.resolve_pending(
            tenant,
            pending,
            message.content,
            scope="customer",
            actor=str(message.author),
        )
        try:
            await message.reply(
                f"Answered pending #{int(pending['id'])}. {resolution.summary}",
                mention_author=False,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException:
            pass

    async def resolve_pending(
        self,
        tenant: sqlite3.Row,
        pending: sqlite3.Row,
        text: str,
        *,
        scope: str,
        actor: str,
    ) -> PendingResolution:
        result = PendingResolution()
        customer = (
            self.services.db.get_customer(int(pending["customer_id"]))
            if pending["customer_id"]
            else None
        )
        conversation = (
            self.services.db.get_conversation(int(pending["conversation_id"]))
            if pending["conversation_id"]
            else None
        )
        if scope == "organization":
            title = f"Organization update from pending #{int(pending['id'])}"
        else:
            if customer is None:
                return PendingResolution(skipped=["pending has no customer record"])
            title = f"Answer to pending #{int(pending['id'])}"
        self.services.knowledge.add(
            int(tenant["id"]),
            scope="org" if scope == "organization" else "customer",
            title=title,
            content=text,
            actor=actor,
            customer_id=int(customer["id"]) if customer is not None and scope != "organization" else None,
            source=f"Maintainer answer (pending #{int(pending['id'])})",
            supersedes_id=None,
        )
        if self.services.db.resolve_pending(int(pending["id"]), text, actor):
            result.resolved_ids.append(int(pending["id"]))

        if customer is not None and self.services.db.is_spam(int(tenant["id"]), customer["platform_user_id"]):
            result.skipped.append(f"pending #{int(pending['id'])}: customer is blocked")
        else:
            try:
                if conversation is not None:
                    await self.send_to_conversation(conversation, text)
                    self.services.db.add_message(
                        int(conversation["id"]),
                        self.user.id if self.user else None,
                        "assistant",
                        text,
                    )
                elif customer is not None:
                    await self.dm_user(customer["platform_user_id"], text)
                else:
                    result.skipped.append(f"pending #{int(pending['id'])}: no delivery route")
                    return result
                result.delivered += 1
            except (discord.HTTPException, DeliveryBlocked) as exc:
                result.skipped.append(f"pending #{int(pending['id'])}: {exc}")

        if scope == "organization":
            for other in self.services.db.open_pending_for_tenant(int(tenant["id"])):
                if int(other["id"]) == int(pending["id"]):
                    continue
                score, coverage = self.services.agent.context_score(other["question"], text)
                if score < 3.0 or coverage < 0.25:
                    continue
                other_customer = (
                    self.services.db.get_customer(int(other["customer_id"]))
                    if other["customer_id"]
                    else None
                )
                if other_customer is not None and self.services.db.is_spam(
                    int(tenant["id"]), other_customer["platform_user_id"]
                ):
                    continue
                other_conversation = (
                    self.services.db.get_conversation(int(other["conversation_id"]))
                    if other["conversation_id"]
                    else None
                )
                try:
                    if other_conversation is not None:
                        await self.send_to_conversation(other_conversation, text)
                        self.services.db.add_message(
                            int(other_conversation["id"]),
                            self.user.id if self.user else None,
                            "assistant",
                            text,
                        )
                    elif other_customer is not None:
                        await self.dm_user(other_customer["platform_user_id"], text)
                    else:
                        continue
                except (discord.HTTPException, DeliveryBlocked) as exc:
                    result.skipped.append(f"pending #{int(other['id'])}: {exc}")
                    continue
                if self.services.db.resolve_pending(int(other["id"]), text, actor):
                    result.resolved_ids.append(int(other["id"]))
                    result.delivered += 1

        self.services.db.audit(
            int(tenant["id"]),
            actor,
            "pending_answered",
            {
                "pending_id": int(pending["id"]),
                "scope": scope,
                "resolved_ids": result.resolved_ids,
                "delivered": result.delivered,
            },
        )
        return result

    # DMs --------------------------------------------------------------------
    async def handle_dm(self, message: discord.Message) -> None:
        tenants = self.services.db.customer_tenants(message.author.id)
        if not tenants:
            self.ensure_dm_tenant(message.author)
            tenants = self.services.db.customer_tenants(message.author.id)
        if len(tenants) == 1:
            await self.handle_dm_for_tenant(message, int(tenants[0]["tenant_id"]))
            return
        view = TenantSelectView(self, message, tenants)
        await message.channel.send(
            "You’ve talked with more than one organization. Which one is this about?",
            view=view,
        )

    async def handle_dm_for_tenant(self, message: discord.Message, tenant_id: int) -> None:
        tenant = self.services.db.get_tenant(tenant_id)
        if tenant is None:
            await message.channel.send("That organization is no longer configured.")
            return
        if self.services.db.is_spam(tenant_id, message.author.id):
            return
        customer = self.resolve_customer(tenant, message.author)
        conversation = self.services.db.get_dm_conversation(tenant_id, int(customer["id"]), message.channel.id)
        if conversation is None:
            conversation = self.services.db.create_conversation(
                tenant_id,
                int(customer["id"]),
                message.channel.id,
            )
        content = self.clean_question(message.content, self.user.id if self.user else None)
        if not content:
            return
        if looks_like_greeting(content):
            await message.channel.send("Hi! Ask me anything about the organization, its projects, or scheduling.")
            return
        if looks_like_thanks(content):
            await message.channel.send("You’re welcome. Ask here anytime.")
            return
        await self.process_question(
            tenant,
            customer,
            conversation,
            content,
            message.channel,
            message.author.id,
            str(message.author),
        )

    # Delivery ----------------------------------------------------------------
    async def send_long(self, target: discord.abc.Messageable, content: str, **kwargs: Any) -> discord.Message | None:
        chunks = split_message(content)
        first: discord.Message | None = None
        for index, chunk in enumerate(chunks):
            sent = await target.send(
                chunk,
                allowed_mentions=discord.AllowedMentions.none(),
                **(kwargs if index == 0 else {}),
            )
            if first is None:
                first = sent
        return first

    async def send_to_conversation(self, conversation: sqlite3.Row, content: str, **kwargs: Any) -> discord.Message | None:
        tenant = self.services.db.get_tenant(int(conversation["tenant_id"]))
        customer = self.services.db.get_customer(int(conversation["customer_id"]))
        if tenant is None:
            raise DeliveryBlocked("Tenant no longer exists.")
        if customer is not None and self.services.db.is_spam(int(tenant["id"]), customer["platform_user_id"]):
            raise DeliveryBlocked("Customer is on the spam list.")
        channel = None
        channel_id = conversation["thread_id"] or conversation["channel_id"]
        if channel_id:
            channel = self.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.fetch_channel(int(channel_id))
                except discord.HTTPException:
                    channel = None
        if channel is not None:
            try:
                return await self.send_long(channel, content, **kwargs)
            except discord.HTTPException:
                self.logger.warning("Conversation channel %s is not writable; trying DM", channel_id)
        if customer is not None:
            return await self.dm_user(customer["platform_user_id"], content, **kwargs)
        raise DeliveryBlocked("No delivery route for the conversation.")

    async def dm_user(
        self,
        user_id: int | str,
        content: str | None = None,
        *,
        embed: discord.Embed | None = None,
        view: discord.ui.View | None = None,
    ) -> discord.Message | None:
        user = self.get_user(int(user_id))
        if user is None:
            try:
                user = await self.fetch_user(int(user_id))
            except discord.HTTPException as exc:
                raise DeliveryBlocked("User could not be fetched.") from exc
        if content:
            chunks = split_message(content)
            first = await user.send(chunks[0], embed=embed, view=view)
            for chunk in chunks[1:]:
                await user.send(chunk)
            return first
        return await user.send(embed=embed, view=view)

    # Durable notifications ---------------------------------------------------
    @tasks.loop(seconds=30)
    async def notification_loop(self) -> None:
        await self.wait_until_ready()
        try:
            self.services.db.cleanup_past()
        except Exception:
            self.logger.exception("Notification cleanup failed")
        for row in self.services.notifications.due(50):
            try:
                await self.deliver_notification(row)
                self.services.notifications.mark_sent(int(row["id"]))
            except Exception as exc:
                self.logger.warning("Notification %s failed: %s", row["id"], exc)
                self.services.notifications.mark_failed(int(row["id"]), str(exc))

    async def deliver_notification(self, row: sqlite3.Row) -> None:
        tenant = self.services.db.get_tenant(int(row["tenant_id"]))
        if tenant is None:
            return
        payload = json.loads(row["payload"] or "{}")
        kind = str(row["kind"])
        booking = self.services.db.get_booking(int(row["booking_id"])) if row["booking_id"] else None
        customer = (
            self.services.db.get_customer(int(booking["customer_id"]))
            if booking is not None
            else None
        )
        if customer is not None and self.services.db.is_spam(
            int(tenant["id"]), customer["platform_user_id"]
        ):
            self.services.db.audit(
                int(tenant["id"]),
                "system",
                "notification_skipped_spam",
                {"notification_id": int(row["id"]), "kind": kind},
            )
            return
        if row["recipient_kind"] == "user" and self.services.db.is_spam(
            int(tenant["id"]), row["recipient_id"]
        ):
            self.services.db.audit(
                int(tenant["id"]),
                "system",
                "notification_skipped_spam",
                {"notification_id": int(row["id"]), "kind": kind, "recipient": row["recipient_id"]},
            )
            return
        content, embed, view = self.render_notification(row, tenant, booking, customer, payload)
        if content is None and embed is None:
            return
        if row["recipient_kind"] == "channel":
            channel_id = row["channel_id"] or row["recipient_id"]
            if not channel_id:
                raise DeliveryBlocked("Notification has no channel.")
            channel = self.get_channel(int(channel_id))
            if channel is None:
                try:
                    channel = await self.fetch_channel(int(channel_id))
                except discord.HTTPException as exc:
                    raise DeliveryBlocked("Notification channel is unavailable.") from exc
            await self.send_long(channel, content or "", embed=embed, view=view)
            return
        try:
            await self.dm_user(row["recipient_id"], content, embed=embed, view=view)
        except (discord.HTTPException, DeliveryBlocked):
            if row["channel_id"]:
                channel = self.get_channel(int(row["channel_id"]))
                if channel is not None:
                    fallback = content or "A front desk update is available."
                    if customer is not None:
                        fallback = f"<@{customer['platform_user_id']}> {fallback}"
                    await self.send_long(channel, fallback)
                    return
            raise

    def render_notification(
        self,
        row: sqlite3.Row,
        tenant: sqlite3.Row,
        booking: sqlite3.Row | None,
        customer: sqlite3.Row | None,
        payload: dict[str, Any],
    ) -> tuple[str | None, discord.Embed | None, discord.ui.View | None]:
        kind = str(row["kind"])
        timezone_name = tenant["timezone"]
        if kind == "broadcast":
            return str(payload.get("message") or ""), None, None
        if booking is None:
            return "A front desk update is available, but the related booking no longer exists.", None, None
        when = format_dt(booking["start_ts"], timezone_name)
        service = booking["service"]
        staff = f"<@{booking['staff_id']}>"
        member = f"<@{customer['platform_user_id']}>" if customer is not None else "the member"
        location = f"\nLocation: {booking['location']}" if booking["location"] else ""
        notes = f"\nNotes: {booking['notes']}" if booking["notes"] else ""
        if kind == "booking_confirmed":
            return (
                f"Your meeting is confirmed: **{service}** with {staff} on {when} ({timezone_name}). "
                f"Booking #{int(booking['id'])}.{location}{notes}",
                None,
                None,
            )
        if kind == "booking_confirmed_staff":
            return (
                f"New meeting booked: **{service}** with {member} on {when} ({timezone_name}). "
                f"Booking #{int(booking['id'])}.{location}{notes}",
                None,
                None,
            )
        if kind in {"booking_reminder", "booking_reminder_staff"}:
            start = parse_iso(booking["start_ts"])
            relative = humanize_delta(start) if start else "soon"
            if kind == "booking_reminder":
                return (
                    f"Reminder: **{service}** with {staff} is {relative} — {when} ({timezone_name}). "
                    f"Booking #{int(booking['id'])}. Use the buttons below to confirm attendance.",
                    None,
                    AttendanceView(self, int(booking["id"])),
                )
            return (
                f"Reminder: **{service}** with {member} is {relative} — {when} ({timezone_name}). "
                f"Booking #{int(booking['id'])}.",
                None,
                None,
            )
        if kind == "booking_cancelled":
            return f"Your meeting **{service}** on {when} was cancelled. Booking #{int(booking['id'])}.", None, None
        if kind == "booking_cancelled_staff":
            return f"{member} cancelled **{service}** on {when}. Booking #{int(booking['id'])}.", None, None
        if kind == "booking_rescheduled":
            return (
                f"Your meeting **{service}** was moved to {when} ({timezone_name}). "
                f"Booking #{int(booking['id'])}.{location}{notes}",
                None,
                None,
            )
        if kind == "booking_rescheduled_staff":
            return f"{member} moved **{service}** to {when}. Booking #{int(booking['id'])}.", None, None
        if kind == "availability_changed":
            slots = self.services.scheduling.alternatives(
                tenant,
                booking["staff_id"],
                after=parse_iso(booking["start_ts"]),
                limit=3,
            )
            alternatives = "\n".join(f"• {slot.label(timezone_name)}" for slot in slots) or "• No alternatives are published right now."
            return (
                f"A maintainer’s availability changed. Your booking **{service}** on {when} is still reserved. "
                f"You can keep it or choose a new time with `/meet reschedule {int(booking['id'])} <date> <time>`.\n"
                f"**Available alternatives**\n{alternatives}",
                None,
                None,
            )
        if kind == "attendance_declined_staff":
            return (
                f"{member} said they can’t attend **{service}** on {when} (booking #{int(booking['id'])}). "
                "The booking is still reserved until they reschedule or cancel.",
                None,
                None,
            )
        return f"Front desk update for booking #{int(booking['id'])}: {kind}.", None, None

    # Command error handling --------------------------------------------------
    async def on_tree_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        self.logger.exception("Command error", exc_info=error)
        message = "Something went wrong while handling that command. Please try again or ask a maintainer."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)
        except discord.HTTPException:
            pass

    async def on_guild_join(self, guild: discord.Guild) -> None:
        try:
            tenant = self.ensure_tenant(guild)
            org = self.org_for(tenant)
        except Exception:
            self.logger.exception("Could not provision joined guild %s", guild.id)
            return
        channel = guild.system_channel
        if channel is None:
            channel = next(
                (item for item in guild.text_channels if item.permissions_for(guild.me).send_messages),
                None,
            )
        if channel is None:
            return
        embed = discord.Embed(
            title=f"{org.display_name} AI Front Desk",
            description=(
                "I answer contributor questions from maintainer-approved information and public project docs, "
                "open pending questions for maintainers, and coordinate meetings.\n\n"
                "**Next step:** an administrator can run `/frontdesk setup` to choose the support channel, "
                "staff channel, and maintainer role. `/help` lists what members can do."
            ),
            color=discord.Color.blurple(),
        )
        try:
            await channel.send(embed=embed)
        except discord.HTTPException:
            pass
