"""Helpers pra rodar comandos Node/npm no projeto gerado."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def has_node() -> bool:
    return shutil.which("node") is not None and shutil.which("npm") is not None


def run_npm_install(project_dir: str | Path, timeout: int = 300) -> dict:
    """Roda `npm install --no-audit --no-fund` no projeto. Retorna dict com status."""
    if not has_node():
        return {"status": "skipped", "reason": "node/npm nao instalado"}
    project_dir = str(project_dir)
    try:
        proc = subprocess.run(
            ["npm", "install", "--no-audit", "--no-fund", "--loglevel=error"],
            cwd=project_dir, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return {"status": "ok", "stdout": proc.stdout[-2000:], "stderr": proc.stderr[-1000:]}
        return {"status": "error", "code": proc.returncode, "stderr": proc.stderr[-2000:]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout", "reason": f"npm install excedeu {timeout}s"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def run_typecheck(project_dir: str | Path, timeout: int = 120) -> dict:
    """Roda `npx tsc --noEmit`. Retorna {status, errors?}."""
    if not has_node():
        return {"status": "skipped", "reason": "node/npm nao instalado"}
    project_dir = str(project_dir)
    try:
        proc = subprocess.run(
            ["npx", "--no-install", "tsc", "--noEmit"],
            cwd=project_dir, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return {"status": "ok"}
        # tsc errors saem em stdout
        return {"status": "error", "errors": (proc.stdout + proc.stderr)[-3000:]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}


def run_build(project_dir: str | Path, timeout: int = 300) -> dict:
    """Roda `npm run build`. Retorna {status, errors?}."""
    if not has_node():
        return {"status": "skipped", "reason": "node/npm nao instalado"}
    project_dir = str(project_dir)
    try:
        proc = subprocess.run(
            ["npm", "run", "build"],
            cwd=project_dir, capture_output=True, text=True, timeout=timeout,
        )
        if proc.returncode == 0:
            return {"status": "ok", "stdout": proc.stdout[-1500:]}
        return {"status": "error", "errors": (proc.stdout + proc.stderr)[-3000:]}
    except subprocess.TimeoutExpired:
        return {"status": "timeout"}
    except Exception as e:
        return {"status": "error", "reason": str(e)}
