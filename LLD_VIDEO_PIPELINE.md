# LLD — 视频元数据 / 下载 / 抽帧管线

> 版本：0.1
> 日期：2026-10-31
> 范围：v5 视频列表/详情 + Linux 下载 + ffmpeg 抽帧 + 导出
> 关联：[DESIGN.md](DESIGN.md)、[NEXT_ROUND_PLAN.md](NEXT_ROUND_PLAN.md)、[MEDIA_REPORT.md](data/pilot/pilot-video-20261031-01/MEDIA_REPORT.md)、[FRAME_REPORT.md](data/frames/pilot-video-20261031-01/FRAME_REPORT.md)

---

## 1. 目标与非目标

**目标：**

- 对指定抖音账号，采集视频级元数据（含 raw-only 字段）；
- 对研究样本视频，下载“最小可用” mp4；
- 用 ffmpeg 抽帧成 JPEG，供 OpenCV/视觉模型读取；
- 保留可追溯的 run、快照、文件 hash、下载状态和帧清单；
- 不覆盖旧 run 的数据。

**非目标：**

- 不在本管线抓评论/回复（一级评论仍走 v5，回复走 Windows worker）；
- 不做 ASR/字幕；
- 不做人物检测/场景分类模型本身（P5b 后续）；
- 不做多账号并发调度（后续生产队列）；
- 不默认下载 765 条全量视频。

---

## 2. 总体架构

```text
                 ┌─────────────────────────────┐
                 │ v5 REST (Linux container)   │
                 │ /user, /user/posts, /video  │
                 │ include_raw=true            │
                 └──────────────┬──────────────┘
                                │ JSON + raw
                                ▼
┌─────────────────────────────────────────────────────────────┐
│ Linux collection scripts                                    │
│  fetch_video_metadata.py  → run/account/video snapshots      │
│  select_next_videos.sql   → selected_videos.csv              │
│  download_videos.py       → media_download + mp4             │
│  extract_frames.py        → JPEG + frames.jsonl              │
│  export_video_run.py      → Parquet/CSV/manifest            │
└─────────────────────────────────────────────────────────────┘
        │ mp4                          │ JPEG
        ▼                              ▼
 data/media/<run_id>/            data/frames/<run_id>/
 (long-term media vault)         (derived; OpenCV reads)
```

**Windows worker 不参与本管线。** 它只用于评论回复的页面内签名请求。

---

## 3. 组件

### 3.1 `fetch_video_metadata.py`

- 输入：`sec_user_id`、`run_id`、v5 base、count/max-pages。
- 调用：
  - `/api/v1/douyin/user?include_raw=true`
  - `/api/v1/douyin/user/posts?include_raw=true`
- 输出：
  - `data/raw/<run_id>/account.json`
  - `data/raw/<run_id>/video_list/page_XXX.json`
  - `data/pilot/<run_id>/account.json/csv`
  - `data/pilot/<run_id>/videos.jsonl/csv`
  - `data/pilot/<run_id>/run.json`
- 解析：
  - normalized：`web_url`、`kind`、`tags`、`stats`、`media.*`、`created_at`、`fetched_at`
  - raw：`statistics.recommend_count`、`author.account_cert_info`/`enterprise_verify_reason`、`share_url`
- 失败：HTTP 202/429/5xx 重试 3 次；仍失败则 run `partial`，不写半页。

### 3.2 `select_next_videos.sql`

- 输入：`video_snapshot` 指定 run、pilot 已用 20 条排除列表。
- 规则：target author、`comment_count>=1`、未删除/私密；10 high_comment + 10 time_spread。
- 输出：`selected_videos.csv`；记录 `selection_reason`/`rank_in_group`。
- 可重复：同一 run 重跑会重算，不修改旧 run。

### 3.3 `download_videos.py`

- 输入：`selected_videos.csv`、v5 base。
- 对每条：
  1. `/api/v1/douyin/video?aweme_id=...&include_raw=true`
  2. 选择流：`mp4`、无水印、`height>=540`，同条件最小 `size_bytes`；排除 `dash`。
  3. 顺序下载，写 `.part`，支持 Range 续传，成功后原子 rename。
  4. `ffprobe` 校验容器/分辨率/时长；首/中/末帧解码。
  5. 计算 SHA256；写 `media_download.csv`。
- 失败：
  - 403/410：刷新 detail，重试 1 次；
  - 5xx/网络：退避重试；
  - size/hash/ffprobe 失败：标记 failed，不阻塞其它视频。
- 输出：
  - `data/media/<run_id>/<aweme_id>.mp4`
  - `data/raw/<run_id>/video_detail/<aweme_id>.json`
  - `data/pilot/<run_id>/media_download.csv`
  - `data/pilot/<run_id>/media_manifest.json`

### 3.4 `extract_frames.py`

- 输入：`media_download.csv` 中 `status=success` 的视频。
- 参数（已冻结的候选）：
  - `fps=1.0`
  - `max_side=1280`，不放大
  - JPEG `-q:v 2`
- 输出：
  - `data/frames/<run_id>/<aweme_id>/%08d.jpg`
  - `frames.jsonl`：每帧 source hash、timestamp、frame hash、尺寸、参数
  - `frames_manifest.json`
- 失败：单视频失败记录，不阻塞其它视频。
- OpenCV 只读 JPEG，不解 HEVC。

### 3.5 `export_video_run.py`

- 输入：DB snapshot + media_download + selected CSV + frames manifest。
- 输出：
  - `exports/<run_id>/parquet/videos.parquet`
  - `selected_videos.parquet`
  - `media_downloads.parquet`
  - `account.parquet`
  - `samples/*.csv`（UTF-8-sig）
  - `manifest.json`（schema、完整率、下载统计、文件 SHA256、帧引用）
- 隐私：导出不含 `account_id`/`sec_uid`/昵称/raw page path/签名 URL。

---

## 4. 数据模型

### 4.1 `run`

沿用现有 `run` 表；每个采集轮一个 `run_id`。

### 4.2 `account_snapshot`

```sql
PRIMARY KEY (run_id, account_id)
```

关键字段：`sec_uid`、`unique_id`、`nickname`、`signature`、`verified`、`follower_count`、`following_count`、`total_favorited`、`aweme_count`、`certification`、`favoriting_count`、`collected_at`、`raw_path`、`raw_sha256`。

### 4.3 `video_snapshot`

```sql
PRIMARY KEY (run_id, aweme_id)
```

关键字段：

- 基础：`account_id`、`author_sec_uid`、`author_nickname`、`is_target_author`
- 内容：`caption`、`created_at`、`duration_ms`
- 统计：`digg_count`、`comment_count`、`share_count`、`collect_count`、`play_count`、`recommend_count`
- 新字段：`web_url`、`kind`、`tags`、`media_width/height/format/size/bitrate`、`author_certification`、`author_favoriting_count`、`collected_at`
- 下载：`video_file_path`、`video_sha256`、`video_variant`、`video_bytes`、`video_width/height/format/duration_ms`、`video_codec`、`downloaded_at`
- 溯源：`raw_path`、`raw_sha256`、`fetched_at`

### 4.4 `media_download`

```sql
PRIMARY KEY (run_id, aweme_id)
```

`status`：`pending | downloading | success | failed | skipped`。

字段：`variant`、`codec`、`file_path`、`bytes`、`sha256`、`width/height/format`、`duration_ms`、`bitrate`、`attempts`、`error`、`started_at`、`finished_at`。

**不存签名 URL。** 只存本地路径、hash、variant。

### 4.5 帧数据

帧不进 DB；用 `frames.jsonl` + `frames_manifest.json` 管理：

- 单帧记录：`aweme_id`、`frame_index`、`timestamp_ms`、`file_path`、`frame_sha256`、`width/height`、`source_video_sha256`、`source_video_codec`、`fps/max_side/jpeg_quality`。
- 这样 1,376 帧也不会给业务表增加压力；需要查询时导入 Parquet/分析库。

---

## 5. 状态机与失败处理

### 5.1 `media_download`

```text
pending → downloading → success
                      ↘ failed
                      ↘ skipped (已存在且 hash 匹配)
```

- 每条视频独立；失败不阻塞整批。
- `attempts` 记录重试次数；`error` 记录最后错误。
- 403/410：刷新 detail 后重试；仍失败则 failed。
- size 与预期不符：failed，保留 `.part` 供排查。
- ffprobe/帧解码失败：failed，保留文件，不写 snapshot 成功字段。

### 5.2 v5 错误

| 情况 | 处理 |
|---|---|
| 202 | 增加 wait / 轮询 task；当前脚本直接报错，建议生产实现轮询 |
| 429/503 | 退避 + 降低速率；不要并发冲 |
| 502 风控/上游 | 停止，记录；按身份冷却 |
| 403/410 CDN | 重新 detail，取新 URL，重试 1 次 |
| size/hash/ffprobe | 标记失败，人工复核 |

---

## 6. 速率、并发与规模

- 当前：单账号、串行；v5 请求间 2–4 s；下载视频间 2 s。
- 不并发下载；不并发 detail。
- 10–50 个账号时：
  - 每账号独立 run；
  - 任务队列 + 单 worker 顺序执行；
  - 每账号只下载研究样本（建议 20–50 条），不默认全量；
  - 下载/抽帧可按账号分片，但每个身份保持低频。
- 存储估算：
  - 当前 20 条视频：0.108 GB；1 fps 帧：145 MB；
  - 20 条合计约 0.25 GB；
  - 10–50 个账号要按“每账号样本数 × 0.25 GB”估算，并预留 30% 余量。

---

## 7. 存储与保留

```text
data/media/<run_id>/<aweme_id>.mp4          # 长期保留
data/frames/<run_id>/<aweme_id>/*.jpg       # 派生，可重建
data/raw/<run_id>/...                       # raw vault（含签名 URL，受限）
exports/<run_id>/...                        # 分析导出
```

- mp4 长期保留；SHA256 定期校验。
- 帧可重建；若模型参数变更，重抽，不覆盖旧 run。
- raw detail 含签名 URL，访问受限，不进共享/导出。
- 视频/帧可能含人脸、路人、室内场景；按 IRB 控制访问，发表前脱敏。

---

## 8. 隐私与安全

- 分析导出不含 `account_id`/`sec_uid`/`author_sec_uid`/`author_nickname`/`unique_id`/raw page path/签名 URL/cookie/header。
- `author_certification` 是公开认证文本；`caption/tags` 是公开内容。
- 原始 detail JSON 在 raw vault；不对外。
- media vault 与 frames 目录限制权限；不进 git、不进共享目录。
- 下载 URL 不落 DB/Parquet；只存本地路径与 hash。
- 视频分析涉及肖像/场景伦理；人物检测结果不用于再识别。

---

## 9. 验收与测试

当前 run `pilot-video-20261031-01` 已验证：

- [x] V1：765 unique（730 target + 35 other）；19 页；`stop_reason=complete`。
- [x] V2：20 条新样本；10 high_comment + 10 time_spread；与 pilot 重叠 0。
- [x] V3/V4：20/20 下载成功；0 失败；107,869,966 bytes。
- [x] duration 与元数据最大差 116 ms；0 条 >1 s。
- [x] 首/中/末帧解码 20/20。
- [x] P5b：1,376 帧；0 失败；1,376/1,376 `cv2.imread` 成功。
- [x] 导出：videos 765、selected 20、media 20、account 1；manifest hash 全部匹配。
- [x] 旧 `pilot-20261030-01` 未修改。

待补：

- [ ] 生产级 v5 202 task 轮询；
- [ ] 多账号 job queue/lease；
- [ ] 帧清单的 Parquet/分析库导入；
- [ ] 视觉模型 smoke（人物/室内外）；
- [ ] 帧参数是否需要按模型调整（fps/尺寸/JPEG 质量）。

---

## 10. 已冻结的决策

| 决策 | 值 |
|---|---|
| 视频容器 | mp4 |
| 下载编码 | 不强制；最小可用；当前 HEVC 16 / H.264 4 |
| 是否转 H.264 | 不转；OpenCV 读 JPEG 帧 |
| 下载清晰度 | 无水印 mp4，height≥540，最小 size |
| 抽帧 | 1 fps、最长边 1280、JPEG `-q:v 2` |
| 帧用途 | OpenCV/视觉模型读图片 |
| 视频保留 | 长期保留，SHA256 校验 |
| 逐视频作者快照 | 不做；账号级 snapshot |
| Windows worker | 仅评论回复，不参与视频下载 |
