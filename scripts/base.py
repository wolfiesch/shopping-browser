"""
ShopperBase — Abstract base class for shopping site adapters.

Provides shared browser management, cookie injection, JS evaluation,
and optional session pool integration.
"""

import sys
from abc import ABC, abstractmethod
from pathlib import Path

# Add stealth-browser scripts to path for shared infrastructure
STEALTH_SCRIPTS = Path.home() / ".claude" / "skills" / "stealth-browser" / "scripts"
sys.path.insert(0, str(STEALTH_SCRIPTS))

from config import BROWSER_ARGS  # noqa: E402
from chrome_cookies import extract_cookies as extract_chrome_cookies  # noqa: E402

import nodriver as uc  # noqa: E402
from nodriver import cdp  # noqa: E402

from cdp_parser import parse_cdp_response  # noqa: E402

SCREENSHOT_DIR = Path(__file__).parent.parent / "data" / "screenshots"
SOCKET_PATH = Path(__file__).parent.parent / "data" / "pool.sock"


async def inject_cookies(browser, cookies: list, domain_filter: str):
    """Inject cookies into browser via CDP. Shared across all adapters.

    Args:
        browser: nodriver Browser instance
        cookies: List of cookie dicts from chrome_cookies
        domain_filter: Domain to filter cookies for (e.g. "amazon.com")
    Returns:
        Number of cookies injected
    """
    injected = 0
    for c in cookies:
        if not c.get("value"):
            continue
        cookie_domain = c.get("domain", "").lstrip(".")
        if domain_filter not in cookie_domain and cookie_domain not in domain_filter:
            continue
        try:
            same_site = None
            if c.get("same_site") in ("Strict", "Lax", "None"):
                same_site = cdp.network.CookieSameSite(c["same_site"])
            param = cdp.network.CookieParam(
                name=c["name"], value=c["value"],
                domain=c.get("domain"), path=c.get("path", "/"),
                secure=c.get("secure", False),
                http_only=c.get("http_only", False),
                same_site=same_site,
            )
            await browser.connection.send(cdp.storage.set_cookies([param]))
            injected += 1
        except Exception:
            pass
    return injected


class ShopperBase(ABC):
    """Abstract base for shopping site adapters."""

    DOMAIN: str = ""           # e.g. "amazon.com"
    DISPLAY_NAME: str = ""     # e.g. "Amazon"

    def __init__(self):
        self.browser = None
        self.page = None
        self._from_pool = False
        self._owns_browser = False

    async def ensure_browser(self):
        """Get a browser instance — from pool if available, else fresh."""
        if SOCKET_PATH.exists():
            try:
                self.browser, self.page = await self._acquire_from_pool()
                self._from_pool = True
                return
            except Exception as e:
                print(f"[shopping] Pool acquire failed: {e}", file=sys.stderr)
        self.browser, self.page, _ = await self._create_authed_browser()
        self._owns_browser = True

    async def _create_authed_browser(self):
        """Create a nodriver browser with auth cookies for this site."""
        cookie_result = extract_chrome_cookies([self.DOMAIN], decrypt=True)
        if not cookie_result.get("success"):
            return None, None, 0

        cookies = cookie_result["cookies"]
        browser = await uc.start(headless=True, browser_args=BROWSER_ARGS)
        page = await browser.get(f"https://www.{self.DOMAIN}")
        await page.sleep(1)

        injected = await inject_cookies(browser, cookies, self.DOMAIN)
        return browser, page, injected

    async def _acquire_from_pool(self):
        """Acquire browser from session pool daemon via Unix socket."""
        import asyncio
        import json

        reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
        request = json.dumps({"action": "acquire", "domain": self.DOMAIN})
        writer.write(request.encode() + b"\n")
        await writer.drain()

        # Cold starts take 10-15s (Chrome launch + navigate + cookies), warm is instant
        response = await asyncio.wait_for(reader.readline(), timeout=30)
        writer.close()
        await writer.wait_closed()

        data = json.loads(response.decode())
        if not data.get("success"):
            raise RuntimeError(data.get("error", "Pool acquire failed"))

        # Connect to existing Chrome via CDP (host+port triggers connect_existing in nodriver)
        host = data["host"]
        port = data["port"]
        browser = await uc.Browser.create(config=uc.Config(host=host, port=port))
        page = browser.main_tab
        return browser, page

    async def navigate(self, url: str, wait: int = 3):
        """Navigate to URL and wait for page load."""
        self.page = await self.browser.get(url)
        await self.page.sleep(wait)
        return self.page

    async def evaluate(self, js: str) -> dict:
        """Evaluate JS and parse CDP response to plain Python types."""
        raw = await self.page.evaluate(js)
        return parse_cdp_response(raw)

    async def close(self):
        """Release browser — return to pool or stop."""
        if self._from_pool:
            # Disconnect our CDP WebSocket without killing Chrome (daemon owns the process)
            try:
                if self.browser and self.browser.connection:
                    await self.browser.connection.disconnect()
            except Exception:
                pass
            # Tell daemon we're done
            try:
                import asyncio
                import json
                reader, writer = await asyncio.open_unix_connection(str(SOCKET_PATH))
                request = json.dumps({"action": "release", "domain": self.DOMAIN})
                writer.write(request.encode() + b"\n")
                await writer.drain()
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        elif self._owns_browser and self.browser:
            self.browser.stop()

    # ── Abstract methods (must implement) ─────────────────────────────────

    @abstractmethod
    async def search(self, query: str, limit: int = 5) -> dict:
        """Search for products."""

    @abstractmethod
    async def check_price(self, product_id: str) -> dict:
        """Get price/availability for a product."""

    @abstractmethod
    async def product_details(self, product_id: str) -> dict:
        """Get full product details."""

    # ── Optional methods (not all sites support) ──────────────────────────

    async def add_to_cart(self, product_id: str) -> dict:
        return {"success": False, "error": f"{self.DISPLAY_NAME} add-to-cart not implemented"}

    async def view_cart(self) -> dict:
        return {"success": False, "error": f"{self.DISPLAY_NAME} cart not implemented"}

    async def my_orders(self, limit: int = 10) -> dict:
        return {"success": False, "error": f"{self.DISPLAY_NAME} orders not implemented"}
