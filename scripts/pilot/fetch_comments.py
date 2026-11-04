#!/usr/bin/env python3
"""Stage 2: fetch top-level comments for the 20 selected pilot videos via v5.

Writes per video:
  data/raw/<run_id>/comments/<aweme_id>/page_001.json ...
  data/pilot/<run_id>/comments/<aweme_id>/comments.jsonl
  data/pilot/<run_id>/comments/<aweme_id>/comment_raw.jsonl
  data/pilot/<run_id>/comments/<aweme_id>/state.json

Run-level:
  comments.csv
  comment_raw.csv
  comment_fetch_state.csv
  quality_metric.csv
  comments_summary.json
  thread_candidates.csv

No DB writes here; use sql/import_comments.sql after this.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import hmac
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASE = "http://127.0.0.1:8000"
API_KEY_FILE = ROOT / ".secrets" / "dtk-api-key.txt"
SALT_FILE = ROOT / ".secrets" / "dtk-hmac-salt"
DEFAULT_RUN_ID = "pilot-20261030-01"
TARGET_SEC_UID = "MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return hashlib.sha256(data).hexdigest()


def read_key(path: Path) -> str:
    if not path.is_file():
        raise SystemExit(f"missing: {path}")
    return path.read_text(encoding="utf-8").strip()


def author_hash(sec_uid: str | None, salt: str) -> str | None:
    if not sec_uid:
        return None
    return hmac.new(
        salt.encode("utf-8"),
        f"douyin:{sec_uid}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def api_get(session, base: str, key: str, path: str, params: dict) -> tuple[dict, bytes]:
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {key}"}
    last = None
    for attempt in range(1, 4):
        try:
            resp = session.get(url, headers=headers, params=params, timeout=90)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success") is False:
                    raise RuntimeError(f"v5 error: {body.get('error')}")
                return body, resp.content
            if resp.status_code == 202:
                raise RuntimeError("v5 returned 202; increase wait or add task polling")
            last = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"request failed: {last}")


def raw_token(raw: dict, key: str, default=None):
    value = raw.get(key)
    return value if value not in (None, "") else default


def comment_row(item: dict, raw: dict, aweme_id: str, run_id: str, salt: str, raw_page: str, target_sec_uid: str) -> dict:
    cid = str(item.get("comment_id") or raw.get("cid") or "")
    user = raw.get("user") or {}
    sec = user.get("sec_uid") or (item.get("author") or {}).get("sec_uid") or (item.get("author") or {}).get("uid")
    labels = raw.get("label_list") or []
    label_texts = [
        str(x.get("text"))
        for x in labels
        if isinstance(x, dict) and x.get("text")
    ]
    label_text = raw.get("label_text") or ""
    created = item.get("created_at")
    if not created and raw.get("create_time"):
        try:
            created = datetime.fromtimestamp(int(raw["create_time"]), tz=timezone.utc).isoformat()
        except Exception:
            created = None
    raw_json = json.dumps(raw, ensure_ascii=False, sort_keys=True)
    raw_sha = sha256_text(raw_json)
    return {
        "comment_id": cid,
        "aweme_id": aweme_id,
        "thread_root_id": cid,
        "reply_to_comment_id": "",
        "depth": 1,
        "is_orphan": False,
        "text": item.get("text") or raw.get("text") or "",
        "created_at": created or "",
        "digg_count": item.get("digg_count") or raw.get("digg_count") or 0,
        "reply_count": item.get("reply_count") or raw.get("reply_comment_total") or 0,
        "is_pinned": bool(item.get("is_pinned")),
        "is_author_liked": bool(item.get("is_author_liked")),
        "ip_province": raw.get("ip_label"),
        "is_author": (sec == target_sec_uid) if sec else None,
        "is_thread_author": "",
        "author_hash": author_hash(sec, salt),
        "hash_version": "v1",
        "label_text": label_text,
        "label_texts": json.dumps(label_texts, ensure_ascii=False),
        "is_creator_label": bool(
            label_text == "作者" or any(t in ("作者", "Creator") for t in label_texts)
        ),
        "source": "top_level",
        "raw_sha256": raw_sha,
        "raw_page": raw_page,
        "run_id": run_id,
        "_raw_json": raw_json,
    }


def load_existing_video(out_dir: Path) -> tuple[dict, list[dict]] | None:
    state_path = out_dir / "state.json"
    comments_path = out_dir / "comments.jsonl"
    raw_path = out_dir / "comment_raw.jsonl"
    if not (state_path.is_file() and comments_path.is_file() and raw_path.is_file()):
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if state.get("stop_reason") not in ("complete", "upstream_changed"):
        return None
    raw_map = {}
    for line in raw_path.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
            if r.get("comment_id"):
                raw_map[r["comment_id"]] = r.get("raw_json") or "{}"
        except Exception:
            continue
    rows = []
    for line in comments_path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except Exception:
            continue
        row["_raw_json"] = raw_map.get(row.get("comment_id"), "{}")
        rows.append(row)
    return state, rows


def fetch_video(
    session,
    base: str,
    key: str,
    run_id: str,
    aweme_id: str,
    platform_comment_count: int,
    salt: str,
    raw_root: Path,
    pilot_root: Path,
    count: int,
    max_pages: int,
    sleep: float,
    target_sec_uid: str,
) -> dict:
    out_dir = pilot_root / "comments" / aweme_id
    out_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = raw_root / "comments" / aweme_id
    pages: list[dict] = []
    rows: list[dict] = []
    seen: set[str] = set()
    fetched = 0  # total items returned across pages (including duplicates)
    cursor = None
    stop_reason = None
    last_has_more = None
    guest_fallback = None
    started = time.time()

    for page_no in range(1, max_pages + 1):
        params = {
            "aweme_id": aweme_id,
            "count": count,
            "include_raw": "true",
            "wait": 30,
        }
        if cursor:
            params["cursor"] = cursor
        body, content = api_get(
            session, base, key, "/api/v1/douyin/video/comments", params
        )
        data = body.get("data") or {}
        meta = body.get("meta") or {}
        items = data.get("items") or []
        raw_path = raw_dir / f"page_{page_no:03d}.json"
        raw_sha = write_bytes(raw_path, content)
        raw_page = str(raw_path.relative_to(ROOT))
        gf = meta.get("guest_fallback")
        if gf is not None:
            guest_fallback = gf
        fetched += len(items)
        for item in items:
            raw = item.get("raw") or {}
            row = comment_row(item, raw, aweme_id, run_id, salt, raw_page, target_sec_uid)
            cid = row["comment_id"]
            if not cid or cid in seen:
                continue
            seen.add(cid)
            rows.append(row)
        next_cursor = data.get("cursor")
        last_has_more = bool(data.get("has_more"))
        pages.append(
            {
                "page": page_no,
                "items": len(items),
                "unique_so_far": len(rows),
                "cursor": next_cursor,
                "has_more": last_has_more,
                "guest_fallback": gf,
                "raw_path": raw_page,
                "raw_sha256": raw_sha,
            }
        )
        log(
            f"{aweme_id} page {page_no}: items={len(items)} unique={len(rows)} "
            f"has_more={last_has_more} cursor={next_cursor} gf={gf}"
        )
        if not last_has_more:
            stop_reason = "complete"
            break
        if next_cursor in (None, "") or str(next_cursor) == "0":
            stop_reason = "upstream_changed"
            break
        cursor = str(next_cursor)
        time.sleep(sleep)
    else:
        stop_reason = "max_pages"

    expected = int(platform_comment_count or 0) or None
    unique = len(rows)
    coverage = round(unique / expected, 4) if expected else None
    duplicates = fetched - unique
    state = {
        "run_id": run_id,
        "aweme_id": aweme_id,
        "thread_id": "__top_level__",
        "pages": pages,
        "pages_done": len(pages),
        "fetched": fetched,
        "unique": unique,
        "duplicates": duplicates,
        "expected_total": expected,
        "coverage": coverage,
        "stop_reason": stop_reason,
        "guest_fallback": guest_fallback,
        "elapsed_s": round(time.time() - started, 2),
        "finished_at": now_iso(),
    }
    (out_dir / "state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    with (out_dir / "comments.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            clean = {k: v for k, v in row.items() if not k.startswith("_")}
            f.write(json.dumps(clean, ensure_ascii=False) + "\n")
    with (out_dir / "comment_raw.jsonl").open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(
                json.dumps(
                    {
                        "comment_id": row["comment_id"],
                        "raw_json": row["_raw_json"],
                        "raw_sha256": row["raw_sha256"],
                        "run_id": run_id,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return {"state": state, "rows": rows}


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch top-level comments for pilot videos")
    parser.add_argument("--run-id", default=DEFAULT_RUN_ID)
    parser.add_argument("--selected", default="data/pilot/pilot-20261030-01/selected_videos.csv")
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=15)
    parser.add_argument("--sleep", type=float, default=2.0)
    parser.add_argument("--max-videos", type=int, default=0)
    parser.add_argument("--target-sec-uid", default=TARGET_SEC_UID)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--out-data", default="data")
    args = parser.parse_args()

    key = read_key(API_KEY_FILE)
    salt = read_key(SALT_FILE)
    data_root = ROOT / args.out_data
    raw_root = data_root / "raw" / args.run_id
    pilot_root = data_root / "pilot" / args.run_id
    pilot_root.mkdir(parents=True, exist_ok=True)

    selected_path = ROOT / args.selected
    with selected_path.open(encoding="utf-8", newline="") as f:
        selected = list(csv.DictReader(f))
    if args.max_videos:
        selected = selected[: args.max_videos]
    log(f"run_id={args.run_id} videos={len(selected)}")

    session = requests.Session()
    all_rows: list[dict] = []
    states: list[dict] = []
    for idx, video in enumerate(selected, 1):
        aweme_id = video["aweme_id"]
        platform_count = int(video.get("comment_count") or 0)
        log(f"[{idx}/{len(selected)}] {aweme_id} platform_comment_count={platform_count}")
        out_dir = pilot_root / "comments" / aweme_id
        if args.resume:
            existing = load_existing_video(out_dir)
            if existing:
                state, rows = existing
                log(
                    f"{aweme_id} resume-skip: {len(rows)} rows, "
                    f"stop={state.get('stop_reason')}"
                )
                all_rows.extend(rows)
                states.append(state)
                continue
        try:
            target_sec_uid = video.get("account_id") or video.get("author_sec_uid") or args.target_sec_uid
            result = fetch_video(
                session, args.base, key, args.run_id, aweme_id, platform_count,
                salt, raw_root, pilot_root, args.count, args.max_pages, args.sleep,
                target_sec_uid,
            )
        except Exception as exc:  # noqa: BLE001
            log(f"{aweme_id} exception: {exc}")
            states.append(
                {
                    "run_id": args.run_id,
                    "aweme_id": aweme_id,
                    "thread_id": "__top_level__",
                    "pages_done": 0,
                    "fetched": 0,
                    "unique": 0,
                    "duplicates": 0,
                    "expected_total": platform_count or None,
                    "coverage": None,
                    "stop_reason": "exception",
                    "error": repr(exc),
                    "guest_fallback": None,
                }
            )
            continue
        all_rows.extend(result["rows"])
        states.append(result["state"])

    # Global CSVs.
    comment_cols = [
        "comment_id", "aweme_id", "thread_root_id", "reply_to_comment_id", "depth",
        "is_orphan", "text", "created_at", "digg_count", "reply_count",
        "is_pinned", "is_author_liked", "ip_province", "is_author",
        "is_thread_author", "author_hash", "hash_version", "label_text",
        "label_texts", "is_creator_label", "source", "raw_sha256", "raw_page",
        "run_id",
    ]
    raw_cols = ["comment_id", "raw_json", "raw_sha256", "run_id"]
    state_cols = [
        "run_id", "aweme_id", "thread_id", "cursor", "pages_done", "has_more",
        "expected_total", "fetched", "unique_count", "duplicates", "coverage",
        "stop_reason",
    ]
    quality_cols = [
        "run_id", "aweme_id", "thread_id", "expected_total", "fetched",
        "unique_count", "duplicates", "orphan_edges", "depth3", "coverage",
        "stop_reason",
    ]

    def s(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    comments_csv = pilot_root / "comments.csv"
    with comments_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(comment_cols)
        for row in all_rows:
            w.writerow([s(row.get(c)) for c in comment_cols])

    raw_csv = pilot_root / "comment_raw.csv"
    with raw_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(raw_cols)
        for row in all_rows:
            w.writerow([
                s(row.get("comment_id")),
                s(row.get("_raw_json")),
                s(row.get("raw_sha256")),
                s(row.get("run_id")),
            ])

    state_csv = pilot_root / "comment_fetch_state.csv"
    with state_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(state_cols)
        for st in states:
            last = (st.get("pages") or [{}])[-1] if st.get("pages") else {}
            w.writerow([
                s(st.get("run_id")),
                s(st.get("aweme_id")),
                s(st.get("thread_id") or "__top_level__"),
                s(last.get("cursor")),
                s(st.get("pages_done")),
                s(last.get("has_more")),
                s(st.get("expected_total")),
                s(st.get("fetched")),
                s(st.get("unique")),
                s(st.get("duplicates")),
                s(st.get("coverage")),
                s(st.get("stop_reason")),
            ])

    quality_csv = pilot_root / "quality_metric.csv"
    with quality_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(quality_cols)
        for st in states:
            w.writerow([
                s(st.get("run_id")),
                s(st.get("aweme_id")),
                s(st.get("thread_id") or "__top_level__"),
                s(st.get("expected_total")),
                s(st.get("fetched")),
                s(st.get("unique")),
                s(st.get("duplicates")),
                0,
                0,
                s(st.get("coverage")),
                s(st.get("stop_reason")),
            ])

    # Thread candidates for Stage 3 (top-level comments with reply_count > 0).
    candidates = [r for r in all_rows if int(r.get("reply_count") or 0) > 0]
    candidates.sort(key=lambda r: (r["aweme_id"], -int(r["reply_count"]), -int(r["digg_count"] or 0)))
    thread_csv = pilot_root / "thread_candidates.csv"
    with thread_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow([
            "aweme_id", "comment_id", "reply_count", "digg_count", "created_at",
            "is_author", "ip_province",
        ])
        for r in candidates:
            w.writerow([
                s(r.get("aweme_id")), s(r.get("comment_id")), s(r.get("reply_count")),
                s(r.get("digg_count")), s(r.get("created_at")),
                s(r.get("is_author")), s(r.get("ip_province")),
            ])

    total_fetched = sum(int(st.get("fetched") or 0) for st in states)
    total_unique = sum(int(st.get("unique") or 0) for st in states)
    summary = {
        "run_id": args.run_id,
        "videos": len(states),
        "total_fetched": total_fetched,
        "total_unique": total_unique,
        "total_duplicates": total_fetched - total_unique,
        "total_thread_candidates": len(candidates),
        "videos_with_risk": sum(1 for st in states if st.get("stop_reason") == "risk_control"),
        "videos_complete": sum(1 for st in states if st.get("stop_reason") == "complete"),
        "states": [
            {
                "aweme_id": st.get("aweme_id"),
                "expected_total": st.get("expected_total"),
                "fetched": st.get("fetched"),
                "unique": st.get("unique"),
                "duplicates": st.get("duplicates"),
                "coverage": st.get("coverage"),
                "stop_reason": st.get("stop_reason"),
                "guest_fallback": st.get("guest_fallback"),
                "elapsed_s": st.get("elapsed_s"),
            }
            for st in states
        ],
        "files": {
            "comments_csv": str(comments_csv.relative_to(ROOT)),
            "comment_raw_csv": str(raw_csv.relative_to(ROOT)),
            "comment_fetch_state_csv": str(state_csv.relative_to(ROOT)),
            "quality_metric_csv": str(quality_csv.relative_to(ROOT)),
            "thread_candidates_csv": str(thread_csv.relative_to(ROOT)),
        },
    }
    (pilot_root / "comments_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(
        f"done: videos={len(states)} fetched={total_fetched} unique={total_unique} "
        f"thread_candidates={len(candidates)}"
    )
    log(f"comments_csv={comments_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
