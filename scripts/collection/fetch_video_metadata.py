#!/usr/bin/env python3
"""V1: fetch account + full video list with video metadata for the next run.

Unlike scripts/pilot/fetch_video_list.py, this requests `include_raw=true` so
that fields the normalized v5 model drops -- `recommend_count`, certification
text, share_url -- are available. It writes a new run only; it does not touch
the completed pilot-20261030-01 database rows.

Writes:
  data/raw/<run_id>/account.json
  data/raw/<run_id>/video_list/page_001.json ...
  data/pilot/<run_id>/account.json / account.csv
  data/pilot/<run_id>/videos.jsonl / videos.csv
  data/pilot/<run_id>/run.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SEC_UID = "MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c"
DEFAULT_BASE = "http://127.0.0.1:8000"
DEFAULT_RUN = "pilot-video-20261031-01"
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


def api_get(
    session: requests.Session, base: str, key: str, path: str, params: dict
) -> tuple[dict, bytes]:
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {key}"}
    last_error = None
    for attempt in range(1, 4):
        try:
            resp = session.get(url, headers=headers, params=params, timeout=180)
            if resp.status_code == 200:
                body = resp.json()
                if body.get("success") is False:
                    raise RuntimeError(f"v5 error: {body.get('error')}")
                return body, resp.content
            if resp.status_code == 202:
                task = (resp.json() or {}).get("task_id")
                raise RuntimeError(f"v5 returned 202 (task_id={task}); increase wait")
            last_error = f"HTTP {resp.status_code}: {resp.text[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_error = repr(exc)
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"request failed: {last_error}")


def cert_text(node: dict) -> str | None:
    """Extract certification text from a raw Douyin user/author object."""
    raw = node.get("account_cert_info")
    if raw:
        try:
            info = json.loads(raw) if isinstance(raw, str) else raw
            label = (info or {}).get("label_text") or (info or {}).get("label")
            if label:
                return str(label)
        except Exception:
            pass
    for key in ("enterprise_verify_reason", "custom_verify"):
        val = node.get(key)
        if val:
            return str(val)
    return None


def fetch_account(session, base, key, sec_uid: str, raw_dir: Path, pilot_dir: Path) -> dict:
    body, content = api_get(
        session,
        base,
        key,
        "/api/v1/douyin/user",
        {"sec_user_id": sec_uid, "include_raw": "true", "wait": 30},
    )
    raw_path = raw_dir / "account.json"
    raw_sha = write_bytes(raw_path, content)
    data = body.get("data") or {}
    stats = data.get("stats") or {}
    raw_user = data.get("raw") or {}
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
        "certification": cert_text(raw_user),
        "favoriting_count": raw_user.get("favoriting_count"),
        "collected_at": now_iso(),
        "raw_path": str(raw_path.relative_to(ROOT)),
        "raw_sha256": raw_sha,
    }
    (pilot_dir / "account.json").write_text(
        json.dumps(account, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return account


def media_fields(item: dict) -> dict:
    media = item.get("media") or {}
    video = media.get("video") or {}
    raw = item.get("raw") or {}
    raw_video = raw.get("video") or {}
    if not video and raw_video:
        pa = raw_video.get("play_addr") or {}
        video = {
            "width": pa.get("width"),
            "height": pa.get("height"),
            "format": raw_video.get("format"),
            "size_bytes": pa.get("data_size"),
            "bitrate": None,
        }
    size = video.get("size_bytes")
    if size is None:
        size = ((raw_video.get("play_addr") or {}).get("data_size"))
    return {
        "media_width": video.get("width"),
        "media_height": video.get("height"),
        "media_format": video.get("format"),
        "media_size_bytes": size,
        "media_bitrate": video.get("bitrate"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Fetch video list + metadata via v5")
    ap.add_argument("--sec-uid", default=DEFAULT_SEC_UID)
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--run-id", default=DEFAULT_RUN)
    ap.add_argument("--count", type=int, default=50)
    ap.add_argument("--max-pages", type=int, default=30)
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--out-data", default="data")
    args = ap.parse_args()

    key = api_key()
    data_root = ROOT / args.out_data
    raw_dir = data_root / "raw" / args.run_id
    pilot_dir = data_root / "pilot" / args.run_id
    raw_dir.mkdir(parents=True, exist_ok=True)
    pilot_dir.mkdir(parents=True, exist_ok=True)

    session = requests.Session()
    started = now_iso()
    log(f"run_id={args.run_id} sec_uid={args.sec_uid} include_raw=true")

    account = fetch_account(session, args.base, key, args.sec_uid, raw_dir, pilot_dir)
    log(
        f"account: {account.get('nickname')} unique_id={account.get('unique_id')} "
        f"aweme_count={account.get('aweme_count')} "
        f"favoriting={account.get('favoriting_count')}"
    )

    videos: dict[str, dict] = {}
    page = 0
    cursor = None
    guest_fallback = None
    stop_reason = None
    pages: list[dict] = []

    while page < args.max_pages:
        page += 1
        params = {
            "sec_user_id": args.sec_uid,
            "count": args.count,
            "include_raw": "true",
            "wait": 30,
        }
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
            raw = item.get("raw") or {}
            raw_stats = raw.get("statistics") or {}
            author = item.get("author") or {}
            raw_author = raw.get("author") or {}
            author_sec = author.get("sec_uid") or author.get("uid") or raw_author.get("sec_uid")
            tags = item.get("tags") or []
            mf = media_fields(item)
            collected_at = item.get("fetched_at") or now_iso()
            videos[aid] = {
                "aweme_id": aid,
                "account_id": args.sec_uid,
                "author_sec_uid": author_sec,
                "author_nickname": author.get("nickname") or raw_author.get("nickname"),
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
                "web_url": item.get("web_url"),
                "kind": item.get("kind"),
                "tags": tags,
                "recommend_count": raw_stats.get("recommend_count"),
                "media_width": mf["media_width"],
                "media_height": mf["media_height"],
                "media_format": mf["media_format"],
                "media_size_bytes": mf["media_size_bytes"],
                "media_bitrate": mf["media_bitrate"],
                "author_certification": cert_text(raw_author) or account.get("certification"),
                "author_favoriting_count": account.get("favoriting_count"),
                "collected_at": collected_at,
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

    def s(value):
        if value is None:
            return ""
        if isinstance(value, bool):
            return "true" if value else "false"
        if isinstance(value, (list, dict)):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    video_columns = [
        "aweme_id", "account_id", "author_sec_uid", "author_nickname",
        "is_target_author", "caption", "created_at", "duration_ms",
        "digg_count", "comment_count", "share_count", "collect_count",
        "play_count", "is_deleted", "is_private", "web_url", "kind", "tags",
        "recommend_count", "media_width", "media_height", "media_format",
        "media_size_bytes", "media_bitrate", "author_certification",
        "author_favoriting_count", "collected_at", "raw_path", "raw_sha256",
        "run_id",
    ]
    videos_csv = pilot_dir / "videos.csv"
    with videos_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(video_columns)
        for row in videos_list:
            writer.writerow([s(row.get(c)) for c in video_columns])

    account_csv = pilot_dir / "account.csv"
    account_columns = [
        "account_id", "sec_uid", "unique_id", "nickname", "signature",
        "verified", "follower_count", "following_count", "total_favorited",
        "aweme_count", "certification", "favoriting_count", "collected_at",
        "raw_path", "raw_sha256", "run_id",
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
        "include_raw": True,
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
            "account_json": str((pilot_dir / "account.json").relative_to(ROOT)),
            "account_csv": str(account_csv.relative_to(ROOT)),
            "videos_jsonl": str(videos_jsonl.relative_to(ROOT)),
            "videos_csv": str(videos_csv.relative_to(ROOT)),
        },
    }
    (pilot_dir / "run.json").write_text(
        json.dumps(run_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
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
