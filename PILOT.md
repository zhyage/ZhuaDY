# Phase 1 Pilot 报告 — 绍兴文旅

> 日期：2026-10-30
> 状态：Stage 1–6 完成；导出见 `exports/pilot-20261030-01/`（`manifest.json` 有 schema/行数/哈希）
> 账号：绍兴文旅 `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c`
> 关联：[PILOT_SPEC.md](PILOT_SPEC.md)、[DESIGN.md](DESIGN.md)、[ROADMAP.md](ROADMAP.md)、[WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)、[FEASIBILITY.md](FEASIBILITY.md)

---

## 1. 目的与范围

用 1 个账号、20 个视频跑通端到端采集：

```text
v5：账号 + 全量视频列表 + 20 个视频的一级评论
Windows worker：3 个深抓视频的全部 thread + 14 个浅抓视频的前 10 个 thread
Linux：入库、去重、隐私转换、质量报告、Parquet/CSV 导出
```

**不是**正式研究抽样，不做统计推断；pilot 只验证字段、翻页、回复结构、耗时、风控和存储。

## 2. 账号与样本

| 项目 | 值 |
|---|---|
| 账号 | 绍兴文旅 |
| `sec_uid` | `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c` |
| 视频列表 | 765 unique；730 目标作者 + 35 其他作者 |
| Pilot 视频 | 20（10 高评论 + 10 时间跨度；只取 `is_target_author=true`） |
| 深抓 | 3 个视频，所有 `reply_count>0` thread，`max_pages=10` |
| 浅抓 | 14 个视频，每视频前 10 个 thread，`max_pages=3` |
| 跳过 | 3 个视频没有回复 thread |

其他作者的 35 个视频保留在 `video` 表用于审计，不进入 pilot 样本。

## 3. 管线

| 阶段 | 做什么 | 结果 |
|---|---|---|
| 0 | v5 / Postgres / 共享目录 / Windows worker 就绪 | 完成 |
| 1 | v5 `author_posts` 全量视频列表 | 19 页、765 unique |
| 2 | v5 一级评论，`count=50`、`include_raw=true` | 20/20 `complete`；23,012 unique |
| 3 | 按一级评论 `reply_count` 选 thread，生成 `jobs.json` | 17 jobs / 804 threads |
| 4 | Windows Chrome 页面内 `fetch` 抓回复 | 4,199 unique；801/804 `complete` |
| 5 | 入库、合并、隐私转换、质量报告 | 27,211 comments；841 quality rows |
| 6 | Parquet / CSV samples / manifest | `exports/pilot-20261030-01/` |

## 4. 数据量

| 数据 | 行数 |
|---|---:|
| `account` | 1 |
| `video` | 765（730 target + 35 other） |
| `comment` | **27,211**（23,012 一级 + 4,199 回复） |
| `comment_raw` | 23,012（仅一级评论） |
| `comment_fetch_state` | 20（仅一级评论分页） |
| `quality_metric` | 841（20 一级 + 804 线程 + 17 视频汇总） |
| `worker_job` | 17（15 success + 2 partial） |
| 回复 normalized | 17 个 JSONL，4,199 行 |

## 5. 质量

### 一级评论

- 20/20 视频 `stop_reason=complete`；0 风控；0 `guest_fallback`。
- 24,847 次返回；23,012 unique；1,835 重复（7.4%）。
- `ip_province` 非空 20,711/23,012（约 90%）。
- `is_author=true` 7 条。
- 注意：`coverage = unique / platform_comment_count` 在高评论视频上只有 33–69%，因为平台 `comment_count` 包含回复；**`complete` 才表示一级评论列表耗尽**，不要把 33% 当作“只抓了三分之一”。

### 回复

| 口径 | expected | unique | coverage |
|---|---:|---:|---:|
| 全部 804 threads | 4,835 | 4,199 | **86.85%** |
| 801 个 `complete` threads | 3,759 | 3,751 | **99.79%** |
| 3 个浅抓 `max_pages` threads | 1,076 | 448 | 41.64% |

- 801 个 `complete` 中：793 个完全相等；7 个合计缺 10 条；1 个多 2 条（平台计数滞后）。
- 3 个 `max_pages` 全是 shallow，按设计在 3 页停止，不是失败。
- Stage 3 估算 4,810；Round 005 端点 `total` 合计 4,835（+25 平台漂移）；20 个 thread 与一级评论 `reply_count` 不一致。
- 0 重复；0 空文本；`author_hash` 100% 非空。
- `ip_province` 非空 4,109/4,199（97.86%）。
- `is_author=true` 57 条，全部带 `label_text='作者'`；分布在 8 个视频，最多 31 条。
- `is_thread_author` 本轮全为 null（pilot 预留）。

### 结构与缺口

- `orphan_edges=43`：直接父评论不在已抓回复集。
- `depth is null=72`：43 个孤儿 + 29 个孤儿后代。
- 最大 depth=14；depth 2 有 2,868 条，depth≥3 有 1,259 条。
- 父子关系校验 0 矛盾：`depth=2` 的父节点都等于 thread root；`depth>2` 都不等于 root。
- 孤儿保留 `reply_to_comment_id`/`thread_root_id`；不伪造 depth。

## 6. 隐私与伦理

- 分三层：
  - **Raw vault**：完整原始 JSON（含昵称/UID/文本），只在本地受控目录；回复 raw 在 Windows 本地。
  - **Analysis DB/Parquet**：文本 + 线程结构 + `author_hash` + `ip_province`；无昵称/头像/签名/原始 UID。
  - **Publication**：聚合统计；引用需脱敏/改写。
- `author_hash = HMAC-SHA256(salt, "douyin:" + sec_uid)`；salt 在 `.secrets/dtk-hmac-salt`（600），不进仓库/共享目录/导出。
- Salt 一致性：554 个回复作者哈希也出现在一级评论作者集合；942 条回复来自同时发过一级评论的用户。
- 伪名化 ≠ 匿名化：文本可能含姓名、地点、联系方式、罕见经历；发表前必须处理。
- `comment_raw` 仅一级评论；回复 raw/state 留在 Windows 本地；导出不含 raw JSON、cookie、header 值。
- 保留期按 IRB 计划：pilot 后保留 90 天再复核；正式 IRB 批件/豁免号待补。

## 7. 风控与验证码

- 用户在整个过程中观察到 **2 次人机验证**，并手动通过。
- `worker_summary` 没有记录 `risk_control`、`bad_json`、0 字节或 `global_stop`；801 个完整线程只缺 10 条，未发现验证导致的数据损失。
- 结论：本轮数据可用，但长跑（约 82 分钟）会出现验证码；**生产不能假设完全无人值守**。
- 生产要求：
  - 检测验证码/登录墙页面并暂停 + 告警；
  - 人工通过后再 resume；
  - 不自动绕过验证码；
  - 记录事件（时间、类型、影响的 thread）；
  - 保持低频、串行、请求间 1.5–3 s、线程间 4–7 s。

## 8. 产出

```text
exports/pilot-20261030-01/
  parquet/videos.parquet
  parquet/comments.parquet
  parquet/reply_edges.parquet
  parquet/quality.parquet
  samples/comments_sample.csv      # 每视频前 100 条，UTF-8-sig
  samples/replies_sample.csv       # 每 thread 前 50 条，UTF-8-sig
  manifest.json                    # schema、行数、覆盖率、字段字典、文件哈希
  README.md
```

数据库：`douyin_research`（Postgres/TimescaleDB，容器 `dtk-postgres-1`）。

## 9. 关键文件

| 文件 | 说明 |
|---|---|
| `scripts/pilot/fetch_video_list.py` | Stage 1 视频列表 |
| `scripts/pilot/fetch_comments.py` | Stage 2 一级评论 |
| `scripts/pilot/build_jobs.py` | Stage 3 jobs |
| `spike/windows-reply/reply_worker.py` | Stage 4 Windows worker |
| `scripts/pilot/prepare_replies_import.py` | Stage 5 校验/生成入库 CSV |
| `sql/import_replies.sql` | Stage 5 入库 |
| `scripts/pilot/export_pilot.py` | Stage 6 导出 |
| `data/pilot/pilot-20261030-01/replies_import/STAGE5_REPORT.md` | Stage 5 质量报告 |

## 10. 限制与下一步

**限制：**

- Pilot 样本不是正式研究抽样；20 个视频不能代表账号或平台。
- 3 个浅抓 thread 在 3 页截断；整体 coverage 86.85%，完整线程 99.79%。
- 7 个完整线程合计缺 10 条；1 个多 2 条；20 个 thread 的端点 total 与一级评论计数不一致；均为平台计数/缺口现象。
- 回复 raw/state 只在 Windows 本地；`comment_raw` 只有一级评论。
- 本 pilot **没有下载视频文件**；如果以后要做人物/室内外等视觉分析，需要单独下载选中的视频（P5a），但不需要 ASR/字幕。
- `videos.play_count` 全为 NULL（v5 视频列表未返回）；`duration_ms` 有 3 个 NULL。
- 回复的 `reply_count`/`is_pinned`/`is_author_liked` 未采集（NULL）；一级评论有这些字段。
- `is_thread_author` 未实现；`is_author` 只表示“视频作者”，不是“一级评论作者”。
- 两次人工验证说明长跑需要人；worker 目前不自动检测验证码。

**下一步：**

1. 审阅 Stage 5/6 数据质量和导出。
2. 下一轮采集增加 P5a 视频下载（只下载选中视频，不做 ASR）；如需分析本 pilot 的 20 条视频，另做一次媒体下载，不改旧元数据。
3. 如需补齐 3 个浅抓 thread：单独发一轮 deep 抓取，不重跑本轮。
4. 如研究需要“一级评论作者是否回复”：实现 `is_thread_author`。
5. 写 LLD：正式模块划分、任务队列、验证码检测/人工介入、多账号调度、保留期任务。
5. 正式研究抽样与 IRB 材料。
