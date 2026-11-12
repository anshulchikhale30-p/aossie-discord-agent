"""Interactive codebase-understanding gate for issue and PR requests."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import discord


@dataclass(frozen=True)
class QuizQuestion:
    prompt: str
    options: tuple[str, ...]
    correct: int
    explanation: str


QUESTIONS = (
    QuizQuestion(
        "Before opening an issue or PR, what should you read first?",
        ("Only the issue title", "README.md and CONTRIBUTING.md", "A random online tutorial", "Nothing; the Agent will decide"),
        1,
        "The README explains the project and CONTRIBUTING.md explains the repository workflow.",
    ),
    QuizQuestion(
        "If the repository documentation does not answer your question, what is the safest next step?",
        ("Guess and submit a PR", "Copy an AI-generated solution without checking it", "Ask a maintainer or request clarification with evidence", "Delete the existing implementation"),
        2,
        "Unclear behavior should be clarified with maintainers and supported by reproducible evidence.",
    ),
    QuizQuestion(
        "What should a useful issue or PR description include?",
        ("Only a one-word summary", "Problem or goal, relevant files, steps to reproduce, and testing", "A screenshot with no context", "A request for someone else to investigate everything"),
        1,
        "A maintainer needs the goal, context, reproduction steps, affected code, and validation details.",
    ),
)


class CodebaseQuizView(discord.ui.View):
    def __init__(
        self,
        bot: "FrontDeskBot",
        tenant_id: int,
        customer_id: int,
        repository: str,
        original_question: str,
        target: discord.abc.Messageable,
        conversation: Any,
        author_id: int | str,
        author_label: str,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot
        self.tenant_id = tenant_id
        self.customer_id = customer_id
        self.repository = repository
        self.original_question = original_question
        self.target = target
        self.conversation = conversation
        self.author_id = author_id
        self.author_label = author_label
        self.index = 0
        self.score = 0
        self._render_buttons()

    def _render_buttons(self) -> None:
        self.clear_items()
        question = QUESTIONS[self.index]
        for index, option in enumerate(question.options):
            button = discord.ui.Button(
                label=f"{chr(65 + index)}. {option[:70]}",
                style=discord.ButtonStyle.secondary,
                custom_id=f"codebase-check:{self.index}:{index}",
            )
            button.callback = self._make_callback(index)
            self.add_item(button)

    def prompt(self) -> str:
        question = QUESTIONS[self.index]
        return (
            f"**Codebase understanding check · {self.repository}**\n"
            f"Before creating an issue or PR, answer question {self.index + 1}/{len(QUESTIONS)}:\n\n"
            f"{question.prompt}\n\n" + "\n".join(f"**{chr(65 + i)}.** {option}" for i, option in enumerate(question.options))
        )

    def _make_callback(self, selected: int):
        async def callback(interaction: discord.Interaction) -> None:
            if int(interaction.user.id) != int(self.author_id):
                await interaction.response.send_message("This codebase check belongs to the person who started it.", ephemeral=True)
                return
            question = QUESTIONS[self.index]
            if selected != question.correct:
                self.bot.services.db.save_codebase_check(
                    self.tenant_id, self.customer_id, self.repository, "failed", self.score, len(QUESTIONS)
                )
                for item in self.children:
                    item.disabled = True
                await interaction.response.edit_message(
                    content=(
                        "That option is not correct. **Please re-study the codebase, README, and CONTRIBUTING.md "
                        "before creating an issue or PR.**\n\n"
                        f"Hint: {question.explanation}"
                    ),
                    view=self,
                )
                self.stop()
                return
            self.score += 1
            self.index += 1
            if self.index >= len(QUESTIONS):
                self.bot.services.db.save_codebase_check(
                    self.tenant_id, self.customer_id, self.repository, "passed", self.score, len(QUESTIONS)
                )
                await interaction.response.edit_message(
                    content=(
                        "**Codebase understanding check passed.** You can now continue with your issue or PR request.\n\n"
                        "The Agent will still route the request to a maintainer when human review is needed."
                    ),
                    view=None,
                )
                self.stop()
                await self.bot.process_question(
                    self.bot.services.db.get_tenant(self.tenant_id),
                    self.bot.services.db.get_customer(self.customer_id),
                    self.conversation,
                    self.original_question,
                    self.target,
                    self.author_id,
                    self.author_label,
                    skip_codebase_check=True,
                )
                return
            self.bot.services.db.save_codebase_check(
                self.tenant_id, self.customer_id, self.repository, "in_progress", self.score, len(QUESTIONS)
            )
            self._render_buttons()
            await interaction.response.edit_message(content=self.prompt(), view=self)

        return callback


if False:  # pragma: no cover
    from .bot import FrontDeskBot
