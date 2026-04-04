"""Vercel agent-browser CLI wrapper.

Install: npm install -g @anthropic-ai/agent-browser
"""
import logging
import subprocess
import time

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        r = subprocess.run(["agent-browser", "--version"], capture_output=True, text=True, timeout=5)
        return r.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def open_url(url: str, task: str = "") -> dict:
    if not is_available():
        return {"error": "agent-browser not installed. Run: npm install -g @anthropic-ai/agent-browser"}
    try:
        cmd = ["agent-browser", "open", url]
        if task:
            cmd.extend(["--task", task])
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}
    except subprocess.TimeoutExpired:
        return {"error": "Timeout 120s"}
    except Exception as e:
        return {"error": str(e)}


def screenshot(url: str, output: str = "") -> dict:
    if not is_available():
        return {"error": "agent-browser not installed"}
    if not output:
        output = f"/tmp/screenshot_{int(time.time())}.png"
    try:
        r = subprocess.run(
            ["agent-browser", "screenshot", url, "--output", output],
            capture_output=True, text=True, timeout=30,
        )
        return {"path": output, "status": "ok"} if r.returncode == 0 else {"error": r.stderr}
    except Exception as e:
        return {"error": str(e)}
