"""Skill Marketplace — install, uninstall, and manage skills.

Usage:
    clow install <skill-name>
    clow uninstall <skill-name>
    clow marketplace
"""
import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

SKILLS_DIR = Path(__file__).parent / "skills" / "imported"
REGISTRY_URL = "https://raw.githubusercontent.com/anthropics/skills/main/skills"
LOCAL_REGISTRY = SKILLS_DIR / "registry.json"


def _load_registry() -> dict:
    if LOCAL_REGISTRY.exists():
        with open(LOCAL_REGISTRY) as f:
            return json.load(f)
    return {"skills": []}


def _save_registry(data: dict):
    with open(LOCAL_REGISTRY, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def install_skill(name: str, source: str = "") -> dict:
    dest = SKILLS_DIR / name
    if dest.exists():
        return {"status": "already_installed", "name": name}

    if source and Path(source).exists():
        shutil.copytree(source, dest)
        _register(name, dest)
        return {"status": "installed", "name": name, "source": "local"}

    try:
        import httpx
        r = httpx.get(f"{REGISTRY_URL}/{name}/SKILL.md", timeout=10, follow_redirects=True)
        if r.status_code == 200:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "SKILL.md").write_text(r.text, encoding="utf-8")
            _register(name, dest)
            return {"status": "installed", "name": name, "source": "github"}
        return {"status": "not_found", "name": name}
    except Exception as e:
        return {"status": "error", "name": name, "error": str(e)}


def uninstall_skill(name: str) -> dict:
    dest = SKILLS_DIR / name
    if not dest.exists():
        return {"status": "not_installed", "name": name}
    shutil.rmtree(dest)
    reg = _load_registry()
    reg["skills"] = [s for s in reg["skills"] if s["id"] != name]
    _save_registry(reg)
    return {"status": "uninstalled", "name": name}


def _register(name: str, path: Path):
    reg = _load_registry()
    if name in {s["id"] for s in reg["skills"]}:
        return
    desc = name
    skill_md = path / "SKILL.md"
    if skill_md.exists():
        for line in skill_md.read_text("utf-8").split("\n"):
            if line.startswith("description:"):
                desc = line.split(":", 1)[1].strip()
                break
    reg["skills"].append({
        "id": name, "name": desc, "category": "installed",
        "trigger_words": [name.replace("-", " ")],
        "path": f"imported/{name}/SKILL.md",
    })
    _save_registry(reg)


def list_installed() -> list[dict]:
    return _load_registry()["skills"]


def search_marketplace(query: str) -> list[dict]:
    known = ["algorithmic-art", "brand-guidelines", "canvas-design", "claude-api",
             "doc-coauthoring", "docx", "frontend-design", "internal-comms",
             "mcp-builder", "pdf", "pptx", "skill-creator", "theme-factory",
             "webapp-testing", "web-artifacts-builder", "xlsx"]
    q = query.lower()
    return [{"id": s, "source": "anthropic/skills"} for s in known if q in s]


def format_marketplace() -> str:
    installed = list_installed()
    by_cat = {}
    for s in installed:
        by_cat.setdefault(s.get("category", "other"), []).append(s)
    lines = [f"## Marketplace — {len(installed)} skills\n"]
    for cat, skills in sorted(by_cat.items()):
        lines.append(f"### {cat.title()} ({len(skills)})")
        for s in skills:
            lines.append(f"  - `{s['id']}` — {s.get('name', '')}")
        lines.append("")
    lines.append("Instalar: `clow install <skill-name>`")
    return "\n".join(lines)
