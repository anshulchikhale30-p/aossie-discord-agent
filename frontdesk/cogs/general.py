"""Member-facing commands and help."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from ..permissions import is_support_channel
from ..text import looks_urgent
from ..timeutil import now_iso


class GeneralCog(commands.Cog):
    def __init__(self, bot: "FrontDeskBot") -> None:
        self.bot = bot

    @app_commands.command(name="ask", description="Ask the organization front desk a question")
    @app_commands.describe(question="What would you like to know?")
    async def ask(self, interaction: discord.Interaction, question: str) -> None:
        if not self.bot.demo_allowed(interaction.user):
            await interaction.response.send_message(
                "This demonstration instance is limited to authorized accounts.",
                ephemeral=True,
            )
            return
        question = question.strip()
        if not question:
            await interaction.response.send_message("Please include a question.", ephemeral=True)
            return

        if interaction.guild is None:
            await self._ask_dm(interaction, question)
            return

        tenant = self.bot.ensure_tenant(interaction.guild)
        if self.bot.services.db.is_spam(int(tenant["id"]), interaction.user.id):
            await interaction.response.send_message("I can’t process that request.", ephemeral=True)
            return
        customer = self.bot.resolve_customer(tenant, interaction.user)
        conversation = self.bot.services.db.get_conversation_by_thread(interaction.channel_id)
        target: discord.abc.Messageable = interaction.channel
        thread = None
        if conversation is None:
            if isinstance(interaction.channel, discord.TextChannel):
                try:
                    thread = await interaction.channel.create_thread(
                        name=f"Front desk · {question[:80]}",
                        type=discord.ChannelType.public_thread,
                        auto_archive_duration=1440,
                    )
                except discord.HTTPException:
                    thread = None
            target = thread or interaction.channel
            conversation = self.bot.services.db.create_conversation(
                int(tenant["id"]),
                int(customer["id"]),
                interaction.channel_id,
                thread_id=thread.id if thread else None,
                parent_channel_id=interaction.channel_id if thread else None,
            )
        await interaction.response.defer(thinking=True)
        await self.bot.process_question(
            tenant,
            customer,
            conversation,
            question,
            target,
            interaction.user.id,
            str(interaction.user),
        )
        if thread is not None:
            await interaction.followup.send(f"Answered in {thread.mention}.", ephemeral=True)
        else:
            await interaction.followup.send("Answered above.", ephemeral=True)

    async def _ask_dm(self, interaction: discord.Interaction, question: str) -> None:
        tenants = self.bot.services.db.customer_tenants(interaction.user.id)
        if not tenants:
            await interaction.response.send_message(
                "I don’t have a verified organization for you yet. Please message me in the "
                "AOSSIE or Stability Nexus Discord server first, then I can continue here.",
                ephemeral=True,
            )
            return
        if len(tenants) > 1:
            names = ", ".join(str(row["tenant_name"]) for row in tenants)
            await interaction.response.send_message(
                f"You’re linked to more than one organization ({names}). Please use `/ask` in the "
                "server for the organization you mean, or send a normal DM and choose from the list.",
                ephemeral=True,
            )
            return
        tenant = self.bot.services.db.get_tenant(int(tenants[0]["tenant_id"]))
        if tenant is None:
            await interaction.response.send_message("That organization is no longer configured.", ephemeral=True)
            return
        if self.bot.services.db.is_spam(int(tenant["id"]), interaction.user.id):
            await interaction.response.send_message("I can’t process that request.", ephemeral=True)
            return
        customer = self.bot.resolve_customer(tenant, interaction.user)
        conversation = self.bot.services.db.get_dm_conversation(
            int(tenant["id"]),
            int(customer["id"]),
            interaction.channel_id,
        )
        if conversation is None:
            conversation = self.bot.services.db.create_conversation(
                int(tenant["id"]),
                int(customer["id"]),
                interaction.channel_id,
            )
        await interaction.response.defer(thinking=True)
        await self.bot.process_question(
            tenant,
            customer,
            conversation,
            question,
            interaction.channel,
            interaction.user.id,
            str(interaction.user),
        )
        await interaction.followup.send("Answered above.", ephemeral=True)

    @app_commands.command(name="human", description="Ask a maintainer to follow up on a question or issue")
    @app_commands.describe(reason="What do you need a maintainer to look at?")
    async def human(self, interaction: discord.Interaction, reason: str) -> None:
        if not self.bot.demo_allowed(interaction.user):
            await interaction.response.send_message(
                "This demonstration instance is limited to authorized accounts.",
                ephemeral=True,
            )
            return
        reason = reason.strip()
        if not reason:
            await interaction.response.send_message("Please describe what you need help with.", ephemeral=True)
            return
        tenant = None
        customer = None
        conversation = None
        if interaction.guild is not None:
            tenant = self.bot.ensure_tenant(interaction.guild)
            customer = self.bot.resolve_customer(tenant, interaction.user)
            conversation = self.bot.services.db.get_conversation_by_thread(interaction.channel_id)
            if conversation is None:
                conversation = self.bot.services.db.create_conversation(
                    int(tenant["id"]),
                    int(customer["id"]),
                    interaction.channel_id,
                )
        else:
            tenants = self.bot.services.db.customer_tenants(interaction.user.id)
            if len(tenants) == 1:
                tenant = self.bot.services.db.get_tenant(int(tenants[0]["tenant_id"]))
                if tenant is not None:
                    customer = self.bot.resolve_customer(tenant, interaction.user)
                    conversation = self.bot.services.db.get_dm_conversation(
                        int(tenant["id"]),
                        int(customer["id"]),
                        interaction.channel_id,
                    )
                    if conversation is None:
                        conversation = self.bot.services.db.create_conversation(
                            int(tenant["id"]),
                            int(customer["id"]),
                            interaction.channel_id,
                        )
        if tenant is None or customer is None or conversation is None:
            await interaction.response.send_message(
                "Please use `/human` in the organization server so I know who should follow up.",
                ephemeral=True,
            )
            return
        if self.bot.services.db.is_spam(int(tenant["id"]), interaction.user.id):
            await interaction.response.send_message("I can’t process that request.", ephemeral=True)
            return
        priority = "urgent" if looks_urgent(reason) else "high"
        history = self.bot.services.db.recent_messages(int(conversation["id"]), 10)
        summary = self.bot.services.agent.summarize(history, reason)
        pending = self.bot.services.db.create_pending(
            int(tenant["id"]),
            question=reason,
            customer_id=int(customer["id"]),
            conversation_id=int(conversation["id"]),
            priority=priority,
            summary=summary,
        )
        await self.bot.notify_pending_staff(
            tenant,
            pending,
            customer,
            conversation,
            reason,
            "",
            summary,
        )
        self.bot.services.db.audit(
            int(tenant["id"]),
            str(interaction.user),
            "human_handoff_requested",
            {"pending_id": int(pending["id"]), "priority": priority, "reason": reason},
        )
        await interaction.response.send_message(
            "I’ve passed this to an authorized maintainer with the conversation context. "
            "You can keep using the front desk in the meantime. If this is an emergency or immediate risk, "
            "contact the appropriate local emergency service rather than waiting for a Discord reply.",
            ephemeral=True,
        )

    @app_commands.command(name="help", description="Show what the front desk can do")
    async def help_command(self, interaction: discord.Interaction) -> None:
        embed = discord.Embed(
            title="AI Front Desk",
            description=(
                "I answer questions from maintainer-approved organization information and public project docs, "
                "route unanswered questions to maintainers, and coordinate meetings. I never guess when the "
                "information is missing or conflicting."
            ),
            color=discord.Color.blurple(),
        )
        embed.add_field(
            name="Ask a question",
            value="`/ask` · mention me · or post in a support channel. I create a thread and keep the context there.",
            inline=False,
        )
        embed.add_field(
            name="Meet a maintainer",
            value="`/meet availability` · `/meet book` · `/meet list` · `/meet reschedule` · `/meet cancel`",
            inline=False,
        )
        embed.add_field(
            name="Need a person",
            value="`/human` opens a priority handoff with a conversation summary. You can also ask for a human in a thread.",
            inline=False,
        )
        embed.add_field(
            name="Maintainers",
            value="`/knowledge` · `/pending` · `/staff` · `/frontdesk setup`",
            inline=False,
        )
        embed.add_field(
            name="Privacy",
            value=(
                "Each Discord server is a separate data boundary. Customer-specific notes stay with that member. "
                "I only answer DMs after you have contacted me in an organization server."
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)


if False:  # pragma: no cover
    from ..bot import FrontDeskBot
