"""Pending-question queue for maintainers."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..permissions import channel_link
from ..timeutil import format_dt, humanize_delta, parse_iso


class PendingCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    group = app_commands.Group(name="pending", description="Review questions waiting for a maintainer")

    @group.command(name="list", description="List pending questions")
    @app_commands.describe(status="Open, resolved, or dismissed", limit="How many to show")
    @app_commands.choices(
        status=[
            app_commands.Choice(name="Open", value="open"),
            app_commands.Choice(name="Resolved", value="resolved"),
            app_commands.Choice(name="Dismissed", value="dismissed"),
        ]
    )
    async def list_questions(
        self,
        interaction: discord.Interaction,
        status: app_commands.Choice[str] | None = None,
        limit: int = 15,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        rows = self.bot.services.db.list_pending(
            int(tenant["id"]),
            status=status.value if status else "open",
            limit=max(1, min(limit, 25)),
        )
        if not rows:
            await interaction.response.send_message("No pending questions match that filter.", ephemeral=True)
            return
        lines = []
        for row in rows:
            customer = self.bot.services.db.get_customer(int(row["customer_id"])) if row["customer_id"] else None
            who = f"<@{customer['platform_user_id']}>" if customer else "unknown member"
            age = humanize_delta(parse_iso(row["created_at"])) if parse_iso(row["created_at"]) else ""
            lines.append(
                f"`#{row['id']}` **{row['priority']}** · {who} · {age}\n"
                f"> {row['question'][:220]}"
            )
        embed = discord.Embed(
            title="Pending questions",
            description="\n\n".join(lines)[:4000],
            color=discord.Color.orange(),
        )
        embed.set_footer(text="Use /pending show <id> or reply to the escalation message in the staff channel.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="show", description="Show one pending question and its context")
    async def show(self, interaction: discord.Interaction, pending_id: int) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        row = self.bot.services.db.get_pending(pending_id)
        if row is None or int(row["tenant_id"]) != int(tenant["id"]):
            await interaction.response.send_message("Pending question not found.", ephemeral=True)
            return
        customer = self.bot.services.db.get_customer(int(row["customer_id"])) if row["customer_id"] else None
        conversation = self.bot.services.db.get_conversation(int(row["conversation_id"])) if row["conversation_id"] else None
        embed = discord.Embed(
            title=f"Pending #{row['id']} · {row['priority']} · {row['status']}",
            description=row["question"][:4000],
            color=discord.Color.orange() if row["status"] == "open" else discord.Color.dark_gray(),
        )
        if customer:
            embed.add_field(name="Member", value=f"<@{customer['platform_user_id']}> ({customer['username']})", inline=True)
        embed.add_field(name="Opened", value=format_dt(row["created_at"], tenant["timezone"]), inline=True)
        if conversation:
            link = channel_link(tenant["guild_id"], conversation["thread_id"] or conversation["channel_id"])
            if link:
                embed.add_field(name="Conversation", value=f"[Open]({link})", inline=False)
        if row["answer_given"]:
            embed.add_field(name="What the bot said", value=row["answer_given"][:1000], inline=False)
        if row["clarification"]:
            embed.add_field(name="Member clarification", value=row["clarification"][:1000], inline=False)
        if row["summary"]:
            embed.add_field(name="Context", value=row["summary"][:1000], inline=False)
        if row["resolution"]:
            embed.add_field(name="Resolution", value=row["resolution"][:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="answer", description="Answer a pending question and send it to the member")
    @app_commands.describe(
        pending_id="Pending question number",
        text="The answer to send",
        scope="Keep this answer with the member, or make it organization-wide knowledge",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="This member only (default)", value="customer"),
            app_commands.Choice(name="Organization-wide knowledge", value="organization"),
        ]
    )
    async def answer(
        self,
        interaction: discord.Interaction,
        pending_id: int,
        text: str,
        scope: app_commands.Choice[str] | None = None,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, member = guard
        row = self.bot.services.db.get_pending(pending_id)
        if row is None or int(row["tenant_id"]) != int(tenant["id"]):
            await interaction.response.send_message("Pending question not found.", ephemeral=True)
            return
        if row["status"] != "open":
            await interaction.response.send_message("That question is no longer open.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        resolution = await self.bot.resolve_pending(
            tenant,
            row,
            text,
            scope=scope.value if scope else "customer",
            actor=str(member),
        )
        await interaction.followup.send(resolution.summary, ephemeral=True)

    @group.command(name="dismiss", description="Close a pending question without sending an answer")
    async def dismiss(
        self,
        interaction: discord.Interaction,
        pending_id: int,
        reason: str = "Dismissed by a maintainer",
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, member = guard
        row = self.bot.services.db.get_pending(pending_id)
        if row is None or int(row["tenant_id"]) != int(tenant["id"]):
            await interaction.response.send_message("Pending question not found.", ephemeral=True)
            return
        if self.bot.services.db.dismiss_pending(pending_id, reason, str(member)):
            self.bot.services.db.audit(
                int(tenant["id"]),
                str(member),
                "pending_dismissed",
                {"pending_id": pending_id, "reason": reason},
            )
            await interaction.response.send_message(f"Pending #{pending_id} dismissed.", ephemeral=True)
        else:
            await interaction.response.send_message("That question is no longer open.", ephemeral=True)


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
