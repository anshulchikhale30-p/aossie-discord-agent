"""Maintainer-entered operational knowledge."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..timeutil import format_dt, parse_effective, parse_expiry


class KnowledgeCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    group = app_commands.Group(name="knowledge", description="Manage maintainer-approved information")

    @group.command(name="add", description="Add plain-text operational knowledge")
    @app_commands.describe(
        scope="Organization-wide or one member only",
        title="Short label shown as the source",
        text="Plain text only; no file uploads",
        customer="Required when scope is customer",
        tags="Comma-separated search terms",
        source="Optional URL or note describing where this came from",
        expires="Optional expiry: YYYY-MM-DD, 7d, 2w, or an ISO timestamp",
        effective="Optional start: YYYY-MM-DD or an ISO timestamp",
    )
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="Organization-wide", value="organization"),
            app_commands.Choice(name="One member", value="customer"),
        ]
    )
    async def add(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str],
        title: str,
        text: str,
        customer: discord.Member | None = None,
        tags: str = "",
        source: str = "",
        expires: str = "",
        effective: str = "",
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, member = guard
        if scope.value == "customer" and customer is None:
            await interaction.response.send_message("Choose a member for customer-specific knowledge.", ephemeral=True)
            return
        customer_row = None
        if scope.value == "customer" and customer is not None:
            customer_row = self.bot.resolve_customer(tenant, customer)
        try:
            effective_at = parse_effective(effective, tenant["timezone"])
            expires_at = parse_expiry(expires, tenant["timezone"])
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return
        row = self.bot.services.knowledge.add(
            int(tenant["id"]),
            scope="customer" if scope.value == "customer" else "org",
            title=title,
            content=text,
            actor=str(member),
            customer_id=int(customer_row["id"]) if customer_row else None,
            tags=tags,
            source=source,
            effective_at=effective_at,
            expires_at=expires_at,
        )
        embed = discord.Embed(title=f"Knowledge #{int(row['id'])} added", color=discord.Color.green())
        embed.add_field(name="Scope", value="Organization-wide" if scope.value == "organization" else f"<@{customer.id}>", inline=True)
        embed.add_field(name="Title", value=row["title"][:1000], inline=False)
        if expires_at:
            embed.add_field(name="Expires", value=format_dt(expires_at, tenant["timezone"]), inline=True)
        embed.set_footer(text="Adding knowledge does not broadcast it to members.")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="list", description="List current knowledge entries")
    @app_commands.describe(scope="Filter by scope", limit="How many entries to show")
    @app_commands.choices(
        scope=[
            app_commands.Choice(name="All", value="all"),
            app_commands.Choice(name="Organization-wide", value="org"),
            app_commands.Choice(name="Customer-specific", value="customer"),
        ]
    )
    async def list_entries(
        self,
        interaction: discord.Interaction,
        scope: app_commands.Choice[str] | None = None,
        limit: int = 10,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        scope_value = scope.value if scope and scope.value != "all" else None
        rows = self.bot.services.knowledge.list(
            int(tenant["id"]),
            scope=scope_value,
            limit=max(1, min(limit, 25)),
        )
        if not rows:
            await interaction.response.send_message("No current knowledge entries match that filter.", ephemeral=True)
            return
        lines = []
        for row in rows:
            expiry = f" · expires {format_dt(row['expires_at'], tenant['timezone'])}" if row["expires_at"] else ""
            target = ""
            if row["scope"] == "customer" and row["customer_id"]:
                customer = self.bot.services.db.get_customer(int(row["customer_id"]))
                if customer is not None:
                    target = f" · <@{customer['platform_user_id']}>"
            lines.append(f"`#{row['id']}` **{row['title']}** — {row['scope']}{target}{expiry}")
        embed = discord.Embed(title="Current knowledge", description="\n".join(lines)[:4000], color=discord.Color.blurple())
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="show", description="Show one knowledge entry")
    async def show(self, interaction: discord.Interaction, knowledge_id: int) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        row = self.bot.services.db.get_knowledge(knowledge_id)
        if row is None or int(row["tenant_id"]) != int(tenant["id"]):
            await interaction.response.send_message("Knowledge entry not found.", ephemeral=True)
            return
        embed = discord.Embed(title=f"Knowledge #{row['id']} · {row['title']}", description=row["content"][:4000], color=discord.Color.blurple())
        embed.add_field(name="Scope", value=row["scope"], inline=True)
        embed.add_field(name="Status", value=row["status"], inline=True)
        if row["expires_at"]:
            embed.add_field(name="Expires", value=format_dt(row["expires_at"], tenant["timezone"]), inline=True)
        if row["tags"]:
            embed.add_field(name="Tags", value=row["tags"][:1000], inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="cancel", description="Cancel an outdated knowledge entry")
    async def cancel(self, interaction: discord.Interaction, knowledge_id: int) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, member = guard
        if self.bot.services.knowledge.cancel(int(tenant["id"]), knowledge_id, str(member)):
            await interaction.response.send_message(f"Knowledge #{knowledge_id} is cancelled and will no longer be used.", ephemeral=True)
        else:
            await interaction.response.send_message("Knowledge entry not found.", ephemeral=True)


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
