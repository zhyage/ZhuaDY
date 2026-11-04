# 下一轮采集计划 — 视频元数据 + P5a 视频下载

> 日期：2026-10-31
> 状态：V0–V6 完成（视频管线 + LLD，2026-10-31）；视觉模型 smoke 待做
> 目标 run_id：`pilot-video-20261031-01`（示例）
> 关联：[VIDEO_FIELD_GAP.md](VIDEO_FIELD_GAP.md)、[PILOT.md](PILOT.md)、[PILOT_SPEC.md](PILOT_SPEC.md)

---

## 1. 目标

用一个小样本验证一条**新的、面向视频分析的采集链路**：

```text
v5：账号 profile + 视频列表（include_raw=true）
Linux：解析视频元数据 → 入库/导出
Linux：下载选中视频 mp4 → 校验 → 记录路径/大小/SHA256
```

**不是**回填 `pilot-20261030-01`，也**不是**重抓评论/回复。

## 2. 非目标

- 不补现有 pilot 的字段；旧 run 保持不动。
- 不重抓 23,012 条一级评论或 4,199 条回复。
- 不做 ASR/字幕；不做人物检测/室内外分类（P5b 后续）。
- 不默认下载 765 条全量视频；只下载本轮研究样本。
- 不做多账号并发/生产任务队列（留给 LLD）。

## 3. 建议范围（待确认）

| 项目 | 建议 |
|---|---|
| 账号 | **绍兴文旅**（已确认） |
| 视频样本 | **新的 20 条**，排除 pilot 已用的 20 条；10 高评论 + 10 时间跨度（已确认） |
| 评论/回复 | 本轮不抓；需要时另开评论轮 |
| 视频下载 | 20 条全部尝试；失败逐条记录 |
| 下载清晰度 | **最小可用**：优先最小体积的无水印 mp4（排除 dash），高度 ≥540；若没有则回退 480/720；记录 variant/width/height/bitrate |
| 保留期 | **长期保留 mp4**；media vault 本地受控，记录 SHA256，定期校验；不随导出/共享目录发布 |
| 作者快照 | **不做逐视频快照**；用账号级 `account` 快照（已确认） |
| 存储 | `data/media/<run_id>/`，本地受控，不进共享目录/导出 |

如果更希望用 pilot 同 20 条做对照，也可以，但那是“重新采集 + 下载”，不是回填；建议至少排除已分析过的样本，避免混淆。

## 4. 阶段

### V0 — 准备（0.5 天）

- 建 schema migration：`sql/002_video_media.sql`。
- 新 run_id、目录、manifest 模板。
- 复用现有 `.secrets/dtk-api-key.txt`；不新增 cookie/分享目录。
- 确定 20 条新样本并冻结列表。

### V1 — 账号 + 视频元数据（0.5 天）

- `/api/v1/douyin/user?include_raw=true`：补齐认证文本、`favoriting_count`、完整签名。
- `/api/v1/douyin/user/posts?include_raw=true`：分页拉全量列表；解析：
  - `web_url`、`kind`、`tags`、`statistics.recommend_count`
  - `author.account_cert_info` / `enterprise_verify_reason`
  - `media.video.size_bytes`、`width`、`height`、`format`
  - `fetched_at` → `collected_at`
- 旧 `pilot-20261030-01` 不动；新表列 nullable。

### V2 — 样本选择（0.5 天）

- 排除 pilot 20 条。
- 10 条高评论 + 10 条时间跨度；写 `selected_videos.csv`。
- 记录选择规则、平台总数、排除原因。

### V3 — 视频下载 smoke（0.5 天）

先下载 3 条，验证：

- v5 detail 重新取流地址（不存签名 URL）。
- 下载 `.part` → 校验 size → 原子重命名 `.mp4`。
- `ffprobe` 校验 duration/width/height/format。
- 解码首帧/中间帧/末帧，确认可读。
- 计算 SHA256、记录 bytes、variant、耗时。
- 比较 `download_addr` 与 `play_addr` 的水印/清晰度/大小，冻结策略。

### V4 — 批量下载 17 条（1 天）

- 顺序下载，不并发；请求间 2–4 s。
- 每条记录 `status/attempts/error`。
- 403/410（URL 过期）：重新取 detail，重试 1 次。
- 连续失败/风控：停止，写报告，不无限重试。
- 已存在且 SHA256 匹配的文件跳过，支持 resume。

### V5 — 校验与报告（0.5 天）

- 20/20 元数据非空率（允许平台 null，记录原因）。
- 20/20 下载尝试；成功/失败列表。
- 文件 size vs `media_size_bytes`、ffprobe duration vs `duration_ms`。
- 总字节、总耗时、平均大小、失败率。
- 输出 `NEXT_ROUND_REPORT.md` + `media_manifest.json`。

### V6 — 冻结与进入 LLD（0.5 天）

- 确认字段/下载策略稳定。
- 把 schema、下载重试、存储路径、保留期写进 LLD。
- 再决定是否扩到 10–50 个账号。

## 4.1 V0–V2 实际结果（2026-10-31）

- **V0**：`sql/002_video_media.sql` + `sql/003_video_snapshots.sql` 已应用。
  - 为保护旧 pilot，不把新 run upsert 进 `account`/`video`；新增 run 级快照表：
    - `account_snapshot (run_id, account_id)`
    - `video_snapshot (run_id, aweme_id)`
    - `media_download (run_id, aweme_id)`
  - 旧 `account`/`video` 未修改；旧行新列为 NULL。
- **V1**：`scripts/collection/fetch_video_metadata.py` 已跑通。
  - 19 页、765 unique（730 target + 35 other）、0 guest_fallback、`stop_reason=complete`。
  - include_raw 原始页 19 个，约 **67 MB**。
  - 新字段非空：`web_url` 765/765、`kind` 765/765、`tags` 738/765（21 条空）、`recommend_count` 765/765（其中 316 条为 0）、`media_size_bytes` 661/765、`author_certification` 765/765、`author_favoriting_count` 765/765。
  - `media_size_bytes` 有 104 条缺失；V3 下载时用流地址/size 补，不阻塞。
  - 账号快照：粉丝 369,479；关注 121；获赞 2,207,877；作品 730；认证文本已抓到；`favoriting_count=0`。
- **V2**：`sql/select_next_videos.sql` 已生成 `selected_videos.csv`。
  - 20 条：10 high_comment + 10 time_spread；与 pilot 20 条重叠 0。
  - 选择时排除 `pilot-20261030-01` 的 20 条。
- **V3/V4**：用户安装 ffmpeg 6.1.1 后，`scripts/collection/download_videos.py` 跑通。
  - 3 条 smoke 后批量 17 条；**20/20 成功，0 失败**。
  - 总大小 **107,869,966 bytes（0.108 GB）**；平均 5.39 MB；最小 1.66 MB，最大 21.35 MB。
  - duration 与元数据最大差 116.3 ms；0 条 >1 s；首/中/末帧解码 20/20 通过。
  - codec：HEVC 16 条、H.264 4 条；尺寸以 1024×576 为主，另有 540×960/576×1024/960×540。
  - 报告：`data/pilot/pilot-video-20261031-01/MEDIA_REPORT.md`
  - 不需要 Windows worker；v5 detail + Linux HTTP 下载完成。

---

## 5. Schema 变更

### 实际采用：run 级快照表

为保护 `pilot-20261030-01`，新 run 不 upsert 旧 `account`/`video`，而是写：

```sql
account_snapshot (run_id, account_id, ...)
video_snapshot   (run_id, aweme_id, ...)
```

字段：

- `account_snapshot`：`certification`、`favoriting_count`、`collected_at` + 原有账号字段。
- `video_snapshot`：`web_url`、`kind`、`tags`、`recommend_count`、`media_width/height/format/size/bitrate`、`author_certification`、`author_favoriting_count`、`collected_at` + 原有视频字段。
- 旧 `account`/`video` 的新列已加但本轮新 run 不写；旧行保持 NULL。
- `author_snapshot jsonb` **默认不加**；只有明确需要逐视频作者快照时才加。
- `media_download` 主键改为 `(run_id, aweme_id)`。

### 新表 `media_download`

```sql
CREATE TABLE media_download (
  aweme_id text PRIMARY KEY,
  run_id text NOT NULL,
  status text NOT NULL,          -- pending/downloading/success/failed/skipped
  variant text,                  -- download_addr/play_addr
  file_path text,
  bytes bigint,
  sha256 text,
  width integer,
  height integer,
  format text,
  duration_ms integer,
  attempts integer NOT NULL DEFAULT 0,
  error text,
  started_at timestamptz,
  finished_at timestamptz
);
```

不存完整签名 URL；只存 `variant` 和本地路径/hash。

## 5.1 P5b 抽帧实际结果（2026-10-31）

- `scripts/collection/extract_frames.py` 已跑通。
- 20/20 视频抽帧；1,376 帧；145.2 MB；0 失败。
- 参数：1 fps、最长边 1280、不放大、JPEG `-q:v 2`。
- 帧尺寸：1024×576 1,133；540×960 134；576×1024 79；960×540 30。
- 输出：`data/frames/pilot-video-20261031-01/<aweme_id>/*.jpg` + `frames.jsonl` + `frames_manifest.json`。
- 1,376 帧全部存在且 SHA256 匹配；每条帧记录源视频 SHA256 和 timestamp。
- 报告：`data/frames/pilot-video-20261031-01/FRAME_REPORT.md`
- OpenCV 5.0.0 已安装；1,376/1,376 帧 `cv2.imread` 成功。

---

## 6. 下载实现建议

- 取流：优先 v5 detail `include_raw=true` 的最新地址；CDN URL 会过期，不能复用旧 URL。
- 下载：`requests` stream + `Range` 续传 + timeout；写 `.part`，成功后原子 rename。
- 校验：`Content-Length`/`size_bytes`、SHA256、`ffprobe`、首/中/末帧解码。
- 失败：403/410 刷新 detail 重试 1 次；5xx/网络退避 2 次；仍失败记录，不阻塞整批。
- 节奏：顺序，请求间 2–4 s；不并发。
- 存储：`data/media/<run_id>/<aweme_id>.mp4`；权限 600/700；不进共享目录、不进 git、不进 Parquet。
- 导出：`videos.parquet` 含 `video_file_path`/`video_sha256`/`bytes`，但不含签名 URL；视频文件单独放 media vault。

## 7. 验收标准

- [ ] 20/20 视频元数据行写入；关键字段非空率记录在案。
- [ ] `web_url` 100%、`kind` 100%、`tags` 有值率 ≥95%、`recommend_count` 有值率记录。
- [ ] 20/20 下载尝试；成功文件逐条 SHA256/bytes/ffprobe 校验。
- [ ] 至少 19/20 成功；失败必须有 `error` 和重试记录。
- [ ] 文件 duration 与 `duration_ms` 差异 ≤1 s；首/中/末帧可解码。
- [ ] 总存储、总耗时、平均大小、失败率写入报告。
- [ ] DB/导出/共享目录无签名 URL、cookie、header。
- [ ] 旧 `pilot-20261030-01` 未被修改。
- [ ] `media_manifest.json` 可从文件路径+hash 复核。

## 8. 风险与限制

- CDN URL 过期/403：必须下载前刷新，不能只存 URL。
- 平台风控：v5 仍可能要求冷却/换身份；下载失败不等于评论失败。
- 存储：当前账号 765 条约 10.1 GB；20 条约 0.26 GB；10–50 账号需先定抽样。
- 视频含人脸/路人：属于视觉分析伦理范围；media vault 受限，发表前脱敏/不公开原帧。
- 下载清晰度/水印：需在 smoke 中固定 variant，避免批次间不可比。
- 不下载全量：默认只下载研究样本；全量需单独决定。

## 9. 已确认的决策（2026-10-31）

1. 账号：**继续绍兴文旅**。
2. 样本：**新的 20 条**，排除 pilot 已用的 20 条。
3. 下载清晰度：**最小可用**。定义为：在 v5 返回的流中，选择**无水印、mp4、高度 ≥540** 的最小体积版本；没有 540 则回退 480/720；排除 dash（需要额外音视频合并）；记录 `variant`、`width`、`height`、`bitrate`、`size_bytes`。
4. 保留期：**长期保留 mp4**。放在本地 media vault，记录 SHA256，定期校验；不进入共享目录/Parquet/公开导出。
5. 逐视频作者快照：**不做**；使用账号级 `account` 快照。

## 10. 时间预估

| 阶段 | 时间 |
|---|---|
| V0–V2 准备/元数据/选样 | 1–1.5 天 |
| V3 smoke 3 条 | 0.5 天 |
| V4 批量 17 条 | 0.5–1 天 |
| V5–V6 校验/报告/冻结 | 0.5–1 天 |
| 合计 | **2.5–4 天**（取决于下载速度和风控） |
