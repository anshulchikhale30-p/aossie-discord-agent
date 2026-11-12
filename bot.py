from __future__ import annotations

import json
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import discord
import httpx
from discord.ext import commands
from dotenv import load_dotenv

from repo_metadata import REPO_METADATA

load_dotenv()

ORG_NAME = os.getenv("ORG_NAME", "AOSSIE")
DISCORD_CHANNEL_ID = int(os.getenv("DISCORD_CHANNEL_ID", "0") or 0)
DOCS_DIR = Path(os.getenv("DOCS_DIR", "./data/repos"))
GAP_LOG = Path(os.getenv("GAP_LOG", "./data/gap_log.json"))
AUDIT_LOG = Path(os.getenv("AUDIT_LOG", "./data/audit.jsonl"))
USE_OLLAMA = os.getenv("USE_OLLAMA", "false").lower() == "true"
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
PORT = int(os.getenv("PORT", "10000"))

QUESTION_STARTERS = re.compile(r"^(how|where|what|when|why|can|could|is|are|does|do|which|who)\b", re.I)
HELP_SIGNALS = re.compile(
    r"\b(help|stuck|blocked|issue|problem|error|bug|install|setup|start|run|build|deploy|contribut|docs?|guide|beginner|configur)\b",
    re.I,
)


@dataclass
class Route:
    name: str
    url: str
    description: str
    score: int
    docs: list[str]


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def append_jsonl(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def append_gap(record: dict[str, Any]) -> None:
    GAP_LOG.parent.mkdir(parents=True, exist_ok=True)
    gaps: list[dict[str, Any]] = []
    if GAP_LOG.exists():
        try:
            gaps = json.loads(GAP_LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            gaps = []
    gaps.append(record)
    GAP_LOG.write_text(json.dumps(gaps, indent=2, ensure_ascii=False), encoding="utf-8")


def likely_question(message: discord.Message) -> bool:
    content = message.content.strip()
    if not content:
        return False
    return (
        "?" in content
        or bool(QUESTION_STARTERS.match(content))
        or bool(HELP_SIGNALS.search(content))
        or bool(message.mentions)
    )


def route_question(question: str) -> Route | None:
    normalized = question.casefold()
    candidates: list[Route] = []
    for name, metadata in REPO_METADATA.items():
        tokens = [name, *metadata.get("keywords", [])]
        score = sum(3 if token.casefold() == normalized else 2 for token in tokens if token.casefold() in normalized)
        if score:
            candidates.append(Route(name, metadata["url"], metadata["description"], score, metadata.get("docs", ["README.md"])))
    return max(candidates, key=lambda route: route.score, default=None)


def retrieve_docs(route: Route, question: str) -> list[tuple[str, str]]:
    repo_dir = DOCS_DIR / route.name
    repo_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, str]] = []
    question_terms = set(re.findall(r"[a-z0-9]{3,}", question.casefold()))
    for doc in route.docs:
        local_path = repo_dir / doc.replace("/", "_")
        if local_path.exists():
            results.append((doc, local_path.read_text(encoding="utf-8", errors="ignore")[:4000]))
    if results:
        return results
    with httpx.Client(timeout=12, follow_redirects=True) as client:
        for doc in route.docs:
            raw_url = route.url.replace("https://github.com/", "https://raw.githubusercontent.com/")
            parts = raw_url.split("/", 5)
            if len(parts) < 5:
                continue
            owner_repo = "/".join(parts[3:5])
            url = f"https://raw.githubusercontent.com/{owner_repo}/main/{doc}"
            try:
                response = client.get(url)
                if response.status_code == 200:
                    text = response.text[:4000]
                    local_path.write_text(text, encoding="utf-8")
                    if question_terms:
                        text_terms = set(re.findall(r"[a-z0-9]{3,}", text.casefold()))
                        if question_terms & text_terms or doc.casefold() == "readme.md":
                            results.append((doc, text))
            except httpx.HTTPError:
                continue
    return results[:3]


def extract_answer(route: Route, docs: list[tuple[str, str]], question: str) -> str:
    if not docs:
        return f"I found **{route.name}**, but I could not retrieve a matching contributor document. I’ve flagged this for maintainer review."
    if USE_OLLAMA:
        try:
            prompt = (
                f"You are the {ORG_NAME} open-source community assistant. Answer the contributor question using only the supplied repository docs. "
                "Be concise, never invent steps, and say when the docs are insufficient.\n\n"
                f"Question: {question}\nRepository: {route.name}\nDocs:\n" + "\n\n".join(f"[{name}]\n{text}" for name, text in docs)
            )
            response = httpx.post(f"{OLLAMA_BASE_URL}/api/generate", json={"model": OLLAMA_MODEL, "prompt": prompt, "stream": False}, timeout=45)
            response.raise_for_status()
            answer = response.json().get("response", "").strip()
            if answer:
                return answer
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            pass
    first_doc = docs[0][0]
    return f"I routed this to **{route.name}**. Start with the project README and follow the contributor guidance for the local setup path. I found the relevant section in `{first_doc}`. If you tell me whether you need setup, contribution, or architecture help, I can narrow the next step."


def source_links(route: Route, docs: list[tuple[str, str]]) -> str:
    return "\n".join(f"• [{doc}]({route.url}/blob/main/{doc})" for doc, _ in docs)


class AOSSIEAgent(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(command_prefix="!", intents=intents, help_command=None)

    async def on_ready(self) -> None:
        print(f"AOSSIE Agent online as {self.user} · watching channel {DISCORD_CHANNEL_ID or 'allowlisted names'}")

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not isinstance(message.channel, discord.TextChannel):
            return
        if DISCORD_CHANNEL_ID and message.channel.id != DISCORD_CHANNEL_ID:
            return
        if not DISCORD_CHANNEL_ID and not any(word in message.channel.name.casefold() for word in ("agent", "support", "gsoc", "skill")):
            return
        if not likely_question(message):
            return
        if isinstance(message.channel, discord.TextChannel):
            await self.handle_question(message)

    async def handle_question(self, message: discord.Message) -> None:
        route = route_question(message.content)
        append_jsonl(AUDIT_LOG, {"timestamp": now(), "event": "question_received", "message_id": str(message.id), "channel_id": str(message.channel.id), "author": str(message.author), "question": message.content, "route": route.name if route else None})
        thread: discord.Thread | None = None
        try:
            thread = await message.create_thread(name=f"AOSSIE Agent · {message.content[:65]}")
        except discord.HTTPException:
            if isinstance(message.channel, discord.TextChannel):
                thread = await message.channel.create_thread(name=f"AOSSIE Agent · {message.content[:65]}", type=discord.ChannelType.public_thread)
        target = thread or message.channel
        if route is None:
            await target.send("I’m not sure which AOSSIE project this is about. Could you name the repository or project? I’ll route the question to the right docs instead of guessing.")
            append_gap({"timestamp": now(), "message_id": str(message.id), "question": message.content, "reason": "no repository route"})
            return
        docs = retrieve_docs(route, message.content)
        if not docs:
            append_gap({"timestamp": now(), "message_id": str(message.id), "question": message.content, "repository": route.name, "reason": "no matching docs"})
        answer = extract_answer(route, docs, message.content)
        response = f"{answer}\n\n**Sources**\n{source_links(route, docs) if docs else route.url}\n\n_Observer mode · no GitHub or Discord mutations_"
        await target.send(response)
        append_jsonl(AUDIT_LOG, {"timestamp": now(), "event": "answer_sent", "message_id": str(message.id), "thread_id": str(thread.id) if thread else None, "repository": route.name, "docs": [doc for doc, _ in docs], "gap": not bool(docs)})


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health", "/api/health"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"AOSSIE Discord Agent is running"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server() -> None:
    server = ThreadingHTTPServer(("0.0.0.0", PORT), HealthHandler)
    print(f"Health server listening on port {PORT}")
    server.serve_forever()


TOKEN = os.getenv("DISCORD_TOKEN")
if not TOKEN:
    raise RuntimeError("DISCORD_TOKEN is missing. Copy .env.example to .env and add it locally.")

bot = AOSSIEAgent()
threading.Thread(target=start_health_server, daemon=True).start()
bot.run(TOKEN)
