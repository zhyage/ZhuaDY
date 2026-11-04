#!/usr/bin/env python3
"""Stage 3: build the Windows worker jobs.json from thread candidates.

Rules (PILOT_SPEC):
  * 3 deep videos: most threads with reply_count>0 (tie: sum reply_count)
  * deep: all threads with reply_count>0, max_pages=10
  * shallow: top 10 threads by reply_count (tie: digg_count), max_pages=3
"""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET_SEC_UID = "MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c"
DEFAULT_RUN = "pilot-20261030-01"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build reply worker jobs for pilot")
    parser.add_argument("--run-id", default=DEFAULT_RUN)
    parser.add_argument("--selected", default="data/pilot/pilot-20261030-01/selected_videos.csv")
    parser.add_argument("--candidates", default="data/pilot/pilot-20261030-01/thread_candidates.csv")
    parser.add_argument("--out", default="data/pilot/pilot-20261030-01/jobs.json")
    parser.add_argument("--summary", default="data/pilot/pilot-20261030-01/jobs_summary.json")
    parser.add_argument("--deep-count", type=int, default=3)
    parser.add_argument("--shallow-threads", type=int, default=10)
    parser.add_argument("--deep-max-pages", type=int, default=10)
    parser.add_argument("--shallow-max-pages", type=int, default=3)
    args = parser.parse_args()

    selected_path = ROOT / args.selected
    with selected_path.open(encoding="utf-8", newline="") as f:
        selected = list(csv.DictReader(f))
    selected_ids = [r["aweme_id"] for r in selected]

    by_video: dict[str, list[dict]] = defaultdict(list)
    candidates_path = ROOT / args.candidates
    with candidates_path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            row["reply_count"] = int(row.get("reply_count") or 0)
            row["digg_count"] = int(row.get("digg_count") or 0)
            by_video[row["aweme_id"]].append(row)

    for aweme in by_video:
        by_video[aweme].sort(
            key=lambda r: (-r["reply_count"], -r["digg_count"], r["comment_id"])
        )

    # Rank selected videos by thread count and reply sum.
    ranking = []
    for aweme in selected_ids:
        threads = by_video.get(aweme, [])
        ranking.append(
            {
                "aweme_id": aweme,
                "thread_count": len(threads),
                "reply_sum": sum(t["reply_count"] for t in threads),
            }
        )
    ranking.sort(key=lambda r: (-r["thread_count"], -r["reply_sum"], r["aweme_id"]))
    deep_ids = {r["aweme_id"] for r in ranking[: args.deep_count]}

    jobs = []
    summary_rows = []
    skipped = []
    for aweme in selected_ids:
        threads = by_video.get(aweme, [])
        deep = aweme in deep_ids
        chosen = threads if deep else threads[: args.shallow_threads]
        max_pages = args.deep_max_pages if deep else args.shallow_max_pages
        if chosen:
            jobs.append(
                {
                    "aweme_id": aweme,
                    "author_sec_uid": TARGET_SEC_UID,
                    "max_pages": max_pages,
                    "selection": "deep" if deep else "shallow",
                    "threads": [t["comment_id"] for t in chosen],
                }
            )
        else:
            skipped.append(aweme)
        summary_rows.append(
            {
                "aweme_id": aweme,
                "selection": "deep" if deep else "shallow",
                "available_threads": len(threads),
                "chosen_threads": len(chosen),
                "expected_replies": sum(t["reply_count"] for t in chosen),
                "max_pages": max_pages,
            }
        )

    run_id = args.run_id
    payload = {
        "run_id": run_id,
        "created_at": now_iso(),
        "target_sec_uid": TARGET_SEC_UID,
        "jobs": jobs,
    }
    out_path = ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    summary = {
        "run_id": run_id,
        "created_at": now_iso(),
        "selected_videos": len(selected_ids),
        "jobs": len(jobs),
        "skipped_videos_no_threads": skipped,
        "deep_videos": len(deep_ids),
        "deep_threads": sum(
            len(j["threads"]) for j in jobs if j["selection"] == "deep"
        ),
        "deep_expected_replies": sum(
            r["expected_replies"] for r in summary_rows if r["selection"] == "deep"
        ),
        "shallow_videos": sum(1 for j in jobs if j["selection"] == "shallow"),
        "shallow_threads": sum(
            len(j["threads"]) for j in jobs if j["selection"] == "shallow"
        ),
        "shallow_expected_replies": sum(
            r["expected_replies"] for r in summary_rows if r["selection"] == "shallow"
        ),
        "total_threads": sum(len(j["threads"]) for j in jobs),
        "total_expected_replies": sum(r["expected_replies"] for r in summary_rows),
        "videos": summary_rows,
        "files": {
            "jobs": str(out_path.relative_to(ROOT)),
        },
    }
    summary_path = ROOT / args.summary
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({k: summary[k] for k in (
        "jobs", "deep_videos", "deep_threads", "deep_expected_replies",
        "shallow_videos", "shallow_threads", "shallow_expected_replies",
        "total_threads", "total_expected_replies", "skipped_videos_no_threads",
    )}, ensure_ascii=False, indent=2))
    print("jobs:", out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
