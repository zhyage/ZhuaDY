#!/usr/bin/env python3
"""Stage 1: fetch the full Douyin video list for one account via v5.

Writes:
  data/raw/<run_id>/account.json
  data/raw/<run_id>/video_list/page_001.json ...
  data/pilot/<run_id>/account.json
  data/pilot/<run_id>/videos.jsonl
  data/pilot/<run_id>/videos.csv
  data/pilot/<run_id>/run.json

No database writes here; use sql/import_video_list.sql after this.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEC_UID = "MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c"
DEFAULT_BASE = "http://127.0.0.1:8000"
API_KEY_FILE = ROOT / ".secrets" / "dtk-api-key.txt"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_bytes(path: Path, data: bytes) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return sha256_bytes(data)


def api_key() -> str:
    if not API_KEY_FILE.is_file():
        raise SystemExit(f"API key file not found: {API_KEY_FILE}")
    return API_KEY_FILE.read_text(encoding="utf-8").strip()


def api_get(session: requests.Session, base: str, key: str, path: str, params: dict) -> tuple[dict, bytes]:
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {key}"}
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = session.get(url, headers=headers, params=params, timeout=90)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success") is False:
                    raise RuntimeError(f"v5 error: {body.get('error')}")
                return body, resp.content
            if resp.status_code == 202:
                raise RuntimeError(
                    "v5 returned 202; increase wait or implement task polling"
                )
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"request failed: {last_error}")


def fetch_account(session, base, key, sec_uid: str, raw_dir: Path, pilot_dir: Path) -> dict:
    body, content = api_get(
        session,
        base,
        key,
        "/api/v1/douyin/user",
        {"sec_user_id": sec_uid, "wait": 30},
    )
    raw_path = raw_dir / "account.json"
    raw_sha = write_bytes(raw_path, content)
    data = body.get("data") or {}
    stats = data.get("stats") or {}
    account = {
        "account_id": sec_uid,
        "sec_uid": data.get("sec_uid") or sec_uid,
        "uid": data.get("uid"),
        "unique_id": data.get("unique_id"),
        "nickname": data.get("nickname"),
        "signature": data.get("signature"),
        "verified": data.get("verified"),
        "follower_count": stats.get("follower_count"),
        "following_count": stats.get("following_count"),
        "total_favorited": stats.get("total_digg"),
        "aweme_count": stats.get("content_count"),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "raw_sha256": raw_sha,
        "fetched_at": now_iso(),
    }
    (pilot_dir / "account.json").write_text(
        json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return account


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch full Douyin video list via v5")
    parser.add_argument("--sec-uid", default=DEFAULT_SEC_UID)
    parser.add_argument("--base", default=DEFAULT_BASE)
    parser.add_argument("--run-id", default="pilot-20261030-01")
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--max-pages", type=int, default=30)
    parser.add_argument("--sleep", type=float, default=1.5)
    parser.add_argument("--out-data", default="data")
    args = parser.parse_args()

    key = api_key()
    data_root = ROOT / args.out_data
    raw_dir = data_root / "raw" / args.run_id
    pilot_dir = data_root / "pilot" / args.run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    pilot_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    started = now_iso()
    log(f"run_id={args.run_id} sec_uid={args.sec_uid}")

    account = fetch_account(session, args.base, key, args.sec_uid, raw_dir, pilot_dir)
    log(
        f"account: {account.get('nickname')} unique_id={account.get('unique_id')} "
        f"aweme_count={account.get('aweme_count')}"
    )

    videos: dict[str, dict] = {}
    page = 0
    cursor = None
    guest_fallback = None
    stop_reason = None
    pages: list[dict] = []

    while page < args.max_pages:
        page += 1
        params = {"sec_user_id": args.sec_uid, "count": args.count, "wait": 30}
        if cursor:
            params["cursor"] = cursor
        body, content = api_get(
            session, args.base, key, "/api/v1/douyin/user/posts", params
        )
        data = body.get("data") or {}
        meta = body.get("meta") or {}
        items = data.get("items") or []
        raw_path = raw_dir / "video_list" / f"page_{page:03d}.json"
        raw_sha = write_bytes(raw_path, content)
        gf = meta.get("guest_fallback")
        if gf is not None:
            guest_fallback = gf
        for item in items:
            aid = str(item.get("content_id") or "")
            if not aid:
                continue
            stats = item.get("stats") or {}
            author = item.get("author") or {}
            author_sec = author.get("sec_uid") or author.get("uid")
            videos[aid] = {
                "aweme_id": aid,
                "account_id": args.sec_uid,
                "author_sec_uid": author_sec,
                "author_nickname": author.get("nickname"),
                "is_target_author": author_sec == args.sec_uid,
                "caption": item.get("description") or item.get("title") or "",
                "created_at": item.get("created_at"),
                "duration_ms": item.get("duration_ms"),
                "digg_count": stats.get("digg_count"),
                "comment_count": stats.get("comment_count"),
                "share_count": stats.get("share_count"),
                "collect_count": stats.get("collect_count"),
                "play_count": stats.get("play_count"),
                "is_deleted": item.get("is_deleted"),
                "is_private": item.get("is_private"),
                "raw_path": str(raw_path.relative_to(ROOT)),
                "raw_sha256": raw_sha,
                "run_id": args.run_id,
            }
        next_cursor = data.get("cursor")
        has_more = bool(data.get("has_more"))
        pages.append(
            {
                "page": page,
                "items": len(items),
                "unique_so_far": len(videos),
                "cursor": next_cursor,
                "has_more": has_more,
                "guest_fallback": gf,
                "raw_path": str(raw_path.relative_to(ROOT)),
            }
        )
        log(
            f"page {page}: items={len(items)} unique={len(videos)} "
            f"has_more={has_more} cursor={next_cursor} guest_fallback={gf}"
        )
        if not has_more:
            stop_reason = "complete"
            break
        if next_cursor in (None, "", "0"):
            stop_reason = "upstream_changed"
            break
        cursor = str(next_cursor)
        time.sleep(args.sleep)
    else:
        stop_reason = "max_pages"

    videos_list = list(videos.values())
    target_count = sum(1 for v in videos_list if v.get("is_target_author"))
    other_count = len(videos_list) - target_count
    videos_jsonl = pilot_dir / "videos.jsonl"
    with videos_jsonl.open("w", encoding="utf-8") as f:
        for row in videos_list:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    # CSV for psql import; use empty string for NULL, true/false for booleans.
    videos_csv = pilot_dir / "videos.csv"
    columns = [
        "aweme_id",
        "account_id",
        "author_sec_uid",
        "author_nickname",
        "is_target_author",
        "caption",
        "created_at",
        "duration_ms",
        "digg_count",
        "comment_count",
        "share_count",
        "collect_count",
        "play_count",
        "is_deleted",
        "is_private",
        "raw_path",
        "raw_sha256",
        "run_id",
    ]

    def s(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        return str(value)

    with videos_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(columns)
        for row in videos_list:
            writer.writerow([s(row.get(c)) for c in columns])

    account_csv = pilot_dir / "account.csv"
    account_columns = [
        "account_id",
        "sec_uid",
        "unique_id",
        "nickname",
        "signature",
        "verified",
        "follower_count",
        "following_count",
        "total_favorited",
        "aweme_count",
        "raw_path",
        "raw_sha256",
        "run_id",
    ]
    account_row = dict(account)
    account_row["run_id"] = args.run_id
    with account_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(account_columns)
        writer.writerow([s(account_row.get(c)) for c in account_columns])

    run_manifest = {
        "run_id": args.run_id,
        "account_id": args.sec_uid,
        "started_at": started,
        "finished_at": now_iso(),
        "status": "success" if stop_reason in ("complete", "max_pages") else "partial",
        "stop_reason": stop_reason,
        "pages": pages,
        "page_count": page,
        "expected_content_count": account.get("aweme_count"),
        "fetched_unique": len(videos_list),
        "target_author_count": target_count,
        "other_author_count": other_count,
        "duplicates": sum(p["items"] for p in pages) - len(videos_list),
        "guest_fallback": guest_fallback,
        "v5_base": args.base,
        "files": {
            "account_jsonl": str((pilot_dir / "account.json").relative_to(ROOT)),
            "videos_jsonl": str(videos_jsonl.relative_to(ROOT)),
            "videos_csv": str(videos_csv.relative_to(ROOT)),
        },
    }
    (pilot_dir / "run.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    log(
        f"done: pages={page} unique={len(videos_list)} target={target_count} "
        f"other={other_count} expected={account.get('aweme_count')} "
        f"stop={stop_reason} guest_fallback={guest_fallback}"
    )
    log(f"videos_csv={videos_csv}")
    return 0 if stop_reason in ("complete", "max_pages") else 1


if __name__ == "__main__":
    raise SystemExit(main())
