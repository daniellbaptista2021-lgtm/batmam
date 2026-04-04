"""Browser tool — Playwright headless browser for web navigation.

Capabilities: open URL, screenshot, extract HTML/text, click, scroll,
fill forms, wait selectors, execute JS, navigate back/forward.
"""
import asyncio
import base64
import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

logger = logging.getLogger(__name__)


def is_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        return False


class Browser:
    """Headless browser via Playwright."""

    def __init__(self, headless: bool = True):
        self._pw = None
        self._browser = None
        self._page = None
        self._headless = headless

    def _ensure(self):
        if self._page:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=self._headless)
        self._page = self._browser.new_page(
            viewport={"width": 1440, "height": 900},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        )
        self._page.set_default_timeout(30000)

    def open(self, url: str, wait: str = "networkidle") -> dict:
        self._ensure()
        try:
            self._page.goto(url, wait_until=wait, timeout=60000)
            return {"url": self._page.url, "title": self._page.title(), "status": "ok"}
        except Exception as e:
            return {"url": url, "error": str(e)}

    def screenshot(self, path: str = "", full_page: bool = True) -> dict:
        self._ensure()
        if not path:
            path = f"/tmp/screenshot_{int(time.time())}.png"
        try:
            self._page.screenshot(path=path, full_page=full_page)
            return {"path": path, "size": os.path.getsize(path)}
        except Exception as e:
            return {"error": str(e)}

    def screenshot_base64(self, full_page: bool = True) -> str:
        self._ensure()
        data = self._page.screenshot(full_page=full_page)
        return base64.b64encode(data).decode()

    def html(self) -> str:
        self._ensure()
        return self._page.content()

    def text(self) -> str:
        self._ensure()
        return self._page.inner_text("body")

    def scroll_to_bottom(self, delay: float = 0.5) -> None:
        self._ensure()
        prev_height = 0
        for _ in range(50):
            self._page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            self._page.wait_for_timeout(int(delay * 1000))
            new_height = self._page.evaluate("document.body.scrollHeight")
            if new_height == prev_height:
                break
            prev_height = new_height

    def click(self, selector: str) -> dict:
        self._ensure()
        try:
            self._page.click(selector, timeout=5000)
            return {"clicked": selector}
        except Exception as e:
            return {"error": str(e)}

    def fill(self, selector: str, value: str) -> dict:
        self._ensure()
        try:
            self._page.fill(selector, value, timeout=5000)
            return {"filled": selector}
        except Exception as e:
            return {"error": str(e)}

    def wait(self, selector: str, timeout: int = 10000) -> dict:
        self._ensure()
        try:
            self._page.wait_for_selector(selector, timeout=timeout)
            return {"found": selector}
        except Exception as e:
            return {"error": str(e)}

    def evaluate(self, js: str) -> str:
        self._ensure()
        try:
            result = self._page.evaluate(js)
            return str(result)
        except Exception as e:
            return f"Error: {e}"

    def back(self):
        self._ensure()
        self._page.go_back()

    def forward(self):
        self._ensure()
        self._page.go_forward()

    def extract_assets(self, base_url: str = "") -> dict:
        """Extract all asset URLs from the page."""
        self._ensure()
        if not base_url:
            base_url = self._page.url

        assets = self._page.evaluate("""() => {
            const assets = {images: [], css: [], fonts: [], svgs: [], scripts: [], favicons: []};
            document.querySelectorAll('img[src]').forEach(el => assets.images.push(el.src));
            document.querySelectorAll('link[rel="stylesheet"]').forEach(el => assets.css.push(el.href));
            document.querySelectorAll('link[rel*="icon"]').forEach(el => assets.favicons.push(el.href));
            document.querySelectorAll('svg').forEach((el, i) => {
                if (i < 20) assets.svgs.push(el.outerHTML.substring(0, 2000));
            });
            // Extract background images from computed styles
            document.querySelectorAll('*').forEach(el => {
                const bg = getComputedStyle(el).backgroundImage;
                if (bg && bg !== 'none') {
                    const match = bg.match(/url\\(["']?([^"')]+)["']?\\)/);
                    if (match) assets.images.push(match[1]);
                }
            });
            // Deduplicate
            assets.images = [...new Set(assets.images)];
            assets.css = [...new Set(assets.css)];
            assets.favicons = [...new Set(assets.favicons)];
            return assets;
        }""")
        return assets

    def download_assets(self, output_dir: str) -> dict:
        """Download all assets to a local directory."""
        import httpx
        assets = self.extract_assets()
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        (Path(output_dir) / "assets").mkdir(exist_ok=True)

        downloaded = []
        for url in assets.get("images", [])[:30]:
            try:
                fname = self._url_to_filename(url)
                fpath = Path(output_dir) / "assets" / fname
                r = httpx.get(url, timeout=10, follow_redirects=True)
                if r.status_code == 200 and len(r.content) > 100:
                    fpath.write_bytes(r.content)
                    downloaded.append({"url": url, "file": f"assets/{fname}", "size": len(r.content)})
            except Exception:
                continue

        for url in assets.get("css", [])[:10]:
            try:
                fname = self._url_to_filename(url)
                fpath = Path(output_dir) / "assets" / fname
                r = httpx.get(url, timeout=10, follow_redirects=True)
                if r.status_code == 200:
                    fpath.write_bytes(r.content)
                    downloaded.append({"url": url, "file": f"assets/{fname}", "size": len(r.content)})
            except Exception:
                continue

        return {"downloaded": len(downloaded), "files": downloaded}

    def _url_to_filename(self, url: str) -> str:
        parsed = urlparse(url)
        name = parsed.path.split("/")[-1] or "file"
        name = re.sub(r'[^\w.\-]', '_', name)[:80]
        if not Path(name).suffix:
            name += ".bin"
        return name

    def close(self):
        if self._page:
            self._page.close()
            self._page = None
        if self._browser:
            self._browser.close()
            self._browser = None
        if self._pw:
            self._pw.stop()
            self._pw = None

    def __del__(self):
        self.close()
