"""AI Front Desk entry point for AOSSIE and Stability Nexus Discord servers."""

from __future__ import annotations

import logging
import json
import os
import sys
import threading
from urllib.parse import parse_qs, urlparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from frontdesk.bot import FrontDeskBot
from frontdesk.config import Settings


def make_health_handler(bot: FrontDeskBot):
    class HealthHandler(BaseHTTPRequestHandler):
        def _json(self, payload: dict[str, Any], status: int = 200) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", os.getenv("FRONTDESK_API_ORIGIN", "*"))
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path in ("/", "/health", "/api/health"):
                self._json({"status": "ok", "service": "aossie-frontdesk-agent", "discord_ready": bot.is_ready()})
                return
            if parsed.path != "/api/frontdesk":
                self._json({"error": "not_found"}, 404)
                return
            expected = os.getenv("FRONTDESK_API_TOKEN", "").strip()
            if not expected:
                self._json({"error": "dashboard_api_not_configured"}, 503)
                return
            if expected and self.headers.get("Authorization", "") != f"Bearer {expected}":
                self._json({"error": "unauthorized"}, 401)
                return
            tenants = bot.services.db.list_tenants()
            requested = (parse_qs(parsed.query).get("guild_id") or [""])[0]
            tenant = next((item for item in tenants if str(item["guild_id"]) == requested), None) if requested else (tenants[0] if tenants else None)
            if tenant is None:
                self._json({"live": True, "discord_ready": bot.is_ready(), "tenants": [], "metrics": {}})
                return
            tenant_id = int(tenant["id"])
            pending = bot.services.db.list_pending(tenant_id, limit=25)
            conversations = bot.services.db.list_conversations(tenant_id, limit=25)
            self._json({
                "live": True,
                "discord_ready": bot.is_ready(),
                "tenant": {"id": tenant_id, "guild_id": tenant["guild_id"], "name": tenant["display_name"], "timezone": tenant["timezone"]},
                "metrics": bot.services.db.provider_metrics(tenant_id),
                "pending": [dict(row) for row in pending],
                "conversations": [dict(row) for row in conversations],
            })

        def log_message(self, format: str, *args: Any) -> None:
            return

    return HealthHandler

def start_health_server(port: int, bot: FrontDeskBot) -> None:
    server = ThreadingHTTPServer(("0.0.0.0", port), make_health_handler(bot))
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
    bot = FrontDeskBot(settings)
    port = os.getenv("PORT")
    if port:
        try:
            threading.Thread(target=start_health_server, args=(int(port), bot), daemon=True).start()
        except ValueError:
            logging.warning("PORT is not a valid integer; health server not started.")
    try:
        bot.run(settings.token)
    except KeyboardInterrupt:
        sys.exit(0)


if __name__ == "__main__":
    main()
