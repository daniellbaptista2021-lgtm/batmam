"""Time Travel — sistema de checkpoints para undo/redo de mudancas.

Antes de cada turno com tools de escrita, salva snapshot dos arquivos
que serao modificados. Permite restaurar qualquer checkpoint anterior.
"""

from __future__ import annotations
import json
import shutil
import time
from pathlib import Path
from typing import Any

from . import config
from .logging import log_action

CHECKPOINTS_DIR = config.CLOW_HOME / "checkpoints"
CHECKPOINTS_DIR.mkdir(parents=True, exist_ok=True)

# Tools que modificam arquivos
WRITE_TOOLS = {"write", "edit", "bash"}

# Comandos bash de escrita (heuristicas)
BASH_WRITE_PATTERNS = [
    "mv ", "cp ", "rm ", "mkdir ", "touch ", "chmod ", "chown ",
    "sed -i", "tee ", ">>", "> ", "cat >", "echo >",
    "git checkout", "git reset", "git restore",
    "pip install", "npm install", "yarn add",
]


def _checkpoint_dir(session_id: str, turn_number: int) -> Path:
    return CHECKPOINTS_DIR / session_id / str(turn_number)


def is_write_tool_call(tool_name: str, arguments: dict) -> bool:
    """Verifica se a tool call vai modificar arquivos."""
    if tool_name in ("write", "edit"):
        return True
    if tool_name == "bash":
        cmd = arguments.get("command", "")
        return any(pat in cmd for pat in BASH_WRITE_PATTERNS)
    return False


def extract_target_files(tool_calls_data: list[dict]) -> list[str]:
    """Extrai lista de arquivos que serao modificados pelas tool calls."""
    files = []
    for tc in tool_calls_data:
        name = tc.get("name", "")
        args_raw = tc.get("arguments", "{}")
        if isinstance(args_raw, str):
            try:
                args = json.loads(args_raw)
            except (json.JSONDecodeError, TypeError):
                args = {}
        else:
            args = args_raw

        if name in ("write", "edit"):
            fp = args.get("file_path", "")
            if fp:
                files.append(fp)
    return files


def save_checkpoint(
    session_id: str,
    turn_number: int,
    files_list: list[str],
    summary: str = "",
) -> dict[str, Any]:
    """Salva checkpoint com copia dos arquivos antes da modificacao.

    Returns dict com metadados do checkpoint.
    """
    if not config.CLOW_CHECKPOINTS:
        return {}

    cp_dir = _checkpoint_dir(session_id, turn_number)
    cp_dir.mkdir(parents=True, exist_ok=True)

    saved_files = []
    for filepath in files_list:
        src = Path(filepath)
        if src.exists() and src.is_file():
            # Salva com path relativo seguro
            safe_name = src.name
            dest = cp_dir / safe_name
            # Se nome duplica, adiciona indice
            idx = 0
            while dest.exists():
                idx += 1
                dest = cp_dir / f"{src.stem}_{idx}{src.suffix}"
            shutil.copy2(str(src), str(dest))
            saved_files.append({
                "original_path": str(src.resolve()),
                "backup_name": dest.name,
                "size": src.stat().st_size,
            })

    metadata = {
        "session_id": session_id,
        "turn_number": turn_number,
        "timestamp": time.time(),
        "timestamp_iso": time.strftime("%Y-%m-%d %H:%M:%S"),
        "files": saved_files,
        "summary": summary,
    }

    meta_file = cp_dir / "checkpoint.json"
    meta_file.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    # Limpa checkpoints antigos se exceder limite
    _prune_old_checkpoints(session_id)

    log_action(
        "checkpoint_save",
        f"turn={turn_number} files={len(saved_files)}",
        session_id=session_id,
    )
    return metadata


def restore_checkpoint(session_id: str, turn_number: int) -> dict[str, Any]:
    """Restaura arquivos de um checkpoint.

    Returns dict com resultado da restauracao.
    """
    cp_dir = _checkpoint_dir(session_id, turn_number)
    meta_file = cp_dir / "checkpoint.json"

    if not meta_file.exists():
        return {"success": False, "error": f"Checkpoint {turn_number} nao encontrado"}

    metadata = json.loads(meta_file.read_text(encoding="utf-8"))
    restored = []
    errors = []

    for file_info in metadata.get("files", []):
        original_path = file_info["original_path"]
        backup_name = file_info["backup_name"]
        backup_path = cp_dir / backup_name

        if not backup_path.exists():
            errors.append(f"Backup nao encontrado: {backup_name}")
            continue

        try:
            dest = Path(original_path)
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(backup_path), str(dest))
            restored.append(original_path)
        except Exception as e:
            errors.append(f"Erro restaurando {original_path}: {e}")

    log_action(
        "checkpoint_restore",
        f"turn={turn_number} restored={len(restored)} errors={len(errors)}",
        session_id=session_id,
    )

    return {
        "success": len(errors) == 0,
        "turn_number": turn_number,
        "restored": restored,
        "errors": errors,
        "metadata": metadata,
    }


def list_checkpoints(session_id: str) -> list[dict[str, Any]]:
    """Lista todos os checkpoints de uma sessao, ordenados por turno."""
    session_dir = CHECKPOINTS_DIR / session_id
    if not session_dir.exists():
        return []

    checkpoints = []
    for turn_dir in sorted(session_dir.iterdir(), key=lambda p: p.name):
        if not turn_dir.is_dir():
            continue
        meta_file = turn_dir / "checkpoint.json"
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                checkpoints.append(meta)
            except Exception:
                continue

    return checkpoints


def diff_checkpoint(session_id: str, turn_number: int) -> list[dict[str, Any]]:
    """Compara checkpoint com estado atual dos arquivos.

    Returns lista de diffs por arquivo.
    """
    cp_dir = _checkpoint_dir(session_id, turn_number)
    meta_file = cp_dir / "checkpoint.json"

    if not meta_file.exists():
        return []

    metadata = json.loads(meta_file.read_text(encoding="utf-8"))
    diffs = []

    for file_info in metadata.get("files", []):
        original_path = file_info["original_path"]
        backup_name = file_info["backup_name"]
        backup_path = cp_dir / backup_name

        current = Path(original_path)
        diff_entry: dict[str, Any] = {
            "file": original_path,
            "status": "unknown",
        }

        if not backup_path.exists():
            diff_entry["status"] = "backup_missing"
        elif not current.exists():
            diff_entry["status"] = "deleted"
            diff_entry["detail"] = "arquivo foi deletado desde o checkpoint"
        else:
            try:
                backup_content = backup_path.read_text(encoding="utf-8")
                current_content = current.read_text(encoding="utf-8")

                if backup_content == current_content:
                    diff_entry["status"] = "unchanged"
                else:
                    diff_entry["status"] = "modified"
                    # Conta linhas diferentes
                    backup_lines = backup_content.splitlines()
                    current_lines = current_content.splitlines()
                    diff_entry["backup_lines"] = len(backup_lines)
                    diff_entry["current_lines"] = len(current_lines)
                    diff_entry["detail"] = (
                        f"checkpoint: {len(backup_lines)} linhas, "
                        f"atual: {len(current_lines)} linhas"
                    )
            except UnicodeDecodeError:
                # Arquivo binario
                backup_size = backup_path.stat().st_size
                current_size = current.stat().st_size
                diff_entry["status"] = "binary_modified" if backup_size != current_size else "binary_unchanged"

        diffs.append(diff_entry)

    return diffs


def _prune_old_checkpoints(session_id: str) -> None:
    """Remove checkpoints mais antigos se exceder CLOW_MAX_CHECKPOINTS."""
    session_dir = CHECKPOINTS_DIR / session_id
    if not session_dir.exists():
        return

    turn_dirs = sorted(
        [d for d in session_dir.iterdir() if d.is_dir()],
        key=lambda p: p.name,
    )

    max_cp = config.CLOW_MAX_CHECKPOINTS
    while len(turn_dirs) > max_cp:
        oldest = turn_dirs.pop(0)
        try:
            shutil.rmtree(oldest)
        except Exception:
            pass
