"""Notification Tools - send files and push notifications to users."""

from __future__ import annotations
import json
import time
import uuid
import shutil
from pathlib import Path
from typing import Any
from .base import BaseTool


class SendUserFileTool(BaseTool):
    """Send a file to the user (copy to downloads or serve URL)."""

    name = "send_user_file"
    description = (
        "Send a file to the user. Copies the file to a downloads directory "
        "or generates a download URL. Use to deliver generated files."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "send file download deliver user"
    _aliases = ["deliver_file", "download"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Path to the file to send.",
                },
                "filename": {
                    "type": "string",
                    "description": "Display filename for the user. Default: original filename.",
                },
                "description": {
                    "type": "string",
                    "description": "Description of the file being sent.",
                },
            },
            "required": ["file_path"],
        }

    def execute(self, **kwargs: Any) -> str:
        file_path = kwargs.get("file_path", "")
        filename = kwargs.get("filename", "")
        description = kwargs.get("description", "")

        if not file_path:
            return "[ERROR] file_path is required."

        source = Path(file_path).expanduser().resolve()
        if not source.exists():
            return f"[ERROR] File not found: {source}"
        if not source.is_file():
            return f"[ERROR] Not a file: {source}"

        display_name = filename if filename else source.name

        # Copy to downloads directory
        try:
            from .. import config
            downloads_dir = config.CLOW_HOME / "downloads"
            downloads_dir.mkdir(parents=True, exist_ok=True)

            # Add timestamp to avoid collisions
            ts = time.strftime("%Y%m%d_%H%M%S")
            dest_name = f"{ts}_{display_name}"
            dest = downloads_dir / dest_name
            shutil.copy2(str(source), str(dest))

            size_kb = dest.stat().st_size / 1024

            msg = (
                f"File delivered: {display_name}\n"
                f"  Location: {dest}\n"
                f"  Size: {size_kb:.1f} KB"
            )
            if description:
                msg += f"\n  Description: {description}"
            return msg
        except Exception as e:
            return f"[ERROR] Failed to send file: {e}"


class PushNotificationTool(BaseTool):
    """Send a notification to the user."""

    name = "push_notification"
    description = (
        "Send a push notification to the user. Stores the notification "
        "and can trigger external channels (webhook, email)."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "notification push alert notify user"
    _aliases = ["notify", "alert"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Notification title.",
                },
                "message": {
                    "type": "string",
                    "description": "Notification message body.",
                },
                "priority": {
                    "type": "string",
                    "enum": ["low", "normal", "high", "urgent"],
                    "description": "Priority level. Default: normal.",
                },
                "notification_type": {
                    "type": "string",
                    "description": "Type/category of notification.",
                },
            },
            "required": ["title", "message"],
        }

    def execute(self, **kwargs: Any) -> str:
        title = kwargs.get("title", "")
        message = kwargs.get("message", "")
        priority = kwargs.get("priority", "normal")
        ntype = kwargs.get("notification_type", "general")

        if not title or not message:
            return "[ERROR] title and message are required."

        # Store notification
        try:
            from .. import config
            notif_dir = config.CLOW_HOME / "notifications" / "default"
            notif_dir.mkdir(parents=True, exist_ok=True)

            notif = {
                "id": uuid.uuid4().hex[:12],
                "title": title,
                "message": message,
                "priority": priority,
                "type": ntype,
                "timestamp": time.time(),
                "read": False,
            }

            # Append to notifications file
            notif_file = notif_dir / "notifications.json"
            existing = []
            if notif_file.exists():
                try:
                    existing = json.loads(notif_file.read_text(encoding="utf-8"))
                except (json.JSONDecodeError, OSError):
                    existing = []

            existing.append(notif)
            # Keep last 1000 notifications
            if len(existing) > 1000:
                existing = existing[-1000:]

            notif_file.write_text(json.dumps(existing, indent=2), encoding="utf-8")

            return (
                f"Notification sent.\n"
                f"  ID: {notif['id']}\n"
                f"  Title: {title}\n"
                f"  Priority: {priority}"
            )
        except Exception as e:
            return f"[ERROR] Failed to send notification: {e}"
