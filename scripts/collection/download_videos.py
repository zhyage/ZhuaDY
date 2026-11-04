#!/usr/bin/env python3
"""V3/V4: download selected videos at the minimum usable quality.

Policy (confirmed 2026-10-31):
  * only watermarked-free MP4 streams (no dash: avoids audio/video merge);
  * prefer height >= 540; fall back to 480, then 720;
  * among eligible streams, choose the smallest size_bytes;
  * refresh the v5 detail immediately before download (CDN URLs expire).

Writes:
  data/raw/<run_id>/video_detail/<aweme_id>.json
  data/media/<run_id>/<aweme_id>.mp4
  data/pilot/<run_id>/media_download.csv
  data/pilot/<run_id>/media_manifest.json
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = "pilot-video-20261031-01"
DEFAULT_SELECTED = ROOT / "data" / "pilot" / DEFAULT_RUN / "selected_videos.csv"
API_KEY_FILE = ROOT / ".secrets" / "dtk-api-key.txt"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/156.0.0.0 Safari/537.36"
)
DOWNLOAD_HEADERS = {
    "User-Agent": UA,
    "Referer": "https://www.douyin.com/",
    "Accept": "*/*",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def api_key() -> str:
    if not API_KEY_FILE.is_file():
        raise SystemExit(f"API key file not found: {API_KEY_FILE}")
    return API_KEY_FILE.read_text(encoding="utf-8").strip()


def api_get(session, base, key, path, params):
    url = base.rstrip("/") + path
    headers = {"Authorization": f"Bearer {key}"}
    last = None
    for attempt in range(1, 4):
        try:
            r = session.get(url, headers=headers, params=params, timeout=180)
            if r.status_code == 200:
                body = r.json()
                if body.get("success") is False:
                    raise RuntimeError(f"v5 error: {body.get('error')}")
                return body, r.content
            if r.status_code == 202:
                raise RuntimeError(f"v5 returned 202: {r.text[:200]}")
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except Exception as exc:  # noqa: BLE001
            last = repr(exc)
        if attempt < 3:
            time.sleep(2 * attempt)
    raise RuntimeError(f"detail failed: {last}")


def choose_stream(streams: list[dict]) -> dict:
    candidates = [
        s for s in streams
        if s.get("format") == "mp4"
        and not s.get("watermark")
        and s.get("url")
    ]
    if not candidates:
        raise RuntimeError("no watermark-free mp4 stream")
    preferred = [s for s in candidates if (s.get("height") or 0) >= 540]
    if not preferred:
        preferred = [s for s in candidates if (s.get("height") or 0) >= 480]
    if not preferred:
        preferred = candidates
    return min(
        preferred,
        key=lambda s: (
            s.get("size_bytes") or 10**18,
            s.get("bitrate") or 10**18,
        ),
    )


def probe(path: Path) -> dict:
    out = subprocess.run(
        [
            "ffprobe", "-v", "error", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    info = json.loads(out.stdout)
    vs = next((s for s in info.get("streams", []) if s.get("codec_type") == "video"), None)
    if not vs:
        raise RuntimeError("ffprobe: no video stream")
    duration = info.get("format", {}).get("duration") or vs.get("duration")
    return {
        "width": int(vs.get("width") or 0),
        "height": int(vs.get("height") or 0),
        "format": (info.get("format", {}).get("format_name") or "").split(",")[0],
        "duration_ms": int(round(float(duration) * 1000)) if duration else None,
    }


def decode_samples(path: Path, duration_ms: int | None) -> None:
    duration = (duration_ms or 1000) / 1000.0
    points = [0.1, max(0.1, duration / 2), max(0.2, duration - 0.3)]
    for t in points:
        subprocess.run(
            [
                "ffmpeg", "-v", "error", "-ss", f"{t:.3f}", "-i", str(path),
                "-frames:v", "1", "-f", "null", "-",
            ],
            check=True, capture_output=True,
        )


def download(url: str, dest: Path, expected_size: int | None) -> int:
    part = dest.with_name(dest.name + ".part")
    start = part.stat().st_size if part.exists() else 0
    headers = dict(DOWNLOAD_HEADERS)
    if start:
        headers["Range"] = f"bytes={start}-"
    with requests.get(url, headers=headers, stream=True, timeout=180) as r:
        if r.status_code not in (200, 206):
            raise RuntimeError(f"download HTTP {r.status_code}")
        mode = "ab" if start and r.status_code == 206 else "wb"
        with part.open(mode) as f:
            for chunk in r.iter_content(chunk_size=1024 * 256):
                if chunk:
                    f.write(chunk)
    size = part.stat().st_size
    if expected_size and size != expected_size:
        raise RuntimeError(f"size mismatch: got {size}, expected {expected_size}")
    part.replace(dest)
    return size


def main() -> int:
    ap = argparse.ArgumentParser(description="Download selected videos via v5")
    ap.add_argument("--run-id", default=DEFAULT_RUN)
    ap.add_argument("--selected", type=Path, default=DEFAULT_SELECTED)
    ap.add_argument("--base", default="http://127.0.0.1:8000")
    ap.add_argument("--limit", type=int, default=0, help="0 = all selected")
    ap.add_argument("--sleep", type=float, default=2.0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--max-attempts", type=int, default=2)
    args = ap.parse_args()

    rows = list(csv.DictReader(args.selected.open(encoding="utf-8")))
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("no selected videos")

    key = api_key()
    session = requests.Session()
    raw_dir = ROOT / "data" / "raw" / args.run_id / "video_detail"
    media_dir = ROOT / "data" / "media" / args.run_id
    pilot_dir = ROOT / "data" / "pilot" / args.run_id
    for d in (raw_dir, media_dir, pilot_dir):
        d.mkdir(parents=True, exist_ok=True)

    csv_path = pilot_dir / "media_download.csv"
    existing = {}
    if csv_path.is_file():
        for r in csv.DictReader(csv_path.open(encoding="utf-8")):
            existing[r["aweme_id"]] = r

    columns = [
        "run_id", "aweme_id", "status", "variant", "file_path", "bytes",
        "sha256", "width", "height", "format", "duration_ms", "bitrate",
        "attempts", "error", "started_at", "finished_at",
    ]
    results = []
    total_bytes = 0
    failures = []

    for i, row in enumerate(rows, 1):
        aid = str(row["aweme_id"])
        dest = media_dir / f"{aid}.mp4"
        started = now_iso()
        attempts = 0
        last_error = None
        info = {"variant": None, "width": None, "height": None,
                "format": None, "duration_ms": None, "bitrate": None}
        try:
            if dest.exists() and not args.force:
                size = dest.stat().st_size
                digest = sha256_file(dest)
                prev = existing.get(aid) or {}
                info = {
                    "variant": prev.get("variant") or None,
                    "bitrate": prev.get("bitrate") or None,
                }
                info.update(probe(dest))
                decode_samples(dest, info["duration_ms"])
                status = "success"
                log(f"{i}/{len(rows)} {aid}: existing file ok ({size} bytes)")
            else:
                body, content = api_get(
                    session, args.base, key, "/api/v1/douyin/video",
                    {"aweme_id": aid, "include_raw": "true", "wait": 30},
                )
                (raw_dir / f"{aid}.json").write_bytes(content)
                data = body.get("data") or {}
                if data.get("kind") != "video":
                    raise RuntimeError(f"not a video: kind={data.get('kind')}")
                stream = choose_stream((data.get("media") or {}).get("streams") or [])
                info.update(
                    variant=f"mp4_{stream.get('width')}x{stream.get('height')}_{stream.get('bitrate')}",
                    width=stream.get("width"),
                    height=stream.get("height"),
                    format=stream.get("format"),
                    bitrate=stream.get("bitrate"),
                )
                expected = stream.get("size_bytes")
                for attempt in range(1, args.max_attempts + 1):
                    attempts = attempt
                    try:
                        size = download(stream["url"], dest, expected)
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_error = repr(exc)
                        if attempt == args.max_attempts:
                            raise
                        # Refresh detail/stream URL once before retrying.
                        body, content = api_get(
                            session, args.base, key, "/api/v1/douyin/video",
                            {"aweme_id": aid, "include_raw": "true", "wait": 30},
                        )
                        (raw_dir / f"{aid}.json").write_bytes(content)
                        stream = choose_stream(
                            ((body.get("data") or {}).get("media") or {}).get("streams") or []
                        )
                        time.sleep(2)
                digest = sha256_file(dest)
                info = {**info, **probe(dest)}
                decode_samples(dest, info["duration_ms"])
                status = "success"
                log(f"{i}/{len(rows)} {aid}: downloaded {size} bytes "
                    f"{info['width']}x{info['height']} {info['format']}")
            total_bytes += int(dest.stat().st_size)
            rel = str(dest.relative_to(ROOT))
            result = {
                "run_id": args.run_id, "aweme_id": aid, "status": status,
                "variant": info.get("variant"), "file_path": rel,
                "bytes": dest.stat().st_size, "sha256": digest,
                "width": info.get("width"), "height": info.get("height"),
                "format": info.get("format"), "duration_ms": info.get("duration_ms"),
                "bitrate": info.get("bitrate"), "attempts": attempts or 1,
                "error": "", "started_at": started, "finished_at": now_iso(),
            }
        except Exception as exc:  # noqa: BLE001
            status = "failed"
            last_error = repr(exc)
            failures.append({"aweme_id": aid, "error": last_error})
            log(f"{i}/{len(rows)} {aid}: FAILED {last_error}")
            result = {
                "run_id": args.run_id, "aweme_id": aid, "status": "failed",
                "variant": info.get("variant"), "file_path": "",
                "bytes": "", "sha256": "", "width": info.get("width"),
                "height": info.get("height"), "format": info.get("format"),
                "duration_ms": info.get("duration_ms"), "bitrate": info.get("bitrate"),
                "attempts": attempts or 1, "error": last_error,
                "started_at": started, "finished_at": now_iso(),
            }
        results.append(result)
        existing[aid] = result
        with csv_path.open("w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=columns)
            w.writeheader()
            for r in existing.values():
                w.writerow({k: r.get(k, "") for k in columns})
        if i < len(rows):
            time.sleep(args.sleep)

    manifest = {
        "run_id": args.run_id,
        "generated_at": now_iso(),
        "policy": "min usable: wm-free mp4, height>=540, smallest size_bytes; no dash",
        "selected_rows": len(rows),
        "success": sum(1 for r in results if r["status"] == "success"),
        "failed": len(failures),
        "total_bytes": total_bytes,
        "files": {"media_download_csv": str(csv_path.relative_to(ROOT))},
        "failures": failures,
    }
    (pilot_dir / "media_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
