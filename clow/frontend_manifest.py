"""Frontend build manifest — maps original filenames to hashed builds.

After `npm run build`, Vite outputs files like `chat_js.hTfR4I_3.js`.
This module reads the dist/ directory and provides functions to get
the correct hashed path for templates, enabling cache-busting.

Falls back to unbuilt paths if dist/ doesn't exist (dev mode).
"""
from __future__ import annotations

import os
import re
from pathlib import Path

_STATIC_DIR = Path(__file__).parent.parent / "static"
_DIST_DIR = _STATIC_DIR / "dist"

_manifest_cache: dict[str, str] | None = None


def _build_manifest() -> dict[str, str]:
    """Scan dist/ and map base names to hashed filenames."""
    manifest: dict[str, str] = {}
    if not _DIST_DIR.exists():
        return manifest

    for subdir in ("js", "css", "assets"):
        d = _DIST_DIR / subdir
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file():
                # chat_js.hTfR4I_3.js -> chat_js
                base = re.sub(r'\.[A-Za-z0-9_-]{6,}\.(js|css|map)$', '', f.name)
                # Map: "chat_js" -> "dist/js/chat_js.hTfR4I_3.js"
                manifest[base] = f"/static/dist/{subdir}/{f.name}"
    return manifest


def get_asset(name: str, fallback: str = "") -> str:
    """Get the hashed asset path, or fallback to dev path.

    Usage in templates:
        get_asset("chat_js", "/static/js/chat.js")
        -> "/static/dist/js/chat_js.hTfR4I_3.js" (prod)
        -> "/static/js/chat.js" (dev)
    """
    global _manifest_cache
    if _manifest_cache is None:
        _manifest_cache = _build_manifest()
    return _manifest_cache.get(name, fallback)


def has_build() -> bool:
    """Check if production build exists."""
    return _DIST_DIR.exists() and any(_DIST_DIR.iterdir())


def invalidate_cache():
    """Force re-scan of dist/ directory."""
    global _manifest_cache
    _manifest_cache = None
