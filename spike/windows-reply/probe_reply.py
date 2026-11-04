"""Windows Douyin reply probe (read-only).

Connects to an already-running headed Chrome over CDP, opens one video page,
and runs four experiments:

  A. UI click + response interception (baseline)
  B. page-context bare fetch for a comment that is not visible
  C. replay a captured signed URL, then change cursor / comment_id
  D. inspect page globals for signing helpers (diagnostic only)

It never likes/follows/comments, never closes the browser, and never writes
cookie or request-header values to disk. Raw response bodies are written under
out/ (gitignored) for local analysis; report.md contains only a PII-minimized
summary.

Usage (Windows, Chrome already running with --remote-debugging-port=9222):

  python probe_reply.py ^
    --video-id 7681929945538497843 ^
    --comment-text "爷爷考虑到大家太热情会有安全隐患" ^
    --comment-id 7682054941225698091 ^
    --deep-comment-id 7682223064176395049

See README.md for the Chrome launch command and safety notes.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from playwright.sync_api import sync_playwright

REPLY_PATH = "/aweme/v1/web/comment/list/reply/"
DEFAULT_VIDEO = "7681929945537843"
DEFAULT_COMMENT = "7682054941225698091"
DEFAULT_COMMENT_TEXT = "爷爷考虑到大家太热情会有安全隐患"
DEFAULT_DEEP_COMMENT = "7682223064176395049"

# Header prefixes worth replaying. Values stay in memory only.
REPLAY_HEADER_PREFIXES = ("bd-ticket-guard", "uifid", "x-secsdk")
# Query params we never write to disk.
SENSITIVE_QUERY_KEYS = {
    "a_bogus",
    "msToken",
    "verifyFp",
    "fp",
    "webid",
    "uifid",
    "sessionid",
    "sessionid_ss",
    "sid_guard",
    "sid_tt",
    "passport_auth_status",
}

JS_FIND_THREAD = r"""
(targetText) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const target = norm(targetText);
  if (!target) return null;
  const nodes = [...document.querySelectorAll('div,li,section,article')];
  let best = null;
  for (const el of nodes) {
    if (el.offsetParent === null) continue;
    const btn = el.querySelector('.comment-reply-expand-btn');
    if (!btn) continue;
    const txt = norm(el.innerText);
    if (!txt || txt.length > 12000) continue;
    if (!txt.includes(target)) continue;
    const r = el.getBoundingClientRect();
    const area = Math.max(1, r.width * r.height);
    if (!best || area < best.area) best = {el, area, btn, txt};
  }
  if (!best) return null;
  best.el.setAttribute('data-douyin-probe-thread', '1');
  best.btn.setAttribute('data-douyin-probe-target', '1');
  const attrs = {};
  for (const a of best.el.attributes) {
    if (a.name.startsWith('data-')) attrs[a.name] = a.value;
  }
  return {
    snippet: best.txt.slice(0, 200),
    btnText: norm(best.btn.innerText),
    attrs,
  };
}
"""

JS_FIND_ANY_REPLY_BUTTON = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const btns = [...document.querySelectorAll('.comment-reply-expand-btn')]
    .filter(e => e.offsetParent !== null);
  if (!btns.length) return null;
  btns[0].setAttribute('data-douyin-probe-target', '1');
  return {count: btns.length, text: norm(btns[0].innerText)};
}
"""

JS_FIND_MORE_IN_THREAD = r"""
(targetText) => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const target = norm(targetText);
  let scope = document.querySelector('[data-douyin-probe-thread="1"]');
  if (!scope && target) {
    const nodes = [...document.querySelectorAll('div,li,section,article')];
    let best = null;
    for (const el of nodes) {
      if (el.offsetParent === null) continue;
      const btn = el.querySelector('.comment-reply-expand-btn');
      if (!btn) continue;
      const txt = norm(el.innerText);
      if (!txt || txt.length > 12000) continue;
      if (!txt.includes(target)) continue;
      const r = el.getBoundingClientRect();
      const area = Math.max(1, r.width * r.height);
      if (!best || area < best.area) best = {el, area};
    }
    if (best) {
      scope = best.el;
      scope.setAttribute('data-douyin-probe-thread', '1');
    }
  }
  if (!scope) scope = document;
  const candidates = [...scope.querySelectorAll('span,div,button,a')];
  let el = candidates.find(e => e.offsetParent !== null && norm(e.innerText) === '展开更多');
  if (!el) {
    el = candidates.find(e => e.offsetParent !== null && norm(e.innerText).includes('展开更多'));
  }
  if (!el) return null;
  el.setAttribute('data-douyin-probe-target', '1');
  return {text: norm(el.innerText), scoped: Boolean(scope && scope !== document)};
}
"""

JS_FIND_ANY_MORE = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const candidates = [...document.querySelectorAll('span,div,button,a')];
  const el = candidates.find(e => e.offsetParent !== null && norm(e.innerText) === '展开更多');
  if (!el) return null;
  el.setAttribute('data-douyin-probe-target', '1');
  return {text: norm(el.innerText), scoped: false};
}
"""

JS_SCROLL_COMMENTS = r"""
(dy) => {
  const el = document.querySelector('.route-scroll-container');
  if (el) {
    el.scrollTop = el.scrollTop + dy;
    return {tag: el.tagName, top: el.scrollTop, height: el.scrollHeight};
  }
  window.scrollBy(0, dy);
  return {tag: 'window', top: window.scrollY, height: document.body.scrollHeight};
}
"""

JS_LOGIN_MODAL = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const texts = ['扫码登录', '二维码登录', '手机扫码登录', '登录后查看'];
  const els = [...document.querySelectorAll('div,span,button,a')];
  for (const e of els) {
    if (e.offsetParent === null) continue;
    const t = norm(e.innerText);
    if (!t || t.length > 30) continue;
    if (texts.some(x => t === x || t.includes(x))) return t;
  }
  return null;
}
"""

JS_CAPTCHA = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const texts = ['安全验证', '滑块验证', '验证码', '请完成验证'];
  const els = [...document.querySelectorAll('div,span,button,a')];
  for (const e of els) {
    if (e.offsetParent === null) continue;
    const t = norm(e.innerText);
    if (!t || t.length > 40) continue;
    if (texts.some(x => t.includes(x))) return t;
  }
  return null;
}
"""

JS_ENV = r"""
() => {
  let webgl = null;
  try {
    const c = document.createElement('canvas');
    const gl = c.getContext('webgl') || c.getContext('experimental-webgl');
    if (gl) {
      const ext = gl.getExtension('WEBGL_debug_renderer_info');
      webgl = ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : gl.getParameter(gl.RENDERER);
    }
  } catch (e) {}
  return {
    ua: navigator.userAgent,
    webdriver: navigator.webdriver,
    platform: navigator.platform,
    language: navigator.language,
    webgl,
    href: location.href,
    title: document.title,
  };
}
"""

JS_GLOBALS = r"""
() => {
  const names = ['byted_acrawler', '_webmsxyw', 'bytedAcrawler', 'frontierSign', 'sign', 'a_bogus'];
  const out = {};
  for (const n of names) {
    try { out[n] = typeof window[n]; } catch (e) {}
  }
  const keys = Object.keys(window)
    .filter(k => /sign|bogus|acrawler|frontier/i.test(k))
    .slice(0, 50);
  return {names: out, keys};
}
"""

JS_MUTE = r"""
() => {
  document.querySelectorAll('video, audio').forEach(v => {
    try { v.muted = true; v.pause(); } catch (e) {}
  });
}
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def redact_url(url: str) -> str:
    parsed = urlparse(url)
    q = parse_qs(parsed.query, keep_blank_values=True)
    safe: dict[str, Any] = {}
    for k, vals in q.items():
        if k in SENSITIVE_QUERY_KEYS:
            safe[k] = "<redacted>"
        else:
            safe[k] = vals[0] if len(vals) == 1 else vals
    return urlunparse(parsed._replace(query=urlencode(safe, doseq=True)))


def query_dict(url: str) -> dict[str, str]:
    q = parse_qs(urlparse(url).query, keep_blank_values=True)
    return {k: (v[0] if v else "") for k, v in q.items()}


def parse_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"valid": False}
    comments = payload.get("comments") or []
    rows = []
    for c in comments[:8]:
        if not isinstance(c, dict):
            continue
        labels = c.get("label_list") or []
        rows.append(
            {
                "cid": c.get("cid"),
                "reply_id": c.get("reply_id"),
                "reply_to_reply_id": c.get("reply_to_reply_id"),
                "ip_label": c.get("ip_label"),
                "reply_comment_total": c.get("reply_comment_total"),
                "label_texts": [
                    x.get("text") for x in labels if isinstance(x, dict)
                ],
            }
        )
    return {
        "valid": True,
        "status_code": payload.get("status_code"),
        "n": len(comments),
        "has_more": payload.get("has_more"),
        "cursor": payload.get("cursor"),
        "total": payload.get("total"),
        "rows": rows,
    }


class Recorder:
    def __init__(self) -> None:
        self.reply_responses: list[dict[str, Any]] = []
        self.reply_requests: list[dict[str, Any]] = []
        self.failures: list[dict[str, Any]] = []

    def on_response(self, resp: Any) -> None:
        try:
            if REPLY_PATH not in resp.url:
                return
            if resp.status != 200:
                return
            body = resp.json()
            self.reply_responses.append(
                {
                    "url": redact_url(resp.url),
                    "raw_url": resp.url,
                    "status": resp.status,
                    "body": body,
                    "at": now_iso(),
                }
            )
        except Exception as exc:  # noqa: BLE001 - probe must not crash
            self.failures.append(
                {"url": redact_url(getattr(resp, "url", "")), "error": repr(exc)}
            )

    def on_request(self, req: Any) -> None:
        try:
            if REPLY_PATH not in req.url:
                return
            try:
                headers = req.all_headers()
            except Exception:
                headers = dict(req.headers)
            safe_headers = {
                k: v
                for k, v in headers.items()
                if k.lower().startswith(REPLAY_HEADER_PREFIXES)
            }
            self.reply_requests.append(
                {
                    "url": redact_url(req.url),
                    "raw_url": req.url,
                    "method": req.method,
                    "headers": safe_headers,
                    "header_names": sorted(headers.keys()),
                    "at": now_iso(),
                }
            )
        except Exception as exc:  # noqa: BLE001
            self.failures.append({"request_error": repr(exc)})

    def on_failed(self, req: Any) -> None:
        if REPLY_PATH in req.url:
            self.failures.append(
                {
                    "url": redact_url(req.url),
                    "failure": getattr(req, "failure", None),
                    "at": now_iso(),
                }
            )


def wait_for_new_reply(
    page: Any, rec: Recorder, before: int, timeout_ms: int = 20_000
) -> list[dict[str, Any]]:
    end = time.time() + timeout_ms / 1000.0
    while time.time() < end:
        if len(rec.reply_responses) > before:
            return rec.reply_responses[before:]
        page.wait_for_timeout(300)
    return []


def mark_and_click(page: Any) -> bool:
    loc = page.locator('[data-douyin-probe-target="1"]')
    try:
        if loc.count() == 0:
            return False
        loc.first.scroll_into_view_if_needed(timeout=3_000)
        loc.first.click(timeout=5_000)
        return True
    except Exception as exc:  # noqa: BLE001
        log(f"click failed: {type(exc).__name__}: {str(exc)[:160]}")
        return False
    finally:
        try:
            page.evaluate(
                "() => document.querySelectorAll('[data-douyin-probe-target]')"
                ".forEach(e => e.removeAttribute('data-douyin-probe-target'))"
            )
        except Exception:
            pass


def fetch_in_page(
    page: Any, url: str, headers: dict[str, str] | None = None, timeout_ms: int = 20_000
) -> dict[str, Any]:
    js = r"""
    async ({url, headers, timeout}) => {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), timeout);
      try {
        const r = await fetch(url, {
          credentials: 'include',
          headers: headers || {},
          signal: ctrl.signal,
        });
        const t = await r.text();
        return {status: r.status, bytes: t.length, body: t.slice(0, 200000)};
      } catch (e) {
        return {status: null, bytes: 0, body: '', error: String(e)};
      } finally {
        clearTimeout(timer);
      }
    }
    """
    try:
        return page.evaluate(
            js, {"url": url, "headers": headers or {}, "timeout": timeout_ms}
        )
    except Exception as exc:  # noqa: BLE001
        return {"status": None, "bytes": 0, "body": "", "error": str(exc)}


def result_fields(res: dict[str, Any]) -> dict[str, Any]:
    body = res.get("body") or ""
    parsed: dict[str, Any] | None = None
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


def build_bare_url(
    video_id: str, comment_id: str, cursor: str, count: str, template_url: str | None
) -> str:
    params: dict[str, Any] = {}
    if template_url:
        params = parse_qs(urlparse(template_url).query, keep_blank_values=True)
        params = {k: v for k, v in params.items() if k not in SENSITIVE_QUERY_KEYS}
        params = {k: (v[0] if isinstance(v, list) and v else v) for k, v in params.items()}
    else:
        params = {
            "device_platform": "webapp",
            "aid": "6383",
            "channel": "channel_pc_web",
            "pc_client_type": "1",
            "version_code": "170400",
            "version_name": "17.4.0",
            "cookie_enabled": "true",
            "platform": "PC",
            "browser_language": "zh-CN",
            "browser_platform": "Win32",
            "browser_name": "Chrome",
            "browser_online": "true",
            "engine_name": "Blink",
        }
    params.update(
        {
            "item_id": video_id,
            "comment_id": comment_id,
            "cursor": cursor,
            "count": count,
            "item_type": "0",
            "cut_version": "1",
        }
    )
    return f"https://www.douyin.com{REPLY_PATH}?{urlencode(params, doseq=True)}"


def build_variant_url(base_url: str, **overrides: str) -> str:
    parsed = urlparse(base_url)
    q = parse_qs(parsed.query, keep_blank_values=True)
    for k, v in overrides.items():
        q[k] = [v]
    return urlunparse(parsed._replace(query=urlencode(q, doseq=True)))


def test_a(page: Any, rec: Recorder, args: argparse.Namespace, out: Path) -> dict[str, Any]:
    started = time.time()
    result: dict[str, Any] = {
        "found": False,
        "fallback": False,
        "dom_attrs": None,
        "pages": [],
        "stop_reason": None,
        "elapsed_s": None,
    }

    page.wait_for_timeout(4_000)
    page.evaluate(JS_MUTE)

    found = None
    for i in range(args.max_scrolls):
        found = page.evaluate(JS_FIND_THREAD, args.comment_text)
        if found:
            break
        if i % 5 == 0:
            log(f"A: scrolling for target comment ({i}/{args.max_scrolls})")
        page.evaluate(JS_SCROLL_COMMENTS, 600)
        page.wait_for_timeout(random.uniform(1_500, 3_000))

    if found:
        result["found"] = True
        result["dom_attrs"] = found.get("attrs")
        log(f"A: target found: {found.get('snippet', '')[:80]}")
    else:
        log("A: target not found; falling back to first visible reply button")
        found = page.evaluate(JS_FIND_ANY_REPLY_BUTTON)
        if found:
            result["fallback"] = True
            log(f"A: fallback button count={found.get('count')}")

    if not found:
        result["stop_reason"] = "target_not_found"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    before = len(rec.reply_responses)
    if not mark_and_click(page):
        result["stop_reason"] = "click_failed"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    new = wait_for_new_reply(page, rec, before, args.response_timeout)
    if not new:
        result["stop_reason"] = "no_reply_response"
        result["elapsed_s"] = round(time.time() - started, 1)
        return result

    for page_no, resp in enumerate(new, 1):
        summary = parse_payload(resp.get("body"))
        summary["page"] = page_no
        summary["request_url"] = resp.get("url")
        result["pages"].append(summary)
        save_json(out / "responses" / f"A_page_{page_no}.json", resp.get("body"))
        log(
            f"A page {page_no}: n={summary.get('n')} "
            f"has_more={summary.get('has_more')} cursor={summary.get('cursor')}"
        )

    last = result["pages"][-1]
    for page_no in range(len(result["pages"]) + 1, args.max_pages + 1):
        if not last.get("has_more"):
            result["stop_reason"] = "complete"
            break
        more = page.evaluate(JS_FIND_MORE_IN_THREAD, args.comment_text)
        if not more:
            more = page.evaluate(JS_FIND_ANY_MORE)
        if not more:
            result["stop_reason"] = "no_more_button"
            break
        before = len(rec.reply_responses)
        if not mark_and_click(page):
            result["stop_reason"] = "click_failed"
            break
        new = wait_for_new_reply(page, rec, before, args.response_timeout)
        if not new:
            result["stop_reason"] = "no_reply_response"
            break
        for resp in new:
            summary = parse_payload(resp.get("body"))
            summary["page"] = page_no
            summary["request_url"] = resp.get("url")
            result["pages"].append(summary)
            save_json(out / "responses" / f"A_page_{page_no}.json", resp.get("body"))
            log(
                f"A page {page_no}: n={summary.get('n')} "
                f"has_more={summary.get('has_more')} cursor={summary.get('cursor')}"
            )
        last = result["pages"][-1]
    else:
        result["stop_reason"] = "max_pages"

    if not last.get("has_more"):
        result["stop_reason"] = "complete"
    elif result["stop_reason"] is None:
        result["stop_reason"] = "max_pages"
    result["elapsed_s"] = round(time.time() - started, 1)
    return result


def test_b(
    page: Any, args: argparse.Namespace, out: Path, template_url: str | None
) -> dict[str, Any]:
    url = build_bare_url(
        args.video_id, args.deep_comment_id, "0", args.first_count, template_url
    )
    log(f"B: bare fetch for deep comment {args.deep_comment_id}")
    res = fetch_in_page(page, url, timeout_ms=args.fetch_timeout)
    fields = result_fields(res)
    fields["comment_id"] = args.deep_comment_id
    fields["url_params"] = {
        k: v for k, v in query_dict(url).items() if k not in SENSITIVE_QUERY_KEYS
    }
    save_text(out / "responses" / "B_bare_fetch.json", res.get("body") or "")
    log(f"B: status={fields.get('status')} bytes={fields.get('bytes')} json={fields.get('json')}")
    return fields


def test_c(
    page: Any, rec: Recorder, args: argparse.Namespace, out: Path
) -> dict[str, Any]:
    target_requests = [
        r for r in rec.reply_requests
        if query_dict(r["raw_url"]).get("comment_id") == args.comment_id
    ]
    if not target_requests:
        target_requests = rec.reply_requests
    if not target_requests:
        return {"available": False, "reason": "no_captured_reply_request"}

    req = target_requests[-1]
    base_url = req["raw_url"]
    headers = req.get("headers") or {}
    last_cursor = None
    for resp in reversed(rec.reply_responses):
        payload = resp.get("body")
        if isinstance(payload, dict) and payload.get("cursor") is not None:
            last_cursor = str(payload.get("cursor"))
            break
    cursor_variant = last_cursor or "3"

    variants = [
        ("unchanged", base_url),
        ("cursor_changed", build_variant_url(base_url, cursor=cursor_variant)),
        (
            "comment_id_changed",
            build_variant_url(
                base_url, comment_id=args.deep_comment_id, cursor="0"
            ),
        ),
    ]
    results: dict[str, Any] = {
        "available": True,
        "header_names": sorted(headers.keys()),
        "variants": {},
    }
    for name, url in variants:
        log(f"C: replay {name}")
        res = fetch_in_page(page, url, headers=headers, timeout_ms=args.fetch_timeout)
        fields = result_fields(res)
        fields["url_params"] = {
            k: v for k, v in query_dict(url).items() if k not in SENSITIVE_QUERY_KEYS
        }
        results["variants"][name] = fields
        save_text(out / "responses" / f"C_{name}.json", res.get("body") or "")
        log(
            f"C {name}: status={fields.get('status')} bytes={fields.get('bytes')} "
            f"json={fields.get('json')}"
        )
        if name == "unchanged" and not fields.get("json"):
            # If even an unchanged replay fails, changing params proves little.
            results["unchanged_failed"] = True
    return results


def test_d(page: Any, out: Path) -> dict[str, Any]:
    try:
        globals_info = page.evaluate(JS_GLOBALS)
    except Exception as exc:  # noqa: BLE001
        globals_info = {"error": str(exc)}
    save_json(out / "D_globals.json", globals_info)
    log(f"D: globals={globals_info}")
    return globals_info


def write_report(
    out: Path,
    env: dict[str, Any],
    login_ok: bool,
    a: dict[str, Any],
    b: dict[str, Any] | None,
    c: dict[str, Any] | None,
    d: dict[str, Any] | None,
    rec: Recorder,
    args: argparse.Namespace,
) -> None:
    lines: list[str] = []
    lines.append("# Windows 回复探针报告")
    lines.append("")
    lines.append(f"- 时间：{now_iso()}")
    lines.append(f"- 视频：`{args.video_id}`")
    lines.append(f"- 目标评论：`{args.comment_id}`")
    lines.append(f"- 深评论：`{args.deep_comment_id}`")
    lines.append(f"- 登录态：{'yes' if login_ok else 'no'}")
    lines.append(f"- UA：`{env.get('ua')}`")
    lines.append(f"- webdriver：`{env.get('webdriver')}`")
    lines.append(f"- WebGL：`{env.get('webgl')}`")
    lines.append("")
    lines.append("## A. UI 点击 + 监听")
    lines.append("")
    if a:
        lines.append(f"- 找到目标评论：{a.get('found')}（fallback={a.get('fallback')}）")
        lines.append(f"- 停止原因：`{a.get('stop_reason')}`")
        lines.append(f"- 耗时：{a.get('elapsed_s')} s")
        lines.append("")
        lines.append("| 页 | n | has_more | cursor | total |")
        lines.append("|---|---|---|---|---|")
        for p in a.get("pages") or []:
            lines.append(
                f"| {p.get('page')} | {p.get('n')} | {p.get('has_more')} "
                f"| {p.get('cursor')} | {p.get('total')} |"
            )
    else:
        lines.append("- 未执行")
    lines.append("")
    lines.append("## B. 页面内 bare fetch")
    lines.append("")
    if b:
        lines.append(
            f"- status：{b.get('status')}；bytes：{b.get('bytes')}；"
            f"JSON：{b.get('json')}"
        )
    else:
        lines.append("- 未执行")
    lines.append("")
    lines.append("## C. 重放签名 URL")
    lines.append("")
    if c and c.get("available"):
        lines.append(f"- 捕获请求头名：{', '.join(c.get('header_names') or [])}")
        lines.append("")
        lines.append("| 变体 | status | bytes | JSON 摘要 |")
        lines.append("|---|---|---|---|")
        for name, v in (c.get("variants") or {}).items():
            lines.append(
                f"| {name} | {v.get('status')} | {v.get('bytes')} "
                f"| {json.dumps(v.get('json'), ensure_ascii=False)} |"
            )
    else:
        lines.append(f"- 未执行：{(c or {}).get('reason', 'n/a')}")
    lines.append("")
    lines.append("## D. 页面 globals")
    lines.append("")
    lines.append(f"```json\n{json.dumps(d or {}, ensure_ascii=False, indent=2)}\n```")
    lines.append("")
    lines.append("## 风险与失败")
    lines.append("")
    lines.append(f"- 捕获 reply 响应：{len(rec.reply_responses)}")
    lines.append(f"- 捕获 reply 请求：{len(rec.reply_requests)}")
    lines.append(f"- 失败/异常：{len(rec.failures)}")
    for f in rec.failures[:10]:
        lines.append(f"  - `{json.dumps(f, ensure_ascii=False)}`")
    lines.append("")
    lines.append("## 结论（自动）")
    lines.append("")
    a_ok = bool(a and a.get("pages") and a.get("stop_reason") in ("complete", "max_pages"))
    lines.append(f"- A 基线：{'PASS' if a_ok else 'FAIL'}")
    b_ok = bool(b and b.get("json") and (b.get("json") or {}).get("n"))
    lines.append(f"- B bare fetch：{'PASS' if b_ok else 'FAIL'}")
    c_ok = bool(
        c
        and c.get("available")
        and any(
            v.get("json") and (v.get("json") or {}).get("n")
            for k, v in (c.get("variants") or {}).items()
            if k != "unchanged"
        )
    )
    lines.append(f"- C 改参重放：{'PASS' if c_ok else 'FAIL'}")
    lines.append("")
    lines.append("> 原始响应在 `out/responses/`，不要提交到 git；报告只保留摘要。")
    (out / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Windows Douyin reply probe (read-only)")
    parser.add_argument("--targets", default="", help="UTF-8 JSON with video/comment ids and text")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--video-id", default=DEFAULT_VIDEO)
    parser.add_argument("--comment-id", default=DEFAULT_COMMENT)
    parser.add_argument("--comment-text", default=DEFAULT_COMMENT_TEXT)
    parser.add_argument("--deep-comment-id", default=DEFAULT_DEEP_COMMENT)
    parser.add_argument("--out", default="out")
    parser.add_argument("--max-scrolls", type=int, default=40)
    parser.add_argument("--max-pages", type=int, default=3)
    parser.add_argument("--first-count", type=int, default=3)
    parser.add_argument("--response-timeout", type=int, default=20_000)
    parser.add_argument("--fetch-timeout", type=int, default=20_000)
    parser.add_argument("--skip-b", action="store_true")
    parser.add_argument("--skip-c", action="store_true")
    parser.add_argument("--skip-d", action="store_true")
    args = parser.parse_args()

    if args.targets:
        target_path = Path(args.targets)
        if not target_path.is_file():
            parser.error(f"targets file not found: {target_path}")
        data = json.loads(target_path.read_text(encoding="utf-8"))
        for key in ("video_id", "comment_id", "comment_text", "deep_comment_id"):
            if key in data:
                setattr(args, key, data[key])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"run-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    log("read-only probe: no like/follow/comment; stop on captcha/login")
    log(f"output: {out.resolve()}")

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp)
        if not browser.contexts:
            log("no browser context; start Chrome with a user-data-dir")
            return 2
        context = browser.contexts[0]
        page = context.new_page()
        page.bring_to_front()
        rec = Recorder()
        page.on("response", rec.on_response)
        page.on("request", rec.on_request)
        page.on("requestfailed", rec.on_failed)

        url = f"https://www.douyin.com/video/{args.video_id}"
        log(f"navigate: {url}")
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
        except Exception as exc:  # noqa: BLE001
            log(f"goto failed: {type(exc).__name__}: {str(exc)[:200]}")
        page.wait_for_timeout(5_000)

        try:
            env = page.evaluate(JS_ENV)
        except Exception as exc:  # noqa: BLE001
            env = {"error": repr(exc)}
        cookies = {c["name"] for c in context.cookies()}
        login_ok = bool(cookies & {"sessionid", "sessionid_ss"})
        try:
            modal = page.evaluate(JS_LOGIN_MODAL)
        except Exception:
            modal = None
        try:
            captcha = page.evaluate(JS_CAPTCHA)
        except Exception:
            captcha = None
        log(
            f"env: ua={env.get('ua')} webdriver={env.get('webdriver')} "
            f"webgl={env.get('webgl')} login={login_ok} modal={modal} captcha={captcha}"
        )
        save_json(out / "env.json", {"env": env, "login": login_ok, "modal": modal, "captcha": captcha})

        if captcha:
            log(f"captcha detected: {captcha}; stop")
            save_json(out / "summary.json", {"error": "captcha", "env": env})
            return 3
        if modal:
            log(f"login modal detected: {modal}; scan/close it, then rerun")
            save_json(out / "summary.json", {"error": "login_modal", "env": env})
            return 5
        if not login_ok:
            log("not logged in; scan the QR in the Chrome window, then rerun")
            save_json(out / "summary.json", {"error": "not_logged_in", "env": env})
            return 4

        a = test_a(page, rec, args, out)
        save_json(out / "A_metrics.json", a)

        b = None
        if not args.skip_b:
            try:
                b = test_b(page, args, out, rec.reply_requests[-1]["raw_url"] if rec.reply_requests else None)
            except Exception as exc:  # noqa: BLE001
                b = {"error": repr(exc)}
                log(f"B failed: {exc}")
        save_json(out / "B_metrics.json", b)

        c = None
        if not args.skip_c:
            try:
                c = test_c(page, rec, args, out)
            except Exception as exc:  # noqa: BLE001
                c = {"error": repr(exc)}
                log(f"C failed: {exc}")
        save_json(out / "C_metrics.json", c)

        d = None
        if not args.skip_d:
            d = test_d(page, out)

        summary = {"env": env, "login": login_ok, "a": a, "b": b, "c": c, "d": d}
        save_json(out / "summary.json", summary)
        write_report(out, env, login_ok, a, b, c, d, rec, args)

        log(f"done: {out.resolve()}")
        log("send back report.md and summary.json; do NOT send cookies or headers")

        try:
            page.close()
        except Exception:
            pass
        # Do not close the browser or the context: it is the user's resident Chrome.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
