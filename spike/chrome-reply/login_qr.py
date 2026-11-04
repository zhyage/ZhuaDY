"""Open Douyin's login page in the server Chrome and save a QR screenshot.

Usage:
  # 1) screenshot only (leaves Chrome running)
  spike/.venv/bin/python spike/chrome-reply/login_qr.py

  # 2) after scanning, wait for the session and save cookies
  spike/.venv/bin/python spike/chrome-reply/login_qr.py --wait 180
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "spike" / "out"
COOKIE_FILE = ROOT / ".secrets" / "import-login-server.json"

CLICK_LOGIN_JS = """() => {
    const els = [...document.querySelectorAll('button,div,span,a')];
    const el = els.find(e => {
        const t = (e.innerText || '').trim();
        return (t === '登录' || t === '立即登录' || t === '扫码登录')
            && e.offsetParent !== null;
    });
    if (!el) return null;
    el.click();
    return (el.innerText || '').trim();
}"""

QR_JS = """() => {
    const els = [...document.querySelectorAll('canvas,img')];
    const el = els.find(e => e.offsetParent !== null && e.width >= 100 && e.height >= 100);
    if (!el) return null;
    const r = el.getBoundingClientRect();
    return {tag: el.tagName, x: r.x, y: r.y, w: r.width, h: r.height};
}"""

TEXTS_JS = """() => {
    const out = [];
    for (const e of document.querySelectorAll('button,div,span,a')) {
        const t = (e.innerText || '').trim();
        if (t && t.length < 24 && /登录|扫码|二维码|验证码/.test(t)) out.push(t);
    }
    return [...new Set(out)].slice(0, 20);
}"""


async def shot(page, name: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / name
    await page.screenshot(path=str(path), full_page=True)
    path.chmod(0o600)
    return path


async def do_screenshot(page) -> int:
    await page.bring_to_front()
    await page.goto("https://www.douyin.com/", wait_until="domcontentloaded", timeout=45_000)
    await page.wait_for_timeout(5_000)
    print("title:", (await page.title())[:100], flush=True)
    print("url:", page.url, flush=True)
    print("ua:", await page.evaluate("navigator.userAgent"), flush=True)
    print("saved:", await shot(page, "login_page.png"), flush=True)
    print("texts:", await page.evaluate(TEXTS_JS), flush=True)
    clicked = await page.evaluate(CLICK_LOGIN_JS)
    print("clicked:", clicked, flush=True)
    if clicked:
        await page.wait_for_timeout(3_000)
    print("saved:", await shot(page, "login_after_click.png"), flush=True)
    qr = await page.evaluate(QR_JS)
    print("qr element:", qr, flush=True)
    if qr:
        try:
            path = OUT / "login_qr.png"
            await page.screenshot(
                path=str(path),
                clip={"x": qr["x"], "y": qr["y"], "width": qr["w"], "height": qr["h"]},
            )
            path.chmod(0o600)
            print("saved:", path, flush=True)
        except Exception as exc:
            print("qr crop failed:", type(exc).__name__, str(exc)[:160], flush=True)
    body = await page.evaluate(
        "() => (document.body && document.body.innerText || '').slice(0, 400)"
    )
    print("body:", body.replace("\n", " | "), flush=True)
    return 0


async def do_wait(ctx, page, timeout: int) -> int:
    print(f"waiting up to {timeout}s for login; scan the QR screenshot...", flush=True)
    for i in range(timeout // 2):
        cookies = {
            c["name"]: c["value"]
            for c in await ctx.cookies()
            if "douyin" in (c.get("domain") or "")
        }
        if cookies.get("sessionid") or cookies.get("sid_guard"):
            print("login detected; douyin cookie count:", len(cookies), flush=True)
            header = "; ".join(f"{k}={v}" for k, v in cookies.items())
            payload = {
                "platform": "douyin",
                "cookies": header,
                "user_agent": await page.evaluate("navigator.userAgent"),
                "language": "zh-CN",
                "timezone": "Asia/Shanghai",
                "note": "server Chrome QR login",
                "dry_run": False,
            }
            COOKIE_FILE.parent.mkdir(parents=True, exist_ok=True)
            COOKIE_FILE.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            COOKIE_FILE.chmod(0o600)
            print("saved:", COOKIE_FILE, flush=True)
            try:
                print("saved:", await shot(page, "login_done.png"), flush=True)
            except Exception:
                pass
            return 0
        if i % 15 == 0:
            print(f"still waiting ({i*2}s)...", flush=True)
        await page.wait_for_timeout(2_000)
    print("login not detected before timeout", flush=True)
    return 1


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument(
        "--wait",
        type=int,
        default=0,
        help="Wait up to N seconds for the QR scan instead of taking screenshots.",
    )
    args = parser.parse_args()

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(args.cdp)
        ctx = browser.contexts[0] if browser.contexts else await browser.new_context()
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        if args.wait:
            return await do_wait(ctx, page, args.wait)
        return await do_screenshot(page)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
