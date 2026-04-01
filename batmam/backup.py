"""Feature #22: Backup Automático de Memória.

Faz backup de ~/.batmam/memory/ para .tar.gz datado.
Pode ser executado manualmente ou como cron job built-in.
"""

from __future__ import annotations
import tarfile
import time
from pathlib import Path
from . import config
from .logging import log_action

BACKUP_DIR = config.BATMAM_HOME / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Manter no máximo N backups
MAX_BACKUPS = 30


def backup_memory() -> str:
    """Cria backup da pasta de memórias como .tar.gz datado.

    Retorna o caminho do arquivo criado ou mensagem de erro.
    """
    memory_dir = config.MEMORY_DIR
    if not memory_dir.exists():
        return "Pasta de memórias não existe."

    md_files = list(memory_dir.glob("*.md"))
    if not md_files:
        return "Nenhuma memória para backup."

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_name = f"memory_backup_{timestamp}.tar.gz"
    backup_path = BACKUP_DIR / backup_name

    try:
        with tarfile.open(str(backup_path), "w:gz") as tar:
            for f in md_files:
                tar.add(str(f), arcname=f.name)

        log_action("backup_created", f"{len(md_files)} arquivos -> {backup_name}", tool_name="backup")

        # Limpa backups antigos
        _cleanup_old_backups()

        size_kb = backup_path.stat().st_size / 1024
        return f"Backup criado: {backup_name} ({len(md_files)} arquivos, {size_kb:.1f} KB)"

    except Exception as e:
        log_action("backup_error", str(e), level="error", tool_name="backup")
        return f"Erro no backup: {e}"


def restore_memory(backup_name: str) -> str:
    """Restaura memórias de um backup .tar.gz."""
    backup_path = BACKUP_DIR / backup_name
    if not backup_path.exists():
        return f"Backup não encontrado: {backup_name}"

    try:
        memory_dir = config.MEMORY_DIR
        with tarfile.open(str(backup_path), "r:gz") as tar:
            # Validação de segurança: verifica se não há path traversal
            for member in tar.getmembers():
                if member.name.startswith("/") or ".." in member.name:
                    return f"Backup contém caminhos inseguros: {member.name}"
            tar.extractall(path=str(memory_dir))

        log_action("backup_restored", backup_name, tool_name="backup")
        return f"Backup restaurado: {backup_name}"

    except Exception as e:
        log_action("backup_restore_error", str(e), level="error", tool_name="backup")
        return f"Erro ao restaurar: {e}"


def list_backups() -> list[dict]:
    """Lista backups disponíveis."""
    backups = []
    for f in sorted(BACKUP_DIR.glob("memory_backup_*.tar.gz"), reverse=True):
        size_kb = f.stat().st_size / 1024
        backups.append({
            "name": f.name,
            "size_kb": round(size_kb, 1),
            "created": time.strftime(
                "%Y-%m-%d %H:%M",
                time.localtime(f.stat().st_mtime),
            ),
        })
    return backups


def _cleanup_old_backups() -> None:
    """Remove backups mais antigos que MAX_BACKUPS."""
    backups = sorted(BACKUP_DIR.glob("memory_backup_*.tar.gz"), key=lambda f: f.stat().st_mtime)
    while len(backups) > MAX_BACKUPS:
        oldest = backups.pop(0)
        oldest.unlink()
        log_action("backup_cleaned", oldest.name, tool_name="backup")
