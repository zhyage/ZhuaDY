"""Signature mechanism check for Douyin reply requests (read-only).

Answers one question the first probe could not:

  Does a page-context fetch work because the page's JS wraps fetch and adds
  a_bogus / msToken / bd-ticket-guard headers, or because the endpoint truly
  accepts a bare request?

Tests:
  S1. Is window.fetch / XMLHttpRequest.open native?
  S2. Capture the actual network request for a page-context bare fetch:
      did a_bogus / msToken / bd-ticket-guard appear?
  S3. Same fetch from a same-origin page without the Douyin app JS.
  S4. Playwright context.request.get (no page JS).

Usage (Windows, Chrome already running with CDP 9222 and logged in):

  python probe_signature.py --targets targets.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from probe_reply import (
    JS_CAPTCHA,
    JS_ENV,
    JS_LOGIN_MODAL,
    Recorder,
    build_bare_url,
    fetch_in_page,
    now_iso,
    parse_payload,
    query_dict,
    save_json,
    save_text,
)

JS_FETCH_INFO = r"""
() => ({
  href: location.href,
  origin: location.origin,
  fetchHead: window.fetch.toString().slice(0, 300),
  xhrHead: XMLHttpRequest.prototype.open.toString().slice(0, 300),
})
"""


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def result_summary(res: dict) -> dict:
    body = res.get("body") or ""
    parsed = None
    try:
        parsed = parse_payload(json.loads(body)) if body else None
    except Exception:
        parsed = None
    return {
        "status": res.get("status"),
        "bytes": res.get("bytes"),
        "error": res.get("error"),
        "json": parsed,
    }


def actual_request_info(rec: Recorder, comment_id: str) -> dict:
    candidates = [
        r for r in rec.reply_requests
        if query_dict(r["raw_url"]).get("comment_id") == comment_id
    ]
    if not candidates:
        candidates = rec.reply_requests
    if not candidates:
        return {"captured": False}
    req = candidates[-1]
    q = query_dict(req["raw_url"])
    header_names = [str(h).lower() for h in (req.get("header_names") or [])]
    return {
        "captured": True,
        "url": req.get("url"),
        "param_names": sorted(q.keys()),
        "has_a_bogus": "a_bogus" in q,
        "has_ms_token": "msToken" in q,
        "has_verify_fp": "verifyFp" in q or "fp" in q,
        "has_webid": "webid" in q,
        "has_uifid": "uifid" in q,
        "has_ticket_guard": any(h.startswith("bd-ticket-guard") for h in header_names),
        "header_names": header_names,
    }


def try_same_origin_page(context, bare_url: str, out: Path) -> dict:
    """S3a: text/plain robots.txt page (same origin, no app JS)."""
    page = context.new_page()
    try:
        page.goto(
            "https://www.douyin.com/robots.txt",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        page.wait_for_timeout(1_000)
        info = page.evaluate(JS_FETCH_INFO)
        res = fetch_in_page(page, bare_url, timeout_ms=20_000)
        fields = result_summary(res)
        save_text(out / "signature_same_origin_robots.txt", res.get("body") or "")
        return {"mode": "robots.txt", "page": info, "result": fields}
    except Exception as exc:  # noqa: BLE001
        return {"mode": "robots.txt", "error": repr(exc)}
    finally:
        try:
            page.close()
        except Exception:
            pass


def try_blocked_app_page(context, bare_url: str, out: Path) -> dict:
    """S3b: douyin.com with external scripts blocked, so window.fetch stays native."""
    page = context.new_page()

    def handler(route):
        try:
            if route.request.resource_type == "script":
                route.abort()
            else:
                route.continue_()
        except Exception:
            pass

    try:
        page.route("**/*", handler)
        page.goto(
            "https://www.douyin.com/",
            wait_until="domcontentloaded",
            timeout=45_000,
        )
        page.wait_for_timeout(3_000)
        try:
            page.unroute("**/*", handler)
        except Exception:
            pass
        info = page.evaluate(JS_FETCH_INFO)
        res = fetch_in_page(page, bare_url, timeout_ms=20_000)
        fields = result_summary(res)
        save_text(out / "signature_blocked_app_page.json", res.get("body") or "")
        return {"mode": "blocked_app", "page": info, "result": fields}
    except Exception as exc:  # noqa: BLE001
        return {"mode": "blocked_app", "error": repr(exc)}
    finally:
        try:
            page.close()
        except Exception:
            pass


def try_context_request(context, bare_url: str, out: Path) -> dict:
    """S4: Playwright APIRequestContext, no page JS."""
    try:
        resp = context.request.get(
            bare_url,
            headers={
                "Referer": "https://www.douyin.com/",
                "Origin": "https://www.douyin.com",
                "Accept": "application/json, text/plain, */*",
            },
            timeout=20_000,
        )
        body = resp.text()
        parsed = None
        try:
            parsed = parse_payload(json.loads(body)) if body else None
        except Exception:
            parsed = None
        save_text(out / "signature_context_request.json", body)
        return {"status": resp.status, "bytes": len(body), "json": parsed}
    except Exception as exc:  # noqa: BLE001
        return {"error": repr(exc)}


def write_report(out: Path, payload: dict) -> None:
    actual = payload.get("page_fetch", {}).get("actual_request", {})
    ctx = payload.get("context_request", {})
    same = payload.get("same_origin", {})

    wrapper = bool(
        actual.get("has_a_bogus")
        or actual.get("has_ms_token")
        or actual.get("has_ticket_guard")
    )
    context_ok = bool((ctx.get("json") or {}).get("n"))
    same_ok = bool(
        (same.get("robots", {}).get("result", {}).get("json") or {}).get("n")
        or (same.get("blocked", {}).get("result", {}).get("json") or {}).get("n")
    )

    if not actual.get("captured"):
        conclusion = "未捕获到 S2 的实际请求；看 S3/S4，不能仅凭 B 判断免签。"
        if same_ok or context_ok:
            conclusion += " 同源无 app JS / context.request 能拿到数据，更接近免签。"
    elif wrapper:
        conclusion = (
            "页面 wrapper 自动补签名/头；生产必须保留完整加载的抖音页面。"
        )
    elif context_ok or same_ok:
        conclusion = (
            "未发现 page wrapper 签名，且无页面 JS 的请求可拿到数据；"
            "接口很可能不依赖页面 JS（但仍建议用页面上下文降低风险）。"
        )
    else:
        conclusion = (
            "未捕获到明显签名参数，但无页面 JS 的请求失败；不能定论，"
            "可能是 TLS/指纹或页面上下文要求。"
        )

    lines = [
        "# 签名机制补充实验",
        "",
        f"- 时间：{now_iso()}",
        f"- 视频：`{payload.get('video_id')}`",
        f"- 深评论：`{payload.get('deep_comment_id')}`",
        f"- 登录：{payload.get('login')}",
        f"- `window.fetch` native：{payload.get('native', {}).get('fetch_native')}",
        f"- `XMLHttpRequest.open` native：{payload.get('native', {}).get('xhr_native')}",
        "",
        "## S1. fetch 是否被包裹",
        "",
        f"- fetch head：`{str(payload.get('fetch_info', {}).get('fetchHead'))[:160]}`",
        f"- xhr head：`{str(payload.get('fetch_info', {}).get('xhrHead'))[:160]}`",
        "",
        "## S2. 页面内 bare fetch 的实际请求",
        "",
        f"- 捕获到请求：{actual.get('captured')}",
        f"- 实际参数名：{', '.join(actual.get('param_names') or [])}",
        f"- 实际出现 `a_bogus`：{actual.get('has_a_bogus')}",
        f"- 实际出现 `msToken`：{actual.get('has_ms_token')}",
        f"- 实际出现 ticket-guard 头：{actual.get('has_ticket_guard')}",
        f"- 响应：`{json.dumps(payload.get('page_fetch', {}).get('summary'), ensure_ascii=False)}`",
        "",
        "## S3. 同源无 app JS 页面",
        "",
        f"- robots.txt：`{json.dumps(same.get('robots'), ensure_ascii=False)}`",
        f"- blocked app：`{json.dumps(same.get('blocked'), ensure_ascii=False)}`",
        "",
        "## S4. context.request（无页面 JS）",
        "",
        f"- `{json.dumps(ctx, ensure_ascii=False)}`",
        "",
        "## 结论（自动）",
        "",
        f"- {conclusion}",
        "",
        "> 原始 body 在 `out/signature_*.json`；报告只保留摘要。",
    ]
    (out / "signature_report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Douyin reply signature check")
    parser.add_argument("--targets", default="")
    parser.add_argument("--common-params", default="common_params.json")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--video-id", default="7681929945538497843")
    parser.add_argument("--comment-id", default="7682054941225698091")
    parser.add_argument("--deep-comment-id", default="7682223064176395049")
    parser.add_argument("--out", default="out")
    args = parser.parse_args()

    if args.targets:
        target_path = Path(args.targets)
        if not target_path.is_file():
            parser.error(f"targets file not found: {target_path}")
        data = json.loads(target_path.read_text(encoding="utf-8"))
        for key in ("video_id", "comment_id", "deep_comment_id"):
            if key in data:
                setattr(args, key, data[key])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"signature-{stamp}"
    out.mkdir(parents=True, exist_ok=True)
    log(f"output: {out.resolve()}")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp)
        if not browser.contexts:
            log("no browser context")
            return 2
        context = browser.contexts[0]
        page = context.new_page()
        page.bring_to_front()

        try:
            page.goto(
                f"https://www.douyin.com/video/{args.video_id}",
                wait_until="domcontentloaded",
                timeout=45_000,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"goto failed: {exc}")
        page.wait_for_timeout(5_000)

        try:
            env = page.evaluate(JS_ENV)
        except Exception as exc:  # noqa: BLE001
            env = {"error": repr(exc)}
        cookies = {c["name"] for c in context.cookies()}
        login = bool(cookies & {"sessionid", "sessionid_ss"})
        try:
            modal = page.evaluate(JS_LOGIN_MODAL)
        except Exception:
            modal = None
        try:
            captcha = page.evaluate(JS_CAPTCHA)
        except Exception:
            captcha = None
        log(f"login={login} modal={modal} captcha={captcha}")

        if not login or modal or captcha:
            save_json(
                out / "signature_summary.json",
                {"login": login, "modal": modal, "captcha": captcha, "env": env},
            )
            log("login/captcha issue; stop")
            return 3

        info = page.evaluate(JS_FETCH_INFO)
        native = {
            "fetch_native": "[native code]" in (info.get("fetchHead") or ""),
            "xhr_native": "[native code]" in (info.get("xhrHead") or ""),
        }

        template_url = None
        if args.common_params:
            cp_path = Path(args.common_params)
            if cp_path.is_file():
                cp = json.loads(cp_path.read_text(encoding="utf-8"))
                template_url = (
                    "https://www.douyin.com/aweme/v1/web/comment/list/reply/?"
                    + urlencode(cp, doseq=True)
                )
            else:
                log(f"common params not found: {cp_path}; using minimal params")
        bare_url = build_bare_url(
            args.video_id, args.deep_comment_id, "0", "3", template_url
        )
        rec = Recorder()
        page.on("response", rec.on_response)
        page.on("request", rec.on_request)
        page.on("requestfailed", rec.on_failed)
        # Only keep requests triggered by the S2 fetch.
        rec.reply_requests.clear()
        rec.reply_responses.clear()

        log("S2: page-context bare fetch")
        page_res = fetch_in_page(page, bare_url, timeout_ms=20_000)
        page.wait_for_timeout(1_000)
        save_text(out / "signature_page_fetch.json", page_res.get("body") or "")
        actual = actual_request_info(rec, args.deep_comment_id)

        log("S3: same-origin pages")
        robots = try_same_origin_page(context, bare_url, out)
        blocked = try_blocked_app_page(context, bare_url, out)

        log("S4: context.request")
        ctx_res = try_context_request(context, bare_url, out)

        payload = {
            "video_id": args.video_id,
            "comment_id": args.comment_id,
            "deep_comment_id": args.deep_comment_id,
            "env": env,
            "login": login,
            "fetch_info": info,
            "native": native,
            "page_fetch": {
                "summary": result_summary(page_res),
                "actual_request": actual,
            },
            "same_origin": {"robots": robots, "blocked": blocked},
            "context_request": ctx_res,
        }
        save_json(out / "signature_summary.json", payload)
        write_report(out, payload)

        log(f"done: {out.resolve()}")
        log("send back signature_report.md and signature_summary.json")
        try:
            page.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
