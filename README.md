# ZhuaDY — Douyin Research Data Collection

Research-oriented collection tooling for Douyin:

- account + full video-list metadata via Evil0ctal v5;
- top-level comments via v5;
- comment replies via a real Windows Chrome page (page-context `fetch`);
- video metadata and minimum-usable MP4 downloads on Linux;
- optional JPEG frame extraction for OpenCV;
- run-scoped Postgres snapshots, Parquet/CSV export, manifests and QA metrics.

This repository contains **code, SQL and documentation only**. Research data,
raw responses, videos, frames, exports, cookies, API keys and the HMAC salt are
deliberately not committed.

## Repository layout

```text
scripts/collection/    video metadata, download, frame extraction, unified export
scripts/pilot/         early pilot fetchers, comment fetch, jobs, reply import
sql/                   schema, imports, selection queries
spike/chrome-reply/    early Linux Chrome/Xvfb reply probes
spike/windows-reply/   Windows page-context reply worker and probes
*.md                   design, feasibility, pilot reports, LLD, field analysis
```

## Architecture

```text
Linux
  v5 REST ──► account/video metadata ──► Postgres snapshots
           ──► top-level comments
           ──► video detail ──► min-usable MP4 ──► ffmpeg JPEG frames
  Postgres/psql + pandas/pyarrow ──► Parquet/CSV/manifest

Windows (only for replies)
  real Chrome + logged-in profile + CDP :9222
  page-context fetch ──► reply pages ──► normalized JSONL/state/summary
```

Windows is **not** used for video download, video metadata or top-level
comments. The reply endpoint requires the page's own signed `fetch`; that is the
only reason the worker exists.

## Requirements

- Linux with Python 3.12+
- Evil0ctal v5 API reachable (default `http://127.0.0.1:8000`)
- PostgreSQL/TimescaleDB for the research schema
- `ffmpeg` / `ffprobe`
- Python packages: `pip install -r requirements.txt`
- Windows machine with Chrome, Playwright and a dedicated logged-in profile for
  reply collection

`requests` is used by the v5 scripts; `playwright` by the Windows worker and
Chrome probes. OpenCV is optional and only needed for image analysis.

## Configuration

Create locally (never commit):

```text
.secrets/dtk-api-key.txt     # v5 bearer token
.secrets/dtk-hmac-salt       # HMAC-SHA256 salt for author_hash
```

The Windows reply worker receives the salt through a local file, for example:

```powershell
python reply_worker.py --jobs jobs.pilot.json --common-params common_params.json `
  --hash-salt-file C:\work\dtk-hmac-salt
```

## Example commands

```bash
# 1. Video metadata (include_raw=true)
python3 scripts/collection/fetch_video_metadata.py --run-id pilot-video-20261031-01

# 2. Download selected videos (minimum usable MP4)
python3 scripts/collection/download_videos.py \
  --run-id pilot-video-20261031-01 \
  --selected data/pilot/pilot-video-20261031-01/selected_videos.csv

# 3. Optional: extract JPEG frames for OpenCV
python3 scripts/collection/extract_frames.py --run-id pilot-video-20261031-01

# 4. Top-level comments (v5)
python3 scripts/pilot/fetch_comments.py \
  --run-id pilot-unified-20261031-01 \
  --selected data/pilot/pilot-unified-20261031-01/selected_videos.csv \
  --max-pages 200

# 5. Build 1-deep + N-shallow reply jobs
python3 scripts/pilot/build_jobs.py \
  --run-id pilot-unified-20261031-01 \
  --selected data/pilot/pilot-unified-20261031-01/selected_videos.csv \
  --candidates data/pilot/pilot-unified-20261031-01/thread_candidates.csv \
  --deep-count 1 --shallow-threads 10
```

## Data policy

- No nickname/avatar/signature/sec_uid/raw JSON/commenter identity in analysis
  exports; comments use HMAC `author_hash`.
- The HMAC salt and API key live only in `.secrets/` locally.
- Raw responses, video files, frames and exports are local-only.
- Publication requires further masking/paraphrasing; pseudonymization is not
  anonymization.

## Documentation

- [DESIGN.md](DESIGN.md) — high-level design and constraints
- [FEASIBILITY.md](FEASIBILITY.md) — v5, Chrome, signing and risk findings
- [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) — reply worker design/results
- [SHARE_PROTOCOL.md](SHARE_PROTOCOL.md) — Linux/Windows shared-folder protocol
- [PILOT.md](PILOT.md) — pilot report
- [LLD_VIDEO_PIPELINE.md](LLD_VIDEO_PIPELINE.md) — video metadata/download/frame LLD
- [VIDEO_FIELD_GAP.md](VIDEO_FIELD_GAP.md) — field comparison with prior tooling
- [UNIFIED_ROUND_REPORT.md](UNIFIED_ROUND_REPORT.md) — 10-video unified round

## Scope and caveats

- Read-only collection; no likes, follows or comments.
- No CAPTCHA bypass: the worker stops and requires manual verification.
- Reply collection needs a real logged-in Windows Chrome; this is an operational
  dependency, not an AI-model dependency.
- Large-scale collection still requires sampling, storage planning and IRB
  review.
