# 抖音数据采集 — Evil0ctal v5 调研结论与高层设计

> 日期：2026-10-27
> 调研对象：`Evil0ctal/Douyin_TikTok_Download_API` v5.1.7（`main` 分支 `3d540db`，2026-10-26）
> 本地副本：`Douyin_TikTok_Download_API/`
> 状态：设计草案；字段可用性与翻页上限需 pilot 实测确认
> 关联文档：[HANDOFF.md](HANDOFF.md)、[idea.md](idea.md)
> 术语表：[GLOSSARY.md](GLOSSARY.md)
> 实施路线图：[ROADMAP.md](ROADMAP.md)

---

## 0. 结论摘要

1. **v5 是"抓取与签名服务"，不是研究语料库。** 它解决登录、签名、代理、风控、翻页、异步任务；但**评论不落库**，任务结果默认 24 小时后清空。研究语料必须由我们的采集层自己持久化。
2. **推荐架构：v5 保持不改、固定版本，作为上游 REST 服务；我们另建一个独立的 Python 采集/脱敏/导出层。** 这样升级容易，所有字段补丁都在我们这边完成，不需要 fork v5。
3. **三个关键字段只能从 `raw` 里取：** `ip_label`（IP 省份）、`reply_to_reply_id`（回复的直接父评论）、`label_list`（"Creator" 标记）。v5 的标准化 `Comment` 模型只有 12 个字段，这三个都不在其中。
4. **`is_author` 可以稳定派生：** 用评论作者 `uid/sec_uid` 与视频作者 `uid/sec_uid` 比较。抖音上两者都等于 `sec_uid`。
5. **最大瓶颈不是评论，而是回复。** 每条有一级评论的回复数 > 0 时都要单独请求一次回复接口，且只能一层层翻页。10–50 账号规模下，回复抓取可能从"几小时"变成"几天"，必须在设计里做取舍。
6. **视频列表翻页需要登录态 cookie。** 游客只能拿到第一页，而且第一页会缺少最新几条（源码注释有实测记录）。评论本身游客可抓。
7. **v5 没有扫码登录。** 身份来源只有两种：浏览器容器 mint 游客身份，或手工导入 cookie jar。HANDOFF 里的 "QR 登录" 假设需要更新。

> **2026-10-30 补充：** 回复采集新增一条实现路径——独立的 Windows 桌面浏览器 worker；v5 仍负责视频/一级评论。Phase 0.5 + Round 001–004 已确认：页面 wrapper 自动补 `a_bogus`/`msToken`/`bd-ticket-guard-*`；页面上下文可按 `comment_id` 定向、按 `cursor` 翻页；`count=50` 可用；同页复用 3 线程；worker 原型端到端通过（112/112 normalized）；无 app JS 页面和 `context.request` 都是 200 + 0 字节。**生产必须保留完整加载的页面 + 页面内 `fetch`。** 评审、效率模型与实验见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)、[初测分析](spike/resultFromWindows/ANALYSIS.md)。

---

## 1. v5 调研结论

### 1.1 架构与请求模型

- Python 3.12 + FastAPI + async SQLAlchemy + Alembic + Typer CLI + React 控制台。
- 数据端点默认异步：提交后返回 `202 + task_id`；可加 `?wait=N`（最大 30 秒）等待结果；或轮询 `GET /api/v1/tasks/{task_id}`。
- 任务结果保存在 Postgres `tasks.result`（JSONB），默认保留 **24 小时**（`retention.task_result_hours`，`src/dtk/core/config.py`）。
- 认证：`Authorization: Bearer dtk_...` 或 `X-API-Key: dtk_...`。API key 默认 **120 请求/分钟**。
- 平台身份池：每个身份同一时刻只能发 **1 个上游请求**；吞吐靠增加身份，不靠提高并发。
- 许可：Apache-2.0，可商用/闭源，保留 LICENSE/NOTICE。

### 1.2 本项目会用到的 REST 端点

| 用途 | 方法 + 路径 | 关键参数 | 备注 |
|---|---|---|---|
| 账号资料 | `GET /api/v1/douyin/user` | `url` 或 `sec_user_id`（二选一） | **不接受抖音号 handle** |
| 账号视频列表 | `GET /api/v1/douyin/user/posts` | `sec_user_id`、`cursor`、`count` | 第 2 页起必须有登录身份 |
| 单视频详情 | `GET /api/v1/douyin/video` | `url` 或 `aweme_id` | 列表页通常已含完整字段，可选 |
| 一级评论 | `GET /api/v1/douyin/video/comments` | `aweme_id`、`cursor`、`count`、`include_raw`、`sort` | 抖音只支持热度排序；`count` 最大 50 |
| 评论回复 | `GET /api/v1/douyin/video/comments/replies` | `comment_id` + `aweme_id`、`cursor`、`count`、`include_raw` | 每个一级评论单独请求 |
| 任务查询 | `GET /api/v1/tasks/{task_id}` | — | `202` 后轮询 |
| 实例状态 | `GET /api/v1/system/status` | — | 预检：版本、组件、身份池 |
| 导入身份 | `POST /api/v1/admin/identities/import` | `platform`、`cookies`、`user_agent`、`proxy_id` | 手工 cookie 导入 |
| 下载媒体 | `POST /api/v1/downloads` | `platform`、`content_id`/`url`、`skip_existing` | 需 downloader profile + `media:write` |

**批量能力的真相：** `POST /api/v1/tasks/batch` 最多 50 条，但只接受 **URL**，每条变成一个 parse 任务；没有按 `aweme_id` 批量取视频、批量取评论、批量取回复、批量下载的端点。HANDOFF 里的 "batch 1–50" 对我们的核心工作量帮助有限。

### 1.3 字段真相

#### 视频（`Content`，`src/dtk/models/content.py:156-183`）

`platform, content_id, kind, web_url, title, description, created_at, duration_ms, is_deleted, is_private, author, stats, media, music, tags, location, parts, fetched_at, raw`

- `stats`: `play_count, digg_count, comment_count, share_count, collect_count`（缺失为 `null`，不是 0）。
- `author`: `uid, sec_uid, unique_id, nickname, signature, avatar, web_url, verified, stats, raw`。
- `media`: `covers, video(url/urls/width/height/bitrate/format/size_bytes/watermark), streams, images`。
- 抖音的 `play_count` 经常是 0（平台不提供真实播放量），v5 会转成 `null`。

#### 评论（`Comment`，`src/dtk/models/content.py:186-199`）——只有 12 个字段

`platform, comment_id, content_id, parent_id, text, created_at, digg_count, reply_count, author, is_author_liked, is_pinned, raw`

**缺失但存在于 raw 的字段：**

| 目标字段 | 含义 | v5 是否解析 | 来源 |
|---|---|---|---|
| `ip_label` | 评论者 IP 省份 | ❌ | `raw.ip_label`（fixture 中有；真实接口待 pilot 确认） |
| `reply_to_reply_id` | 回复的直接父评论 | ❌ | `raw.reply_to_reply_id`（fixture 中有；待确认） |
| `label_list` | 含 "Creator" 标记 | ❌ | `raw.label_list` |
| `is_author` | 评论者是否为视频作者 | ❌ | 用 `comment.author.uid == video.author.uid` 派生 |

**不存在于仓库任何地方的字段：** `reply_to_userid`。不要依赖它。

**重要语义：** v5 的 `parent_id` 取自 raw 的 `reply_id`，对二级回复一律指向**一级评论**（`src/dtk/platforms/douyin/parser.py:890-896`）。真正的"回复的回复"关系在 `reply_to_reply_id` 里，v5 不读、不落库。只有 `include_raw=true` 时，原始对象会随每条评论返回。

**fixture 是手写的，不是真实抓包。** `tests/fixtures/README.md` 明确说所有 fixture 都是根据 v4 解析逻辑手写的，不能证明真实平台今天仍返回这些字段。因此 `ip_label` / `reply_to_reply_id` 必须在 pilot 用真实响应验证。

### 1.4 持久化真相

- v5 的 `archive.record()` 只写 `Content` 和 `Author`（`src/dtk/services/archive.py:261-300`）。
- **`Comment` 模型既不归档、也不进 `content_snapshots`**；评论页只存在于 `tasks.result`（24 小时）和 Redis 缓存（5 分钟）。
- 控制台的"保存评论"最多 5 页 × 50 条，只存一级评论，不含回复、不含 raw（`web/src/pages/Downloads.tsx`）。
- 归档导出 `GET /api/v1/archive/export` 只导出视频，不含评论。
- **结论：评论语料 100% 由我们的采集层负责落库；不能依赖 v5 的任何归档/导出路径。**

### 1.5 关键限制（按对 10–50 账号项目的影响排序）

| # | 限制 | 证据 | 影响 | 应对 |
|---|---|---|---|---|
| 1 | 视频列表第 2 页起需要登录身份 | `src/dtk/platforms/douyin/endpoints.py:291-298`；`IDENTITY_LOGIN_REQUIRED` | 没有登录 cookie 就抓不全任何账号 | 导入至少 1 个登录 cookie；按账号串行/多身份 |
| 2 | 单身份串行 + 令牌桶：`author_posts` 约 7.2 页/分钟 | `src/dtk/scheduler/policies.py:53`；`src/dtk/scheduler/leases.py` | 50 账号 × 10 页 ≈ 69 分钟（1 个登录） | 增加登录身份/代理；先跑 pilot |
| 3 | 游客第一页视频列表缺最新几条，且标记 `guest_fallback` | `endpoints.py:291-296`；`src/dtk/services/fetch.py:629-638` | 游客数据不能当完整样本 | 检查 `meta.guest_fallback`；有则重抓 |
| 4 | 评论只有热度排序，`sort=new` 被拒绝 | `documents/en/11-api.md:521`；`src/dtk/worker/registry.py` | 无法按时间顺序抓；热度变化会让 offset 游标漏抓/重抓 | 按 `comment_id` 去重；记录重复率；必要时二次扫描 |
| 5 | 回复每个一级评论单独请求，无批量 | `content.py:601-674` | 回复抓取是时间瓶颈，可能数天 | 限制 thread 数/页数；增加身份；接受部分覆盖 |
| 6 | 评论不归档 | `archive.py:261-300` | 任务 24 小时后数据消失 | 每页立即写自己的库 |
| 7 | `count` 最大 50；默认 20；超过平台上限直接报错 | `src/dtk/platforms/paging.py`；`src/dtk/api/routes/support.py:62-65` | 页数变多 | 评论/回复用 50，视频列表用 20 或 50 |
| 8 | API key 120 请求/分钟（含轮询） | `src/dtk/core/config.py` | 提交过快会 429 | 限流；用 `wait=30` 减少轮询 |
| 9 | 队列 500，任务等身份最多 10 秒 | `src/dtk/scheduler/scheduler.py` | 大批量提交会出现 `IDENTITY_POOL_EXHAUSTED` | 按身份速率提交，不一次性灌队列 |
| 10 | 无扫码登录；cookie 过期不强制下线 | v5 无 QR 路由；`src/dtk/ops/probes.py:240-259` | cookie 需要手工维护；过期后仍参与轮换 | 记录 `sid_guard` 到期时间；提前 3 天告警；定期重导 |
| 11 | 抖音号 handle 不能直接解析成 `sec_uid` | `GET /user` 只收 `url`/`sec_user_id` | 输入必须是主页链接或 sec_uid | 见 §4.5 |
| 12 | 游客 mint 需要 `browser-rpc` 容器（约 8GB 内存） | `documents/en/02-installation.md` | 无浏览器则只能手工导入 cookie | 二选一，见 §4.4 |

### 1.6 与 HANDOFF 原假设的差异（需要更新）

| HANDOFF 假设 | 实际情况 |
|---|---|
| QR 登录 | v5 没有扫码登录；只有 cookie 导入 + 游客 mint |
| 批量 1–50 | 只对"URL list → parse 任务"成立，评论/回复无批量 |
| Postgres/TimescaleDB 存档评论 | v5 只归档视频和作者，评论不落库 |
| 补 `reply_to_reply_id`/`is_author`/`ip_label` 需要改 v5 | 不必改 v5；`include_raw=true` + 客户端提取即可 |
| 视频列表 cookie | 确认：第 2 页起必须登录 |
| 评论游客可抓 | 确认：源码注释记录 "Comments page fine as a guest" |
| 回复层级被压平 | 确认：归一化后只有两层；原始 `reply_to_reply_id` 可还原直接父级 |

---

## 2. 设计原则

1. **v5 不改、固定版本。** 固定到 tag `v5.1.7` 或 commit `3d540bf`；升级前跑回归。所有字段补丁在我们自己的层完成。
2. **评论即抓即存。** 每一页返回后立即写库/写 raw 快照，绝不依赖 v5 的 24 小时任务结果。
3. **先筛选、后抓评论。** 视频列表先落库并本地过滤，只对命中视频抓评论，避免浪费身份配额。
4. **隐私在写入时完成。** 评论者 UID 在入库前哈希；不留原始昵称/头像/签名；raw 快照脱敏后保存。
5. **可复现、可断点、可审计。** 记录运行参数、v5 版本、游标、每次请求、失败原因、质量指标。
6. **失败要显式。** `guest_fallback`、`IDENTITY_LOGIN_REQUIRED`、`UPSTREAM_CHANGED` 都不能静默当成"没数据"。

---

## 3. 总体架构

```mermaid
flowchart TD
    A[accounts.yaml + filters.yaml + runtime.yaml] --> B[采集编排层<br/>Python CLI/服务]
    B -->|REST| C[v5.1.7<br/>FastAPI + worker]
    C --> D[(v5 Postgres/TimescaleDB<br/>仅视频/作者归档)]
    C --> E[(v5 Redis<br/>队列/缓存/身份)]
    C --> F[browser-rpc<br/>游客 mint/签名]
    C --> G[downloader<br/>可选视频下载]
    C -->|REST| M[抖音 web]
    B -->|任务/结果| W[Windows worker<br/>真实 Chrome + CDP]
    W -->|页面 XHR| M

    B --> H[(研究库<br/>douyin_research)]
    B --> I[raw 脱敏快照<br/>data/raw/*.jsonl.zst]
    B --> J[导出<br/>exports/*.parquet/csv]
    B --> K[质量报告 + manifest]
    G --> L[data/media/*.mp4]
```

**组件职责：**

- **v5**：视频、一级评论的主 API 客户端；负责签名、cookie/身份、代理、限速、风控冷却、翻页单页返回。回复不由 v5 负责（当前端点被阻断），由可选的 Windows worker 通过浏览器页面采集。
- **Windows worker（可选）**：真实 Windows 桌面 Chrome + CDP；只补回复（以及 v5 offset 截断时的一级评论）；把每页 raw 与标准化行写回服务器。见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)。
- **采集编排层（我们）**：账号解析、视频列表翻页、过滤、评论/回复翻页、字段提取、隐私转换、落库、导出、断点、质量统计。
- **研究库（我们）**：独立的 Postgres 数据库 `douyin_research`（同一 Postgres 实例即可），不与 v5 的表混用；我们自己的迁移。
- **raw 快照**：按视频分文件的脱敏 JSONL（zstd），保存字段证据，不保存完整原始用户对象。
- **导出**：Parquet 为主，CSV 为辅；附数据字典和 manifest。

---

## 4. 输入设计（What & How）

### 4.1 账号清单：`config/accounts.yaml`

```yaml
accounts:
  - label: "acct_001"
    sec_uid: "MS4wLjABAAAA..."          # 推荐：直接给 sec_uid
    douyin_id: "some_handle"           # 仅备注；v5 不能解析
    enabled: true
  - label: "acct_002"
    profile_url: "https://www.douyin.com/user/MS4wLjABAAAA..."
    enabled: true
```

- **必填：`sec_uid` 或 `profile_url` 二选一。** `profile_url` 必须包含 `sec_uid`（形如 `/user/MS4w...`）。
- `douyin_id` 只作为人工备注，不参与解析。
- 可选字段：`notes`、`expected_videos`（用于 pilot 对账）。
- 输入校验：重复 `sec_uid` 拒绝；两者都缺拒绝；`profile_url` 解析不出 `sec_uid` 拒绝。

### 4.2 过滤条件：`config/filters.yaml`

```yaml
video:
  duration_ms:   { min: 15000, max: 600000 }       # null = 不限
  digg_count:    { min: 1000,  max: null }
  comment_count: { min: 100,   max: null }
  published_at:  { start: "2024-01-01T00:00:00+08:00", end: null }
  null_policy: "exclude"   # 平台未提供该指标时：exclude / include
selection:
  max_videos_per_account: null
  order: "newest_first"
```

- 所有条件 AND；区间为闭区间。
- `comment_count` 用视频元数据里的平台计数，**不是实际抓到的评论数**。两者会有差距，pilot 要记录。
- `null_policy=exclude`（默认）保证"不确定就不抓"，避免把缺失当 0。
- 过滤规则版本号写入 `filter_rule_version`，保证复现。

### 4.3 运行参数：`config/runtime.yaml` 或 CLI

```yaml
posts:
  page_size: 20
  max_pages_per_account: null
comments:
  enabled: true
  page_size: 50
  max_pages_per_video: null
  include_raw: true            # 必须：ip_label / reply_to_reply_id 只在 raw
  second_pass: false           # 热度排序可能漏抓，可选二次扫描
replies:
  enabled: true
  page_size: 50
  max_pages_per_comment: null
  only_threads_with_replies: true
  max_threads_per_video: null  # 控制时间预算的关键旋钮
downloads:
  enabled: false               # 默认关闭
http:
  base_url: "http://127.0.0.1:8000"
  api_key_env: "DTK_API_KEY"
  wait_seconds: 30
  max_inflight_tasks: 8
  request_timeout_seconds: 60
```

### 4.4 凭证与一次性准备

**`.env`（不进仓库）：**

```dotenv
DTK_BASE_URL=http://127.0.0.1:8000
DTK_API_KEY=dtk_...
RESEARCH_DATABASE_URL=postgresql+psycopg://research:***@127.0.0.1:5432/douyin_research
COMMENTER_HMAC_SALT_FILE=/etc/douyin-research/hmac_salt
DATA_DIR=/srv/douyin-research/data
```

**一次性操作（按顺序）：**

1. 部署 v5（Docker Compose），确认 `GET /healthz`、`GET /api/v1/system/status`。
2. 创建控制台管理员/API key（至少 `douyin:read`；下载另加 `media:write`）。
3. **视频列表身份（必须）：** 从已登录的抖音网页复制 cookie（含 `ttwid`）和 User-Agent，调用
   `POST /api/v1/admin/identities/import`，`platform=douyin`。建议给这个身份设置只服务 `author_posts` 的 rotation，避免它被评论请求占用。
4. **评论/回复身份（二选一）：**
   - **A. 浏览器容器**：启用 `browser-rpc` profile，让 v5 自动 mint 游客身份（约 8GB 内存）。
   - **B. 手工导入**：导入 2–5 个游客 cookie jar（无登录会话也可），绑定不同代理。
5. 可选：为每个登录/游客身份绑定独立代理；身份与代理是终身绑定的。
6. 创建研究库 `douyin_research`，运行我们自己的迁移。

### 4.5 输入约束：抖音号 handle 问题（重要）

v5 **没有** `unique_id → sec_uid` 的解析能力：

- `GET /api/v1/douyin/user` 只接受 `url` 或 `sec_user_id`；
- 抖音路由只识别 `/user/{sec_uid}`，没有 `@handle` 路由；
- `parse_url` 对裸 handle 也不解析。

因此输入设计必须二选一：

- **方案 A（推荐，pilot 用）：** 人工提供每个账号的主页链接或 `sec_uid`。10–50 个账号一次整理成本可控。
- **方案 B（后续扩展）：** 单独做一个"handle → 主页链接"的解析步骤（浏览器自动化/搜索接口/商业工具），不放进主采集链路。

**这是 HANDOFF 第 2.1 节需要更新的地方。**

### 4.6 输入校验清单

- `sec_uid` 是否以 `MS4wLjAB` 开头（抖音特征）。
- 账号是否重复、是否 enabled。
- 过滤区间 `min <= max`；时间范围可解析且带时区。
- `page_size`：视频列表 1–50；评论/回复 1–50。
- `max_inflight_tasks` 不超过身份数 × 2，避免 `IDENTITY_POOL_EXHAUSTED`。
- 预检：v5 状态、登录身份数量、游客身份数量、cookie 到期警告、研究库连通、磁盘余量。

---

## 5. 处理流程

### Stage 0 — 预检

- `GET /api/v1/system/status`：版本、Postgres/Redis、身份池各状态数量、存储。
- 统计 `douyin` 登录身份数量（必须 ≥1）与游客身份数量（建议 ≥2）。
- 检查 cookie 到期警告（`sid_guard` 到期前 3 天）。
- 创建 `crawl_run` 行，保存配置快照（密钥脱敏）、v5 版本/commit、开始时间。

**失败即停：** 没有登录身份时，不要开始视频列表翻页。

### Stage 1 — 账号解析

- 对每个账号调用 `GET /api/v1/douyin/user?sec_user_id=...`（或 `url=`）。
- 保存 `account`：`sec_uid, unique_id, nickname, stats, verified, web_url, fetched_at`。
- 做一次合理性检查：粉丝数/作品数与预期是否同量级（防错号）。

### Stage 2 — 视频列表翻页

- `GET /api/v1/douyin/user/posts?sec_user_id=...&count=20&cursor=...`。
- 循环直到 `has_more=false`，或达到 `max_pages_per_account`。
- 每页立即 upsert `video`；保存 `video_metric_snapshot`（用于纵向研究）。
- 记录 `meta.guest_fallback`：**若为 true，标记该账号本次列表不可信**，不要把它当完整样本；等登录身份可用时重抓。
- 游标就是 v5 返回的 `cursor`（内部是 `max_cursor` 时间戳），不要自己构造。
- 页与页之间串行调用；多个账号可以并行，但受同一个登录身份串行约束。

### Stage 3 — 本地筛选

- 对本次拉到的视频逐条应用 `filters.yaml`。
- 写入 `video_filter_result`：是否命中、命中/未命中原因、规则版本、参与比较的值。
- 只对 `pass=true` 的视频进入评论阶段。
- 记录"平台计数 vs 实际抓取"的差异基线（pilot 用）。

### Stage 4 — 一级评论抓取

对每个命中视频：

1. `GET /api/v1/douyin/video/comments?aweme_id=...&count=50&include_raw=true&wait=30`
2. 每页返回后立即逐条处理并落库（见 Stage 6）。
3. 继续用返回的 `cursor` 翻页，直到 `has_more=false` 或 `max_pages_per_video`。
4. 防护：
   - `has_more=true` 但 cursor 为空/为 0 → 视为 `UPSTREAM_CHANGED`，停止并告警。
   - cursor 重复 → 停止，记录异常。
   - 按 `comment_id` upsert；重复计入 `duplicate_count`。
5. 记录 `expected_comment_count = video.stats.comment_count`，`fetched_top_level`，页面数，`guest_fallback`。

**注意：** 抖音评论只有热度排序；offset 游标在热度变化时可能漏抓/重抓。`second_pass=true` 时可在稍后重扫第一页或全量一次，用 `comment_id` 去重并测量漏抓率。

### Stage 5 — 回复抓取与树重建

对每个 `reply_count > 0` 的一级评论：

1. `GET /api/v1/douyin/video/comments/replies?comment_id=...&aweme_id=...&count=50&include_raw=true&wait=30`
2. 翻页直到 `has_more=false` 或 `max_pages_per_comment`。
3. 每条回复同样在 Stage 6 处理并落库。
4. 用 raw 的 `reply_to_reply_id` 重建直接父级：
   - `0` / `-1` / 空 → 直接父级 = 一级评论（depth 2）。
   - 否则 → 直接父级 = `reply_to_reply_id`；若该父级在本次抓到，`depth = parent.depth + 1`；否则标记 `orphan=true`，depth 置 `null` 或保守 3。
5. 回复接口返回的是该一级评论下的扁平列表；`reply_to_reply_id` 是还原"回复的回复"的唯一依据。

**实现路径：**

- **A. v5 REST（默认，当前被阻断）**：`GET /video/comments/replies`；服务器 native/browser 签名均返回 0 字节，暂不可用。
- **B. Windows worker（Phase 0.5 + Round 001–004 通过）**：真实 Windows Chrome 打开视频页 → 确认 `window.fetch` 已被页面 wrapper 包裹 → 在页面上下文 `fetch` `/comment/list/reply/`（可按 `comment_id` 定向、按 `cursor` 翻页）→ 解析响应；A（UI 点击 + 监听）作为 fallback。Round 001 确认页面 wrapper 自动签名；无 app JS 页面和 `context.request` 都是 200 + 0 字节，**不能用无浏览器 HTTP 客户端**。Round 002 确认 `count=50` 可用：3 页 45/50/13，unique 108/113，coverage 95.58%，0 重复；cursor 按请求 count 前进，不按返回条数。Round 003 确认同页复用 3 线程可行：113 线程 108/113、orphans 7、depth3 10；短线程 100%；`global_stop=null`。Round 004 确认 worker 原型端到端：job → raw → normalized → state → summary，112/112 normalized；`is_author=0` 是测试视频作者未回复，不是 sec_uid 错误。孤儿保留 `reply_to_reply_id`/`thread_root_id`，`depth` 可为 null；`is_author` 用 `sec_uid`。见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8/§4.9。

**Stage 5 的输入不是“所有评论”，而是“目标 thread 列表”。** v5 先给出一级评论与 `reply_count`，worker 只展开目标线程；不要按每条评论打开一次视频页。

**优先级控制（时间预算关键）：**

- `only_threads_with_replies`：跳过 `reply_count=0`。
- `max_threads_per_video`：只抓评论点赞数最高的 N 个 thread。
- `max_pages_per_comment`：每个 thread 最多抓几页。
- 被跳过的 thread 写入 `comment_fetch_state.status = 'skipped'`，并记录原因，保证报告里能看出覆盖缺口。

### Stage 6 — 字段提取与隐私转换（逐条、入库前）

对每条评论/回复：

1. 从标准化字段取：`comment_id, content_id, parent_id, text, created_at, digg_count, reply_count, author, is_author_liked, is_pinned`。
2. 从 `raw` 取（`include_raw=true` 时）：
   - `ip_label` → `ip_province`（只保留省份；空值保留 null）
   - `reply_to_reply_id` → 直接父级
   - `label_list` → 是否存在 `text == "Creator"` → `is_creator_label`
   - `status`（如果存在）→ 仅用于调试，不入分析表
3. 派生 `is_author`：`comment.author.uid == video.author.uid`（抖音两者均为 `sec_uid`）。任一缺失则 `null`。
4. 派生 `thread_root_id`：一级评论 = `comment_id`；回复 = 标准化 `parent_id`。
5. 计算 `depth`：一级 = 1；直接回复一级 = 2；回复的回复 = 3+（依赖父级已入库）。
6. 哈希评论者：`author_hash = HMAC-SHA256(salt, "douyin:" + uid)`，十六进制；记录 `hash_version`。**原始 uid、昵称、头像、签名一律不写研究库。**
7. 生成脱敏 raw 快照（见 §6.2），保存 `raw_sha256`（原始对象哈希）用于完整性校验。
8. 写 `comment` 表；写 `comment_metric_snapshot`。

### Stage 7 — 断点与恢复

- `video_fetch_state`：每个视频的评论游标、页数、`has_more`、状态、最后错误。
- `comment_fetch_state`：每个 thread 的回复游标、页数、`has_more`、状态、最后错误。
- 重启后从游标继续；已 `done` 的跳过；`failed` 按重试策略处理。
- 每页提交后更新状态（与数据写入同一事务或先写数据再更新状态）。

### Stage 8 — 导出

- 从研究库生成 Parquet（zstd）+ CSV。
- 生成 `manifest.json`、`quality_report.json`、`DATA_DICTIONARY.md`。
- 可选：对命中视频调用 `POST /api/v1/downloads` 下载媒体，记录文件路径/大小/校验和。

---

## 6. 输出设计（What & How）

### 6.1 研究库表（Postgres，独立数据库 `douyin_research`）

| 表 | 主键 | 关键列 | 说明 |
|---|---|---|---|
| `crawl_run` | `run_id` | `label, started_at, finished_at, status, config_json, dtk_version, dtk_commit` | 每次运行一行；config 中密钥脱敏 |
| `account` | `account_id` (`sec_uid`) | `unique_id, nickname, follower_count, content_count, verified, web_url, first_seen_at, last_seen_at` | 视频作者公开信息保留 |
| `video` | `aweme_id` | `account_id, title, description, created_at, duration_ms, play_count, digg_count, comment_count, share_count, collect_count, web_url, cover_url, play_url, music_id, music_title, tags, location, is_deleted, is_private, first_seen_at, last_seen_at, last_run_id` | 视频元数据 |
| `video_metric_snapshot` | (`aweme_id`,`captured_at`) | `run_id, play_count, digg_count, comment_count, share_count, collect_count` | 纵向指标 |
| `video_filter_result` | (`run_id`,`aweme_id`) | `pass, reason_json, duration_ms, digg_count, comment_count, published_at, rule_version` | 可审计的筛选结果 |
| `comment` | `comment_id` | `aweme_id, thread_root_id, reply_to_comment_id, depth, source, text, created_at, digg_count, reply_count, author_hash, hash_version, is_author, is_creator_label, ip_province, is_author_liked, is_pinned, first_seen_at, last_seen_at, last_run_id, raw_path, raw_sha256` | 一级评论 + 回复统一表 |
| `comment_metric_snapshot` | (`comment_id`,`captured_at`) | `run_id, digg_count, reply_count` | 纵向指标 |
| `video_fetch_state` | (`run_id`,`aweme_id`) | `cursor, pages_done, has_more, expected_count, fetched_count, status, last_error, updated_at` | 评论断点 |
| `comment_fetch_state` | (`run_id`,`comment_id`) | `cursor, pages_done, has_more, expected_reply_count, fetched_reply_count, status, last_error, updated_at` | 回复断点 |
| `request_log` | `id` | `run_id, ts, endpoint, aweme_id, comment_id, cursor, http_status, task_id, error_code, retry_after, duration_ms, attempt` | 请求审计 |
| `quality_metric` | (`run_id`,`aweme_id`) | `expected_comments, fetched_top_level, fetched_replies, distinct_comments, duplicate_count, orphan_reply_count, guest_fallback, comment_pages, reply_calls, errors, computed_at` | 覆盖/质量 |

**索引建议：** `comment(aweme_id)`、`comment(thread_root_id)`、`comment(reply_to_comment_id)`、`comment(author_hash)`、`comment(created_at)`、`video(account_id, created_at)`。

### 6.2 脱敏 raw 快照（文件）

路径：`data/raw/{run_id}/{aweme_id}/comments.jsonl.zst`（一级评论 + 回复同一文件，按抓到顺序追加）。

每行一条 `raw_min`：

```json
{
  "source": "top_level",
  "cid": "7000000000000001001",
  "aweme_id": "7123456789012345678",
  "reply_id": "0",
  "reply_to_reply_id": "0",
  "text": "……",
  "create_time": 1690000000,
  "digg_count": 123,
  "reply_comment_total": 4,
  "ip_label": "广东",
  "label_list": [{"text": "Creator", "type": 1}],
  "is_author_digged": false,
  "stick_position": 0,
  "user": {"uid_hash": "hmac-sha256:...", "ip_label": "广东"},
  "raw_sha256": "…"
}
```

- **不保存**原始 `user.uid`、`nickname`、`avatar`、`signature`、`ip_location`。
- 保留 `text`（研究需要）；如果伦理要求更严格，导出时提供 `--redact-text`。
- 视频 raw 如需要，另存 `data/raw/{run_id}/videos/{aweme_id}.json.zst`，只保留研究字段。

### 6.3 导出数据集（`exports/{run_id}/`）

| 文件 | 内容 |
|---|---|
| `accounts.parquet` | 账号维度 |
| `videos.parquet` | 视频维度（含筛选命中标记） |
| `comments.parquet` | 评论/回复统一表（含 `is_author`、`ip_province`、`depth`、`thread_root_id`、`reply_to_comment_id`） |
| `reply_edges.parquet` | `child_id, parent_id, thread_root_id, depth, orphan`，方便网络分析 |
| `video_metrics.parquet` | 视频指标时间序列（可选） |
| `comment_metrics.parquet` | 评论指标时间序列（可选） |
| `quality_report.json` | 每个视频的覆盖/缺口/错误统计 |
| `manifest.json` | 运行参数、v5 版本/commit、行数、文件 SHA-256、salt 指纹、字段可用率 |
| `DATA_DICTIONARY.md` | 每个字段的定义、来源（标准化/raw/派生）、空值含义 |

- 编码 UTF-8；Parquet 使用 zstd；CSV 为可选镜像。
- `manifest.json` 里的 `salt_fingerprint` 是 HMAC salt 的 SHA-256 前 8 位，用于确认两次导出使用同一哈希空间；**不写 salt 本身**。

### 6.4 可选视频文件

- 仅对 `pass=true` 的视频下载。
- 调用 `POST /api/v1/downloads`（`skip_existing=true`），轮询任务，记录：
  `aweme_id, file_path, size_bytes, sha256, downloaded_at, download_id`。
- 存 `data/media/{aweme_id}.mp4`；封面存 `data/media/covers/{aweme_id}.jpg`。
- 默认关闭；磁盘预算见 §8.3。

---

## 7. 字段映射与派生规则

### 7.1 视频

| 输出列 | 来源 |
|---|---|
| `aweme_id` | `Content.content_id` |
| `account_id` | 请求时的 `sec_user_id` |
| `title/description` | `Content.title/description` |
| `created_at` | `Content.created_at` |
| `duration_ms` | `Content.duration_ms` |
| `play/digg/comment/share/collect_count` | `Content.stats.*` |
| `web_url/cover_url/play_url` | `Content.web_url`；`media.covers[0].url`；`media.video.url` |
| `music_id/music_title` | `Content.music.*` |
| `tags` | `Content.tags` |
| `is_deleted/is_private` | 同名 |

### 7.2 评论/回复

| 输出列 | 来源 | 备注 |
|---|---|---|
| `comment_id` | `Comment.comment_id` | |
| `aweme_id` | `Comment.content_id` | |
| `thread_root_id` | 一级：自身 `comment_id`；回复：`Comment.parent_id` | v5 的 parent_id 指向一级评论 |
| `reply_to_comment_id` | raw `reply_to_reply_id`；无效值回退 `thread_root_id` | 直接父级 |
| `depth` | 由父链计算 | 1/2/3+ |
| `text` | `Comment.text` | |
| `created_at` | `Comment.created_at` | |
| `digg_count` | `Comment.digg_count` | |
| `reply_count` | `Comment.reply_count` | 仅一级评论有意义 |
| `author_hash` | `HMAC(salt, "douyin:"+uid)` | 原始 uid 不落库 |
| `is_author` | `comment.author.uid == video.author.uid` | 缺失则 null |
| `is_creator_label` | raw `label_list` 含 `text=="Creator"` | 交叉验证 |
| `ip_province` | raw `ip_label` | 只保留省份 |
| `is_author_liked` | `Comment.is_author_liked` | 作者赞过，不等于作者回复 |
| `is_pinned` | `Comment.is_pinned` | |
| `source` | `'top_level'` / `'reply'` | |
| `raw_sha256` | 原始 `raw` 的 SHA-256 | 完整性 |

### 7.3 `is_author` 判定

- 抖音：`Author.uid` 与 `Author.sec_uid` 都等于 `sec_uid`（源码 `models/content.py` 注释）。
- 规则：`comment.author.uid == video.author.uid`；如果视频作者 `uid` 为空，退回比较 `sec_uid`；仍为空则 `null`，不猜。
- `is_creator_label` 作为辅助验证；两者不一致时记录 `quality_issue`。

### 7.4 `ip_province` 规范化

- 只保留省级/地区级文本；去掉 "IP属地：" 前缀和空白。
- 海外可能返回国家名；原样保留，增加 `ip_region_type`（`province|country|unknown`）可选列。
- 空值/缺失 → `null`，不推断。

### 7.5 回复树重建

- 一级评论：`depth=1`，`reply_to_comment_id=null`。
- 直接回复一级评论：`reply_to_reply_id` 为 `0`/空 → `reply_to_comment_id=thread_root_id`，`depth=2`。
- 回复的回复：`reply_to_reply_id` 指向某条回复 → `reply_to_comment_id=该回复`；父级已入库则 `depth=parent.depth+1`。
- 父级未抓到（被截断/删除）→ `orphan=true`，`depth=null`；不要硬编码为 2。
- 导出 `reply_edges.parquet` 供网络分析。

### 7.6 哈希

- 算法：HMAC-SHA256；消息 `platform + ":" + uid`；输出小写 hex。
- salt：至少 32 字节随机值，存放在仓库外（文件或密钥管理），权限 600。
- `hash_version` 从 1 开始；换 salt 视为新版本，旧数据不可与新数据直接对齐。
- 同一 salt 下哈希稳定，可做纵向追踪；不保留原始 UID，无法反查。

---

## 8. 调度、限速与时间预算

### 8.1 v5 的速率事实

| 端点 | 每身份容量 | 每分钟 | 风险权重 |
|---|---|---|---|
| `author_posts` | 3 | 7.2 | 1.8 |
| `comments` | 3 | 9 | 1.5 |
| `comment_replies` | 3 | 9 | 1.5 |
| `content_detail` | 5 | 18 | 1.0 |
| `author_profile` | 4 | 12 | 1.2 |

- 每个身份同一时刻只允许 1 个上游请求。
- API key 默认 120 请求/分钟（含轮询）。
- 建议：**登录身份专门服务 `author_posts`；游客身份服务评论/回复**，避免互相占用串行锁。

### 8.2 时间估算（不含网络延迟与风控冷却）

**视频列表：**

- 50 账号 × 10 页 = 500 页；1 个登录身份 ≈ 500 / 7.2 ≈ **69 分钟**。
- 2 个登录身份 ≈ 35 分钟；3 个 ≈ 23 分钟。

**一级评论：**

- 假设 1,000 个命中视频，平均 300 条一级评论 → 每视频 6 页（count=50）→ 6,000 页。
- 1 个身份 ≈ 6000 / 9 ≈ **11.1 小时**；3 个 ≈ 3.7 小时；5 个 ≈ 2.2 小时。

**回复（真正的瓶颈）：**

- 假设每视频 30% 的评论有回复（90 个 thread），平均每个 1.5 页 → 135 页/视频。
- 1,000 个视频 → 135,000 页；1 个身份 ≈ **250 小时（10.4 天）**；3 个 ≈ 3.5 天；5 个 ≈ 2.1 天。
- 结论：**回复必须做优先级截断**，否则 10–50 账号项目不可行。
- 以上是 v5 REST 路径的估算；Windows worker 的成本模型不同：瓶颈是视频页滚动 + 每线程 UI 翻页（首屏 `count=3`、后续 `count=10`），全量约 6–13 分钟/视频。详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §3。

**建议的默认策略：**

- `max_threads_per_video: 50`（按 `digg_count` 取前 50 个 thread）。
- `max_pages_per_comment: 5`。
- 先跑 pilot 测量真实 thread 数和页数，再调整。
- 需要完整回复时，单独开一个"回复补抓"运行，用更多游客身份慢慢补齐。

### 8.3 存储估算

| 数据 | 估算 |
|---|---|
| 视频行 | 10,000 行 × ~2 KB ≈ 20 MB |
| 评论行 | 4,500,000 行 × ~1 KB ≈ 4.5 GB（含索引） |
| 指标快照 | 与运行次数线性增长 |
| 脱敏 raw | 4.5M × ~1.5 KB ≈ 7 GB（zstd 后更小） |
| 视频文件 | 默认关闭；按 10,000 × 30 MB ≈ 300 GB，需单独磁盘 |
| v5 自身 | 安装约 15 GB 磁盘；browser profile 额外数 GB 镜像 |

### 8.4 提交与并发策略

- 不要一次性把所有任务灌进 v5 队列（队列 500，等身份最多 10 秒）。
- 维护一个本地"待提交"队列，按当前可用身份数 × 2 控制 in-flight。
- 优先用 `?wait=30` 直接拿结果；超时再轮询。
- 轮询退避：1s → 2s → 4s → 8s → 15s，最长 5 分钟。
- 每个账号/视频/thread 串行；账号之间可并行，但同一登录身份的 `author_posts` 请求会被 v5 串行化。

---

## 9. 失败模式与处理

| 错误码/现象 | 含义 | 动作 |
|---|---|---|
| `202` | 任务已排队 | 轮询 `tasks/{task_id}`；退避 |
| `429 RATE_LIMITED` | API key 超限 | 按 `retry_after` 休眠；降低提交速率 |
| `503 IDENTITY_LOGIN_REQUIRED` | 视频列表后页需要登录 | **停止翻页**，告警；导入/续期 cookie，不要重试 |
| `503 IDENTITY_POOL_EXHAUSTED` | 没有空闲身份 | 退避；降低 in-flight；增加游客身份 |
| `503 ENDPOINT_CIRCUIT_OPEN` | 端点熔断 | 退避 5–10 分钟；检查风险率 |
| `502 UPSTREAM_RISK_CONTROL` | 触发风控，身份冷却 | 退避；记录；让 v5 轮换身份 |
| `502 UPSTREAM_CHANGED` | 平台响应结构变化，解析失败 | **停止**；保留请求日志；升级/修 parser |
| `502 UPSTREAM_UNREACHABLE` | 网络/出口问题 | 重试；检查代理 |
| `500 INTERNAL` | v5 内部错误 | 有限重试；记录 request_id |
| `meta.guest_fallback=true` | 游客返回的残缺视频列表 | 标记不可信；等登录身份重抓 |
| cookie 到期警告 | `sid_guard` 到期前 3 天 | 提醒人工重导；不要自动停用 |
| `has_more=true` 但 cursor 空/0 | 解析异常 | 视为 `UPSTREAM_CHANGED`，停止该视频 |
| cursor 重复 | 翻页死循环 | 停止，记录异常 |

**重试原则：** 只对可恢复错误（429/503 池耗尽/502 风控/网络）重试；`IDENTITY_LOGIN_REQUIRED` 和 `UPSTREAM_CHANGED` 不重试。默认 3 次，指数退避 + jitter。

---

## 10. 隐私与合规落地

- **评论者最小化：** 入库前只保留 `author_hash` + `ip_province`；原始 UID/昵称/头像/签名不写库、不写日志、不写 raw。
- **raw 脱敏：** 只保留研究字段；用户对象缩减为 `uid_hash` + `ip_label`；保存原始对象哈希用于校验。
- **视频作者：** 作为研究对象的公开账号保留昵称/`sec_uid`；但导出发表时仍需按伦理要求处理。
- **salt 管理：** 仓库外文件，权限 600；`manifest` 只记录指纹；换 salt 升 `hash_version`。
- **访问控制：** 研究库只对项目账号开放；导出目录权限限制；不在 git 中提交 `data/`、`exports/`、`.env`。
- **保留期限：** 按 IRB 要求设置 `retention` 任务（研究库/raw/导出/视频分别配置）；到期删除并记录。
- **发布：** 不直接发布原始评论与可识别信息；引用评论需伦理批准并尽量改写/聚合。
- **验证码/人机验证：** Pilot 在约 82 分钟内出现 2 次人工验证；不要假设 Windows worker 可以长期无人值守。生产需检测验证码/登录墙并暂停+告警，人工通过后 resume；不得自动绕过验证码。
- **合规前提：** 低频、串行、不绕过登录/验证码/风控；遵守抖音用户协议的风险由研究设计承担；本文不是法律意见。

---

## 11. Pilot 计划（在 HANDOFF §10 基础上补充）

选 1 个有 20+ 视频的账号，以及 1 条有 100+ 一级评论、且有评论超过 20 条回复的视频。

**v5 特定验收项：**

- [ ] 登录 cookie 导入成功，`author_posts` 第 2 页起可翻；记录 `guest_fallback` 是否出现。
- [ ] 视频列表能完整翻页，数量与网页显示一致（允许少量差异，记录差值）。
- [ ] 视频字段含 `duration_ms`、点赞/评论/转发/收藏/发布时间。
- [ ] 一级评论 `count=50` 可翻页超过 100 条；记录实际页数和 `has_more` 行为。
- [ ] 回复接口能翻页超过 20 条；记录每页条数与页数。
- [ ] **真实 raw 中确认 `ip_label` 存在**，记录字段路径和空值率。
- [ ] **真实 raw 中确认 `reply_to_reply_id` 存在**，验证"回复的回复"能还原直接父级。
- [ ] 确认 `label_list` 的 "Creator" 标记，并与 `is_author` 派生结果交叉验证。
- [ ] 确认 `is_author` 派生正确（作者回复自己视频的评论）。
- [ ] 确认评论 `total` 是否能从视频 `stats.comment_count` 对齐；记录抓取数 vs 页面显示数。
- [ ] 测量单视频耗时、请求失败率、是否触发验证/限流/冷却。
- [ ] 测量热度排序下 offset 翻页的重复率/漏抓率（建议同一视频抓两遍对比）。
- [ ] 导出 Parquet/CSV，字段完整、编码正常、哈希稳定。

**如果 pilot 不达标：** 不要扩到 10–50 个账号；先判断是 v5 限制、cookie 问题还是平台限制，再决定是否用商业工具做对照。

---

## 12. 分阶段实施

| 阶段 | 范围 | 产出 |
|---|---|---|
| A. Pilot | 1 账号；1 个登录 cookie + 1–2 个游客身份；评论全量、回复限量 | 真实字段报告、翻页上限、耗时、风险记录；确认设计假设 |
| B. 小规模 | 5–10 账号；登录身份 1–2；回复按 thread 截断 | 完整研究库 + 导出 + 质量报告；校准时间预算 |
| C. 规模 | 10–50 账号；多登录/多游客/代理；回复补抓 | 稳定流水线、监控、备份、保留策略 |

**先不要做：** 修改 v5 源码、一次性全量回复、视频全量下载、扩展其他平台。

---

## 13. 需要确认的决策

1. **账号输入：** 你手上是 `sec_uid`/主页链接，还是只有抖音号 handle？如果只有 handle，需要额外的解析步骤（方案 B），否则 pilot 前要人工补齐。
2. **游客身份来源：** 启用 `browser-rpc`（约 8GB 内存，自动 mint）还是手工导入 2–5 个游客 cookie（更省内存，但要维护）？
3. **回复范围：** 全量回复（时间可能数天）还是按 `digg_count` 取前 N 个 thread / 每 thread 最多 M 页？
4. **raw 保留：** 脱敏 `raw_min`（推荐）还是加密保存完整 raw？后者对复现更友好，但 PII 风险更高。
5. **是否允许 fork v5：** 推荐不改；如果后续要利用评论页内嵌的 `reply_comment` 预览来省回复请求，才考虑打补丁。
6. **研究库位置：** 独立数据库 `douyin_research`（推荐）还是独立 Postgres 实例？

---

## 14. 关键源码参考

| 主题 | 文件 |
|---|---|
| 标准化模型 | `Douyin_TikTok_Download_API/src/dtk/models/content.py:156-199` |
| 评论解析 | `Douyin_TikTok_Download_API/src/dtk/platforms/douyin/parser.py:880-945` |
| 评论请求参数 | `Douyin_TikTok_Download_API/src/dtk/platforms/douyin/params.py:532-578` |
| 登录要求 | `Douyin_TikTok_Download_API/src/dtk/platforms/douyin/endpoints.py:285-299` |
| 归档逻辑（不含评论） | `Douyin_TikTok_Download_API/src/dtk/services/archive.py:261-300` |
| 限速/令牌桶 | `Douyin_TikTok_Download_API/src/dtk/scheduler/policies.py` |
| 分页上限 | `Douyin_TikTok_Download_API/src/dtk/platforms/paging.py` |
| 评论/回复 REST 路由 | `Douyin_TikTok_Download_API/src/dtk/api/routes/content.py:525-674` |
| 文档：API | `Douyin_TikTok_Download_API/documents/en/11-api.md` |
| 文档：身份/代理 | `Douyin_TikTok_Download_API/documents/en/06-identities-and-proxies.md` |
| 文档：部署 | `Douyin_TikTok_Download_API/documents/en/02-installation.md` |
| fixture 免责声明 | `Douyin_TikTok_Download_API/tests/fixtures/README.md` |

---

## 15. 文档状态

- 版本：v0.7（2026-10-30）
- 下一步：生产集成（job queue、normalized → 研究库/隐私转换、真实目标账号 `is_author` 非 0、可选 `is_thread_author`）→ pilot；中文 locale 复测可选。
- 回复 worker 的评审、效率模型与实验：[WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)。
- 本文档不包含代码级实现细节；pilot 通过后再写模块设计和任务拆分。
