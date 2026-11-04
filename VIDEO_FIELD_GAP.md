# 视频字段对照：anotherImplement vs 当前实现

> 日期：2026-10-31
> 对象：anotherImplement 的 `VideoRecord`（schema v0.1）与本项目当前 v5 + Windows worker 实现
> 关联：[PILOT.md](PILOT.md)、[DESIGN.md](DESIGN.md)、[PILOT_SPEC.md](PILOT_SPEC.md)

---

## 0. 结论

- **当前实现已经覆盖**：视频 ID、caption、发布时间、点赞/评论/转发/收藏、时长，以及账号级的昵称、签名、粉丝数、关注数、获赞总数、作品数、认证状态。
- **现有 raw 里已有、但没入库**：`url`、`hashtags`、`media.type`、`media.size_bytes`（大部分）、每条视频的 `fetched_at`。
- **v5 能补、当前没抓**：`recommends`、认证文本、`favoriting_count`、数字 `author.id`、逐视频作者快照、生成的 `share_url`。
- **不能精确重建 / 不应保存**：anotherImplement 记录里的原始 `source_short_url`（带 `u_code`/`did`/`iid`/`share_sign`）、anotherImplement 采集时点的历史数值、原始评论者 UID/昵称（当前隐私设计刻意不存）。
- **最大语义差异**：anotherImplement 把“作者画像 + 统计”作为**每条视频的采集时点快照**嵌入；当前实现是**账号一行 + 视频一行**，作者粉丝数等是 Stage 1 的账号级快照。需要逐视频快照的话，要额外抓 detail。

状态图例：

| 标记 | 含义 |
|---|---|
| ✅ | 已入 `video`/`account` 表，已进 Parquet |
| 🟡 | 现有 raw 中已有，只差规范化/入库 |
| 🟠 | 当前没抓，但 v5 `include_raw=true` 或 detail 可补 |
| ❌ | 不能精确重建、不应保存、或不在当前范围 |

---

## 1. 标识、URL、时间

| anotherImplement 字段 | 状态 | 当前情况 / 说明 |
|---|---|---|
| `schema_version` | 🟡 | 当前没有入库；可加常量 `0.1`，不是平台事实 |
| `platform` | 🟡 | 当前隐含为 douyin；raw item 有 `platform`；可加 |
| `platform_item_id` | ✅ | `video.aweme_id` |
| `url` | 🟡 | raw item `web_url` 765/765 有；DB/Parquet 未存；可直接加 |
| `source_short_url` | ❌ / 🟠 | anotherImplement 存的是**输入链接**；当前脚本输入是 `sec_uid`/`aweme_id`，没有原始分享链接。`include_raw` 的 `share_url` 是 API 生成的，带 `did`/`iid`/`share_sign`，和原始链接不同；建议只存 canonical `url`。 |
| `collected_at` | 🟡 | raw item 有 `fetched_at`；当前 `video.fetched_at` 是**导入时间**（`now()`），不是采集时间；需加 `collected_at` 或改导入逻辑 |

**当前 raw 可用性（765 条视频列表）：**

- `web_url`: 765/765
- `kind`: 765/765（763 video + 2 image_album）
- `tags`: 744/765 非空
- `media.video.size_bytes`: 717/765 有值

---

## 2. 作者字段

| anotherImplement 字段 | 状态 | 当前情况 / 说明 |
|---|---|---|
| `author.id` | 🟠 | 当前存 `author_sec_uid`（`MS4w...`），不是数字 `uid`。数字 `uid` 只在 `include_raw` 里有；**技术上可抓，但当前隐私设计刻意不存**。若要与旧数据对齐，可存受限字段或 hash。 |
| `author.nickname` | ✅ | `video.author_nickname` / `account.nickname` |
| `author.certification` | 🟠 | 当前只有 `account.verified` 布尔值；`include_raw` 的 `author.account_cert_info` / `enterprise_verify_reason` 有认证文本。需补字段。 |
| `author.signature` | ✅ | `account.signature`（账号级） |
| `author.follower_count` | ✅ | `account.follower_count`（**账号级快照**，不是每条视频快照） |
| `author.following_count` | ✅ | `account.following_count`（账号级） |
| `author.favoriting_count` | 🟠 | 当前 `AuthorStats` 没有此字段；`include_raw` 的 author 有；账号 profile 调一次即可 |
| `author.total_favorited` | ✅ | `account.total_favorited`（来自 `stats.total_digg`） |
| `author.aweme_count` | ✅ | `account.aweme_count`（来自 `stats.content_count`；detail raw 的 `aweme_count` 可能是 null，profile 接口反而有） |

**逐视频作者快照：**

- anotherImplement 的 `AuthorProfile` 是每条视频采集时的快照。
- 当前 `account` 表只有一行（Stage 1 快照）；`video` 表只存 `author_sec_uid`/`author_nickname`。
- 如果研究需要“每条视频采集时的粉丝数/关注数/获赞总数”，要抓 detail `include_raw` 并存 `author_snapshot`；否则账号级快照足够。

---

## 3. 文案、话题、统计

| anotherImplement 字段 | 状态 | 当前情况 / 说明 |
|---|---|---|
| `caption` | ✅ | `video.caption`（`description`/`title`） |
| `hashtags` | 🟡 | raw item `tags` 已有（744/765）；DB/Parquet 未存；可直接加 `tags jsonb` |
| `publish_time` | ✅ | `video.created_at`（UTC；anotherImplement 用 +08:00） |
| `stats.likes` | ✅ | `video.digg_count` |
| `stats.comments` | ✅ | `video.comment_count` |
| `stats.shares` | ✅ | `video.share_count` |
| `stats.collects` | ✅ | `video.collect_count` |
| `stats.recommends` | 🟠 | v5 的 `ContentStats` 没有 `recommend_count`；list/detail `include_raw` 的 `statistics.recommend_count` 有（已用一条视频验证 27）。当前列表 raw 没开 `include_raw`，所以没存。 |

注意：统计值是采集时点快照，anotherImplement 与当前实现抓取时间不同，数值会漂移；字段能补，历史值不能回溯。

---

## 4. 媒体

| anotherImplement 字段 | 状态 | 当前情况 / 说明 |
|---|---|---|
| `media.type` | 🟡 | raw item `kind` 765/765；DB 未存；可直接加 |
| `media.duration_seconds` | ✅ | `video.duration_ms` / 1000；3 条 `duration_ms` 为 null |
| `media.video_file` | 🟠（下一轮 P5a） | 当前 pilot 不下载；下一轮采集若需要视觉分析，单独下载选中视频并记录路径/大小/SHA256；不做 ASR/字幕 |
| `media.size_bytes` | 🟡 / 🟠 | raw item 717/765 有；DB 未存；剩 48 条需 detail 或可能没有 |

---

## 5. anotherImplement 还有、当前没有的整块

| 字段/模块 | 状态 | 说明 |
|---|---|---|
| `subtitles`（Whisper/ASR） | ❌（P5c，不做） | 你当前只要求下载视频，不要求字幕/ASR；保留为以后可选 |
| `comments` 元数据 | 🟡 | 当前有 27,211 条评论/回复和 804 线程；可计算 `collected_count/platform_total/top_level_count/reply_count/author_reply_count/top_level_coverage`，但没写成单条 video 记录 |
| `author_engagement` | 🟡 | 当前可从评论计算（作者回复 57 条、涉及 8 个视频），但没存成派生字段 |
| 评论者 `user_id`/`user_nickname` | ❌（不应保存） | anotherImplement 存原始身份；当前只存 `author_hash` + `ip_province`，这是有意的隐私设计 |
| 评论 `is_hot` | 🟠 | 当前 comment 表没有；raw 可能有，可按需补 |

**当前实现的强项：**

- 评论/回复完整线程：depth 2–14、孤儿边、父子关系；
- `author_hash`、`ip_province`、`is_author`、`is_creator_label`；
- 每线程 coverage/stop_reason、质量指标；
- 隐私分层：raw vault / analysis DB / publication。

---

## 5.1 P5 拆分：视频下载 vs 视频分析 vs 字幕

你现在的需求是**下载视频**，不是字幕。建议把原来的 P5 拆成三层：

| 子项 | 做什么 | 什么时候 |
|---|---|---|
| **P5a 视频下载** | 下载选中视频的 mp4；记录 `video_file_path`、`size_bytes`、`sha256`、`downloaded_at`、`width/height/format` | 下一轮采集，按研究样本下载 |
| **P5b 视觉分析** | 抽帧、人物检测、室内/室外场景分类等；基于 P5a 的文件 | 后续分析阶段，不影响采集 schema |
| **P5c 字幕/ASR** | Whisper 转写、字幕 JSON | **暂不做**；只有以后需要文本/语音分析时再加 |

存储估算（绍兴文旅当前 765 条，717 条有 size）：

- 全部 765 条约 **10.1 GB**；平均 14.1 MB/条，中位数 10.6 MB，最大 163 MB。
- 20 个 pilot 视频约 **0.26 GB**（19/20 有 size；1 条缺 size）。
- 10–50 个账号不能简单按 10 GB × 账号数估算；要先决定抽样比例。若每个账号只下载几十条，成本可控；若全量下载，可能到几百 GB。

P5a 的实现建议：

- 只下载**研究样本中的视频**，不默认下载 765 条全量。
- 在拿到视频详情后立即下载：CDN/stream URL 会过期，不能只存 URL。
- 存储路径：`data/media/<run_id>/<aweme_id>.mp4`，raw/media vault 本地受控，不进共享目录/导出。
- 记录 `sha256`、`size_bytes`、`downloaded_at`、`download_status`、`format`、`width`、`height`。
- 不把带签名的下载 URL 写入 DB/Parquet；只存本地相对路径和 hash。
- 视觉分析（人物/室内外）在 P5b 做，可以先抽关键帧，减少存储和隐私暴露。

---

## 6. 建议补的最小字段

如果目标是“接近 anotherImplement 的视频记录”，建议加：

```sql
ALTER TABLE video
  ADD COLUMN web_url text,
  ADD COLUMN kind text,
  ADD COLUMN tags jsonb,
  ADD COLUMN recommend_count bigint,
  ADD COLUMN media_size_bytes bigint,
  ADD COLUMN author_certification text,
  ADD COLUMN author_favoriting_count bigint,
  ADD COLUMN collected_at timestamptz,
  ADD COLUMN author_snapshot jsonb;  -- 可选：逐视频作者快照
```

采集方式：

1. **现有列表 raw 直接补**（不新增请求）：
   - `web_url`、`kind`、`tags`、`media.size_bytes`、`fetched_at`。
2. **列表请求加 `include_raw=true`**：
   - `statistics.recommend_count`、`author.account_cert_info`/`enterprise_verify_reason`、`author.uid`、`share_url`。
   - 已用 `/api/v1/douyin/user/posts?...&include_raw=true` 验证：list item 的 `raw` 含 `recommend_count` 和认证字段。
3. **账号 profile 加 `include_raw=true`**（一次）：
   - `favoriting_count`、完整 `signature`、`aweme_count`、认证文本。
4. **逐视频 detail 加 `include_raw=true`**（可选，20 个 pilot 视频可做；765 个全量会放大 raw）：
   - 逐视频作者快照（粉丝/关注/获赞/作品数）。
5. **视频文件**：单独决策；当前不做。

---

## 7. 不能 / 不应

| 项目 | 原因 |
|---|---|
| 原始 `source_short_url` 精确重建 | 带 `u_code`/`did`/`iid`/`share_sign`，是输入/设备/会话相关；API 生成的是另一条链接。建议只存 canonical `web_url`。 |
| anotherImplement 采集时点的历史数值 | 统计和粉丝数会变；只能重新采集当前值，不能回溯。 |
| 原始评论者 UID/昵称 | 当前隐私设计刻意不存；只存 `author_hash`。 |
| 可靠 `play_count` | v5 对 Douyin web 的 `play_count` 返回 null/0；anotherImplement 也没有此字段；不要依赖。 |
| `video_file` | 技术上可下载，但当前范围不做；需要存储和伦理决定。 |
| 48 条视频的 `size_bytes` | 列表 raw 没有；detail 可能也没有；不是保证可得。 |

---

## 8. 一句话回答

**当前实现已经把“视频统计 + 账号画像”的大部分字段抓到了；缺的是 raw 里有但没入库的 `url/tags/kind/size`，以及需要 `include_raw` 才能拿到的 `recommends/认证文本/favoriting_count/逐视频作者快照`。原始分享链接和 anotherImplement 的历史快照值不能精确重建；评论者原始身份则是有意不存。**
