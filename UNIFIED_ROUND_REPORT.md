# 统一采集轮报告 — 10 条视频 + 一级评论 + 回复

> 日期：2026-10-31
> run_id：`pilot-unified-20261031-01`
> Windows round：`20261031T081447Z-unified-replies`
> 结论：同一批 10 条视频已经同时拥有 **mp4 + 一级评论 + 回复**；数据可用。回复为 1 条深抓 + 9 条浅抓。

---

## 1. 规模

| 项目 | 数值 |
|---|---:|
| 视频 | 10 |
| 视频下载 | 10/10 success |
| 视频总大小 | 50,042,593 bytes（0.05 GB） |
| codec | HEVC 7 / H.264 3 |
| 一级评论 | 3,098 unique |
| thread 候选 | 279 |
| 回复 | 969 unique |
| 回复任务 | 10 jobs（1 deep + 9 shallow） |
| 回复 thread | 148 |
| 合并后 `comment` | 4,067 |
| `quality_metric` | 168（10 一级 + 148 线程 + 10 视频汇总） |
| `worker_job` | 10（9 success + 1 partial） |

## 2. 一级评论

- 10/10 视频 `stop_reason=complete`。
- 3,098 unique；0 空文本；0 风控。
- `ip_province` 非空 2,034/3,098（65.7%）。
- `is_author=true` 3 条。
- 注意：平台 `comment_count` 包含回复，`complete` 才表示一级评论列表耗尽。

## 3. 回复

| 口径 | expected | unique | coverage |
|---|---:|---:|---:|
| 全部 148 threads | 1,286 | 969 | **75.35%** |
| 147 个 `complete` threads | 822 | 819 | **99.64%** |
| 1 个 `max_pages` thread（shallow） | 464 | 150 | 32.33% |

- 3 个 `complete` thread 合计缺 3 条：
  - `7323867608339546916`：13 → 12
  - `7494192225594655488`：35 → 34
  - `7533505893846057787`：8 → 7
- `max_pages` 线程：`7494177073062347557`，shallow，`max_pages=3`，464 → 150；这是整体 coverage 偏低的主要原因。
- `orphan_edges=20`；`depth is null=63`（20 孤儿 + 43 后代）；最大 depth=10。
- `is_author=true` 15 条，全部带 `label_text='作者'`；分布在 5 个视频。
- `ip_province` 非空 911/969（94.0%）。
- `author_hash` 100% 非空；120 个回复作者哈希与一级评论重合，salt 一致。
- `expected_total` 合计 1,286，比 Stage 3 的 1,271 多 15，属平台计数漂移。

## 4. 风控/验证码事件

- worker 在约 **08:21Z** 遇到 click-text 人机验证，按协议立即停止。
- 用户手动通过验证；worker 于 **08:24:10Z** resume。
- 41 个已完成 thread 通过 state 跳过；resume 后只处理剩余 107 个线程。
- 最终 normalized 文件包含 **969 行**；`worker_summary.totals.normalized_rows=638` 只统计 resume 部分，**以 normalized 文件为准**。
- 没有 `risk_control` / `bad_json`；147/148 线程 complete。
- 结论：数据可用；长跑仍需人工验证/暂停恢复机制。

## 5. 入库与导出

数据库：

- `comment=4,067`（3,098 top_level + 969 reply）
- `comment_raw=3,098`（仅一级评论）
- `comment_fetch_state=10`（仅一级评论）
- `quality_metric=168`
- `worker_job=10`

导出：`exports/pilot-unified-20261031-01/`

| 文件 | 行数 |
|---|---:|
| `parquet/videos.parquet` | 10 |
| `parquet/comments.parquet` | 4,067 |
| `parquet/reply_edges.parquet` | 969 |
| `parquet/quality.parquet` | 168 |
| `parquet/media_downloads.parquet` | 10 |
| `parquet/account.parquet` | 1 |
| `samples/comments_sample.csv` | 729 |
| `samples/replies_sample.csv` | 860 |

`manifest.json` 含 schema、覆盖率、下载统计、文件 SHA256；旧 pilot 未修改。

## 6. 隐私

- 导出不含 `account_id/sec_uid`、昵称、`raw_page`、签名 URL、cookie、header。
- `comment.text` 保留；`author_hash` 是伪名化，不是匿名化。
- 回复 raw/state 留在 Windows 本地；`comment_raw` 只含一级评论。
- 视频在 `data/media/pilot-unified-20261031-01/`，不进共享目录/导出。

## 7. 下一步

- 原始素材收集到此可以视为完成：10 条视频同时有 mp4 + 一级评论 + 回复。
- 视频分析暂不做；以后按研究需求再抽帧/建模。
- 如需更大样本，按同一统一 run 流程扩到 20–50 条；回复仍按 1 深 + 9 浅或按研究需要调整。
