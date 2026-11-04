"""Chrome spike: fetch Douyin comment replies from a headed Chrome page.

Prerequisites:
  - Chrome launched via ./launch_chrome.sh (CDP on 127.0.0.1:9222)
  - spike/.venv with playwright installed

Usage:
  spike/.venv/bin/python spike/chrome-reply/fetch_replies.py \
      --video-id 7681929945538497843 \
      --comment-id 7682054941225698091

The script injects the login cookies, opens the video page, and calls the reply
endpoint from the page context. It saves raw pages under spike/out/ and prints a
PII-free summary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[2]
LOGIN_PATH = ROOT / ".secrets" / "import-login.json"
OUT_DIR = ROOT / "spike" / "out"

REPLY_BASE = "/aweme/v1/web/comment/list/reply/"


def base_common() -> dict[str, str]:
    return {
        "device_platform": "webapp",
        "aid": "6383",
        "channel": "channel_pc_web",
        "cut_version": "1",
        "item_type": "0",
        "update_version_code": "170400",
        "pc_client_type": "1",
        "pc_libra_divert": "Windows",
        "support_h265": "1",
        "support_dash": "1",
        "cpu_core_num": "20",
        "version_code": "170400",
        "version_name": "17.4.0",
        "cookie_enabled": "true",
        "screen_width": "1537",
        "screen_height": "960",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "154.0.0.0",
        "browser_online": "true",
        "engine_name": "Blink",
        "engine_version": "154.0.0.0",
        "os_name": "Windows",
        "os_version": "10",
        "device_memory": "32",
        "platform": "PC",
        "downlink": "10",
        "effective_type": "4g",
        "round_trip_time": "50",
    }

FETCH_JS = """async (url) => {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), 30000);
    try {
        const r = await fetch(url, {credentials: 'include', signal: ctrl.signal});
        const t = await r.text();
        return {status: r.status, bytes: t.length, body: t};
    } finally { clearTimeout(timer); }
}"""

CLICK_JS = """() => {
    const els = [...document.querySelectorAll('span,div,button,a')];
    const el = els.find(e => {
        const t = (e.innerText || '').trim();
        return t && t.length < 60 && /展开|更多/.test(t) && /回复/.test(t)
            && e.offsetParent !== null;
    });
    if (!el) return null;
    el.click();
    return (el.innerText || '').slice(0, 80);
}"""


def parse_cookies(header: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for part in header.split(";"):
        part = part.strip()
        if part and "=" in part:
            name, value = part.split("=", 1)
            if name:
                out[name] = value
    return out


def reply_path(
    common: dict[str, str], video_id: str, comment_id: str, cursor: str, count: int
) -> str:
    params = {
        **common,
        "item_id": video_id,
        "comment_id": comment_id,
        "cursor": cursor,
        "count": str(count),
    }
    return f"{REPLY_BASE}?{urlencode(params)}"


async def page_common(page: Any) -> dict[str, str]:
    info = await page.evaluate(
        """() => ({
            ua: navigator.userAgent,
            platform: navigator.platform,
            lang: navigator.language,
            width: screen.width,
            height: screen.height,
            cores: navigator.hardwareConcurrency,
            mem: navigator.deviceMemory || 8,
            uaPlatform: navigator.userAgentData ? navigator.userAgentData.platform : null,
            uaPlatformVersion: navigator.userAgentData ? navigator.userAgentData.platformVersion : null,
        })"""
    )
    common = base_common()
    ua = info.get("ua") or ""
    match = re.search(r"Chrome/(\d+)", ua)
    major = match.group(1) if match else "148"
    version = f"{major}.0.0.0"
    os_name = info.get("uaPlatform") or ("Linux" if "Linux" in ua else "Windows")
    common.update(
        {
            "browser_version": version,
            "engine_version": version,
            "browser_platform": info.get("platform") or "Linux x86_64",
            "browser_language": info.get("lang") or "zh-CN",
            "screen_width": str(info.get("width") or 1537),
            "screen_height": str(info.get("height") or 960),
            "cpu_core_num": str(info.get("cores") or 20),
            "device_memory": str(info.get("mem") or 8),
            "os_name": os_name,
            "os_version": info.get("uaPlatformVersion") or "10",
            "pc_libra_divert": os_name,
        }
    )
    return common


def summarize(payload: dict[str, Any]) -> dict[str, Any]:
    comments = payload.get("comments") or []
    rows = []
    for c in comments[:8]:
        user = c.get("user") or {}
        labels = c.get("label_list") or []
        rows.append(
            {
                "cid": c.get("cid"),
                "reply_id": c.get("reply_id"),
                "reply_to_reply_id": c.get("reply_to_reply_id"),
                "ip_label": c.get("ip_label"),
                "reply_comment_total": c.get("reply_comment_total"),
                "digg_count": c.get("digg_count"),
                "label_texts": [x.get("text") for x in labels if isinstance(x, dict)],
                "sec_uid_len": len(user.get("sec_uid") or ""),
                "has_uid": bool(user.get("uid")),
            }
        )
    return {
        "status_code": payload.get("status_code"),
        "comment_count": len(comments),
        "has_more": payload.get("has_more"),
        "cursor": payload.get("cursor"),
        "total": payload.get("total"),
        "rows": rows,
    }


async def page_fetch(page: Any, path: str) -> dict[str, Any]:
    return await asyncio.wait_for(page.evaluate(FETCH_JS, path), timeout=40)


async def ui_fetch(page: Any) -> dict[str, Any] | None:
    try:
        async with page.expect_response(
            lambda r: "comment/list/reply" in r.url, timeout=30_000
        ) as info:
            clicked = await page.evaluate(CLICK_JS)
            if not clicked:
                print("ui fallback: no visible '展开回复' element", flush=True)
                return None
            print(f"ui fallback: clicked {clicked!r}", flush=True)
        resp = await info.value
        body = await resp.text()
        return {"status": resp.status, "bytes": len(body), "body": body}
    except Exception as exc:
        print(f"ui fallback failed: {type(exc).__name__}: {str(exc)[:200]}", flush=True)
        return None


def save_page(comment_id: str, page_no: int, body: str) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"reply_{comment_id}_p{page_no}.json"
    path.write_text(body, encoding="utf-8")
    path.chmod(0o600)
    return path


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--video-id", default="7681929945538497843")
    parser.add_argument("--comment-id", default="7682054941225698091")
    parser.add_argument("--first-count", type=int, default=3)
    parser.add_argument("--page-count", type=int, default=10)
    parser.add_argument("--max-pages", type=int, default=20)
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--skip-ui", action="store_true")
    parser.add_argument("--login-file", default=str(LOGIN_PATH))
    parser.add_argument(
        "--no-cookies",
        action="store_true",
        help="Use the browser's existing session (e.g. after QR login), not import-login.json.",
    )
    args = parser.parse_args()

    login = json.loads(Path(args.login_file).read_text(encoding="utf-8"))
    cookies = {} if args.no_cookies else parse_cookies(login["cookies"])
    url = f"https://www.douyin.com/video/{args.video_id}"
    print(f"cookies={len(cookies)} video={args.video_id} comment={args.comment_id}", flush=True)

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(args.cdp)
        context = browser.contexts[0] if browser.contexts else await browser.new_context()
        if cookies:
            await context.add_cookies(
                [
                    {"name": name, "value": value, "domain": ".douyin.com", "path": "/"}
                    for name, value in cookies.items()
                ]
            )
        await context.set_extra_http_headers({"Accept-Language": "zh-CN,zh;q=0.9"})
        page = context.pages[0] if context.pages else await context.new_page()
        page.on("requestfailed", lambda req: print(f"REQFAIL {req.url[:140]}", flush=True))
        await page.bring_to_front()
        print(f"navigating {url}", flush=True)
        await page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        print("title:", (await page.title())[:80], flush=True)
        try:
            diag = await page.evaluate(
                "() => ({ua: navigator.userAgent, ready: document.readyState,"
                " body: (document.body && document.body.innerText || '').slice(0,160)})"
            )
            print("diag:", json.dumps(diag, ensure_ascii=False), flush=True)
        except Exception as exc:
            print("diag failed:", type(exc).__name__, flush=True)
        await page.wait_for_timeout(6_000)
        try:
            await page.evaluate(
                """() => {
                    const hush = (el) => {
                        if (el instanceof HTMLMediaElement) { el.muted = true; el.pause(); }
                    };
                    document.querySelectorAll('video, audio').forEach(hush);
                    document.addEventListener('play', (e) => hush(e.target), true);
                }"""
            )
        except Exception:
            pass

        common = await page_common(page)
        print(
            "common:",
            {
                k: common[k]
                for k in (
                    "browser_version",
                    "browser_platform",
                    "os_name",
                    "os_version",
                    "screen_width",
                    "screen_height",
                    "cpu_core_num",
                    "device_memory",
                )
            },
            flush=True,
        )
        first_path = reply_path(common, args.video_id, args.comment_id, "0", args.first_count)
        try:
            result = await page_fetch(page, first_path)
            print(f"first fetch: status={result.get('status')} bytes={result.get('bytes')}", flush=True)
        except Exception as exc:
            print(f"first fetch failed: {type(exc).__name__}", flush=True)
            result = {"status": None, "bytes": 0, "body": ""}

        if not result.get("body") and not args.skip_ui:
            result = await ui_fetch(page) or result

        body = result.get("body") or ""
        if not body:
            print("no reply body; page body snippet:", flush=True)
            try:
                text = await page.evaluate("() => (document.body && document.body.innerText || '').slice(0,300)")
                print(text, flush=True)
            except Exception:
                pass
            await browser.close()
            return 1

        payload = json.loads(body)
        save_page(args.comment_id, 1, body)
        print("page 1:", json.dumps(summarize(payload), ensure_ascii=False, indent=2), flush=True)

        pages = [payload]
        cursor = payload.get("cursor")
        has_more = payload.get("has_more")
        while has_more and cursor and len(pages) < args.max_pages and result.get("status") == 200:
            path = reply_path(common, args.video_id, args.comment_id, str(cursor), args.page_count)
            try:
                result = await page_fetch(page, path)
            except Exception as exc:
                print(f"page {len(pages)+1} failed: {type(exc).__name__}", flush=True)
                break
            if not result.get("body"):
                print(f"page {len(pages)+1}: empty", flush=True)
                break
            p = json.loads(result["body"])
            save_page(args.comment_id, len(pages) + 1, result["body"])
            pages.append(p)
            cursor = p.get("cursor")
            has_more = p.get("has_more")
            print(
                f"page {len(pages)}: status={result.get('status')} bytes={result.get('bytes')} "
                f"comments={len(p.get('comments') or [])} has_more={has_more} cursor={cursor}",
                flush=True,
            )

        all_comments = [c for p in pages for c in (p.get("comments") or [])]
        unique = {c.get("cid") for c in all_comments if c.get("cid")}
        ip = sum(1 for c in all_comments if c.get("ip_label") is not None)
        rtr = sum(
            1
            for c in all_comments
            if c.get("reply_to_reply_id") not in (None, "0", "-1")
        )
        creator = sum(
            1
            for c in all_comments
            if any(
                isinstance(x, dict) and x.get("text") == "Creator"
                for x in (c.get("label_list") or [])
            )
        )
        print(
            json.dumps(
                {
                    "pages": len(pages),
                    "comments": len(all_comments),
                    "unique": len(unique),
                    "duplicates": len(all_comments) - len(unique),
                    "ip_label": ip,
                    "reply_to_reply_id_nonzero": rtr,
                    "creator_label": creator,
                },
                ensure_ascii=False,
                indent=2,
            ),
            flush=True,
        )
        await browser.close()
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
