"""Member-facing availability and meeting commands."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..timeutil import format_dt, parse_iso


def _booking_embed(tenant, booking, title: str = "Booking") -> discord.Embed:
    embed = discord.Embed(title=title, color=discord.Color.green())
    embed.add_field(name="Service", value=booking["service"], inline=True)
    embed.add_field(name="When", value=format_dt(booking["start_ts"], tenant["timezone"]), inline=True)
    embed.add_field(name="Maintainer", value=f"<@{booking['staff_id']}>", inline=True)
    if booking["location"]:
        embed.add_field(name="Location", value=booking["location"][:1000], inline=False)
    if booking["notes"]:
        embed.add_field(name="Notes", value=booking["notes"][:1000], inline=False)
    embed.set_footer(text=f"Booking #{booking['id']} · {tenant['timezone']}")
    return embed


class _BookingConfirmView(discord.ui.View):
    def __init__(
        self,
        bot,
        tenant,
        customer,
        staff,
        service: str,
        date_text: str,
        time_text: str,
        location: str,
        notes: str,
        author_id: int,
    ) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.tenant = tenant
        self.customer = customer
        self.staff = staff
        self.service = service
        self.date_text = date_text
        self.time_text = time_text
        self.location = location
        self.notes = notes
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started this booking can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm booking", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        booking, error = self.bot.services.scheduling.create_booking(
            self.tenant,
            self.customer,
            self.staff.id,
            self.service,
            self.date_text,
            self.time_text,
            location=self.location,
            notes=self.notes,
            source_channel_id=interaction.channel_id,
            actor=str(interaction.user),
        )
        if booking is None:
            await interaction.followup.send(error or "That slot is no longer available.", ephemeral=True)
            return
        self.stop()
        await interaction.message.edit(embed=_booking_embed(self.tenant, booking, "Booking confirmed"), view=None)
        await interaction.followup.send(f"Booked. Your booking number is **#{booking['id']}**.", ephemeral=True)

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="Booking cancelled.", embed=None, view=None)


class _CancelConfirmView(discord.ui.View):
    def __init__(self, bot, tenant, booking, author_id: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.tenant = tenant
        self.booking = booking
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started this cancellation can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm cancellation", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.bot.services.scheduling.cancel_booking(self.tenant, self.booking, str(interaction.user))
        self.stop()
        await interaction.response.edit_message(
            content=f"Booking #{self.booking['id']} cancelled.",
            embed=None,
            view=None,
        )

    @discord.ui.button(label="Keep booking", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="No changes made.", embed=None, view=None)


class _RescheduleConfirmView(discord.ui.View):
    def __init__(self, bot, tenant, booking, date_text: str, time_text: str, author_id: int) -> None:
        super().__init__(timeout=180)
        self.bot = bot
        self.tenant = tenant
        self.booking = booking
        self.date_text = date_text
        self.time_text = time_text
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Only the person who started this change can confirm it.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Confirm new time", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.defer(ephemeral=True)
        updated, error = self.bot.services.scheduling.reschedule_booking(
            self.tenant,
            self.booking,
            self.date_text,
            self.time_text,
            actor=str(interaction.user),
        )
        if updated is None:
            await interaction.followup.send(error or "That slot is no longer available.", ephemeral=True)
            return
        self.stop()
        await interaction.message.edit(embed=_booking_embed(self.tenant, updated, "Booking moved"), view=None)
        await interaction.followup.send(f"Booking #{updated['id']} moved.", ephemeral=True)

    @discord.ui.button(label="Keep current time", style=discord.ButtonStyle.secondary)
    async def keep(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(content="No changes made.", embed=None, view=None)


class MeetingCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    group = app_commands.Group(name="meet", description="Check availability and manage meetings")

    async def _booking_for_user(self, tenant, booking_id: int, user: discord.Member):
        booking = self.bot.services.db.get_booking(booking_id)
        if booking is None or int(booking["tenant_id"]) != int(tenant["id"]):
            return None
        customer = self.bot.services.db.get_customer(int(booking["customer_id"]))
        if customer is None:
            return None
        if str(user.id) != str(customer["platform_user_id"]) and not self.bot.is_staff(user, tenant):
            return None
        return booking

    @group.command(name="availability", description="Show published meeting slots")
    @app_commands.describe(member="Maintainer to check (default: everyone)", days="How many days ahead", limit="How many slots")
    async def availability(
        self,
        interaction: discord.Interaction,
        member: discord.Member | None = None,
        days: int = 14,
        limit: int = 10,
    ) -> None:
        guard = await self.bot.guard_customer(interaction)
        if guard is None:
            return
        tenant, _ = guard
        limit = max(1, min(limit, 20))
        staff_ids = [member.id] if member is not None else self.bot.services.scheduling.staff_with_availability(int(tenant["id"]))
        if not staff_ids:
            await interaction.response.send_message("No maintainer has published availability yet.", ephemeral=True)
            return
        slots = []
        for staff_id in staff_ids[:10]:
            slots.extend(
                self.bot.services.scheduling.generate_slots(
                    tenant,
                    staff_id,
                    days=max(1, min(days, 60)),
                    limit=limit,
                )
            )
        slots.sort(key=lambda slot: slot.start_utc)
        if not slots:
            await interaction.response.send_message("No free slots in that range.", ephemeral=True)
            return
        lines = [f"• {slot.label(tenant['timezone'])} with <@{slot.staff_id}>" for slot in slots[:limit]]
        embed = discord.Embed(
            title="Available meeting slots",
            description="\n".join(lines),
            color=discord.Color.blurple(),
        )
        embed.set_footer(text="Book with /meet book member:@maintainer date:YYYY-MM-DD time:HH:MM")
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="book", description="Request a meeting with a maintainer")
    @app_commands.describe(
        member="Maintainer to meet",
        date="Date in YYYY-MM-DD",
        time="Start time in the server timezone, HH:MM",
        service="What the meeting is about",
        location="Optional location or meeting link",
        notes="Optional context for the maintainer",
    )
    async def book(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        date: str,
        time: str,
        service: str = "Meeting",
        location: str = "",
        notes: str = "",
    ) -> None:
        guard = await self.bot.guard_customer(interaction)
        if guard is None:
            return
        tenant, user = guard
        if not self.bot.is_staff(member, tenant):
            await interaction.response.send_message("Choose a maintainer with published availability.", ephemeral=True)
            return
        validation = self.bot.services.scheduling.validate_slot(tenant, member.id, date, time)
        if validation.slot is None:
            await interaction.response.send_message(validation.error, ephemeral=True)
            return
        customer = self.bot.resolve_customer(tenant, user)
        slot = validation.slot
        embed = discord.Embed(title="Confirm meeting", color=discord.Color.blurple())
        embed.add_field(name="Service", value=service[:1000], inline=True)
        embed.add_field(name="When", value=slot.label(tenant["timezone"]), inline=True)
        embed.add_field(name="Maintainer", value=member.mention, inline=True)
        if location:
            embed.add_field(name="Location", value=location[:1000], inline=False)
        if notes:
            embed.add_field(name="Notes", value=notes[:1000], inline=False)
        embed.set_footer(text="The slot is only held after you press Confirm booking.")
        view = _BookingConfirmView(
            self.bot,
            tenant,
            customer,
            member,
            service,
            date,
            time,
            location,
            notes,
            interaction.user.id,
        )
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @group.command(name="list", description="Show your upcoming meetings")
    async def list_bookings(self, interaction: discord.Interaction) -> None:
        guard = await self.bot.guard_customer(interaction)
        if guard is None:
            return
        tenant, user = guard
        customer = self.bot.resolve_customer(tenant, user)
        rows = self.bot.services.db.list_customer_bookings(int(tenant["id"]), int(customer["id"]))
        if not rows:
            await interaction.response.send_message("You have no upcoming meetings.", ephemeral=True)
            return
        lines = [
            f"`#{row['id']}` {format_dt(row['start_ts'], tenant['timezone'])} · "
            f"**{row['service']}** · <@{row['staff_id']}> · {row['status']}"
            for row in rows
        ]
        embed = discord.Embed(
            title="Your upcoming meetings",
            description="\n".join(lines)[:4000],
            color=discord.Color.blurple(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="cancel", description="Cancel one of your meetings")
    async def cancel(self, interaction: discord.Interaction, booking_id: int) -> None:
        guard = await self.bot.guard_customer(interaction)
        if guard is None:
            return
        tenant, user = guard
        booking = await self._booking_for_user(tenant, booking_id, user)
        if booking is None:
            await interaction.response.send_message("Booking not found.", ephemeral=True)
            return
        embed = _booking_embed(tenant, booking, "Cancel this booking?")
        view = _CancelConfirmView(self.bot, tenant, booking, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @group.command(name="reschedule", description="Move one of your meetings")
    @app_commands.describe(booking_id="Booking number", date="New date in YYYY-MM-DD", time="New start time HH:MM")
    async def reschedule(
        self,
        interaction: discord.Interaction,
        booking_id: int,
        date: str,
        time: str,
    ) -> None:
        guard = await self.bot.guard_customer(interaction)
        if guard is None:
            return
        tenant, user = guard
        booking = await self._booking_for_user(tenant, booking_id, user)
        if booking is None:
            await interaction.response.send_message("Booking not found.", ephemeral=True)
            return
        validation = self.bot.services.scheduling.validate_slot(tenant, booking["staff_id"], date, time)
        if validation.slot is None:
            await interaction.response.send_message(validation.error, ephemeral=True)
            return
        embed = _booking_embed(tenant, booking, "Confirm new time")
        embed.add_field(name="New time", value=validation.slot.label(tenant["timezone"]), inline=False)
        embed.set_footer(text="Your current booking stays in place until you confirm.")
        view = _RescheduleConfirmView(self.bot, tenant, booking, date, time, interaction.user.id)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
