"""Lightweight GitHub webhook receiver for auto-deploy.

Run on VPS: python3 /root/clow/deploy/webhook.py
Listens on port 9000 for GitHub push events, then runs deploy.sh.

Configure in GitHub repo → Settings → Webhooks:
  URL: http://145.223.30.216:9000/deploy
  Content type: application/json
  Secret: (set same as WEBHOOK_SECRET env var)
  Events: Just the push event
"""

import hashlib
import hmac
import json
import os
import subprocess
import sys
from http.server import HTTPServer, BaseHTTPRequestHandler

WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "clow-deploy-secret")
DEPLOY_SCRIPT = "/root/clow/deploy/deploy.sh"
LOG_FILE = "/root/clow/deploy/deploy.log"


class WebhookHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/deploy":
            self.send_response(404)
            self.end_headers()
            return

        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length)

        # Verify signature
        sig_header = self.headers.get("X-Hub-Signature-256", "")
        if WEBHOOK_SECRET != "clow-deploy-secret":  # Only verify if secret is set
            expected = "sha256=" + hmac.new(
                WEBHOOK_SECRET.encode(), body, hashlib.sha256
            ).hexdigest()
            if not hmac.compare_digest(sig_header, expected):
                self.send_response(403)
                self.end_headers()
                self.wfile.write(b"Invalid signature")
                return

        # Parse payload
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        ref = payload.get("ref", "")
        if ref != "refs/heads/main":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"Ignored: not main branch")
            return

        # Run deploy
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Deploy started")

        print(f"[DEPLOY] Push to main detected, running deploy...")
        try:
            result = subprocess.run(
                ["bash", DEPLOY_SCRIPT],
                capture_output=True,
                text=True,
                timeout=120,
            )
            with open(LOG_FILE, "a") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"STDOUT:\n{result.stdout}\n")
                if result.stderr:
                    f.write(f"STDERR:\n{result.stderr}\n")
                f.write(f"Exit code: {result.returncode}\n")
            print(f"[DEPLOY] Exit code: {result.returncode}")
        except Exception as e:
            print(f"[DEPLOY] Error: {e}")

    def do_GET(self):
        if self.path == "/health":
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"webhook ok")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        print(f"[WEBHOOK] {args[0]}")


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 9000
    server = HTTPServer(("0.0.0.0", port), WebhookHandler)
    print(f"[WEBHOOK] Listening on port {port}")
    print(f"[WEBHOOK] Deploy script: {DEPLOY_SCRIPT}")
    server.serve_forever()
