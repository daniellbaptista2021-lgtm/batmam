"""Test marketplace remote registry."""
from clow.marketplace import search_marketplace, install_skill, uninstall_skill, list_installed

print("=== 1. Buscar skills remotas (GitHub API) ===")
results = search_marketplace("doc")
for r in results:
    tag = "[instalada]" if r.get("installed") else ""
    print(f"  {r['id']} — {r['source']} {tag}")

print("\n=== 2. Buscar 'pdf' ===")
results = search_marketplace("pdf")
for r in results:
    tag = "[instalada]" if r.get("installed") else ""
    print(f"  {r['id']} — {r['source']} {tag}")

print("\n=== 3. Total remotas ===")
all_remote = search_marketplace("")
print(f"  {len(all_remote)} skills nos registries")
for r in all_remote[:10]:
    print(f"    {r['id']} ({r['source']})")
if len(all_remote) > 10:
    print(f"    ... +{len(all_remote)-10} mais")

print("\n=== 4. Instalar do registry remoto ===")
r = install_skill("slack-gif-creator")
print(f"  {r}")

print("\n=== 5. Desinstalar ===")
r = uninstall_skill("slack-gif-creator")
print(f"  {r}")

print(f"\n=== Total instaladas: {len(list_installed())} ===")
