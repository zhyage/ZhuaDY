# PROJECT STATUS — 当前唯一跟踪页

> 更新时间：2026-11-04
> 本页是当前状态、采样规则和下一步的唯一入口；其它文档作为参考/历史。

## 1. 当前阶段

**多账号原始素材采集（P1）已完成**。30 条视频 + 5,182 一级评论 + 1,362 回复；不做视频分析、不做 ASR。

## 2. 已完成的资产

| run_id | 内容 | 状态 |
|---|---|---|
| `pilot-20261030-01` | 20 条视频：一级评论 + 选定回复 | 数据完成；`run.status` 仍为 running（仅状态字段） |
| `pilot-video-20261031-01` | 20 条视频：元数据 + mp4 + frames | 完成 |
| `pilot-unified-20261031-01` | 10 条视频：mp4 + 一级评论 + 回复 | 完成 |

数据库当前：37,822 comments；31,292 comment_raw；60 media_download；805 video_snapshot；5 account_snapshot；46 worker_job。

恢复点：Git tag `baseline-2026-11-04`；本地快照 `/home/vdmc34/my/douyin-snapshots/2026-11-04/`。详见 `BASELINE_2026-11-04.md`。

## 3. 当前采样计划（P1）

| 项目 | 决定 |
|---|---|
| 账号数 | 3 |
| 每账号视频 | 10 条 |
| 选样 | 随机；只从 `comment_count >= 1` 且 `is_target_author=true` 的视频中选 |
| 绍兴 | 排除之前 pilot 已用过的视频 |
| 回复 | 计划每账号 1 深 + 9 浅；实际因 11 条视频无回复 thread，保留当前 30 条，实际 3 深 + 16 浅（19 jobs） |
| 深抓选择 | 一级评论抓完后，每账号按“有回复的 thread 数”最多选择 1 条 |
| 视频下载 | 30 条全部下载，最小可用 mp4 |
| 抽帧/分析 | 本轮不做 |
| 账号 | 绍兴文旅、杭州文旅、丽水文旅 |

### 账号清单

| 账号 | sec_uid |
|---|---|
| 绍兴文旅 | `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c` |
| 杭州文旅 | `MS4wLjABAAAAOKGkGnuk4TM9gsbbyfGBGpn6y5WscWChImG33T2Q1w4-Qgo6gV7zbn659d3R2Dp_` |
| 丽水文旅 | `MS4wLjABAAAAjmiMB76QeVw3zfuY8kknvIKiD2SHIJy5f_E1rNj_0Dg1kD8DHZ70Mc3h6WrkqKBB` |

## 3.1 当前样本实际结果

- 3 个账号 × 10 条 = 30 条视频；30/30 下载成功，159,359,343 bytes；HEVC 22 / H.264 8。
- 一级评论：5,182 unique；298 个 thread 候选。
- 回复任务：**19 jobs（3 深 + 16 浅）**；229 threads；实际 1,371 expected / 1,362 unique。
- Windows：第一轮 blocked（178/229），补采 round 51/51 complete；合计 1,362 回复。
- 导出：`exports/multi-20261104-01/`；报告：`MULTI_ROUND_REPORT.md`。
- 11 条视频没有回复 thread，保留视频 + 一级评论；不回填、不替换（已确认）。
- 每账号 jobs：绍兴 8（1 深 + 7 浅）、杭州 7（1 深 + 6 浅）、丽水 4（1 深 + 3 浅）。

## 4. 下一步（按顺序）

1. ✅ 杭州/丽水元数据已拉取；绍兴复用 `pilot-video-20261031-01`。
2. ✅ 每账号随机选 10 条有评论的视频；combined run `multi-20261104-01` 已建。
3. ✅ 30 条视频下载、30 条一级评论抓取完成。
4. ✅ 第一轮 blocked + 补采 round success；229/229 threads complete。
5. ✅ 导入/合并/导出 + 质量报告完成（`MULTI_ROUND_REPORT.md`）。
6. 下一步：决定是否扩到更多账号、是否做视频分析，或进入 LLD/自动化。

## 4.1 Worker wrapper 修复（2026-11-04）

- `reply_worker.py` 已增加 `--wrapper-timeout`、`--wrapper-retries`、`--wrapper-policy`。
- 失败会重开视频页；默认 `skip`，单个视频 wrapper_not_ready 不再中断整批。
- `worker_summary.json` / `worker_report.md` 增加 `job_failures`，Linux 只补失败视频。
- 已有数据不受影响；后续 round 使用新 worker。

## 5. 阻塞/依赖

- Windows 机器 + Chrome/CDP + 登录态；验证码需要人工。
- 30 条视频的存储与 Windows 运行时长需要观察。
- 目前没有一键编排；按脚本/手工步骤执行。

## 6. 只跟踪这份

日常只看本页。需要细节时再看：

- 架构：`DESIGN.md`
- 视频管线：`LLD_VIDEO_PIPELINE.md`
- 最新多账号结果：`MULTI_ROUND_REPORT.md`
- 早期 pilot：`PILOT.md`
- Windows 回复：`WINDOWS_REPLY_WORKER.md` / `SHARE_PROTOCOL.md`
- 恢复：`BASELINE_2026-11-04.md`
- 历史方案：`NEXT_ROUND_PLAN.md`、`UNIFIED_ROUND_PLAN.md`、`LIGHTPANDA_EVAL.md`、`UNIFIED_ROUND_REPORT.md`
