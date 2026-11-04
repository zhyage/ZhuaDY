#!/usr/bin/env python3
"""Validate Round 005 normalized replies and build DB import CSVs.

Inputs:
  data/pilot/pilot-20261030-01/jobs.json
  /data/shareFolder/douYin/<round>/result/outputs/worker_summary.json
  /data/shareFolder/douYin/<round>/result/outputs/normalized/*.jsonl
  data/pilot/pilot-20261030-01/comments.csv  (top-level roots)

Outputs (data/pilot/pilot-20261030-01/replies_import/):
  replies.csv
  replies_quality.csv
  replies_quality_video.csv
  validation.json
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_JOBS = ROOT / "data/pilot/pilot-20261030-01/jobs.json"
DEFAULT_TOP = ROOT / "data/pilot/pilot-20261030-01/comments.csv"
DEFAULT_OUT = ROOT / "data/pilot/pilot-20261030-01/replies_import"
DEFAULT_RESULT = Path(
    "/data/shareFolder/douYin/20261030T125114Z-pilot-replies/result/outputs"
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--jobs", type=Path, default=DEFAULT_JOBS)
    ap.add_argument("--top-comments", type=Path, default=DEFAULT_TOP)
    ap.add_argument("--result", type=Path, default=DEFAULT_RESULT)
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    jobs_doc = load_json(args.jobs)
    run_id = jobs_doc["run_id"]
    jobs = jobs_doc["jobs"]

    thread_to_job: dict[str, dict] = {}
    aweme_to_job: dict[str, dict] = {}
    for job in jobs:
        aweme = str(job["aweme_id"])
        aweme_to_job[aweme] = job
        for tid in job["threads"]:
            tid = str(tid)
            if tid in thread_to_job:
                raise SystemExit(f"duplicate thread in jobs: {tid}")
            thread_to_job[tid] = {"aweme_id": aweme, "job": job}

    summary_path = args.result / "worker_summary.json"
    summary = load_json(summary_path)
    summary_threads = summary["threads"]
    if summary.get("run_id") != run_id:
        raise SystemExit(f"run_id mismatch: {summary.get('run_id')} != {run_id}")

    summary_by_tid = {str(t["thread_id"]): t for t in summary_threads}
    if len(summary_by_tid) != len(summary_threads):
        raise SystemExit("duplicate thread_id in worker_summary")

    missing_in_summary = sorted(set(thread_to_job) - set(summary_by_tid))
    extra_in_summary = sorted(set(summary_by_tid) - set(thread_to_job))
    if missing_in_summary or extra_in_summary:
        raise SystemExit(
            f"thread set mismatch: missing={missing_in_summary[:5]} "
            f"extra={extra_in_summary[:5]}"
        )

    top_ids = set()
    top_hashes = set()
    with args.top_comments.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            top_ids.add(r["comment_id"])
            if r.get("author_hash"):
                top_hashes.add(r["author_hash"])

    norm_dir = args.result / "normalized"
    files = sorted(norm_dir.glob("*.jsonl"))
    file_awemes = {p.stem for p in files}
    if file_awemes != set(aweme_to_job):
        raise SystemExit(
            f"normalized file set mismatch: files={sorted(file_awemes)} "
            f"jobs={sorted(aweme_to_job)}"
        )

    rows: list[dict] = []
    rows_by_aweme: dict[str, list[dict]] = defaultdict(list)
    for p in files:
        aweme = p.stem
        for line in p.open(encoding="utf-8"):
            r = json.loads(line)
            if str(r.get("aweme_id")) != aweme:
                raise SystemExit(f"aweme mismatch in {p}: {r.get('aweme_id')}")
            tid = str(r.get("thread_root_id"))
            if tid not in thread_to_job:
                raise SystemExit(f"thread not in jobs: {tid} ({p})")
            if thread_to_job[tid]["aweme_id"] != aweme:
                raise SystemExit(f"thread/aweme mismatch: {tid} {aweme}")
            if r.get("source") != "reply":
                raise SystemExit(f"unexpected source: {r.get('source')}")
            if not r.get("author_hash") or len(r["author_hash"]) != 64:
                raise SystemExit(f"bad author_hash: {r.get('comment_id')}")
            if not r.get("text"):
                raise SystemExit(f"empty text: {r.get('comment_id')}")
            rows.append(r)
            rows_by_aweme[aweme].append(r)

    ids = [str(r["comment_id"]) for r in rows]
    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate comment_id in normalized replies")

    # Depth / parent consistency.
    depth_counts = Counter()
    depth_mismatch = []
    orphan_depth_mismatch = []
    for r in rows:
        d = r.get("depth")
        depth_counts[str(d)] += 1
        parent = str(r.get("reply_to_comment_id"))
        root = str(r.get("thread_root_id"))
        if d == 2 and parent != root:
            depth_mismatch.append((r["comment_id"], d, parent, root))
        if d is not None and d > 2 and parent == root:
            depth_mismatch.append((r["comment_id"], d, parent, root))
        if r.get("is_orphan") and d is not None:
            orphan_depth_mismatch.append((r["comment_id"], d, r.get("is_orphan")))

    # Per-thread normalized counts vs summary.
    rows_by_tid = Counter(str(r["thread_root_id"]) for r in rows)
    thread_mismatch = []
    for tid, s in summary_by_tid.items():
        n = rows_by_tid.get(tid, 0)
        if n != int(s.get("unique") or 0):
            thread_mismatch.append(
                {"thread_id": tid, "normalized_rows": n, "summary_unique": s.get("unique")}
            )

    # Per-video aggregate from summary.
    summary_by_aweme: dict[str, list[dict]] = defaultdict(list)
    for tid, s in summary_by_tid.items():
        summary_by_aweme[thread_to_job[tid]["aweme_id"]].append(s)

    video_rows = []
    for aweme, slist in sorted(summary_by_aweme.items()):
        expected = sum(int(s.get("expected_total") or 0) for s in slist)
        fetched = sum(int(s.get("fetched") or 0) for s in slist)
        unique = sum(int(s.get("unique") or 0) for s in slist)
        duplicates = sum(int(s.get("duplicates") or 0) for s in slist)
        orphans = sum(int(s.get("orphan_edges") or 0) for s in slist)
        depth3 = sum(int(s.get("depth3") or 0) for s in slist)
        non_complete = sum(1 for s in slist if s.get("stop_reason") != "complete")
        coverage = (unique / expected) if expected else None
        video_rows.append(
            {
                "run_id": run_id,
                "aweme_id": aweme,
                "thread_id": "__replies__",
                "expected_total": expected,
                "fetched": fetched,
                "unique_count": unique,
                "duplicates": duplicates,
                "orphan_edges": orphans,
                "depth3": depth3,
                "coverage": coverage,
                "stop_reason": "partial" if non_complete else "complete",
                "threads": len(slist),
                "non_complete_threads": non_complete,
                "normalized_rows": len(rows_by_aweme.get(aweme, [])),
            }
        )

    # Root existence.
    missing_roots = sorted(set(thread_to_job) - top_ids)

    # Author hash overlap with top-level comments.
    reply_hashes = {r["author_hash"] for r in rows}
    hash_overlap = len(reply_hashes & top_hashes)
    rows_by_top_author = sum(1 for r in rows if r["author_hash"] in top_hashes)

    # Write comment CSV.
    comment_cols = [
        "comment_id", "aweme_id", "thread_root_id", "reply_to_comment_id",
        "depth", "is_orphan", "text", "created_at", "digg_count", "reply_count",
        "is_pinned", "is_author_liked", "ip_province", "is_author",
        "is_thread_author", "author_hash", "hash_version", "label_text",
        "label_texts", "is_creator_label", "source", "raw_sha256", "raw_page",
        "run_id",
    ]
    replies_csv = args.out / "replies.csv"
    with replies_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=comment_cols)
        w.writeheader()
        for r in rows:
            w.writerow(
                {
                    "comment_id": r["comment_id"],
                    "aweme_id": r["aweme_id"],
                    "thread_root_id": r.get("thread_root_id") or "",
                    "reply_to_comment_id": r.get("reply_to_comment_id") or "",
                    "depth": "" if r.get("depth") is None else r["depth"],
                    "is_orphan": str(bool(r.get("is_orphan"))).lower(),
                    "text": r.get("text") or "",
                    "created_at": r.get("created_at") or "",
                    "digg_count": "" if r.get("digg_count") is None else r["digg_count"],
                    "reply_count": "",
                    "is_pinned": "",
                    "is_author_liked": "",
                    "ip_province": r.get("ip_province") or "",
                    "is_author": "" if r.get("is_author") is None else str(bool(r["is_author"])).lower(),
                    "is_thread_author": "",
                    "author_hash": r.get("author_hash") or "",
                    "hash_version": "v1",
                    "label_text": r.get("label_text") or "",
                    "label_texts": json.dumps(r.get("label_texts") or [], ensure_ascii=False),
                    "is_creator_label": "" if r.get("is_creator_label") is None else str(bool(r["is_creator_label"])).lower(),
                    "source": "reply",
                    "raw_sha256": r.get("raw_sha256") or "",
                    "raw_page": r.get("raw_page") or "",
                    "run_id": r.get("run_id") or run_id,
                }
            )

    quality_cols = [
        "run_id", "aweme_id", "thread_id", "expected_total", "fetched",
        "unique_count", "duplicates", "orphan_edges", "depth3", "coverage",
        "stop_reason",
    ]
    quality_csv = args.out / "replies_quality.csv"
    with quality_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=quality_cols)
        w.writeheader()
        for tid, s in sorted(summary_by_tid.items()):
            w.writerow(
                {
                    "run_id": run_id,
                    "aweme_id": thread_to_job[tid]["aweme_id"],
                    "thread_id": tid,
                    "expected_total": s.get("expected_total") or 0,
                    "fetched": s.get("fetched") or 0,
                    "unique_count": s.get("unique") or 0,
                    "duplicates": s.get("duplicates") or 0,
                    "orphan_edges": s.get("orphan_edges") or 0,
                    "depth3": s.get("depth3") or 0,
                    "coverage": "" if s.get("coverage") is None else s["coverage"],
                    "stop_reason": s.get("stop_reason") or "",
                }
            )

    video_csv = args.out / "replies_quality_video.csv"
    with video_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=quality_cols)
        w.writeheader()
        for v in video_rows:
            w.writerow({k: v[k] for k in quality_cols})

    # Worker jobs (one row per video job).
    job_rows = []
    for job in jobs:
        aweme = str(job["aweme_id"])
        slist = summary_by_aweme.get(aweme, [])
        non_complete = sum(1 for s in slist if s.get("stop_reason") != "complete")
        job_rows.append(
            {
                "job_id": f"{run_id}:{aweme}",
                "run_id": run_id,
                "aweme_id": aweme,
                "threads": json.dumps(
                    {
                        "selection": job.get("selection"),
                        "max_pages": job.get("max_pages"),
                        "thread_ids": [str(t) for t in job["threads"]],
                    },
                    ensure_ascii=False,
                ),
                "status": "partial" if non_complete else "success",
                "attempt": 1,
                "result_path": f"result/outputs/normalized/{aweme}.jsonl",
            }
        )
    jobs_csv = args.out / "worker_jobs.csv"
    with jobs_csv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "job_id", "run_id", "aweme_id", "threads", "status",
                "attempt", "result_path",
            ],
        )
        w.writeheader()
        w.writerows(job_rows)

    validation = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": run_id,
        "result_dir": str(args.result),
        "jobs": len(jobs),
        "job_awemes": len(aweme_to_job),
        "job_threads": len(thread_to_job),
        "summary_threads": len(summary_threads),
        "normalized_files": len(files),
        "normalized_rows": len(rows),
        "unique_comment_ids": len(set(ids)),
        "duplicate_comment_ids": len(ids) - len(set(ids)),
        "thread_rows_mismatch": thread_mismatch,
        "missing_roots": missing_roots,
        "depth_counts": dict(sorted(depth_counts.items())),
        "depth_mismatch": depth_mismatch[:20],
        "depth_mismatch_count": len(depth_mismatch),
        "orphan_with_depth_count": len(orphan_depth_mismatch),
        "author_hash_64hex": sum(1 for r in rows if len(r["author_hash"]) == 64),
        "author_hash_overlap_top_level": hash_overlap,
        "reply_rows_by_top_level_author": rows_by_top_author,
        "is_author_true": sum(1 for r in rows if r.get("is_author") is True),
        "label_text_nonempty": sum(1 for r in rows if (r.get("label_text") or "") != ""),
        "is_creator_label_true": sum(1 for r in rows if r.get("is_creator_label") is True),
        "ip_province_nonnull": sum(1 for r in rows if (r.get("ip_province") or "") != ""),
        "video_rows": video_rows,
        "stop_reason_counts": dict(Counter(s.get("stop_reason") for s in summary_threads)),
        "worker_job_status_counts": dict(Counter(j["status"] for j in job_rows)),
        "max_pages_threads": [
            {
                "thread_id": tid,
                "aweme_id": thread_to_job[tid]["aweme_id"],
                "selection": thread_to_job[tid]["job"].get("selection"),
                "max_pages": thread_to_job[tid]["job"].get("max_pages"),
                "expected_total": s.get("expected_total"),
                "unique": s.get("unique"),
                "coverage": s.get("coverage"),
            }
            for tid, s in summary_by_tid.items()
            if s.get("stop_reason") == "max_pages"
        ],
        "salt_consistency_ok": hash_overlap > 0,
    }
    (args.out / "validation.json").write_text(
        json.dumps(validation, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(json.dumps({
        k: validation[k] for k in (
            "jobs", "job_awemes", "job_threads", "summary_threads",
            "normalized_files", "normalized_rows", "unique_comment_ids",
            "duplicate_comment_ids", "depth_counts", "depth_mismatch_count",
            "orphan_with_depth_count", "author_hash_64hex",
            "author_hash_overlap_top_level", "reply_rows_by_top_level_author",
            "is_author_true", "label_text_nonempty", "is_creator_label_true",
            "ip_province_nonnull", "stop_reason_counts", "max_pages_threads",
            "missing_roots", "thread_rows_mismatch", "salt_consistency_ok",
        )
    }, ensure_ascii=False, indent=2))
    print("out:", args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
