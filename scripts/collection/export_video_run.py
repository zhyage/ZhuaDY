#!/usr/bin/env python3
"""V5: export pilot-video-20261031-01 snapshots + downloads.

Writes:
  exports/<run_id>/parquet/{videos,selected_videos,media_downloads,account}.parquet
  exports/<run_id>/samples/{selected_videos,media_downloads}.csv
  exports/<run_id>/manifest.json
  exports/<run_id>/README.md
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[2]
RUN_ID = "pilot-video-20261031-01"
OUT = ROOT / "exports" / RUN_ID
SOURCE = ROOT / "data" / "pilot" / RUN_ID / "export_source"
PARQUET = OUT / "parquet"
SAMPLES = OUT / "samples"
DB_CONTAINER = "dtk-postgres-1"
DB_USER = "dtk"
DB_NAME = "douyin_research"

QUERIES = {
    "videos": f"""
        SELECT run_id, aweme_id, account_id, author_sec_uid, author_nickname,
               is_target_author, caption, created_at, duration_ms, digg_count,
               comment_count, share_count, collect_count, play_count,
               is_deleted, is_private, web_url, kind, tags, recommend_count,
               media_width, media_height, media_format, media_size_bytes,
               media_bitrate, author_certification, author_favoriting_count,
               collected_at, raw_sha256, fetched_at, video_file_path,
               video_sha256, video_variant, video_bytes, video_width,
               video_height, video_format, video_duration_ms, downloaded_at,
               video_codec
        FROM video_snapshot
        WHERE run_id = '{RUN_ID}'
        ORDER BY aweme_id
    """,
    "media_downloads": f"""
        SELECT run_id, aweme_id, status, codec, variant, file_path, bytes,
               sha256, width, height, format, duration_ms, bitrate, attempts,
               error, started_at, finished_at
        FROM media_download
        WHERE run_id = '{RUN_ID}'
        ORDER BY aweme_id
    """,
    "account": f"""
        SELECT run_id, account_id, sec_uid, unique_id, nickname, signature,
               verified, follower_count, following_count, total_favorited,
               aweme_count, certification, favoriting_count, collected_at,
               raw_sha256, fetched_at
        FROM account_snapshot
        WHERE run_id = '{RUN_ID}'
    """,
}

BOOL_COLS = {
    "videos": ["is_target_author", "is_deleted", "is_private", "is_selected"],
    "media_downloads": [],
    "account": ["verified"],
}
INT_COLS = {
    "videos": [
        "duration_ms", "digg_count", "comment_count", "share_count",
        "collect_count", "play_count", "recommend_count", "media_width",
        "media_height", "media_size_bytes", "media_bitrate",
        "author_favoriting_count", "video_bytes", "video_width",
        "video_height", "video_duration_ms", "pilot_rank_in_group",
    ],
    "media_downloads": ["bytes", "width", "height", "duration_ms", "bitrate", "attempts"],
    "account": ["follower_count", "following_count", "total_favorited", "aweme_count", "favoriting_count"],
}
FLOAT_COLS = {"videos": [], "media_downloads": [], "account": []}
TS_COLS = {
    "videos": ["created_at", "collected_at", "fetched_at", "downloaded_at"],
    "media_downloads": ["started_at", "finished_at"],
    "account": ["collected_at", "fetched_at"],
}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def export_csv(name: str, sql: str) -> Path:
    path = SOURCE / f"{name}.csv"
    cmd = [
        "docker", "exec", DB_CONTAINER,
        "psql", "-U", DB_USER, "-d", DB_NAME, "-X", "-q",
        "-v", "ON_ERROR_STOP=1",
        "-c", f"\\copy ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true, NULL '')",
    ]
    with path.open("wb") as f:
        subprocess.run(cmd, check=True, stdout=f)
    return path


def read_csv(path: Path) -> pd.DataFrame:
    return pd.read_csv(path, dtype=str, keep_default_na=False, na_values=[""], encoding="utf-8")


def cast(df: pd.DataFrame, name: str) -> pd.DataFrame:
    for c in BOOL_COLS.get(name, []):
        if c in df:
            df[c] = df[c].map({"true": True, "false": False, "t": True, "f": False}).astype("boolean")
    for c in INT_COLS.get(name, []):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in TS_COLS.get(name, []):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def write_parquet(df: pd.DataFrame, name: str) -> Path:
    path = PARQUET / f"{name}.parquet"
    pq.write_table(pa.Table.from_pandas(df, preserve_index=False), path, compression="zstd")
    return path


def main() -> int:
    for d in (SOURCE, PARQUET, SAMPLES):
        d.mkdir(parents=True, exist_ok=True)

    paths = {name: export_csv(name, sql) for name, sql in QUERIES.items()}
    frames = {name: cast(read_csv(path), name) for name, path in paths.items()}
    videos = frames["videos"]
    media = frames["media_downloads"]
    account = frames["account"]

    selected_path = ROOT / "data" / "pilot" / RUN_ID / "selected_videos.csv"
    selected = {r["aweme_id"]: r for r in csv.DictReader(selected_path.open(encoding="utf-8"))}
    videos["is_selected"] = videos["aweme_id"].isin(selected).astype("boolean")
    videos["selection_reason"] = videos["aweme_id"].map(lambda x: (selected.get(x) or {}).get("selection_reason"))
    videos["pilot_rank_in_group"] = pd.to_numeric(
        videos["aweme_id"].map(lambda x: (selected.get(x) or {}).get("rank_in_group")),
        errors="coerce",
    ).astype("Int64")
    videos["tags"] = videos["tags"].map(lambda x: json.loads(x) if isinstance(x, str) and x else [])

    # Privacy: do not export direct author identifiers or raw page paths.
    videos = videos.drop(columns=["account_id", "author_sec_uid", "author_nickname"], errors="ignore")
    account = account.drop(columns=["account_id", "sec_uid", "unique_id", "nickname"], errors="ignore")

    video_cols = [
        "run_id", "aweme_id", "is_target_author", "is_selected",
        "selection_reason", "pilot_rank_in_group", "caption", "created_at",
        "duration_ms", "digg_count", "comment_count", "share_count",
        "collect_count", "play_count", "is_deleted", "is_private", "web_url",
        "kind", "tags", "recommend_count", "media_width", "media_height",
        "media_format", "media_size_bytes", "media_bitrate",
        "author_certification", "author_favoriting_count", "collected_at",
        "raw_sha256", "fetched_at", "video_file_path", "video_sha256",
        "video_variant", "video_bytes", "video_width", "video_height",
        "video_format", "video_duration_ms", "downloaded_at", "video_codec",
    ]
    videos = videos[video_cols]
    selected_df = videos[videos["is_selected"] == True].copy()  # noqa: E712
    media_cols = [
        "run_id", "aweme_id", "status", "codec", "variant", "file_path",
        "bytes", "sha256", "width", "height", "format", "duration_ms",
        "bitrate", "attempts", "error", "started_at", "finished_at",
    ]
    media = media[media_cols]
    account_cols = [
        "run_id", "signature", "verified",
        "follower_count", "following_count", "total_favorited", "aweme_count",
        "certification", "favoriting_count", "collected_at", "raw_sha256",
        "fetched_at",
    ]
    account = account[account_cols]

    selected_df.to_csv(SAMPLES / "selected_videos.csv", index=False, encoding="utf-8-sig")
    media.to_csv(SAMPLES / "media_downloads.csv", index=False, encoding="utf-8-sig")

    parquet_paths = {
        "videos": write_parquet(videos, "videos"),
        "selected_videos": write_parquet(selected_df, "selected_videos"),
        "media_downloads": write_parquet(media, "media_downloads"),
        "account": write_parquet(account, "account"),
    }

    files = {}
    for p in sorted(list(PARQUET.glob("*.parquet")) + list(SAMPLES.glob("*.csv"))):
        files[str(p.relative_to(OUT))] = {"bytes": p.stat().st_size, "sha256": sha256(p)}

    schema = {
        name: [{"name": f.name, "type": str(f.type)} for f in pq.read_schema(p)]
        for name, p in parquet_paths.items()
    }

    codec_counts = media["codec"].value_counts(dropna=False).to_dict()
    status_counts = media["status"].value_counts(dropna=False).to_dict()
    total_bytes = int(media.loc[media["status"] == "success", "bytes"].fillna(0).sum())
    durations = videos["duration_ms"].dropna()
    selected_durations = selected_df["duration_ms"].dropna()
    actual_durations = selected_df["video_duration_ms"].dropna()
    duration_diff = (actual_durations - selected_durations).abs().dropna()
    tags_nonempty = int(videos["tags"].map(lambda x: len(x) > 0).sum())

    manifest = {
        "export_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "source_db": f"postgres://{DB_USER}@/{DB_NAME} (container {DB_CONTAINER})",
        "source_selection": str(selected_path.relative_to(ROOT)),
        "row_counts": {name: int(len(df)) for name, df in {
            "videos": videos, "selected_videos": selected_df,
            "media_downloads": media, "account": account,
        }.items()},
        "metadata": {
            "videos": int(len(videos)),
            "target_author": int(videos["is_target_author"].sum()),
            "other_author": int((~videos["is_target_author"].fillna(False)).sum()),
            "selected": int(len(selected_df)),
            "web_url_nonnull": int(videos["web_url"].notna().sum()),
            "kind_nonnull": int(videos["kind"].notna().sum()),
            "tags_nonempty": tags_nonempty,
            "recommend_nonnull": int(videos["recommend_count"].notna().sum()),
            "media_size_nonnull": int(videos["media_size_bytes"].notna().sum()),
            "author_certification_nonnull": int(videos["author_certification"].notna().sum()),
            "collected_at_nonnull": int(videos["collected_at"].notna().sum()),
        },
        "downloads": {
            "attempted": int(len(media)),
            "status_counts": {str(k): int(v) for k, v in status_counts.items()},
            "success": int((media["status"] == "success").sum()),
            "failed": int((media["status"] == "failed").sum()),
            "total_bytes": total_bytes,
            "total_GB": round(total_bytes / 1e9, 3),
            "avg_MB": round(total_bytes / max(1, int((media["status"] == "success").sum())) / 1e6, 2),
            "codec_counts": {str(k): int(v) for k, v in codec_counts.items()},
            "duration_diff_max_ms": round(float(duration_diff.max()), 1) if len(duration_diff) else None,
            "duration_diff_over_1s": int((duration_diff > 1000).sum()) if len(duration_diff) else 0,
        },
        "privacy": {
            "layer": "analysis",
            "included": ["caption", "public video metadata", "tags", "author certification", "local media path/hash"],
            "excluded": ["account_id/sec_uid", "author_sec_uid", "author_nickname", "unique_id", "raw page paths", "signed media URLs", "cookies", "headers", "ASR/subtitles"],
            "note": "视频文件保留在本地 media vault；caption/tags 是公开内容；视觉分析需遵守 IRB 和肖像/场景伦理。",
        },
        "known_issues": [
            "104/765 条 media_size_bytes 为 NULL；以实际下载 video_bytes 为准。",
            "21/765 条 tags 为空数组。",
            "新 20 条中 HEVC 16、H.264 4；视觉分析走 ffmpeg 抽帧，不需要转码。",
            "本轮不抓评论/回复、不做 ASR/字幕、不做人物/室内外模型。",
            "旧 pilot-20261030-01 的 account/video 未被修改。",
        ],
        "files": files,
        "schema": schema,
    }
    frames_dir = ROOT / "data" / "frames" / RUN_ID
    if (frames_dir / "frames_manifest.json").is_file():
        fm = json.loads((frames_dir / "frames_manifest.json").read_text(encoding="utf-8"))
        manifest["frames"] = {
            "frames_root": str(frames_dir.relative_to(ROOT)),
            "frames_total": fm.get("frames_total"),
            "frames_bytes": fm.get("frames_bytes"),
            "videos_success": fm.get("videos_success"),
            "videos_failed": fm.get("videos_failed"),
            "params": fm.get("params"),
            "frames_jsonl": fm.get("files", {}).get("frames_jsonl"),
            "frames_manifest": str((frames_dir / "frames_manifest.json").relative_to(ROOT)),
            "frames_jsonl_sha256": sha256(frames_dir / "frames.jsonl") if (frames_dir / "frames.jsonl").is_file() else None,
            "note": "JPEG frames are in data/frames/<run_id>/; not copied into exports/.",
        }
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    readme = f"""# Video Metadata Export — {RUN_ID}

> 生成：{manifest['generated_at']}
> 来源：{RUN_ID}（v5 include_raw=true + P5a 下载）
> 这是**分析层**导出；视频文件在本地 media vault，不在导出目录。

## 文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `parquet/videos.parquet` | {len(videos)} | 765 条视频快照；`is_selected` 标出 20 条 |
| `parquet/selected_videos.parquet` | {len(selected_df)} | 新 20 条 |
| `parquet/media_downloads.parquet` | {len(media)} | 20 条下载记录 |
| `parquet/account.parquet` | {len(account)} | 账号快照 |
| `samples/selected_videos.csv` | {len(selected_df)} | UTF-8-sig |
| `samples/media_downloads.csv` | {len(media)} | UTF-8-sig |

帧数据在 `data/frames/{RUN_ID}/`：1 fps、最长边 1280、JPEG；不复制进导出目录。

## 关键结果

- 765 条：730 target + 35 other；`web_url` 765/765、`kind` 765/765、`tags` 有值 {tags_nonempty}/765、`recommend_count` 765/765。
- 新 20 条：10 high_comment + 10 time_spread；与 pilot 重叠 0。
- 下载 20/20：{total_bytes:,} bytes（{total_bytes/1e9:.3f} GB）；平均 {total_bytes/20/1e6:.2f} MB；0 失败。
- codec：{codec_counts}；duration 最大差 {manifest['downloads']['duration_diff_max_ms']} ms，>1s 条数 {manifest['downloads']['duration_diff_over_1s']}。
- 视觉分析：保留 HEVC 原文件，ffmpeg 抽帧 → JPEG → OpenCV；不转 H.264。

## 隐私

- 导出不含 `account_id`/`sec_uid`/`author_sec_uid`/`author_nickname`/`unique_id`/raw page path/签名 URL/cookie/header。
- `caption`/`tags` 是公开内容；视频文件与帧需按 IRB 控制访问。

## 复现

```bash
python scripts/collection/fetch_video_metadata.py --run-id {RUN_ID}
docker exec ... psql ... -f sql/import_video_metadata.sql
docker exec ... psql ... -f sql/select_next_videos.sql
python scripts/collection/download_videos.py
python scripts/collection/export_video_run.py
```
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "row_counts": manifest["row_counts"],
        "downloads": manifest["downloads"],
        "files": {k: v["bytes"] for k, v in files.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
