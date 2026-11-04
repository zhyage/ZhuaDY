#!/usr/bin/env python3
"""P5b: extract JPEG frames from downloaded videos for OpenCV.

Design (confirmed 2026-10-31):
  * keep HEVC originals; do not transcode to H.264;
  * ffmpeg -> JPEG -> OpenCV reads images;
  * default 1 fps, longest side max 1280, JPEG qscale 2;
  * write frames.jsonl + frames_manifest.json with source hashes/timestamps.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUN = "pilot-video-20261031-01"
DEFAULT_MEDIA = ROOT / "data" / "pilot" / DEFAULT_RUN / "media_download.csv"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def log(msg: str) -> None:
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def extract_one(video: Path, outdir: Path, fps: float, max_side: int, quality: int) -> int:
    outdir.mkdir(parents=True, exist_ok=True)
    for old in outdir.glob("*.jpg"):
        old.unlink()
    # Fit inside max_side x max_side without upscaling.
    vf = (
        f"fps={fps},"
        f"scale=w='min({max_side},iw)':h='min({max_side},ih)'"
        f":force_original_aspect_ratio=decrease"
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video), "-vf", vf, "-q:v", str(quality),
        "-start_number", "0", str(outdir / "%08d.jpg"),
    ]
    subprocess.run(cmd, check=True)
    return len(list(outdir.glob("*.jpg")))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-id", default=DEFAULT_RUN)
    ap.add_argument("--media-csv", type=Path, default=DEFAULT_MEDIA)
    ap.add_argument("--fps", type=float, default=1.0)
    ap.add_argument("--max-side", type=int, default=1280)
    ap.add_argument("--quality", type=int, default=2, help="ffmpeg -q:v (2=high, 31=low)")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    rows = list(csv.DictReader(args.media_csv.open(encoding="utf-8")))
    rows = [r for r in rows if r.get("status") == "success"]
    if args.limit:
        rows = rows[: args.limit]
    if not rows:
        raise SystemExit("no successful downloads")

    frames_root = ROOT / "data" / "frames" / args.run_id
    frames_root.mkdir(parents=True, exist_ok=True)
    jsonl_path = frames_root / "frames.jsonl"
    records = []
    per_video = []
    failures = []

    with jsonl_path.open("w", encoding="utf-8") as fh:
        for i, r in enumerate(rows, 1):
            aid = r["aweme_id"]
            video = ROOT / r["file_path"]
            outdir = frames_root / aid
            try:
                n = extract_one(video, outdir, args.fps, args.max_side, args.quality)
                files = sorted(outdir.glob("*.jpg"))
                width = height = None
                total_bytes = 0
                for idx, p in enumerate(files):
                    with Image.open(p) as im:
                        width, height = im.size
                    h = sha256_file(p)
                    total_bytes += p.stat().st_size
                    rec = {
                        "run_id": args.run_id,
                        "aweme_id": aid,
                        "frame_index": idx,
                        "timestamp_ms": int(round(idx * 1000 / args.fps)),
                        "file_path": str(p.relative_to(ROOT)),
                        "frame_sha256": h,
                        "width": width,
                        "height": height,
                        "jpeg_quality": args.quality,
                        "source_video_path": r["file_path"],
                        "source_video_sha256": r.get("sha256") or "",
                        "source_video_duration_ms": int(r["duration_ms"]) if r.get("duration_ms") else None,
                        "source_video_codec": r.get("codec") or "",
                        "fps": args.fps,
                        "max_side": args.max_side,
                        "extractor_version": "1.0",
                    }
                    records.append(rec)
                    fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                per_video.append({
                    "aweme_id": aid, "status": "success", "frames": n,
                    "bytes": total_bytes, "width": width, "height": height,
                    "source_video_sha256": r.get("sha256") or "",
                })
                log(f"{i}/{len(rows)} {aid}: {n} frames")
            except Exception as exc:  # noqa: BLE001
                failures.append({"aweme_id": aid, "error": repr(exc)})
                per_video.append({"aweme_id": aid, "status": "failed", "frames": 0,
                                  "error": repr(exc)})
                log(f"{i}/{len(rows)} {aid}: FAILED {exc!r}")

    manifest = {
        "run_id": args.run_id,
        "generated_at": now_iso(),
        "params": {
            "fps": args.fps, "max_side": args.max_side,
            "jpeg_qscale": args.quality, "scale_mode": "fit_without_upscale",
        },
        "videos_attempted": len(rows),
        "videos_success": sum(1 for v in per_video if v["status"] == "success"),
        "videos_failed": len(failures),
        "frames_total": len(records),
        "frames_bytes": sum(p.stat().st_size for p in frames_root.glob("*/*.jpg")),
        "failures": failures,
        "per_video": per_video,
        "files": {
            "frames_jsonl": str(jsonl_path.relative_to(ROOT)),
            "frames_root": str(frames_root.relative_to(ROOT)),
        },
    }
    (frames_root / "frames_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
