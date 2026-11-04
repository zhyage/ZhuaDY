# DATA DICTIONARY — Douyin 研究数据

> 更新时间：2026-11-04
> 适用范围：`pilot-*`、`multi-20261104-01` 研究库与导出
> 关联：`PROJECT_STATUS.md`、`MULTI_ROUND_REPORT.md`、`LLD_VIDEO_PIPELINE.md`

## 1. 数据层

| 层 | 内容 | 访问 |
|---|---|---|
| Raw vault | 原始 v5 JSON、评论区页、视频 detail、Windows raw/state | 本地受限；不进仓库/导出 |
| Analysis DB | `account_snapshot`、`video_snapshot`、`comment`、`quality_metric`、`media_download` | 研究库 |
| Analysis export | Parquet、CSV samples、manifest | 本地；不含直接身份字段 |
| Publication | 聚合统计；引用需脱敏/改写 | 公开前另审 |

**原则：** 评论正文保留；昵称/头像/原始 UID/sec_uid 不进分析导出；账号签名作为公开文本单独保留；`author_hash` 是 HMAC 伪名化，不是匿名化。

## 2. 表概览

| 表 | 粒度 | 当前总量（约） |
|---|---|---:|
| `run` | 一次采集 | 4 |
| `account_snapshot` | run + 账号 | 5 |
| `video_snapshot` | run + 视频 | 805 |
| `comment` | 评论/回复 | 37,822 |
| `comment_raw` | 一级评论 raw JSON | 31,292 |
| `quality_metric` | run + 视频/线程 | 1,287 |
| `media_download` | run + 视频文件 | 60 |
| `worker_job` | Windows 回复 job | 46 |

## 3. `run`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` | text PK | 采集轮次 ID |
| `account_id` | text | 账号或 `multi-account` 标签 |
| `status` | text | `running` / `success` / `complete` / `partial` / `blocked` |
| `started_at` / `finished_at` | timestamptz | 时间 |
| `v5_version` | text | v5 版本 |
| `worker_version` | text | Windows worker 版本（可空） |
| `protocol_version` | text | 共享协议版本 |
| `irb_reference` | text | IRB/豁免号（待补） |
| `notes` | text | 轮次说明/异常/覆盖率 |

## 4. `account_snapshot`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id`, `account_id` | text PK | 轮次 + 账号 |
| `sec_uid` | text | 账号稳定 ID（原始；不导出） |
| `unique_id` | text | 抖音号（原始；不导出） |
| `nickname` | text | 昵称（原始；不导出） |
| `signature` | text | 签名（原始；导出可含公开文本） |
| `verified` | bool | 认证状态 |
| `follower_count` | bigint | 粉丝数（采集时点） |
| `following_count` | bigint | 关注数 |
| `total_favorited` | bigint | 获赞总数 |
| `aweme_count` | bigint | 作品数 |
| `certification` | text | 认证文本（如 enterprise_verify_reason） |
| `favoriting_count` | bigint | 喜欢数（include_raw） |
| `collected_at` / `fetched_at` | timestamptz | 采集/入库时间 |
| `raw_path`, `raw_sha256` | text | raw vault 路径与哈希（不导出 path） |

## 5. `video_snapshot`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` + `aweme_id` | text PK | 轮次 + 视频 |
| `account_id` | text | 目标账号 sec_uid（不导出） |
| `author_sec_uid` / `author_nickname` | text | 视频作者（不导出） |
| `is_target_author` | bool | 是否目标账号作品 |
| `caption` | text | 视频文案（公开） |
| `created_at` | timestamptz | 发布时间 |
| `duration_ms` | int | 时长毫秒 |
| `digg_count` / `comment_count` / `share_count` / `collect_count` / `play_count` | bigint | 平台统计；`play_count` 多为 null |
| `web_url` | text | 规范视频 URL |
| `kind` | text | `video` / `image_album` |
| `tags` | jsonb | 话题标签数组 |
| `recommend_count` | bigint | 推荐数（raw `statistics.recommend_count`） |
| `media_width/height/format/size_bytes/bitrate` | int/text/bigint | 平台默认媒体信息 |
| `author_certification` | text | 作者认证文本 |
| `author_favoriting_count` | bigint | 作者喜欢数（账号级快照） |
| `collected_at` | timestamptz | 采集时间 |
| `video_file_path` | text | 本地 mp4 相对路径 |
| `video_sha256` | text | mp4 SHA256 |
| `video_variant` | text | 下载流 variant |
| `video_bytes` | bigint | 实际文件大小 |
| `video_width/height/format/duration_ms` | int/text | 实际文件 ffprobe |
| `video_codec` | text | `hevc` / `h264` |
| `downloaded_at` | timestamptz | 下载时间 |
| `raw_sha256` | text | 视频列表页 hash |
| `fetched_at` | timestamptz | 入库时间 |

## 6. `comment`

| 字段 | 类型 | 说明 |
|---|---|---|
| `comment_id` | text PK | 评论/回复 ID |
| `aweme_id` | text | 视频 ID |
| `thread_root_id` | text | 所属一级评论 ID |
| `reply_to_comment_id` | text | 直接父评论 ID；一级评论为 null |
| `depth` | int | 1/2/3…；未知为 null（孤儿/后代） |
| `is_orphan` | bool | 直接父节点是否不在已抓集合 |
| `text` | text | 完整评论/回复文本 |
| `created_at` | timestamptz | 发布时间 |
| `digg_count` | bigint | 点赞 |
| `reply_count` | bigint | 一级评论的平台回复数；回复为 null |
| `is_pinned` / `is_author_liked` | bool | 一级评论字段；回复为 null |
| `ip_province` | text | IP 属地（省级） |
| `is_author` | bool | 是否视频作者（按 sec_uid） |
| `is_thread_author` | bool | 预留；当前全 null |
| `author_hash` | text | HMAC-SHA256(salt, "douyin:"+sec_uid) |
| `hash_version` | text | `v1` |
| `label_text` | text | 平台标签（如 `作者`） |
| `label_texts` | jsonb | 平台 label 列表 |
| `is_creator_label` | bool | 是否作者/创作者标签 |
| `source` | text | `top_level` / `reply` |
| `raw_sha256` | text | raw 记录 hash |
| `raw_page` | text | raw 页路径（不导出） |
| `fetched_at` / `run_id` | timestamptz/text | 入库时间/轮次 |

## 7. `comment_raw`

| 字段 | 类型 | 说明 |
|---|---|---|
| `comment_id` | text PK | 一级评论 ID |
| `raw_json` | jsonb | 完整 v5 comment raw |
| `raw_sha256`, `fetched_at`, `run_id` | text/timestamptz | 溯源 |

回复 raw 留在 Windows 本地 `out/raw`，不在此表。

## 8. `quality_metric`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id`, `aweme_id`, `thread_id` | text PK | 轮次/视频/线程；`__top_level__`、`__replies__` 为汇总 |
| `expected_total` | int | 平台 expected |
| `fetched` / `unique_count` / `duplicates` | int | 抓取/去重 |
| `orphan_edges` / `depth3` | int | 结构指标 |
| `coverage` | float | unique / expected；可能 >1 |
| `stop_reason` | text | `complete` / `max_pages` / `risk_control` / `wrapper_not_ready` 等 |
| `computed_at` | timestamptz | 计算时间 |

## 9. `media_download`

| 字段 | 类型 | 说明 |
|---|---|---|
| `run_id` + `aweme_id` | text PK | 轮次 + 视频 |
| `status` | text | pending/downloading/success/failed/skipped |
| `codec` | text | h264/hevc |
| `variant` | text | 选中的流标识 |
| `file_path` | text | 本地 mp4 路径 |
| `bytes` / `sha256` | bigint/text | 文件大小/hash |
| `width/height/format/duration_ms/bitrate` | int/text | 实际媒体信息 |
| `attempts` / `error` | int/text | 重试/错误 |
| `started_at` / `finished_at` | timestamptz | 时间 |

## 10. `worker_job`

| 字段 | 类型 | 说明 |
|---|---|---|
| `job_id` | text PK | `<run_id>:<aweme_id>` |
| `run_id`, `aweme_id` | text | 轮次/视频 |
| `threads` | jsonb | selection/max_pages/thread_ids |
| `status` | text | success/partial/failed/blocked |
| `attempt` | int | 尝试次数 |
| `result_path` | text | normalized 文件路径 |

## 11. 导出字段

`exports/<run_id>/parquet/`：

- `videos.parquet`：`video_snapshot` 去掉直接身份字段；含 `web_url`、`tags`、`media_*`、`video_file_path`、`video_sha256`、`video_codec`。
- `comments.parquet`：`comment` 去掉 `raw_page`；保留 `text`、`author_hash`、`ip_province`。
- `reply_edges.parquet`：`child_id,parent_id,thread_root_id,depth,is_orphan,aweme_id,raw_sha256,run_id`。
- `quality.parquet`：线程/视频/轮次质量指标。
- `media_downloads.parquet`：下载记录。
- `account.parquet`：账号级统计/认证文本/公开签名；不含 sec_uid/昵称/unique_id。

CSV samples 使用 UTF-8-sig；只用于抽样/QA，不作为全量语料库。

## 12. 多账号当前空值/限制（`multi-20261104-01`）

- 30 视频；`web_url`/`kind` 全有；`tags` 空 2 条；`recommend_count` 全有；`media_size_bytes` 空 4 条；mp4/codec 30/30。
- 一级评论 5,182：`ip_province` 空 293；`is_author=true` 2；`is_thread_author` 全 null。
- 回复 1,362：`ip_province` 空 38；`is_author=true` 7；`is_thread_author` 全 null。
- 回复线程 229/229 complete；expected 1,371 / unique 1,362（99.34%）；9 条平台缺口分布在 5 个线程。
- 8 个孤儿边；8 个 depth null；最大 depth 10。
- 11 条视频没有回复 thread，只有视频 + 一级评论。
- `is_author` 的 top-level 已按每视频目标账号回填；此前固定绍兴 sec_uid 的 bug 已修复（`fetch_comments.py` 支持 `--target-sec-uid`/selected `account_id`）。
- `author_hash` 全非空；salt 一致；导出不含 cookie/header/签名 URL。
