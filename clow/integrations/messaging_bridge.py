"""Messaging bridge - connect Clow to WhatsApp, Telegram, Discord."""
import logging
import json
import os
from pathlib import Path

logger = logging.getLogger(__name__)
BRIDGE_DIR = Path.home() / ".clow" / "messaging"


class MessagingBridge:
    def __init__(self):
        self.platforms = {}
        self._load_config()

    def _load_config(self):
        p = BRIDGE_DIR / "config.json"
        if p.exists():
            with open(p) as f:
                self.platforms = json.load(f)

    def configure(self, platform: str, token: str, **kwargs) -> dict:
        BRIDGE_DIR.mkdir(parents=True, exist_ok=True)
        self.platforms[platform] = {"token": token, "enabled": True, **kwargs}
        with open(BRIDGE_DIR / "config.json", "w") as f:
            json.dump(self.platforms, f, indent=2)
        return {"status": "configured", "platform": platform}

    def send_message(self, platform: str, to: str, message: str) -> dict:
        if platform not in self.platforms:
            return {"error": f"Platform {platform} not configured"}
        c = self.platforms[platform]
        try:
            import httpx
        except ImportError:
            return {"error": "httpx not installed"}
        try:
            if platform == "whatsapp":
                api = c.get("api_url", "")
                if not api:
                    return {"error": "WhatsApp API URL not configured"}
                r = httpx.post(
                    f"{api}/message/sendText/{c.get('instance', '')}",
                    json={"number": to, "text": message},
                    headers={"apikey": c["token"]}, timeout=10,
                )
                return {"status": "sent", "response": r.json()}
            elif platform == "telegram":
                r = httpx.post(
                    f"https://api.telegram.org/bot{c['token']}/sendMessage",
                    json={"chat_id": to, "text": message, "parse_mode": "Markdown"},
                    timeout=10,
                )
                return {"status": "sent", "response": r.json()}
            elif platform == "discord":
                wh = c.get("webhook_url", "")
                if not wh:
                    return {"error": "Discord webhook URL not configured"}
                r = httpx.post(wh, json={"content": message}, timeout=10)
                return {"status": "sent", "code": r.status_code}
        except Exception as e:
            return {"error": str(e)}
        return {"error": f"Unknown platform: {platform}"}

    def list_platforms(self) -> list:
        return [{"platform": k, "enabled": v.get("enabled", False)} for k, v in self.platforms.items()]


bridge = MessagingBridge()
