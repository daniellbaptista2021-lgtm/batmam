#!/usr/bin/env python3
"""Migra memórias globais (/root/.clow/memory/) para o diretório do admin user.

Uso: python scripts/migrate_global_memory.py [admin_user_id]
Se admin_user_id não for fornecido, usa CLOW_ADMIN_EMAIL do .env.

As memórias globais são COPIADAS (não movidas) para manter backward compatibility.
"""
import hashlib
import os
import shutil
import sys
from pathlib import Path

# Adiciona o diretório do projeto ao path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clow import config
from clow.memory import _user_memory_dir, _update_user_index


def migrate(admin_user_id: str):
    """Copia memórias globais para o diretório do admin."""
    global_dir = config.MEMORY_DIR
    user_dir = _user_memory_dir(admin_user_id)

    if not global_dir.exists():
        print(f"Diretório global {global_dir} não existe. Nada a migrar.")
        return

    files = list(global_dir.glob("*.md"))
    if not files:
        print("Nenhuma memória global encontrada.")
        return

    copied = 0
    skipped = 0
    for f in files:
        target = user_dir / f.name
        if target.exists():
            skipped += 1
            continue
        shutil.copy2(f, target)
        copied += 1

    # Atualiza índice do usuário
    _update_user_index(admin_user_id)

    print(f"Migração concluída:")
    print(f"  - Copiados: {copied} arquivo(s)")
    print(f"  - Ignorados (já existiam): {skipped}")
    print(f"  - De: {global_dir}")
    print(f"  - Para: {user_dir}")
    print(f"\nAs memórias globais foram preservadas em {global_dir}")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        admin_id = sys.argv[1]
    else:
        admin_id = os.getenv("CLOW_ADMIN_EMAIL", "")
        if not admin_id:
            print("Erro: forneça admin_user_id como argumento ou defina CLOW_ADMIN_EMAIL")
            sys.exit(1)

    print(f"Migrando memórias globais para usuário: {admin_id}")
    print(f"Hash do diretório: {hashlib.sha256(admin_id.encode()).hexdigest()[:16]}")
    migrate(admin_id)
