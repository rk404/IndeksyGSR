"""URL scraping logic extracted from dashboard.py."""

from __future__ import annotations

import asyncio
import json
import platform
import random
import subprocess
import sys

from playwright.sync_api import ViewportSize

from app.pipeline.enums import BotSecuredPages
from app.pipeline.scrape import human_delay, human_scroll

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

try:
    import nest_asyncio
    loop = asyncio.get_event_loop()
    if type(loop).__module__.startswith("asyncio"):
        nest_asyncio.apply()
except Exception:
    pass

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/146.0.0.0 Safari/537.36",
]


def _get_launch_args() -> list[str]:
    system = platform.system().lower()
    base_args = [
        "--enable-gpu",
        "--disable-software-rasterizer",
        "--disable-blink-features=AutomationControlled",
    ]
    if "windows" in system:
        return base_args + ["--use-angle=d3d11"]
    elif "darwin" in system:
        return base_args + ["--use-angle=metal"]
    elif "linux" in system:
        return base_args + ["--use-gl=desktop"]
    return base_args


def _hide_browser_window() -> None:
    system = platform.system()
    try:
        if system == "Linux":
            result = subprocess.check_output(
                ["xdotool", "search", "--onlyvisible", "--class", "Chromium"]
            )
            for wid in result.decode().split():
                subprocess.call(["xdotool", "windowminimize", wid])
        elif system == "Windows":
            import win32gui
            import win32con
            def callback(hwnd, _):
                title = win32gui.GetWindowText(hwnd)
                if "Chrome" in title or "Chromium" in title:
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
            win32gui.EnumWindows(callback, None)
        elif system == "Darwin":
            result = subprocess.run(
                ["yabai", "-m", "query", "--windows"],
                capture_output=True, text=True,
            )
            windows = json.loads(result.stdout)
            for w in windows:
                if w["has-focus"]:
                    subprocess.run(["yabai", "-m", "window", str(w["id"]), "--minimize"])
                    return
    except Exception as e:
        print(f"[WARN] Nie udało się ukryć okna: {e}")


async def _async_scrape_url(url: str) -> dict:
    from playwright.async_api import async_playwright
    from app.core.extractors import extract

    async with async_playwright() as pw:
        args = _get_launch_args()
        browser = await pw.chromium.launch(headless=False, args=args)
        ctx = await browser.new_context(viewport=ViewportSize({"width": 1920, "height": 1080}))

        await ctx.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => false });

        const toDataURL = HTMLCanvasElement.prototype.toDataURL;
        HTMLCanvasElement.prototype.toDataURL = function(...args) {
            const ctx = this.getContext("2d");
            if (ctx) {
                const shift = {
                    r: Math.floor(Math.random() * 10),
                    g: Math.floor(Math.random() * 10),
                    b: Math.floor(Math.random() * 10),
                    a: Math.floor(Math.random() * 10)
                };
                const width = this.width;
                const height = this.height;
                if (width && height) {
                    const imageData = ctx.getImageData(0, 0, width, height);
                    for (let i = 0; i < imageData.data.length; i += 4) {
                        imageData.data[i + 0] += shift.r;
                        imageData.data[i + 1] += shift.g;
                        imageData.data[i + 2] += shift.b;
                        imageData.data[i + 3] += shift.a;
                    }
                    ctx.putImageData(imageData, 0, 0);
                }
            }
            return toDataURL.apply(this, args);
        };
        """)

        page = await ctx.new_page()
        await page.set_extra_http_headers({
            "User-Agent": random.choice(_USER_AGENTS),
            "Sec-CH-UA": '"Chromium";v="146", "Not-A.Brand";v="24", "Google Chrome";v="146"',
            "Accept-Language": "en-GB,en-US;q=0.9,en;q=0.8,pl;q=0.7",
        })

        try:
            _hide_browser_window()
            await page.goto(url, timeout=20_000, wait_until="load")

            if any(secured in url for secured in BotSecuredPages):
                await human_delay()
                await human_scroll(page)

            extracted = await extract(page, url)
            if not extracted.get("title") and not extracted.get("description"):
                body = await page.evaluate("() => document.body?.innerText || ''")
                extracted["description"] = body[:3000].strip()
                extracted["title"] = (await page.title()) or ""
        finally:
            await browser.close()

    return extracted


def scrape_url(url: str) -> dict:
    """Synchronous wrapper for URL scraping."""
    return asyncio.run(_async_scrape_url(url))


def build_query_from_scraped(data: dict) -> str:
    """Build a search query string from scraped product data."""
    parts = []
    if data.get("title"):
        parts.append(data["title"])
    specs = data.get("specifications") or {}
    if specs:
        parts.append(" ".join(f"{k} {v}" for k, v in list(specs.items())[:20]))
    if data.get("description"):
        parts.append(data["description"][:500])
    return " ".join(parts)[:1000]
