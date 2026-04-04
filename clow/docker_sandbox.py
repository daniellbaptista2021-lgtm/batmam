"""Docker sandbox — run each task in an isolated container."""
import logging
import subprocess
import tempfile
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        return subprocess.run(["docker", "info"], capture_output=True, timeout=5).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


class DockerSandbox:
    IMAGE = "python:3.12-slim"
    TIMEOUT = 120

    def __init__(self, workspace: str = "", image: str = ""):
        self.workspace = workspace or tempfile.mkdtemp(prefix="clow-sandbox-")
        self.image = image or self.IMAGE
        self._own_workspace = not workspace

    def run(self, command: str, timeout: int = 0) -> dict:
        if not is_available():
            return {"error": "Docker not available", "stdout": "", "stderr": "", "code": -1}
        try:
            r = subprocess.run(
                ["docker", "run", "--rm", "--network", "none", "--memory", "512m",
                 "--cpus", "1", "--pids-limit", "100",
                 "-v", f"{self.workspace}:/workspace", "-w", "/workspace",
                 self.image, "bash", "-c", command],
                capture_output=True, text=True, timeout=timeout or self.TIMEOUT)
            return {"stdout": r.stdout, "stderr": r.stderr, "code": r.returncode}
        except subprocess.TimeoutExpired:
            return {"error": f"Timeout {timeout or self.TIMEOUT}s", "stdout": "", "stderr": "", "code": -1}
        except Exception as e:
            return {"error": str(e), "stdout": "", "stderr": "", "code": -1}

    def run_python(self, code: str, timeout: int = 60) -> dict:
        f = Path(self.workspace) / "_run.py"
        f.write_text(code, encoding="utf-8")
        result = self.run("python3 _run.py", timeout)
        f.unlink(missing_ok=True)
        return result

    def cleanup(self):
        if self._own_workspace:
            shutil.rmtree(self.workspace, ignore_errors=True)


def run_sandboxed(command: str, workspace: str = "", timeout: int = 120) -> dict:
    sb = DockerSandbox(workspace=workspace)
    try:
        return sb.run(command, timeout)
    finally:
        if not workspace:
            sb.cleanup()


def run_python_sandboxed(code: str, timeout: int = 60) -> dict:
    sb = DockerSandbox()
    try:
        return sb.run_python(code, timeout)
    finally:
        sb.cleanup()
