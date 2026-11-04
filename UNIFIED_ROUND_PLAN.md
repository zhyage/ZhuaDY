# 统一采集轮 — 10 条视频 + 一级评论 + 回复

> 日期：2026-10-31
> run_id：`pilot-unified-20261031-01`
> 目标：同一批 10 条视频同时拥有 **mp4 + 一级评论 + 回复**；不再把评论和视频拆成两轮。
> Windows round：`20261031T081447Z-unified-replies`

---

> **完成状态（2026-10-31）：** 10/10 视频、3,098 一级评论、969 回复已入库；147/148 线程 complete；导出见 `exports/pilot-unified-20261031-01/`。详见 `UNIFIED_ROUND_REPORT.md`。

## 1. 范围

| 项目 | 值 |
|---|---|
| 账号 | 绍兴文旅 |
| 视频 | 10 条新视频（排除前两套 pilot 的 40 条） |
| 选样 | 5 high_comment + 5 time_spread |
| 视频 | 10/10 下载成功，最小可用 mp4 |
| 一级评论 | 10/10 complete；3,098 unique |
| 回复 | 1 条深抓 + 9 条浅抓 |
| 深抓 | `7569431411968650091`，71 threads，299 expected |
| 浅抓 | 9 条，每视频前 10 thread，77 threads，972 expected |
| 合计 | 10 jobs / 148 threads / 1,271 expected replies |
| 抽帧 | 本轮不做；以后按需生成 |
| 视频分析 | 不做 |

## 2. 已完成（Linux）

- 10 条新视频元数据已从 `pilot-video-20261031-01` 快照复制到 `video_snapshot`。
- 10/10 视频下载成功：50,042,593 bytes；codec：HEVC 7 / H.264 3。
- 一级评论：3,098 unique；279 thread candidates；10/10 `complete`。
- `comment`、`comment_raw`、`comment_fetch_state`、`quality_metric` 已入库（run_id=`pilot-unified-20261031-01`）。
- `jobs.json`：10 jobs（1 deep + 9 shallow）/ 148 threads / 1,271 expected replies。

## 3. Windows 子步骤（待执行）

共享目录：

```text
/data/shareFolder/douYin/20261031T081447Z-unified-replies
Windows: Z:\douYin\20261031T081447Z-unified-replies
```

Windows 运行：

```powershell
python reply_worker.py --jobs jobs.pilot.json --common-params common_params.json --hash-salt-file C:\work\dtk-hmac-salt
```

输出回传：

```text
result/outputs/worker_report.md
result/outputs/worker_summary.json
result/outputs/normalized_sample.jsonl
result/outputs/normalized/
```

不回传 raw/state。

## 4. 待完成（Linux）

- 导入 Windows normalized 回复到 `comment`。
- 合并 10 条视频的 mp4 + 一级评论 + 回复。
- 质量报告：每视频/每线程 coverage、orphans、depth3、作者回复。
- 导出统一 `videos.parquet` / `comments.parquet` / `reply_edges.parquet` / `quality.parquet`。
- 更新 `run` 状态和 notes。

## 5. 数据位置

```text
data/media/pilot-unified-20261031-01/<aweme_id>.mp4
data/raw/pilot-unified-20261031-01/video_detail/<aweme_id>.json
data/raw/pilot-unified-20261031-01/comments/<aweme_id>/page_*.json
data/pilot/pilot-unified-20261031-01/
  selected_videos.csv
  media_download.csv
  comments.csv
  comment_raw.csv
  comment_fetch_state.csv
  quality_metric.csv
  thread_candidates.csv
  jobs.json
  jobs_summary.json
```

## 6. 关键约束

- 同一 run；评论和视频不再拆轮。
- Windows 只做回复；视频下载和一级评论都在 Linux。
- 不覆盖旧 pilot。
- 不把 raw/state 放进共享目录。
