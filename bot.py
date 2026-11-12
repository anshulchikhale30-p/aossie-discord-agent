"""AI Front Desk entry point for AOSSIE and Stability Nexus Discord servers."""

from __future__ import annotations

import logging
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from frontdesk.bot import FrontDeskBot
from frontdesk.config import Settings


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path not in ("/", "/health", "/api/health"):
            self.send_response(404)
            self.end_headers()
            return
        body = b"AI Front Desk is running"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        return


def start_health_server(port: int) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), HealthHandler)
    print(f"Health server listening on port {port}")
    server.serve_forever()


def main() -> None:
    settings = Settings.from_env()
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    if not settings.token:
        raise SystemExit(
            "DISCORD_TOKEN is missing. Copy .env.example to .env and add the bot token."
        )
    if not settings.catalog_path.exists():
        raise SystemExit(
            f"Organization catalog not found at {settings.catalog_path}. "
            "Run: python scripts/build_org_catalog.py"
        )
    port = os.getenv("PORT")
    if port:
        try:
            threading.Thread(target=start_health_server, args=(int(port),), daemon=True).start()
        except ValueError:
            logging.warning("PORT is not a valid integer; health server not started.")
    bot = FrontDeskBot(settings)
    try:
        bot.run(settings.token)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
