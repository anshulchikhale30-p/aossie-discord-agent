"""Maintainer scheduling, availability, and spam tools."""

from __future__ import annotations

from datetime import timedelta

import discord
from discord import app_commands
from discord.ext import commands

from ..timeutil import format_dt, iso, now_iso, utc_now

WEEKDAYS = [
    app_commands.Choice(name="Monday", value=0),
    app_commands.Choice(name="Tuesday", value=1),
    app_commands.Choice(name="Wednesday", value=2),
    app_commands.Choice(name="Thursday", value=3),
    app_commands.Choice(name="Friday", value=4),
    app_commands.Choice(name="Saturday", value=5),
    app_commands.Choice(name="Sunday", value=6),
]


class StaffCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    group = app_commands.Group(name="staff", description="Maintainer scheduling and safety tools")

    @group.command(name="availability-add", description="Publish a weekly availability window")
    @app_commands.describe(
        weekday="Day of the week",
        start="Start time in the server timezone, HH:MM",
        end="End time in the server timezone, HH:MM",
        slot="Meeting length in minutes",
        member="Maintainer whose availability this is (default: you)",
    )
    @app_commands.choices(weekday=WEEKDAYS)
    async def availability_add(
        self,
        interaction: discord.Interaction,
        weekday: app_commands.Choice[int],
        start: str,
        end: str,
        slot: int = 30,
        member: discord.Member | None = None,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, staff = guard
        target = member or staff
        if not self.bot.is_staff(target, tenant):
            await interaction.response.send_message("Availability can only be published for a maintainer.", ephemeral=True)
            return
        error = self.bot.services.scheduling.validate_availability(weekday.value, start, end, slot)
        if error:
            await interaction.response.send_message(error, ephemeral=True)
            return
        row = self.bot.services.db.add_availability(
            int(tenant["id"]),
            target.id,
            weekday.value,
            start,
            end,
            slot,
            tenant["timezone"],
        )
        self.bot.services.db.audit(
            int(tenant["id"]),
            str(staff),
            "availability_added",
            {"availability_id": int(row["id"]), "staff_id": target.id, "weekday": weekday.value},
        )
        await interaction.response.send_message(
            f"Availability #{int(row['id'])} added for {target.mention}: "
            f"{weekday.name} {start}–{end} ({slot}-minute slots, `{tenant['timezone']}`).",
            ephemeral=True,
        )

    @group.command(name="availability-list", description="Show published availability")
    async def availability_list(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        rows = self.bot.services.db.list_availability(
            int(tenant["id"]),
            staff_id=member.id if member else None,
        )
        if not rows:
            await interaction.response.send_message("No availability is published.", ephemeral=True)
            return
        lines = [
            f"`#{row['id']}` <@{row['staff_id']}> · {WEEKDAYS[int(row['weekday'])].name} "
            f"{row['start_time']}–{row['end_time']} · {row['slot_minutes']} min"
            for row in rows
        ]
        embed = discord.Embed(
            title="Published availability",
            description="\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        embed.set_footer(text=f"Timezone: {tenant['timezone']}")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="availability-remove", description="Remove an availability window")
    async def availability_remove(self, interaction: discord.Interaction, availability_id: int) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, staff = guard
        removed, affected = self.bot.services.scheduling.remove_availability(
            tenant,
            availability_id,
            str(staff),
        )
        if not removed:
            await interaction.response.send_message("Availability window not found.", ephemeral=True)
            return
        if affected:
            lines = [
                f"`#{row['id']}` <@{row['customer_id']}> · {format_dt(row['start_ts'], tenant['timezone'])}"
                for row in affected[:10]
            ]
            await self.bot.notify_staff(
                tenant,
                interaction.guild,
                content=(
                    f"Availability #{availability_id} was removed. {len(affected)} existing booking(s) "
                    "no longer fit the published windows. The bookings were kept and each member was "
                    "notified with alternatives.\n" + "\n".join(lines)
                ),
            )
        await interaction.response.send_message(
            f"Availability #{availability_id} removed. "
            f"{len(affected)} existing booking(s) were kept and their members were notified."
            if affected
            else f"Availability #{availability_id} removed. No existing bookings were affected.",
            ephemeral=True,
        )

    @group.command(name="schedule", description="Show upcoming bookings")
    @app_commands.describe(days="How many days ahead to show", member="Filter to one maintainer")
    async def schedule(
        self,
        interaction: discord.Interaction,
        days: int = 14,
        member: discord.Member | None = None,
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        start = now_iso()
        end = iso(utc_now() + timedelta(days=max(1, min(days, 90))))
        rows = self.bot.services.db.bookings_in_range(
            int(tenant["id"]),
            start,
            end,
            staff_id=member.id if member else None,
        )
        if not rows:
            await interaction.response.send_message("No upcoming bookings in that range.", ephemeral=True)
            return
        lines = []
        for row in rows[:25]:
            customer = self.bot.services.db.get_customer(int(row["customer_id"]))
            who = f"<@{customer['platform_user_id']}>" if customer else "unknown member"
            lines.append(
                f"`#{row['id']}` {format_dt(row['start_ts'], tenant['timezone'])} · "
                f"**{row['service']}** · {who} · <@{row['staff_id']}>"
            )
        embed = discord.Embed(
            title=f"Upcoming bookings ({len(rows)})",
            description="\n".join(lines)[:4000],
            color=discord.Color.green(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="spam-add", description="Stop processing a member's messages")
    @app_commands.describe(member="Member to block", reason="Why this member is blocked")
    async def spam_add(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        reason: str = "",
    ) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, staff = guard
        if member.id == staff.id or self.bot.is_staff(member, tenant):
            await interaction.response.send_message("Maintainers cannot be added to the spam list.", ephemeral=True)
            return
        self.bot.services.db.add_spam(int(tenant["id"]), member.id, reason, str(staff))
        self.bot.services.db.audit(
            int(tenant["id"]),
            str(staff),
            "spam_added",
            {"member_id": member.id, "reason": reason},
        )
        await interaction.response.send_message(
            f"{member.mention} is blocked from normal requests. Existing bookings and records were kept.",
            ephemeral=True,
        )

    @group.command(name="spam-remove", description="Allow a blocked member to use the front desk again")
    async def spam_remove(self, interaction: discord.Interaction, member: discord.Member) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, staff = guard
        if self.bot.services.db.remove_spam(int(tenant["id"]), member.id):
            self.bot.services.db.audit(
                int(tenant["id"]),
                str(staff),
                "spam_removed",
                {"member_id": member.id},
            )
            await interaction.response.send_message(f"{member.mention} can use the front desk again.", ephemeral=True)
        else:
            await interaction.response.send_message("That member is not on the spam list.", ephemeral=True)

    @group.command(name="spam-list", description="Show blocked members")
    async def spam_list(self, interaction: discord.Interaction) -> None:
        guard = await self.bot.guard_staff(interaction)
        if guard is None:
            return
        tenant, _ = guard
        rows = self.bot.services.db.list_spam(int(tenant["id"]))
        if not rows:
            await interaction.response.send_message("The spam list is empty.", ephemeral=True)
            return
        lines = [f"<@{row['platform_user_id']}> · {row['reason'] or 'no reason recorded'}" for row in rows]
        embed = discord.Embed(
            title="Blocked members",
            description="\n".join(lines)[:4000],
            color=discord.Color.dark_red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
