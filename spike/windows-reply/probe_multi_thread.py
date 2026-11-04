"""Multi-thread reply probe (page-context fetch, read-only).

Validates the worker loop on several threads in one video page:

  - reuse one fully-loaded page (wrapper must be ready)
  - count=50, cursor paging until has_more is false
  - per-thread coverage / duplicates
  - orphan replies (reply_to_reply_id points to a missing reply)
  - depth distribution (depth>=3)
  - ip_label / label_text presence

It does NOT use context.request or any bare HTTP client: Round 001 showed
those return 200 + 0 bytes.

Usage (Windows, Chrome already running with CDP 9222 and logged in):

  python probe_multi_thread.py --targets targets.json --common-params common_params.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

from probe_reply import (
    JS_CAPTCHA,
    JS_ENV,
    JS_LOGIN_MODAL,
    build_bare_url,
    fetch_in_page,
    now_iso,
    save_json,
    save_text,
)
from probe_full_thread import make_template_url, page_metrics, result_summary, wrapper_info

DEFAULT_THREADS = [
    "7682054941225698091",  # 113 replies
    "7682239605306819385",  # 3 replies
    "7682223064176395049",  # 1 reply
]


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def thread_metrics(payloads: list[dict]) -> dict:
    by_id: dict[str, str | None] = {}
    parents: list[str] = []
    ip = 0
    label_text = 0
    label_list = 0
    creator_label = 0
    for payload in payloads:
        for c in payload.get("comments") or []:
            if not isinstance(c, dict):
                continue
            cid = c.get("cid")
            if not cid:
                continue
            parent = c.get("reply_to_reply_id")
            by_id[cid] = parent
            if parent not in (None, "0", "-1"):
                parents.append(str(parent))
            if c.get("ip_label") is not None:
                ip += 1
            if c.get("label_text"):
                label_text += 1
                if c.get("label_text") == "作者":
                    creator_label += 1
            if c.get("label_list"):
                label_list += 1

    memo: dict[str, int | None] = {}

    def depth(cid: str, stack: frozenset[str]) -> int | None:
        if cid in memo:
            return memo[cid]
        if cid in stack:
            return None
        parent = by_id.get(cid)
        if parent in (None, "0", "-1"):
            memo[cid] = 2
            return 2
        if parent not in by_id:
            memo[cid] = None
            return None
        d = depth(str(parent), stack | {cid})
        value = d + 1 if d is not None else None
        memo[cid] = value
        return value

    depths = {cid: depth(cid, frozenset()) for cid in by_id}
    depth3 = sum(1 for d in depths.values() if d is not None and d >= 3)
    orphan_parents = sorted({p for p in parents if p not in by_id})
    orphan_edges = sum(1 for p in parents if p not in by_id)

    return {
        "comments": len(by_id),
        "ip_label": ip,
        "label_text": label_text,
        "label_list": label_list,
        "creator_label": creator_label,
        "reply_to_reply_id_nonzero": len(parents),
        "depth3": depth3,
        "orphan_edges": orphan_edges,
        "orphan_parents_sample": orphan_parents[:10],
    }


def run_thread(
    page,
    args,
    template_url: str | None,
    thread_id: str,
    out: Path,
) -> dict:
    started = time.time()
    cursor = "0"
    pages: list[dict] = []
    payloads: list[dict] = []
    stop_reason: str | None = None

    for page_no in range(1, args.max_pages + 1):
        url = build_bare_url(
            args.video_id, thread_id, cursor, str(args.count), template_url
        )
        t0 = time.time()
        res = fetch_in_page(page, url, timeout_ms=args.fetch_timeout)
        elapsed = round(time.time() - t0, 2)
        summary = result_summary(res)
        body = res.get("body") or ""
        if summary.get("status") != 200 or summary.get("bytes", 0) == 0:
            pages.append(
                {
                    "page": page_no,
                    "status": summary.get("status"),
                    "bytes": summary.get("bytes"),
                    "n": None,
                    "has_more": None,
                    "cursor": None,
                    "total": None,
                    "seconds": elapsed,
                    "stop": "risk_control_or_empty",
                }
            )
            stop_reason = "risk_control"
            break
        try:
            payload = json.loads(body)
        except Exception:
            stop_reason = "bad_json"
            break
        payloads.append(payload)
        metrics = page_metrics(payload)
        pages.append(
            {
                "page": page_no,
                "status": summary.get("status"),
                "bytes": summary.get("bytes"),
                "n": metrics["n"],
                "unique_in_page": metrics["unique_in_page"],
                "has_more": metrics["has_more"],
                "cursor": metrics["cursor"],
                "total": metrics["total"],
                "seconds": elapsed,
            }
        )
        save_text(out / "responses" / f"{thread_id}_p{page_no}.json", body)
        log(
            f"thread {thread_id} page {page_no}: n={metrics['n']} "
            f"has_more={metrics['has_more']} cursor={metrics['cursor']} "
            f"total={metrics['total']}"
        )
        if not metrics["has_more"]:
            stop_reason = "complete"
            break
        if not metrics["cursor"] or str(metrics["cursor"]) == "0":
            stop_reason = "upstream_changed"
            break
        cursor = str(metrics["cursor"])
        page.wait_for_timeout(random.randint(1_500, 3_000))
    else:
        stop_reason = "max_pages"

    m = thread_metrics(payloads)
    unique = len(
        {
            c.get("cid")
            for payload in payloads
            for c in (payload.get("comments") or [])
            if isinstance(c, dict) and c.get("cid")
        }
    )
    fetched = sum(p["n"] for p in pages if p.get("n"))
    expected = None
    for p in pages:
        if p.get("total") is not None:
            expected = p["total"]
            break
    coverage = round(unique / expected, 4) if expected else None
    result = {
        "thread_id": thread_id,
        "count": args.count,
        "pages": pages,
        "fetched": fetched,
        "unique": unique,
        "duplicates": fetched - unique,
        "expected_total": expected,
        "coverage": coverage,
        "stop_reason": stop_reason,
        "elapsed_s": round(time.time() - started, 2),
        **m,
    }
    log(
        f"thread {thread_id} done: unique={unique}/{expected} "
        f"coverage={coverage} stop={stop_reason}"
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Multi-thread Douyin reply probe")
    parser.add_argument("--targets", default="")
    parser.add_argument("--common-params", default="common_params.json")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--video-id", default="7681929945538497843")
    parser.add_argument(
        "--threads",
        default=",".join(DEFAULT_THREADS),
        help="comma-separated root comment ids",
    )
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--fetch-timeout", type=int, default=20_000)
    parser.add_argument("--out", default="out")
    args = parser.parse_args()

    if args.targets:
        p = Path(args.targets)
        if not p.is_file():
            parser.error(f"targets file not found: {p}")
        data = json.loads(p.read_text(encoding="utf-8"))
        if data.get("video_id"):
            args.video_id = data["video_id"]
        if data.get("comment_id") and args.threads == ",".join(DEFAULT_THREADS):
            args.threads = (
                data["comment_id"]
                + ","
                + ",".join(t for t in DEFAULT_THREADS if t != data["comment_id"])
            )

    thread_ids = [t.strip() for t in args.threads.split(",") if t.strip()]
    if not thread_ids:
        parser.error("no thread ids")

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"multi-thread-{stamp}"
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
                out / "multi_thread_summary.json",
                {"login": login, "modal": modal, "captcha": captcha, "env": env},
            )
            return 3

        try:
            info = wrapper_info(page, timeout_s=30)
            wrapper_ready = "[native code]" not in (info.get("fetchHead") or "")
        except Exception as exc:  # noqa: BLE001
            info = {"error": repr(exc)}
            wrapper_ready = False
        save_json(out / "wrapper.json", {"info": info, "ready": wrapper_ready})
        if not wrapper_ready:
            log("wrapper not ready; stop")
            save_json(
                out / "multi_thread_summary.json",
                {"error": "wrapper_not_ready", "info": info, "env": env},
            )
            return 4

        template_url = make_template_url(args.common_params)
        threads: list[dict] = []
        global_stop = None
        for thread_id in thread_ids:
            try:
                result = run_thread(page, args, template_url, thread_id, out)
            except Exception as exc:  # noqa: BLE001
                result = {
                    "thread_id": thread_id,
                    "error": repr(exc),
                    "stop_reason": "exception",
                }
                log(f"thread {thread_id} exception: {exc}")
            threads.append(result)
            if result.get("stop_reason") == "risk_control":
                global_stop = "risk_control"
                break
            # Check login/captcha/wrapper between threads.
            try:
                modal = page.evaluate(JS_LOGIN_MODAL)
                captcha = page.evaluate(JS_CAPTCHA)
            except Exception:
                modal = None
                captcha = None
            if modal or captcha:
                global_stop = "login_or_captcha"
                break
            try:
                info2 = wrapper_info(page, timeout_s=5)
                fetch_head = info2.get("fetchHead") or ""
                if not fetch_head or "[native code]" in fetch_head:
                    global_stop = "wrapper_lost"
                    break
            except Exception:
                global_stop = "wrapper_check_error"
                break
            page.wait_for_timeout(random.randint(4_000, 7_000))

        summary = {
            "video_id": args.video_id,
            "thread_ids": thread_ids,
            "count": args.count,
            "wrapper": info,
            "wrapper_ready": wrapper_ready,
            "env": env,
            "login": login,
            "threads": threads,
            "global_stop": global_stop,
            "finished_at": now_iso(),
        }
        save_json(out / "multi_thread_summary.json", summary)

        report = [
            "# Multi-thread 探针报告",
            "",
            f"- 时间：{now_iso()}",
            f"- 视频：`{args.video_id}`",
            f"- count：{args.count}",
            f"- wrapper ready：{wrapper_ready}",
            f"- global stop：{global_stop}",
            "",
            "| thread | expected | fetched | unique | coverage | dup | ip_label | rtr | depth3 | orphans | stop | 秒 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|",
        ]
        for t in threads:
            report.append(
                f"| `{t.get('thread_id')}` | {t.get('expected_total')} "
                f"| {t.get('fetched')} | {t.get('unique')} | {t.get('coverage')} "
                f"| {t.get('duplicates')} | {t.get('ip_label')} "
                f"| {t.get('reply_to_reply_id_nonzero')} | {t.get('depth3')} "
                f"| {t.get('orphan_edges')} | {t.get('stop_reason')} "
                f"| {t.get('elapsed_s')} |"
            )
        report += [
            "",
            "## 说明",
            "",
            "- `orphans` = `reply_to_reply_id` 指向的父回复不在本线程抓取集合内。",
            "- `depth3` = 能还原到 depth>=3 的回复数。",
            "- `coverage` = unique / platform total；complete + coverage<1 是平台缺口。",
            "- 原始页在 `responses/`，报告只保留摘要。",
        ]
        (out / "multi_thread_report.md").write_text(
            "\n".join(report), encoding="utf-8"
        )
        log(f"done: {out.resolve()}")
        log("send back multi_thread_report.md and multi_thread_summary.json")
        try:
            page.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
