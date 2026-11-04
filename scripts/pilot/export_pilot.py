#!/usr/bin/env python3
"""Stage 6: export pilot analysis tables to Parquet + CSV samples + manifest.

Reads the research DB through `docker exec psql` (CSV STDOUT), then writes:
  exports/pilot-20261030-01/parquet/{videos,comments,reply_edges,quality}.parquet
  exports/pilot-20261030-01/samples/{comments_sample,replies_sample}.csv
  exports/pilot-20261030-01/manifest.json
  exports/pilot-20261030-01/README.md

Privacy: no nickname/avatar/sec_uid/raw_json/cookie/header values. `text` is
retained because it is the core research data; this is an analysis-layer export,
not a publication-layer release.
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
RUN_ID = "pilot-20261030-01"
OUT = ROOT / "exports" / RUN_ID
SOURCE = OUT / "source"
PARQUET = OUT / "parquet"
SAMPLES = OUT / "samples"
DB_CONTAINER = "dtk-postgres-1"
DB_NAME = "douyin_research"
DB_USER = "dtk"

QUERIES = {
    "videos": """
        SELECT aweme_id, caption, created_at, duration_ms, digg_count,
               comment_count, share_count, collect_count, play_count,
               is_deleted, is_private, is_target_author, raw_sha256,
               fetched_at, run_id
        FROM video
        ORDER BY aweme_id
    """,
    "comments": """
        SELECT comment_id, aweme_id, thread_root_id, reply_to_comment_id,
               depth, is_orphan, text, created_at, digg_count, reply_count,
               is_pinned, is_author_liked, ip_province, is_author,
               is_thread_author, author_hash, hash_version, label_text,
               is_creator_label, source, raw_sha256, fetched_at, run_id
        FROM comment
        ORDER BY aweme_id, source, created_at NULLS LAST, comment_id
    """,
    "reply_edges": """
        SELECT comment_id AS child_id, reply_to_comment_id AS parent_id,
               thread_root_id, depth, is_orphan, aweme_id, raw_sha256, run_id
        FROM comment
        WHERE source = 'reply'
        ORDER BY aweme_id, thread_root_id, created_at NULLS LAST, comment_id
    """,
    "quality": """
        SELECT q.run_id, q.aweme_id, q.thread_id,
               CASE
                 WHEN q.thread_id = '__top_level__' THEN 'top_level'
                 WHEN q.thread_id = '__replies__' THEN 'reply_video'
                 ELSE 'reply_thread'
               END AS thread_kind,
               CASE WHEN q.thread_id = '__top_level__' THEN NULL ELSE j.threads->>'selection' END AS selection,
               CASE WHEN q.thread_id = '__top_level__' THEN NULL ELSE (j.threads->>'max_pages')::int END AS max_pages,
               q.expected_total, q.fetched, q.unique_count, q.duplicates,
               q.orphan_edges, q.depth3, q.coverage, q.stop_reason, q.computed_at
        FROM quality_metric q
        LEFT JOIN worker_job j
          ON j.run_id = q.run_id AND j.aweme_id = q.aweme_id
        ORDER BY q.aweme_id, thread_kind, q.thread_id
    """,
}

BOOL_COLS = {
    "videos": ["is_deleted", "is_private", "is_target_author", "is_pilot_video"],
    "comments": [
        "is_orphan", "is_pinned", "is_author_liked", "is_author",
        "is_thread_author", "is_creator_label",
    ],
    "reply_edges": ["is_orphan"],
    "quality": [],
}

INT_COLS = {
    "videos": [
        "duration_ms", "digg_count", "comment_count", "share_count",
        "collect_count", "play_count",
    ],
    "comments": ["depth", "digg_count", "reply_count"],
    "reply_edges": ["depth"],
    "quality": [
        "expected_total", "fetched", "unique_count", "duplicates",
        "orphan_edges", "depth3", "max_pages",
    ],
}

FLOAT_COLS = {"quality": ["coverage"]}
TS_COLS = {
    "videos": ["created_at", "fetched_at"],
    "comments": ["created_at", "fetched_at"],
    "reply_edges": [],
    "quality": ["computed_at"],
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
    return pd.read_csv(
        path, dtype=str, keep_default_na=False, na_values=[""],
        encoding="utf-8",
    )


def cast(df: pd.DataFrame, name: str) -> pd.DataFrame:
    for c in BOOL_COLS.get(name, []):
        if c in df:
            df[c] = df[c].map({"true": True, "false": False, "t": True, "f": False}).astype("boolean")
    for c in INT_COLS.get(name, []):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("Int64")
    for c in FLOAT_COLS.get(name, []):
        if c in df:
            df[c] = pd.to_numeric(df[c], errors="coerce").astype("float64")
    for c in TS_COLS.get(name, []):
        if c in df:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def write_parquet(df: pd.DataFrame, name: str) -> Path:
    path = PARQUET / f"{name}.parquet"
    table = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return path


def add_pilot_selection(videos: pd.DataFrame) -> pd.DataFrame:
    selected_path = ROOT / "data" / "pilot" / RUN_ID / "selected_videos.csv"
    with selected_path.open(encoding="utf-8", newline="") as f:
        selected = {r["aweme_id"]: r for r in csv.DictReader(f)}
    videos["is_pilot_video"] = videos["aweme_id"].isin(selected).astype("boolean")
    videos["pilot_selection_reason"] = videos["aweme_id"].map(
        lambda x: selected.get(x, {}).get("selection_reason")
    )
    videos["pilot_rank_in_group"] = pd.to_numeric(
        videos["aweme_id"].map(lambda x: selected.get(x, {}).get("rank_in_group")),
        errors="coerce",
    ).astype("Int64")
    return videos


def main() -> int:
    for d in (SOURCE, PARQUET, SAMPLES):
        d.mkdir(parents=True, exist_ok=True)

    paths = {name: export_csv(name, sql) for name, sql in QUERIES.items()}
    frames = {name: cast(read_csv(path), name) for name, path in paths.items()}
    frames["videos"] = add_pilot_selection(frames["videos"])

    # Keep a stable, readable column order.
    video_cols = [
        "aweme_id", "caption", "created_at", "duration_ms", "digg_count",
        "comment_count", "share_count", "collect_count", "play_count",
        "is_deleted", "is_private", "is_target_author", "is_pilot_video",
        "pilot_selection_reason", "pilot_rank_in_group", "raw_sha256",
        "fetched_at", "run_id",
    ]
    comment_cols = [
        "comment_id", "aweme_id", "thread_root_id", "reply_to_comment_id",
        "depth", "is_orphan", "text", "created_at", "digg_count",
        "reply_count", "is_pinned", "is_author_liked", "ip_province",
        "is_author", "is_thread_author", "author_hash", "hash_version",
        "label_text", "is_creator_label", "source", "raw_sha256",
        "fetched_at", "run_id",
    ]
    edge_cols = [
        "child_id", "parent_id", "thread_root_id", "depth", "is_orphan",
        "aweme_id", "raw_sha256", "run_id",
    ]
    quality_cols = [
        "run_id", "aweme_id", "thread_id", "thread_kind", "selection",
        "max_pages", "expected_total", "fetched", "unique_count",
        "duplicates", "orphan_edges", "depth3", "coverage", "stop_reason",
        "computed_at",
    ]
    frames["videos"] = frames["videos"][video_cols]
    frames["comments"] = frames["comments"][comment_cols]
    frames["reply_edges"] = frames["reply_edges"][edge_cols]
    frames["quality"] = frames["quality"][quality_cols]

    # CSV samples (full text; analysis layer only).
    top = frames["comments"][frames["comments"]["source"] == "top_level"].copy()
    top = top.sort_values(["aweme_id", "created_at", "comment_id"])
    top_sample = top.groupby("aweme_id", sort=False).head(100)
    top_sample.to_csv(
        SAMPLES / "comments_sample.csv", index=False, encoding="utf-8-sig"
    )

    replies = frames["comments"][frames["comments"]["source"] == "reply"].copy()
    replies = replies.sort_values(["thread_root_id", "created_at", "comment_id"])
    reply_sample = replies.groupby("thread_root_id", sort=False).head(50)
    reply_sample.to_csv(
        SAMPLES / "replies_sample.csv", index=False, encoding="utf-8-sig"
    )

    parquet_paths = {
        name: write_parquet(frame, name) for name, frame in frames.items()
    }

    # Manifest.
    stage5 = json.loads(
        (ROOT / "data" / "pilot" / RUN_ID / "replies_import/stage5_metrics.json").read_text(
            encoding="utf-8"
        )
    )
    run_notes = subprocess.run(
        [
            "docker", "exec", DB_CONTAINER, "psql", "-U", DB_USER, "-d", DB_NAME,
            "-X", "-q", "-A", "-t", "-c",
            "select notes from run where run_id='pilot-20261030-01'",
        ],
        check=True, capture_output=True, text=True,
    ).stdout.strip()

    files = {}
    for p in sorted(list(PARQUET.glob("*.parquet")) + list(SAMPLES.glob("*.csv"))):
        files[str(p.relative_to(OUT))] = {
            "bytes": p.stat().st_size,
            "sha256": sha256(p),
        }

    schema = {}
    for name, p in parquet_paths.items():
        schema[name] = [
            {"name": field.name, "type": str(field.type)}
            for field in pq.read_schema(p)
        ]

    field_dictionary = {
        "videos.aweme_id": "抖音视频 ID；字符串，避免 19 位整数丢失",
        "videos.caption": "视频文案（公开内容；可能含话题/地点）",
        "videos.is_target_author": "是否为目标账号（绍兴文旅）本人作品",
        "videos.is_pilot_video": "是否进入 20 个 pilot 视频",
        "videos.pilot_selection_reason": "high_comment / time_spread",
        "videos.author_sec_uid / author_nickname": "已排除，不进入导出",
        "comments.comment_id": "评论/回复 ID",
        "comments.thread_root_id": "所属一级评论 ID（thread root）",
        "comments.reply_to_comment_id": "直接父评论 ID；一级评论为 NULL",
        "comments.depth": "2=直接回复一级评论；>2=回复的回复；NULL=父节点缺失或深度不可传",
        "comments.is_orphan": "直接父评论不在已抓回复集内",
        "comments.text": "完整文本；分析层核心数据，发表前需脱敏",
        "comments.author_hash": "HMAC-SHA256(salt, 'douyin:'+sec_uid)，v1；伪名化，不是匿名化",
        "comments.ip_province": "平台 IP 属地（省级），准标识符",
        "comments.is_author": "是否视频作者本人（sec_uid 比较）",
        "comments.is_thread_author": "pilot 预留；本轮全为 NULL",
        "reply_edges.child_id": "回复 comment_id",
        "reply_edges.parent_id": "直接父评论 ID；可能不在 comment 表中（孤儿）",
        "quality.thread_kind": "top_level / reply_video / reply_thread",
        "quality.coverage": "unique_count / expected_total；可能 >1（平台计数滞后）",
        "quality.stop_reason": "complete / max_pages / risk_control 等",
    }

    manifest = {
        "export_version": "1.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": RUN_ID,
        "source_round": "20261030T125114Z-pilot-replies",
        "source_db": f"postgres://{DB_USER}@/{DB_NAME} (container {DB_CONTAINER})",
        "row_counts": {name: int(len(df)) for name, df in frames.items()},
        "sample_row_counts": {
            "comments_sample": int(len(top_sample)),
            "replies_sample": int(len(reply_sample)),
        },
        "coverage": {
            "top_level": {
                "unique": 23012,
                "videos": 20,
                "stop_reason": "20/20 complete",
                "duplicates": 1835,
                "duplicate_rate": 0.0738,
            },
            "replies": {
                "threads": stage5["threads"],
                "complete_threads": stage5["complete_threads"],
                "max_pages_threads": stage5["max_pages_threads"],
                "expected_total": stage5["expected_total"],
                "unique_total": stage5["unique_total"],
                "coverage": stage5["coverage"],
                "complete_expected": stage5["complete_expected"],
                "complete_unique": stage5["complete_unique"],
                "complete_coverage": stage5["complete_coverage"],
                "orphan_edges": 43,
                "depth_null": 72,
                "max_depth": 14,
                "author_replies": 57,
                "ip_nonnull": stage5["ip_nonnull"],
                "ip_total": stage5["ip_total"],
                "ip_rate": stage5["ip_rate"],
            },
            "combined_comments": 27211,
        },
        "privacy": {
            "layer": "analysis",
            "included": ["text", "author_hash", "ip_province", "thread structure"],
            "excluded": [
                "nickname", "avatar", "signature", "sec_uid", "uid",
                "raw_json", "cookie", "header values", "HMAC salt",
            ],
            "note": "author_hash 是伪名化，不是匿名化；文本可能含姓名/地点/联系方式；发表前必须脱敏/改写。",
        },
        "known_issues": [
            "3 个 shallow thread 在 max_pages=3 截断，整体 coverage 因此降到 86.85%。",
            "801 个 complete 线程中 7 个合计缺 10 条；1 个多 2 条；不自动重跑。",
            "20 个 thread 的端点 total 与一级评论 reply_count 不一致（+25），属平台计数漂移。",
            "43 个孤儿边；72 个 depth NULL（43 孤儿 + 29 孤儿后代）。",
            "is_thread_author 本轮全为 NULL（pilot 预留）。",
            "videos.play_count 全为 NULL（v5 视频列表未返回）；duration_ms 有 3 个 NULL。",
            "回复的 reply_count/is_pinned/is_author_liked 未采集（NULL）；一级评论有这些字段。",
            "2 次人工人机验证由用户手动通过；worker 未记录 risk_control，未发现数据损失。",
            "回复 raw/state 留在 Windows 本地；comment_raw 仅含 23,012 条一级评论。",
        ],
        "raw_and_incidents": {
            "comment_raw_rows": 23012,
            "comment_raw_scope": "top-level comments only",
            "reply_raw_location": "Windows local out/pilot-20261030-01/raw (not in share/export)",
            "reply_state_location": "Windows local out/pilot-20261030-01/state (not in share/export)",
            "captcha_events_manual": 2,
            "captcha_worker_logged": False,
            "captcha_data_loss_detected": False,
            "salt_included": False,
        },
        "run_notes": run_notes,
        "files": files,
        "schema": schema,
        "field_dictionary": field_dictionary,
    }
    (OUT / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    readme = f"""# Pilot Export — {RUN_ID}

> 生成：{manifest['generated_at']}
> 来源：{RUN_ID} / Round 20261030T125114Z-pilot-replies
> 这是**分析层**导出，不是发表层；`text` 保留，发表前必须脱敏。

## 文件

| 文件 | 行数 | 说明 |
|---|---:|---|
| `parquet/videos.parquet` | {len(frames['videos'])} | 765 个视频；`is_target_author`/`is_pilot_video` 可筛 |
| `parquet/comments.parquet` | {len(frames['comments'])} | 23,012 一级 + 4,199 回复 |
| `parquet/reply_edges.parquet` | {len(frames['reply_edges'])} | 回复父子边；孤儿保留 |
| `parquet/quality.parquet` | {len(frames['quality'])} | 20 一级 + 804 线程 + 17 视频汇总 |
| `samples/comments_sample.csv` | {len(top_sample)} | 每视频前 100 条一级评论，UTF-8-sig |
| `samples/replies_sample.csv` | {len(reply_sample)} | 每 thread 前 50 条回复，UTF-8-sig |

## 关键质量

- 一级评论：23,012 unique；20/20 视频 `complete`；重复 1,835（7.4%）。
- 回复：4,199 unique；801/804 `complete`；3 个浅抓 `max_pages=3`。
- 整体回复 coverage：{stage5['coverage']:.2%}；完整线程 coverage：{stage5['complete_coverage']:.2%}。
- 孤儿边 43；depth NULL 72；最大 depth 14；作者回复 57。
- IP 属地非空：4,109/4,199（{stage5['ip_rate']:.2%}）。
- 两次人工人机验证，未发现数据损失；生产需验证码检测/人工值守。

## 隐私

- 不含昵称/头像/签名/原始 UID/sec_uid/raw_json/cookie/header。
- `author_hash` 是 HMAC 伪名化；文本仍可能识别个人。
- `ip_province` 是准标识符；发表层不要逐条公开。

## 复现

```bash
python scripts/pilot/prepare_replies_import.py
python scripts/pilot/export_pilot.py
```
"""
    (OUT / "README.md").write_text(readme, encoding="utf-8")

    print(json.dumps({
        "out": str(OUT),
        "row_counts": manifest["row_counts"],
        "samples": manifest["sample_row_counts"],
        "files": {k: v["bytes"] for k, v in files.items()},
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
