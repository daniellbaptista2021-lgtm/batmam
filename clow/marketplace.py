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

    # Search remote registry for URL
    remote = _fetch_remote_registry()
    match = next((s for s in remote if s["id"] == name), None)

    try:
        import httpx
        if match and match.get("url"):
            r = httpx.get(match["url"], timeout=15, follow_redirects=True)
            if r.status_code == 200:
                dest.mkdir(parents=True, exist_ok=True)
                fname = "README.md" if match["url"].endswith("README.md") else "SKILL.md"
                (dest / fname).write_text(r.text, encoding="utf-8")
                _register(name, dest)
                return {"status": "installed", "name": name, "source": match["source"]}

        # Fallback: try direct from anthropics/skills
        r = httpx.get(f"{REGISTRY_URL}/{name}/SKILL.md", timeout=10, follow_redirects=True)
        if r.status_code == 200:
            dest.mkdir(parents=True, exist_ok=True)
            (dest / "SKILL.md").write_text(r.text, encoding="utf-8")
            _register(name, dest)
            return {"status": "installed", "name": name, "source": "anthropics/skills"}
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


_remote_cache: list[dict] | None = None
_remote_cache_time: float = 0


def _fetch_remote_registry() -> list[dict]:
    """Fetch available skills from GitHub repos."""
    global _remote_cache, _remote_cache_time
    import time
    # Cache for 1 hour
    if _remote_cache and time.time() - _remote_cache_time < 3600:
        return _remote_cache

    skills = []
    try:
        import httpx
        # 1. Anthropic official skills
        r = httpx.get("https://api.github.com/repos/anthropics/skills/contents/skills",
                      headers={"Accept": "application/vnd.github.v3+json"}, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                if item["type"] == "dir":
                    skills.append({"id": item["name"], "source": "anthropics/skills",
                                   "url": f"https://raw.githubusercontent.com/anthropics/skills/main/skills/{item['name']}/SKILL.md"})
    except Exception as e:
        logger.warning("Failed to fetch anthropics/skills: %s", e)

    try:
        import httpx
        # 2. Knowledge work plugins
        r = httpx.get("https://api.github.com/repos/anthropics/knowledge-work-plugins/contents",
                      headers={"Accept": "application/vnd.github.v3+json"}, timeout=10)
        if r.status_code == 200:
            for item in r.json():
                if item["type"] == "dir" and item["name"] not in ("partner-built", ".github"):
                    skills.append({"id": f"kw-{item['name']}", "source": "anthropics/knowledge-work-plugins",
                                   "url": f"https://raw.githubusercontent.com/anthropics/knowledge-work-plugins/main/{item['name']}/README.md"})
    except Exception as e:
        logger.warning("Failed to fetch knowledge-work-plugins: %s", e)

    if skills:
        _remote_cache = skills
        _remote_cache_time = time.time()
    return skills


def search_marketplace(query: str) -> list[dict]:
    """Search available skills from remote registries."""
    remote = _fetch_remote_registry()
    installed_ids = {s["id"] for s in list_installed()}
    q = query.lower()
    results = []
    for s in remote:
        if q in s["id"]:
            results.append({**s, "installed": s["id"] in installed_ids})
    return results


def format_marketplace(query: str = "") -> str:
    installed = list_installed()
    by_cat = {}
    for s in installed:
        by_cat.setdefault(s.get("category", "other"), []).append(s)
    lines = [f"## Marketplace — {len(installed)} skills instaladas\n"]
    for cat, skills in sorted(by_cat.items()):
        lines.append(f"### {cat.title()} ({len(skills)})")
        for s in skills:
            lines.append(f"  - `{s['id']}` — {s.get('name', '')}")
        lines.append("")
    lines.append("Instalar: `clow install <skill-name>`")
    return "\n".join(lines)
