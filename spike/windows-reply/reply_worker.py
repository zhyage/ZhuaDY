"""Windows Douyin reply worker prototype (read-only).

Reads a job file, opens one fully-loaded Douyin video page per video, and
fetches replies for the requested root comments through the page's own
(signed) `fetch`. It writes:

  out/<run_id>/raw/<aweme_id>/<thread_id>/p<N>.json   raw reply pages
  out/<run_id>/normalized/<aweme_id>.jsonl           one row per reply
  out/<run_id>/state/<aweme_id>.json                 per-thread checkpoint
  out/<run_id>/worker_summary.json                   machine summary
  out/<run_id>/worker_report.md                      human summary
  out/<run_id>/normalized_sample.jsonl               first N rows, text truncated

Round 001-003 confirmed:
  - the page must be fully loaded and its window.fetch wrapper active;
  - context.request / bare HTTP returns 200 + 0 bytes;
  - count=50 works, but cursor advances by requested count, not returned count;
  - large threads may have a platform gap and orphan replies.

Usage:
  python reply_worker.py --jobs jobs.json --common-params common_params.json
  python reply_worker.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import random
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from playwright.sync_api import sync_playwright

from probe_reply import (
    JS_CAPTCHA,
    JS_LOGIN_MODAL,
    JS_MUTE,
    REPLY_PATH,
    build_bare_url,
    fetch_in_page,
    now_iso,
    save_json,
    save_text,
)
from probe_full_thread import wrapper_info

JS_PAGE_ENV = r"""
() => {
  const ua = navigator.userAgent;
  const uaData = navigator.userAgentData || null;
  let version = "148.0.0.0";
  const m = ua.match(/Chrome\/(\d+)/);
  if (m) version = m[1] + ".0.0.0";
  return {
    ua,
    platform: navigator.platform || "Win32",
    language: navigator.language || "zh-CN",
    width: screen.width || 1536,
    height: screen.height || 960,
    cores: navigator.hardwareConcurrency || 8,
    memory: navigator.deviceMemory || 8,
    uaPlatform: uaData ? uaData.platform : null,
    uaPlatformVersion: uaData ? uaData.platformVersion : null,
    version,
  };
}
"""


DEFAULT_BASE_PARAMS = {
    "device_platform": "webapp",
    "aid": "6383",
    "channel": "channel_pc_web",
    "pc_client_type": "1",
    "version_code": "170400",
    "version_name": "17.4.0",
    "cookie_enabled": "true",
    "platform": "PC",
    "support_h265": "0",
    "support_dash": "1",
    "update_version_code": "170400",
    "item_type": "0",
    "cut_version": "1",
    "browser_name": "Chrome",
    "browser_online": "true",
    "engine_name": "Blink",
    "downlink": "10",
    "effective_type": "4g",
    "round_trip_time": "50",
}


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def save_json_atomic(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def load_jobs(path: Path) -> tuple[str, list[dict]]:
    data = load_json(path)
    if "jobs" in data:
        jobs = data.get("jobs") or []
        run_id = data.get("run_id") or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    else:
        jobs = [data]
        run_id = data.get("run_id") or f"run-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    for job in jobs:
        if not job.get("aweme_id") or not job.get("threads"):
            raise ValueError("each job needs aweme_id and threads[]")
    return str(run_id), jobs


def page_params(page, base: dict) -> dict:
    info = page.evaluate(JS_PAGE_ENV)
    params = dict(base)
    os_name = info.get("uaPlatform") or ("Linux" if "Linux" in info["ua"] else "Windows")
    params.update(
        {
            "browser_version": info.get("version") or "148.0.0.0",
            "engine_version": info.get("version") or "148.0.0.0",
            "browser_platform": info.get("platform") or "Win32",
            "browser_language": info.get("language") or "zh-CN",
            "screen_width": str(info.get("width") or 1536),
            "screen_height": str(info.get("height") or 960),
            "cpu_core_num": str(info.get("cores") or 8),
            "device_memory": str(info.get("memory") or 8),
            "os_name": os_name,
            "os_version": info.get("uaPlatformVersion") or "10",
            "pc_libra_divert": os_name,
        }
    )
    return params


def template_url(params: dict) -> str:
    return f"https://www.douyin.com{REPLY_PATH}?{urlencode(params, doseq=True)}"


def open_video(context, video_id: str, timeout_ms: int = 45_000):
    page = context.new_page()
    page.bring_to_front()
    author = {"sec_uid": None}

    def on_response(resp):
        if "/aweme/v1/web/aweme/detail/" not in resp.url or author["sec_uid"]:
            return
        try:
            body = resp.json()
            aw = body.get("aweme_detail") or body.get("aweme") or {}
            a = aw.get("author") or {}
            sec = a.get("sec_uid")
            if sec:
                author["sec_uid"] = sec
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(
            f"https://www.douyin.com/video/{video_id}",
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
    except Exception as exc:  # noqa: BLE001
        log(f"goto failed: {exc}")
    page.wait_for_timeout(5_000)
    try:
        page.evaluate(JS_MUTE)
    except Exception:
        pass
    return page, author


def check_session(page, context) -> tuple[bool, str | None, str | None]:
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
    return login, modal, captcha


def wrapper_ready(page, timeout_s: int = 30) -> tuple[bool, dict]:
    try:
        info = wrapper_info(page, timeout_s=timeout_s)
        head = info.get("fetchHead") or ""
        return bool(head) and "[native code]" not in head, info
    except Exception as exc:  # noqa: BLE001
        return False, {"error": repr(exc)}


def ensure_wrapper(
    context,
    page,
    aweme_id: str,
    timeout_s: int,
    retries: int,
) -> tuple[bool, object, dict, int]:
    """Wait for the page's fetch wrapper, reopening the video page on failure.

    Returns (ready, page, last_info, reloads). The returned page is the page
    that should be used for subsequent requests; it may differ from the input.
    """
    attempts = max(1, int(retries))
    last_info: dict = {}
    reloads = 0
    for attempt in range(1, attempts + 1):
        ready, last_info = wrapper_ready(page, timeout_s=timeout_s)
        if ready:
            return True, page, last_info, reloads
        if attempt >= attempts:
            break
        log(
            f"video {aweme_id}: wrapper not ready; reopening "
            f"({attempt}/{attempts - 1} reloads)"
        )
        reloads += 1
        try:
            page.close()
        except Exception:
            pass
        page, _author = open_video(context, aweme_id)
    return False, page, last_info, reloads


def load_raw_comments(raw_dir: Path) -> tuple[dict[str, dict], dict[str, str]]:
    comments: dict[str, dict] = {}
    page_by_cid: dict[str, str] = {}
    if not raw_dir.is_dir():
        return comments, page_by_cid
    for p in sorted(raw_dir.glob("p*.json")):
        try:
            payload = load_json(p)
        except Exception:
            continue
        for c in payload.get("comments") or []:
            if isinstance(c, dict) and c.get("cid"):
                comments[c["cid"]] = c
                page_by_cid[c["cid"]] = p.name
    return comments, page_by_cid


def load_seen_cids(path: Path) -> set[str]:
    seen: set[str] = set()
    if not path.is_file():
        return seen
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
            cid = row.get("comment_id")
            if cid:
                seen.add(cid)
        except Exception:
            continue
    return seen


def append_rows(path: Path, rows: list[dict], seen: set[str]) -> int:
    new_rows = [r for r in rows if r.get("comment_id") and r["comment_id"] not in seen]
    if not new_rows:
        return 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for row in new_rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    seen.update(r["comment_id"] for r in new_rows)
    return len(new_rows)


def ts_to_iso(ts: Any) -> str | None:
    try:
        value = int(ts)
        if value <= 0:
            return None
        return datetime.fromtimestamp(value, tz=timezone.utc).isoformat()
    except Exception:
        return None


def normalize_thread(
    comments: dict[str, dict],
    page_by_cid: dict[str, str],
    thread_id: str,
    aweme_id: str,
    author_sec_uid: str | None,
    salt: str | None,
    run_id: str,
    out: Path,
) -> tuple[list[dict], dict]:
    by_id = comments
    memo: dict[str, int | None] = {}

    def parent_of(cid: str) -> str | None:
        p = by_id[cid].get("reply_to_reply_id")
        if p in (None, "0", "-1", ""):
            return None
        return str(p)

    def depth(cid: str, stack: frozenset[str]) -> int | None:
        if cid in memo:
            return memo[cid]
        if cid in stack:
            return None
        p = parent_of(cid)
        if p is None:
            memo[cid] = 2
            return 2
        if p not in by_id:
            memo[cid] = None
            return None
        d = depth(p, stack | {cid})
        value = d + 1 if d is not None else None
        memo[cid] = value
        return value

    rows: list[dict] = []
    ip = 0
    rtr = 0
    depth3 = 0
    orphan_edges = 0
    label_texts_nonempty = 0
    creator_label = 0
    author_hash_count = 0
    is_author_true = 0
    for cid, c in by_id.items():
        user = c.get("user") or {}
        sec = user.get("sec_uid")
        parent = parent_of(cid)
        thread_root = c.get("reply_id")
        if thread_root in (None, "0", "-1", ""):
            thread_root = thread_id
        reply_to = thread_root if parent is None else parent
        d = depth(cid, frozenset())
        is_orphan = parent is not None and parent not in by_id
        if c.get("ip_label") is not None:
            ip += 1
        if parent is not None:
            rtr += 1
        if d is not None and d >= 3:
            depth3 += 1
        if is_orphan:
            orphan_edges += 1
        labels = c.get("label_list") or []
        label_texts = [
            str(x.get("text"))
            for x in labels
            if isinstance(x, dict) and x.get("text")
        ]
        if label_texts:
            label_texts_nonempty += 1
        label_text = c.get("label_text") or ""
        if label_text == "作者" or any(t in ("作者", "Creator") for t in label_texts):
            creator_label += 1
        is_author = None
        if sec and author_sec_uid:
            is_author = sec == author_sec_uid
        author_hash = None
        if salt and sec:
            author_hash = hmac.new(
                salt.encode("utf-8"),
                f"douyin:{sec}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            author_hash_count += 1
        if is_author:
            is_author_true += 1
        raw_page = f"raw/{aweme_id}/{thread_id}/{page_by_cid.get(cid, 'unknown.json')}"
        raw_sha = hashlib.sha256(
            json.dumps(c, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
        rows.append(
            {
                "schema_version": "0.1",
                "run_id": run_id,
                "platform": "douyin",
                "aweme_id": aweme_id,
                "comment_id": cid,
                "thread_root_id": str(thread_root),
                "reply_to_comment_id": str(reply_to),
                "depth": d,
                "is_orphan": is_orphan,
                "text": c.get("text") or "",
                "created_at": ts_to_iso(c.get("create_time")),
                "digg_count": int(c.get("digg_count") or 0),
                "ip_province": c.get("ip_label"),
                "is_author": is_author,
                "author_hash": author_hash,
                "label_text": label_text,
                "label_texts": label_texts,
                "is_creator_label": bool(
                    label_text == "作者" or any(t in ("作者", "Creator") for t in label_texts)
                ),
                "source": "reply",
                "raw_page": raw_page,
                "raw_sha256": raw_sha,
                "fetched_at": now_iso(),
            }
        )
    metrics = {
        "comments": len(by_id),
        "ip_label": ip,
        "reply_to_reply_id_nonzero": rtr,
        "depth3": depth3,
        "orphan_edges": orphan_edges,
        "label_texts_nonempty": label_texts_nonempty,
        "creator_label": creator_label,
        "author_hash_non_null": author_hash_count,
        "is_author_true": is_author_true,
    }
    return rows, metrics


def process_thread(
    page,
    args,
    params: dict,
    job: dict,
    thread_id: str,
    out: Path,
    run_id: str,
    author_sec_uid: str | None,
    salt: str | None,
    state: dict,
    state_path: Path,
    normalized_path: Path,
    seen: set[str],
) -> dict:
    aweme_id = str(job["aweme_id"])
    max_pages = int(job.get("max_pages") or args.max_pages)
    thread_state = state.setdefault("threads", {}).setdefault(
        thread_id,
        {
            "status": "pending",
            "next_cursor": "0",
            "pages_done": 0,
            "fetched": 0,
            "expected_total": None,
            "stop_reason": None,
        },
    )
    if thread_state.get("status") == "complete" and not args.force:
        log(f"thread {thread_id}: already complete; skip")
        return {
            "thread_id": thread_id,
            "skipped": True,
            **{k: thread_state.get(k) for k in (
                "expected_total", "fetched", "unique", "coverage",
                "stop_reason", "depth3", "orphan_edges",
            )},
        }

    raw_dir = out / "raw" / aweme_id / thread_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    comments: dict[str, dict] = {}
    page_by_cid: dict[str, str] = {}
    if thread_state.get("pages_done", 0) > 0 and not args.force:
        comments, page_by_cid = load_raw_comments(raw_dir)

    cursor = str(thread_state.get("next_cursor") or "0")
    pages_done = int(thread_state.get("pages_done") or 0)
    fetched = int(thread_state.get("fetched") or 0)
    expected = thread_state.get("expected_total")
    stop_reason = None
    started = time.time()
    template = template_url(params)

    while pages_done < max_pages:
        page_no = pages_done + 1
        url = build_bare_url(str(job["aweme_id"]), thread_id, cursor, str(args.count), template)
        t0 = time.time()
        res = fetch_in_page(page, url, timeout_ms=args.fetch_timeout)
        elapsed = round(time.time() - t0, 2)
        body = res.get("body") or ""
        if res.get("status") != 200 or res.get("bytes", 0) == 0:
            stop_reason = "risk_control"
            thread_state.update(
                {"status": "risk_control", "stop_reason": stop_reason, "updated_at": now_iso()}
            )
            save_json_atomic(state_path, state)
            break
        try:
            payload = json.loads(body)
        except Exception:
            stop_reason = "bad_json"
            thread_state.update(
                {"status": "bad_json", "stop_reason": stop_reason, "updated_at": now_iso()}
            )
            save_json_atomic(state_path, state)
            break
        save_text(raw_dir / f"p{page_no}.json", body)
        items = payload.get("comments") or []
        fetched += len(items)
        for c in items:
            if isinstance(c, dict) and c.get("cid"):
                comments[c["cid"]] = c
                page_by_cid[c["cid"]] = f"p{page_no}.json"
        expected = payload.get("total") or expected
        pages_done = page_no
        has_more = bool(payload.get("has_more"))
        next_cursor = payload.get("cursor")
        thread_state.update(
            {
                "status": "running",
                "pages_done": pages_done,
                "next_cursor": str(next_cursor) if next_cursor is not None else "",
                "fetched": fetched,
                "expected_total": expected,
                "updated_at": now_iso(),
            }
        )
        save_json_atomic(state_path, state)
        log(
            f"thread {thread_id} page {page_no}: n={len(items)} "
            f"has_more={has_more} cursor={next_cursor} total={expected} "
            f"{elapsed}s"
        )
        if not has_more:
            stop_reason = "complete"
            break
        if next_cursor in (None, "") or str(next_cursor) == "0":
            stop_reason = "upstream_changed"
            break
        cursor = str(next_cursor)
        page.wait_for_timeout(random.randint(args.request_min, args.request_max))
    else:
        stop_reason = "max_pages"

    rows, metrics = normalize_thread(
        comments, page_by_cid, thread_id, aweme_id, author_sec_uid, salt, run_id, out
    )
    added = append_rows(normalized_path, rows, seen)
    unique = len(comments)
    duplicates = fetched - unique
    coverage = round(unique / expected, 4) if expected else None
    status = "complete" if stop_reason == "complete" else (stop_reason or "partial")
    thread_state.update(
        {
            "status": status,
            "stop_reason": stop_reason,
            "expected_total": expected,
            "fetched": fetched,
            "unique": unique,
            "coverage": coverage,
            "duplicates": duplicates,
            "depth3": metrics["depth3"],
            "orphan_edges": metrics["orphan_edges"],
            "normalized_rows_added": added,
            "elapsed_s": round(time.time() - started, 2),
            "updated_at": now_iso(),
        }
    )
    save_json_atomic(state_path, state)
    return {
        "thread_id": thread_id,
        "expected_total": expected,
        "fetched": fetched,
        "unique": unique,
        "duplicates": duplicates,
        "coverage": coverage,
        "stop_reason": stop_reason,
        "depth3": metrics["depth3"],
        "orphan_edges": metrics["orphan_edges"],
        "ip_label": metrics["ip_label"],
        "reply_to_reply_id_nonzero": metrics["reply_to_reply_id_nonzero"],
        "label_texts_nonempty": metrics["label_texts_nonempty"],
        "creator_label": metrics["creator_label"],
        "author_hash_non_null": metrics["author_hash_non_null"],
        "is_author_true": metrics["is_author_true"],
        "normalized_rows_added": added,
        "elapsed_s": round(time.time() - started, 2),
    }


def write_outputs(
    out: Path,
    run_id: str,
    status: str,
    started_at: str,
    threads: list[dict],
    errors: list[str],
    notes: list[str],
    sample_rows: int,
    normalized_paths: list[Path],
    job_failures: list[dict] | None = None,
) -> None:
    job_failures = job_failures or []
    total_unique = sum(int(t.get("unique") or 0) for t in threads)
    total_fetched = sum(int(t.get("fetched") or 0) for t in threads)
    total_orphans = sum(int(t.get("orphan_edges") or 0) for t in threads)
    total_depth3 = sum(int(t.get("depth3") or 0) for t in threads)
    total_author_hash = sum(int(t.get("author_hash_non_null") or 0) for t in threads)
    total_is_author = sum(int(t.get("is_author_true") or 0) for t in threads)
    summary = {
        "schema_version": "0.1",
        "run_id": run_id,
        "status": status,
        "started_at": started_at,
        "finished_at": now_iso(),
        "threads": threads,
        "totals": {
            "threads": len(threads),
            "fetched": total_fetched,
            "unique": total_unique,
            "duplicates": total_fetched - total_unique,
            "orphan_edges": total_orphans,
            "depth3": total_depth3,
            "author_hash_non_null": total_author_hash,
            "is_author_true": total_is_author,
            "normalized_rows": sum(int(t.get("normalized_rows_added") or 0) for t in threads),
        },
        "errors": errors,
        "job_failures": job_failures,
        "notes": notes,
    }
    save_json(out / "worker_summary.json", summary)

    lines = [
        "# Reply Worker 原型报告",
        "",
        f"- run_id：`{run_id}`",
        f"- 状态：`{status}`",
        f"- 开始：{started_at}",
        f"- 线程数：{len(threads)}",
        f"- fetched / unique / duplicates：{total_fetched} / {total_unique} / {total_fetched - total_unique}",
        f"- orphan_edges / depth3：{total_orphans} / {total_depth3}",
        f"- author_hash 非空 / is_author=true：{total_author_hash} / {total_is_author}",
        "",
        "| thread | expected | fetched | unique | coverage | dup | depth3 | orphans | stop | 秒 |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for t in threads:
        lines.append(
            f"| `{t.get('thread_id')}` | {t.get('expected_total')} "
            f"| {t.get('fetched')} | {t.get('unique')} | {t.get('coverage')} "
            f"| {t.get('duplicates')} | {t.get('depth3')} "
            f"| {t.get('orphan_edges')} | {t.get('stop_reason')} "
            f"| {t.get('elapsed_s')} |"
        )
    lines += ["", "## 说明", ""]
    lines += [f"- {n}" for n in notes] or ["- 无"]
    if errors:
        lines += ["", "## 错误", ""]
        lines += [f"- `{e}`" for e in errors]
    if job_failures:
        lines += ["", "## 未完成视频", ""]
        for f in job_failures:
            lines.append(
                f"- `{f.get('aweme_id')}` ({f.get('selection')}): "
                f"{f.get('reason')}; threads={f.get('threads')}; "
                f"reloads={f.get('reloads')}"
            )
    lines += [
        "",
        "> raw 页在 `raw/`，normalized 在 `normalized/`；`normalized_sample.jsonl` 只保留前几行并截断 text。",
    ]
    (out / "worker_report.md").write_text("\n".join(lines), encoding="utf-8")

    # Sample: first N rows across normalized files, text truncated.
    sample: list[dict] = []
    for path in normalized_paths:
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            if len(sample) >= sample_rows:
                break
            try:
                row = json.loads(line)
            except Exception:
                continue
            row = dict(row)
            text = row.get("text") or ""
            row["text"] = text[:40] + ("…" if len(text) > 40 else "")
            sample.append(row)
    if sample:
        with (out / "normalized_sample.jsonl").open("w", encoding="utf-8") as f:
            for row in sample:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")


def self_test() -> int:
    comments = {
        "c1": {
            "cid": "c1",
            "reply_id": "root",
            "reply_to_reply_id": "0",
            "text": "direct",
            "create_time": 0,
            "digg_count": 1,
            "ip_label": "浙江",
            "label_list": [],
            "label_text": "",
            "user": {"sec_uid": "author"},
        },
        "c2": {
            "cid": "c2",
            "reply_id": "root",
            "reply_to_reply_id": "c1",
            "text": "nested",
            "create_time": 0,
            "digg_count": 2,
            "ip_label": "江苏",
            "label_list": [],
            "label_text": "",
            "user": {"sec_uid": "other"},
        },
        "c3": {
            "cid": "c3",
            "reply_id": "root",
            "reply_to_reply_id": "missing",
            "text": "orphan",
            "create_time": 0,
            "digg_count": 3,
            "ip_label": None,
            "label_list": [],
            "label_text": "",
            "user": {"sec_uid": "other"},
        },
    }
    rows, metrics = normalize_thread(
        comments,
        {"c1": "p1.json", "c2": "p1.json", "c3": "p1.json"},
        "root",
        "aweme",
        "author",
        "test-salt",
        "self-test",
        Path("out/self-test"),
    )
    by_id = {r["comment_id"]: r for r in rows}
    checks = [
        by_id["c1"]["depth"] == 2,
        by_id["c2"]["depth"] == 3,
        by_id["c3"]["depth"] is None,
        by_id["c1"]["is_author"] is True,
        by_id["c2"]["is_author"] is False,
        by_id["c3"]["is_orphan"] is True,
        metrics["depth3"] == 1,
        metrics["orphan_edges"] == 1,
        bool(by_id["c1"]["author_hash"]),
    ]
    print(
        json.dumps(
            {
                "checks": checks,
                "depths": {cid: by_id[cid]["depth"] for cid in by_id},
                "metrics": metrics,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if all(checks) else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Douyin reply worker prototype")
    parser.add_argument("--jobs", default="jobs.json")
    parser.add_argument("--common-params", default="common_params.json")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    parser.add_argument("--out", default="out")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=5)
    parser.add_argument("--fetch-timeout", type=int, default=20_000)
    parser.add_argument("--wrapper-timeout", type=int, default=45)
    parser.add_argument("--wrapper-retries", type=int, default=2)
    parser.add_argument(
        "--wrapper-policy", choices=("skip", "stop"), default="skip",
        help="skip a video with wrapper_not_ready, or stop the whole batch",
    )
    parser.add_argument("--request-min", type=int, default=1_500)
    parser.add_argument("--request-max", type=int, default=3_000)
    parser.add_argument("--thread-min", type=int, default=4_000)
    parser.add_argument("--thread-max", type=int, default=7_000)
    parser.add_argument("--hash-salt-file", default="")
    parser.add_argument("--hash-salt-env", default="DTK_HASH_SALT")
    parser.add_argument("--sample-rows", type=int, default=5)
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    import os

    salt = None
    if args.hash_salt_file:
        salt_path = Path(args.hash_salt_file)
        if not salt_path.is_file():
            parser.error(f"hash salt file not found: {salt_path}")
        salt = salt_path.read_text(encoding="utf-8").strip() or None
    else:
        salt = os.environ.get(args.hash_salt_env) or None
    jobs_path = Path(args.jobs)
    if not jobs_path.is_file():
        parser.error(f"jobs file not found: {jobs_path}")
    run_id, jobs = load_jobs(jobs_path)
    out_root = Path(args.out) / run_id
    out_root.mkdir(parents=True, exist_ok=True)
    started_at = now_iso()
    errors: list[str] = []
    notes = [
        "page-context fetch only; context.request is known to return 200 + 0 bytes",
        "count=50; cursor comes from the response, not previous+n",
        "large-thread gap/orphans are recorded, not retried",
        "orphan rows keep depth=null; is_author uses sec_uid",
        f"wrapper wait={args.wrapper_timeout}s retries={args.wrapper_retries} "
        f"policy={args.wrapper_policy}",
        f"author_hash salt: {'set' if salt else 'not set'} "
        f"(source: {'file' if args.hash_salt_file else 'env'})",
    ]

    base_params: dict = dict(DEFAULT_BASE_PARAMS)
    cp = Path(args.common_params)
    if cp.is_file():
        base_params.update(load_json(cp))
    else:
        notes.append(f"common params not found: {cp}; using page-derived params")

    threads: list[dict] = []
    normalized_paths: list[Path] = []
    job_failures: list[dict] = []
    global_stop: str | None = None

    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp(args.cdp)
        if not browser.contexts:
            log("no browser context")
            write_outputs(
                out_root, run_id, "blocked", started_at, [], ["no browser context"], notes,
                args.sample_rows, normalized_paths,
            )
            return 2
        context = browser.contexts[0]

        for job in jobs:
            aweme_id = str(job["aweme_id"])
            page, author_capture = open_video(context, aweme_id)
            login, modal, captcha = check_session(page, context)
            log(f"video {aweme_id}: login={login} modal={modal} captcha={captcha}")
            if not login or modal or captcha:
                errors.append(f"video {aweme_id}: login/modal/captcha")
                global_stop = "login_or_captcha"
                page.close()
                break
            ready, page, info, reloads = ensure_wrapper(
                context, page, aweme_id, args.wrapper_timeout, args.wrapper_retries
            )
            if not ready:
                msg = (
                    f"video {aweme_id}: wrapper not ready after "
                    f"{args.wrapper_retries} attempt(s), reloads={reloads}"
                )
                errors.append(msg)
                job_failures.append(
                    {
                        "aweme_id": aweme_id,
                        "selection": job.get("selection"),
                        "threads": len(job.get("threads") or []),
                        "reason": "wrapper_not_ready",
                        "reloads": reloads,
                    }
                )
                if args.wrapper_policy == "stop":
                    global_stop = "wrapper_not_ready"
                    page.close()
                    break
                page.close()
                continue
            try:
                params = page_params(page, base_params)
            except Exception as exc:  # noqa: BLE001
                errors.append(f"video {aweme_id}: page params failed: {exc!r}")
                global_stop = "page_params_error"
                page.close()
                break
            author_sec_uid = job.get("author_sec_uid") or author_capture.get("sec_uid")
            state_path = out_root / "state" / f"{aweme_id}.json"
            normalized_path = out_root / "normalized" / f"{aweme_id}.jsonl"
            if args.force:
                state_path.unlink(missing_ok=True)
                normalized_path.unlink(missing_ok=True)
                shutil.rmtree(out_root / "raw" / aweme_id, ignore_errors=True)
            state = load_json(state_path) if state_path.is_file() else {}
            state.update({"run_id": run_id, "video_id": aweme_id})
            if not state.get("threads"):
                state["threads"] = {}
            seen = load_seen_cids(normalized_path)
            normalized_paths.append(normalized_path)

            for thread_id in job["threads"]:
                try:
                    metrics = process_thread(
                        page, args, params, job, str(thread_id), out_root, run_id,
                        author_sec_uid, salt, state, state_path, normalized_path, seen,
                    )
                except Exception as exc:  # noqa: BLE001
                    log(f"thread {thread_id} exception: {exc}")
                    errors.append(f"thread {thread_id}: {exc!r}")
                    metrics = {"thread_id": str(thread_id), "stop_reason": "exception"}
                threads.append(metrics)
                if metrics.get("stop_reason") in ("risk_control", "bad_json"):
                    global_stop = metrics["stop_reason"]
                    break
                page.wait_for_timeout(random.randint(args.thread_min, args.thread_max))
            page.close()
            if global_stop:
                break

    status = "blocked" if global_stop in ("login_or_captcha", "wrapper_not_ready") else (
        "partial" if global_stop or job_failures or any(
            t.get("stop_reason") not in (None, "complete") for t in threads
        ) else "success"
    )
    write_outputs(
        out_root, run_id, status, started_at, threads, errors, notes,
        args.sample_rows, normalized_paths, job_failures,
    )
    log(f"done: {out_root.resolve()} status={status}")
    log("send back worker_report.md, worker_summary.json, normalized_sample.jsonl")
    return 0 if status == "success" else 1


if __name__ == "__main__":
    raise SystemExit(main())
