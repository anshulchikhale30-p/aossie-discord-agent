"""Server configuration for the front desk."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..permissions import channel_ids, is_guild_admin
from ..timeutil import valid_timezone


async def org_autocomplete(
    interaction: discord.Interaction,
    current: str,
) -> list[app_commands.Choice[str]]:
    catalog = interaction.client.services.catalog
    return [
        app_commands.Choice(name=display, value=key)
        for key, display in catalog.choices()
        if current.casefold() in display.casefold() or current.casefold() in key
    ][:25]


class SetupCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    group = app_commands.Group(name="frontdesk", description="Configure the AI front desk")

    @group.command(name="setup", description="Bind this server to an organization and its channels")
    @app_commands.describe(
        org="Organization this server belongs to",
        support_channel="Channel where members ask questions (repeat to add more)",
        staff_channel="Private channel for pending questions and staff notices",
        staff_role="Role that can use maintainer commands (repeat to add more)",
        timezone="IANA timezone, e.g. Australia/Melbourne or UTC",
        replace="Replace the existing channel/role lists instead of adding to them",
    )
    @app_commands.autocomplete(org=org_autocomplete)
    async def setup(
        self,
        interaction: discord.Interaction,
        org: str,
        support_channel: discord.TextChannel | None = None,
        staff_channel: discord.TextChannel | None = None,
        staff_role: discord.Role | None = None,
        timezone: str | None = None,
        replace: bool = False,
    ) -> None:
        guard = await self.bot.guard_admin(interaction)
        if guard is None:
            return
        tenant, _ = guard
        org_key = org.strip().casefold()
        if org_key not in self.bot.services.catalog.orgs:
            names = ", ".join(f"`{key}` ({display})" for key, display in self.bot.services.catalog.choices())
            await interaction.response.send_message(f"Unknown organization. Choose one of: {names}", ephemeral=True)
            return
        if timezone is not None and not valid_timezone(timezone):
            await interaction.response.send_message("That timezone is not recognized. Use an IANA name such as `UTC`.", ephemeral=True)
            return

        org_def = self.bot.services.catalog.get(org_key)
        support_ids = channel_ids(tenant["support_channel_ids"])
        role_ids = {int(value) for value in channel_ids(tenant["staff_role_ids"])}
        if replace:
            support_ids = set()
            role_ids = set()
        if support_channel is not None:
            support_ids.add(support_channel.id)
        if staff_role is not None:
            role_ids.add(staff_role.id)

        updated = self.bot.services.db.update_tenant(
            int(tenant["id"]),
            org_key=org_key,
            display_name=org_def.display_name,
            timezone=timezone or org_def.timezone,
            support_channel_ids=sorted(support_ids),
            staff_role_ids=sorted(role_ids),
            staff_channel_id=staff_channel.id if staff_channel is not None else tenant["staff_channel_id"],
        )
        self.bot.services.db.audit(
            int(tenant["id"]),
            str(interaction.user),
            "tenant_configured",
            {
                "org": org_key,
                "support_channels": sorted(support_ids),
                "staff_channel": updated["staff_channel_id"],
                "staff_roles": sorted(role_ids),
                "timezone": updated["timezone"],
            },
        )
        staff_channel_text = (
            f"<#{updated['staff_channel_id']}>" if updated["staff_channel_id"] else "not set"
        )
        await interaction.response.send_message(
            f"Configured this server for **{org_def.display_name}**.\n"
            f"Timezone: `{updated['timezone']}`\n"
            f"Support channels: {', '.join(f'<#{value}>' for value in support_ids) or 'name-based fallback'}\n"
            f"Staff channel: {staff_channel_text}\n"
            f"Staff roles: {', '.join(f'<@&{value}>' for value in role_ids) or 'administrators only'}",
            ephemeral=True,
        )

    @group.command(name="status", description="Show this server's front desk configuration")
    async def status(self, interaction: discord.Interaction) -> None:
        guard = await self.bot.guard_admin(interaction)
        if guard is None:
            return
        tenant, _ = guard
        counts = self.bot.services.db.tenant_counts(int(tenant["id"]))
        support_ids = channel_ids(tenant["support_channel_ids"])
        role_ids = channel_ids(tenant["staff_role_ids"])
        embed = discord.Embed(title="Front desk status", color=discord.Color.blurple())
        embed.add_field(name="Organization", value=tenant["display_name"], inline=True)
        embed.add_field(name="Timezone", value=tenant["timezone"], inline=True)
        embed.add_field(name="Open pending", value=str(counts["open_pending"]), inline=True)
        embed.add_field(
            name="Support channels",
            value=", ".join(f"<#{value}>" for value in support_ids) or "name-based fallback",
            inline=False,
        )
        embed.add_field(
            name="Staff channel",
            value=f"<#{tenant['staff_channel_id']}>" if tenant["staff_channel_id"] else "not set",
            inline=True,
        )
        embed.add_field(
            name="Staff roles",
            value=", ".join(f"<@&{value}>" for value in role_ids) or "administrators only",
            inline=False,
        )
        embed.add_field(
            name="Stored records",
            value=(
                f"{counts['knowledge']} knowledge · {counts['pending_questions']} pending · "
                f"{counts['bookings']} bookings · {counts['spam']} blocked"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="autosetup", description="Detect support/staff channels and maintainer roles by name")
    async def autosetup(self, interaction: discord.Interaction) -> None:
        guard = await self.bot.guard_admin(interaction)
        if guard is None:
            return
        tenant, _ = guard
        guild = interaction.guild
        assert guild is not None
        support_ids = [
            channel.id
            for channel in guild.text_channels
            if any(word.casefold() in channel.name.casefold() for word in self.bot.settings.support_channel_words)
        ]
        staff_channel = next(
            (
                channel
                for channel in guild.text_channels
                if any(word.casefold() in channel.name.casefold() for word in self.bot.settings.staff_channel_words)
            ),
            None,
        )
        role_ids = [
            role.id
            for role in guild.roles
            if role.name.casefold() in {name.casefold() for name in self.bot.settings.staff_role_names}
        ]
        self.bot.services.db.update_tenant(
            int(tenant["id"]),
            support_channel_ids=support_ids,
            staff_channel_id=staff_channel.id if staff_channel else None,
            staff_role_ids=role_ids,
        )
        await interaction.response.send_message(
            f"Detected {len(support_ids)} support channel(s), "
            f"{len(role_ids)} maintainer role(s), and "
            f"{'a staff channel' if staff_channel else 'no staff channel'}. "
            "Use `/frontdesk status` to review.",
            ephemeral=True,
        )


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
