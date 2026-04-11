"""Remote Trigger Tool - trigger remote actions/webhooks."""

from __future__ import annotations
import json
import time
from typing import Any
from .base import BaseTool


class RemoteTriggerTool(BaseTool):
    """Trigger a remote action or webhook."""

    name = "remote_trigger"
    description = (
        "Trigger a remote action by sending an HTTP request to a webhook URL. "
        "Supports POST/GET with custom headers and payload."
    )
    requires_confirmation = False
    _is_read_only = False
    _is_concurrency_safe = True
    _is_destructive = False
    _search_hint = "remote trigger webhook http call api"
    _aliases = ["webhook", "trigger"]

    def get_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Webhook URL to trigger.",
                },
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                    "description": "HTTP method. Default: POST.",
                },
                "payload": {
                    "type": "object",
                    "description": "JSON payload to send in the request body.",
                },
                "headers": {
                    "type": "object",
                    "description": "Additional HTTP headers.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Request timeout in seconds. Default: 30.",
                },
            },
            "required": ["url"],
        }

    def execute(self, **kwargs: Any) -> str:
        url = kwargs.get("url", "")
        method = kwargs.get("method", "POST").upper()
        payload = kwargs.get("payload", {})
        headers = kwargs.get("headers", {})
        timeout = kwargs.get("timeout", 30)

        if not url:
            return "[ERROR] url is required."

        try:
            import urllib.request
            import urllib.error

            # Build request
            data = None
            if method in ("POST", "PUT", "PATCH") and payload:
                data = json.dumps(payload).encode("utf-8")
                if "Content-Type" not in headers:
                    headers["Content-Type"] = "application/json"

            req = urllib.request.Request(url, data=data, headers=headers, method=method)

            start = time.time()
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed = time.time() - start
                status = resp.status
                body = resp.read().decode("utf-8", errors="replace")

                # Truncate large responses
                if len(body) > 5000:
                    body = body[:5000] + "\n... (truncated)"

                return (
                    f"Remote trigger successful.\n"
                    f"  URL: {url}\n"
                    f"  Method: {method}\n"
                    f"  Status: {status}\n"
                    f"  Time: {elapsed:.2f}s\n"
                    f"  Response:\n{body}"
                )

        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="replace")[:2000]
            except Exception:
                pass
            return f"[ERROR] HTTP {e.code}: {e.reason}\n{body}"
        except urllib.error.URLError as e:
            return f"[ERROR] URL error: {e.reason}"
        except TimeoutError:
            return f"[ERROR] Request timed out after {timeout}s."
        except Exception as e:
            return f"[ERROR] Remote trigger failed: {e}"
