"""Full-thread reply probe (page-context fetch, read-only).

Round 001 confirmed that the Douyin page wraps window.fetch/XMLHttpRequest and
adds a_bogus / msToken / bd-ticket-guard automatically. This probe uses that
page-context fetch to:

  - try count=50 (fallback to 20/10 if needed)
  - page a full thread until has_more is false
  - compare fetched unique replies with the platform `total`
  - record per-page timing, duplicates, field presence

It does NOT test bare HTTP clients; those are known to return 200 + 0 bytes.

Usage (Windows, Chrome already running with CDP 9222 and logged in):

  python probe_full_thread.py --targets targets.json --common-params common_params.json
"""

from __future__ import annotations

import argparse
import json
import random
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from probe_reply import (
    JS_CAPTCHA,
    JS_ENV,
    JS_LOGIN_MODAL,
    build_bare_url,
    fetch_in_page,
    now_iso,
    parse_payload,
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


def page_metrics(payload: dict) -> dict:
    comments = payload.get("comments") or []
    cids = [
        c.get("cid")
        for c in comments
        if isinstance(c, dict) and c.get("cid")
    ]
    ip = sum(
        1
        for c in comments
        if isinstance(c, dict) and c.get("ip_label") is not None
    )
    rtr = sum(
        1
        for c in comments
        if isinstance(c, dict)
        and c.get("reply_to_reply_id") not in (None, "0", "-1")
    )
    return {
        "n": len(comments),
        "unique_in_page": len(set(cids)),
        "cids": cids,
        "ip_label": ip,
        "reply_to_reply_id_nonzero": rtr,
        "has_more": bool(payload.get("has_more")),
        "cursor": payload.get("cursor"),
        "total": payload.get("total"),
    }


def wrapper_info(page, timeout_s: int = 30) -> dict:
    deadline = time.time() + timeout_s
    info = page.evaluate(JS_FETCH_INFO)
    while time.time() < deadline:
        if "[native code]" not in (info.get("fetchHead") or ""):
            return info
        page.wait_for_timeout(1_000)
        info = page.evaluate(JS_FETCH_INFO)
    return info


def make_template_url(common_params_path: str) -> str | None:
    if not common_params_path:
        return None
    p = Path(common_params_path)
    if not p.is_file():
        return None
    params = json.loads(p.read_text(encoding="utf-8"))
    return (
        "https://www.douyin.com/aweme/v1/web/comment/list/reply/?"
        + urlencode(params, doseq=True)
    )


def try_first_page(
    page, args, template_url: str | None
) -> tuple[int | None, dict | None, dict | None, list[dict]]:
    attempts: list[dict] = []
    for count in [args.count, 20, 10]:
        if count <= 0:
            continue
        url = build_bare_url(
            args.video_id, args.thread_id, "0", str(count), template_url
        )
        log(f"first page attempt: count={count}")
        res = fetch_in_page(page, url, timeout_ms=args.fetch_timeout)
        summary = result_summary(res)
        attempts.append({"count": count, **summary})
        if summary.get("json") and (summary.get("json") or {}).get("n"):
            return count, res, summary, attempts
        if summary.get("status") != 200:
            break
        page.wait_for_timeout(random.uniform(1_000, 2_000))
    return None, None, None, attempts


def main() -> int:
    parser = argparse.ArgumentParser(description="Full-thread Douyin reply probe")
    parser.add_argument("--targets", default="")
    parser.add_argument("--common-params", default="common_params.json")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--video-id", default="7681929945538497843")
    parser.add_argument("--thread-id", default="7682054941225698091")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=20)
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
        if data.get("comment_id"):
            args.thread_id = data["comment_id"]

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) / f"full-thread-{stamp}"
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
                out / "full_thread_summary.json",
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
                out / "full_thread_summary.json",
                {"error": "wrapper_not_ready", "info": info, "env": env},
            )
            return 4

        template_url = make_template_url(args.common_params)
        count_used, first_res, first_summary, attempts = try_first_page(
            page, args, template_url
        )
        if not count_used or not first_summary:
            save_json(
                out / "full_thread_summary.json",
                {
                    "error": "first_page_failed",
                    "attempts": attempts,
                    "env": env,
                    "wrapper": info,
                },
            )
            log("first page failed")
            return 5

        pages: list[dict] = []
        all_cids: list[str] = []
        stop_reason: str | None = None
        cursor = "0"
        page_no = 0

        def process_page(res: dict, page_no: int, count: int) -> dict:
            body = res.get("body") or ""
            payload = json.loads(body) if body else {}
            metrics = page_metrics(payload)
            summary = result_summary(res)
            row = {
                "page": page_no,
                "count": count,
                "status": summary.get("status"),
                "bytes": summary.get("bytes"),
                "error": summary.get("error"),
                "n": metrics["n"],
                "unique_in_page": metrics["unique_in_page"],
                "has_more": metrics["has_more"],
                "cursor": metrics["cursor"],
                "total": metrics["total"],
                "ip_label": metrics["ip_label"],
                "reply_to_reply_id_nonzero": metrics["reply_to_reply_id_nonzero"],
                "seconds": None,
            }
            save_text(out / "responses" / f"page_{page_no}.json", body)
            return row

        t0 = time.time()
        first_row = process_page(first_res, 1, count_used)
        first_row["seconds"] = round(time.time() - t0, 2)
        pages.append(first_row)
        first_payload = json.loads(first_res.get("body") or "{}")
        first_metrics = page_metrics(first_payload)
        all_cids.extend(first_metrics["cids"])
        log(
            f"page 1: n={first_row['n']} has_more={first_row['has_more']} "
            f"cursor={first_row['cursor']} total={first_row['total']}"
        )

        cursor = (
            str(first_metrics["cursor"])
            if first_metrics["cursor"] not in (None, "")
            else ""
        )
        if not first_metrics["has_more"]:
            stop_reason = "complete"
        elif not cursor or cursor == "0":
            stop_reason = "upstream_changed"

        while stop_reason is None and page_no < args.max_pages:
            page_no += 1
            page.wait_for_timeout(random.randint(1_500, 3_000))
            url = build_bare_url(
                args.video_id, args.thread_id, cursor, str(count_used), template_url
            )
            t0 = time.time()
            res = fetch_in_page(page, url, timeout_ms=args.fetch_timeout)
            elapsed = round(time.time() - t0, 2)
            summary = result_summary(res)
            if summary.get("status") != 200 or summary.get("bytes", 0) == 0:
                pages.append(
                    {
                        "page": page_no + 1,
                        "count": count_used,
                        "status": summary.get("status"),
                        "bytes": summary.get("bytes"),
                        "error": summary.get("error"),
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
                payload = json.loads(res.get("body") or "{}")
            except Exception:
                stop_reason = "bad_json"
                break
            metrics = page_metrics(payload)
            row = process_page(res, page_no + 1, count_used)
            row["seconds"] = elapsed
            pages.append(row)
            all_cids.extend(metrics["cids"])
            log(
                f"page {page_no + 1}: n={row['n']} has_more={row['has_more']} "
                f"cursor={row['cursor']} total={row['total']}"
            )
            if not metrics["has_more"]:
                stop_reason = "complete"
                break
            if not metrics["cursor"] or str(metrics["cursor"]) == "0":
                stop_reason = "upstream_changed"
                break
            cursor = str(metrics["cursor"])
        else:
            if stop_reason is None:
                stop_reason = "max_pages"

        unique = len(set(all_cids))
        duplicates = len(all_cids) - unique
        expected = pages[0].get("total") if pages else None
        coverage = round(unique / expected, 4) if expected else None
        elapsed_total = round(sum(p.get("seconds") or 0 for p in pages), 2)
        ip_label_total = sum(p.get("ip_label") or 0 for p in pages)
        rtr_total = sum(p.get("reply_to_reply_id_nonzero") or 0 for p in pages)

        summary = {
            "video_id": args.video_id,
            "thread_id": args.thread_id,
            "count_requested": args.count,
            "count_used": count_used,
            "count_attempts": attempts,
            "wrapper_ready": wrapper_ready,
            "wrapper": info,
            "env": env,
            "login": login,
            "pages": pages,
            "fetched_total": len(all_cids),
            "unique": unique,
            "duplicates": duplicates,
            "expected_total": expected,
            "coverage": coverage,
            "ip_label_total": ip_label_total,
            "reply_to_reply_id_nonzero_total": rtr_total,
            "stop_reason": stop_reason,
            "elapsed_page_s": elapsed_total,
            "finished_at": now_iso(),
        }
        save_json(out / "full_thread_summary.json", summary)

        report = [
            "# Full Thread 探针报告",
            "",
            f"- 时间：{now_iso()}",
            f"- 视频：`{args.video_id}`",
            f"- 线程：`{args.thread_id}`",
            f"- 登录：{login}",
            f"- wrapper ready：{wrapper_ready}",
            f"- count requested / used：{args.count} / {count_used}",
            f"- stop reason：`{stop_reason}`",
            f"- 抓取总数 / 唯一 / 重复：{len(all_cids)} / {unique} / {duplicates}",
            f"- 平台 total / 覆盖率：{expected} / {coverage}",
            f"- ip_label 非空：{ip_label_total} / {len(all_cids)}",
            f"- reply_to_reply_id 非 0：{rtr_total}",
            "",
            "| 页 | count | n | unique | has_more | cursor | total | 秒 |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for p in pages:
            report.append(
                f"| {p.get('page')} | {p.get('count')} | {p.get('n')} "
                f"| {p.get('unique_in_page')} | {p.get('has_more')} "
                f"| {p.get('cursor')} | {p.get('total')} | {p.get('seconds')} |"
            )
        report += [
            "",
            "## 判读",
            "",
            f"- `count={count_used}` 的实际页大小：{pages[0].get('n') if pages else 'n/a'}",
            f"- 是否完整：{'是' if coverage == 1 else '否/部分'}",
            "- 若 coverage < 1，记录 stop_reason 和缺口，不要重跑到无限。",
            "",
            "> 原始页在 `responses/`；报告只保留摘要。",
        ]
        (out / "full_thread_report.md").write_text(
            "\n".join(report), encoding="utf-8"
        )
        log(f"done: {out.resolve()}")
        log("send back full_thread_report.md and full_thread_summary.json")
        try:
            page.close()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
