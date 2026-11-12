"""Interactive Discord components."""

from __future__ import annotations

import sqlite3

import discord

from .timeutil import format_dt, parse_iso


class AttendanceView(discord.ui.View):
    def __init__(self, bot: "FrontDeskBot", booking_id: int) -> None:
        super().__init__(timeout=None)
        self.bot = bot
        self.booking_id = booking_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        booking = self.bot.services.db.get_booking(self.booking_id)
        if booking is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return False
        tenant = self.bot.services.db.get_tenant(int(booking["tenant_id"]))
        customer = self.bot.services.db.get_customer(int(booking["customer_id"]))
        if tenant is None or customer is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return False
        is_owner = str(interaction.user.id) == str(customer["platform_user_id"])
        is_staff = isinstance(interaction.user, discord.Member) and self.bot.is_staff(interaction.user, tenant)
        if not (is_owner or is_staff):
            await interaction.response.send_message("Only the person on this booking can confirm attendance.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="I'll attend", style=discord.ButtonStyle.success, custom_id="attendance:yes")
    async def attend(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        booking = self.bot.services.db.get_booking(self.booking_id)
        if booking is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return
        tenant = self.bot.services.db.get_tenant(int(booking["tenant_id"]))
        if tenant is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return
        self.bot.services.scheduling.set_attendance(tenant, booking, "attending", str(interaction.user))
        await interaction.response.send_message("Thanks — your attendance is confirmed.", ephemeral=True)

    @discord.ui.button(label="Can't attend", style=discord.ButtonStyle.danger, custom_id="attendance:no")
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        booking = self.bot.services.db.get_booking(self.booking_id)
        if booking is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return
        tenant = self.bot.services.db.get_tenant(int(booking["tenant_id"]))
        if tenant is None:
            await interaction.response.send_message("That booking no longer exists.", ephemeral=True)
            return
        self.bot.services.scheduling.set_attendance(tenant, booking, "declined", str(interaction.user))
        slots = self.bot.services.scheduling.alternatives(
            tenant,
            booking["staff_id"],
            after=parse_iso(booking["start_ts"]),
            limit=3,
        )
        lines = [
            "I’m sorry you can’t make it. Your booking is still reserved until you change it.",
            f"Use `/meet reschedule {self.booking_id} <date> <time>` to move it, or `/meet cancel {self.booking_id}` to release it.",
        ]
        if slots:
            lines.append("**Next available times**")
            lines.extend(f"• {slot.label(tenant['timezone'])}" for slot in slots)
        else:
            lines.append("No alternative slots are published right now; a maintainer has been notified.")
        await interaction.response.send_message("\n".join(lines), ephemeral=True)


class TenantSelectView(discord.ui.View):
    def __init__(self, bot: "FrontDeskBot", message: discord.Message, tenants: list[sqlite3.Row]) -> None:
        super().__init__(timeout=300)
        self.bot = bot
        self.message = message
        options = [
            discord.SelectOption(
                label=str(row["tenant_name"])[:100],
                value=str(row["tenant_id"]),
                description=f"Ask {row['tenant_name']}",
            )
            for row in tenants[:25]
        ]
        select = discord.ui.Select(placeholder="Which organization is this about?", options=options)
        select.callback = self.select_org
        self.add_item(select)
        self._select = select

    async def select_org(self, interaction: discord.Interaction) -> None:
        if not self._select.values:
            return
        tenant_id = int(self._select.values[0])
        await interaction.response.defer(ephemeral=True)
        try:
            await self.bot.handle_dm_for_tenant(self.message, tenant_id)
        except Exception:
            self.bot.logger.exception("DM tenant selection failed")
            await interaction.followup.send("I couldn’t process that. Please try again.", ephemeral=True)
            return
        await interaction.followup.send("I’ve answered in this conversation.", ephemeral=True)


# Forward declaration for type checkers only; the bot module imports this file.
if False:  # pragma: no cover
    from .bot import FrontDeskBot
