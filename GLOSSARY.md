# 抖音数据采集 — 术语表（Glossary）

> 用途：解释本项目里出现的平台术语、字段名和缩写。
> 关联：[DESIGN.md](DESIGN.md)、[HANDOFF.md](HANDOFF.md)、[idea.md](idea.md)
> 日期：2026-10-27
> 说明：术语定义以 Evil0ctal v5.1.7 源码和文档为准；平台字段可能变化，pilot 时以真实响应复核。

---

## 0. 十秒速查

| 名称 | 一句话解释 | 你应该记住的 |
|---|---|---|
| `uid` | 用户 ID。**但在不同上下文里含义不同** | 抖音 raw 里是数字内部 ID；v5 标准化模型里是 `sec_uid` |
| `sec_uid` | 平台对外的稳定用户标识（secure user ID） | 以 `MS4wLjAB...` 开头；v5 的账号端点用它 |
| `unique_id` | 抖音号 / handle | 用户可以改，不能当主键 |
| `aweme_id` | 视频/作品的 ID | 19 位数字字符串；v5 里叫 `content_id` |
| `comment_id` / `cid` | 评论 ID | 一级评论和回复都有 |
| `cursor` | 翻页游标 | v5 统一叫 `cursor`；不要自己构造 |
| `raw` | 平台原始 JSON | 很多字段只在 raw 里有 |
| `identity` | 发请求用的平台身份 | 登录 cookie 或游客身份 |

---

## 1. 先判断：你手上的是哪种 ID

把你在浏览器或表格里看到的东西，对照下表：

| 你看到的形态 | 最可能是 | 能否直接给 v5 | 稳定性 |
|---|---|---|---|
| `MS4wLjABAAAA...` 一长串 | `sec_uid` | ✅ 作为 `sec_user_id` 参数 | 稳定 |
| `https://www.douyin.com/user/MS4wLjAB...` | 主页链接，里面含 `sec_uid` | ✅ 作为 `url` 参数 | 稳定 |
| `https://www.douyin.com/video/7123456789012345678` | 视频链接，里面含 `aweme_id` | ✅ 作为 `url` 或 `aweme_id` | 视频不变 |
| `@some_name` 或一段短文本 | `unique_id`（抖音号 / handle） | ❌ v5 不能直接解析 | 用户可改 |
| 纯数字，约 10 位 | 可能是 `short_id` 或数值 `uid` | ❌ 不建议直接用 | 可能变 |
| 纯数字，19 位 | 很可能是 `aweme_id` 或 `comment_id` | ✅ 看上下文 | 对应对象不变 |

### 只有抖音号，怎么办？

v5 不能把裸 handle 解析成 `sec_uid`，但你可以手工拿到主页链接：

1. 在抖音网页版/客户端打开该账号的主页；
2. 复制地址栏里的 `https://www.douyin.com/user/MS4wLjAB...`；
3. 其中 `MS4wLjAB...` 就是 `sec_uid`。

所以“只有抖音号”不是死路，只是需要**一次性人工整理**成主页链接或 `sec_uid`。

---

## 2. 账号与用户标识

### `uid`

**含义分两种上下文，这是最容易混淆的地方：**

| 上下文 | `uid` 指什么 | 例子 |
|---|---|---|
| 抖音原始 JSON（`raw.user.uid`） | 平台内部的**数值用户 ID** | `1234567890` |
| v5 标准化模型 `Author.uid`（抖音） | 实际是 `sec_uid` | `MS4wLjABAAAA...` |
| v5 标准化模型 `Author.uid`（TikTok） | 数值 ID | `6789012345` |

v5 源码注释（[parser.py:161-176](Douyin_TikTok_Download_API/src/dtk/platforms/douyin/parser.py#L161-L176)）说：抖音的数值 `uid` 会轮换（rotates），不能做主键，所以 v5 把 `sec_uid` 同时写进 `Author.uid` 和 `Author.sec_uid`。

**记住：** 读 v5 返回的抖音数据时，`author.uid` 不是 raw 里的数字，而是 `sec_uid`。

### `sec_uid`

- **全称理解：** secure user ID（安全版用户 ID）；具体生成算法平台没有公开。
- **形态：** 以 `MS4wLjAB` 开头的长字符串，例如 `MS4wLjABAAAA...`。
- **用途：** 抖音主页 URL 用它；v5 的账号/作品端点用它。
- **稳定性：** 稳定；改昵称、改抖音号都不影响。
- **隐私：** 它是公开出现在主页 URL 里的标识，不是秘密；但对它做哈希仍然有意义，因为它能跨数据集关联同一个用户。

### `sec_user_id`

v5 REST 请求里的**参数名**，值就是 `sec_uid`。两者是同一个东西：

- 响应字段叫 `sec_uid`；
- 请求参数叫 `sec_user_id`。

### `unique_id`

- 中文：**抖音号** / handle。
- 形态：一段短文本，例如 `some_name`。
- 稳定性：**用户可修改**，所以不能当主键。
- 特殊情况：如果账号从未设置自定义抖音号，`unique_id` 可能为空；v5 会回退到 `short_id`（[parser.py:176](Douyin_TikTok_Download_API/src/dtk/platforms/douyin/parser.py#L176)）。

### `handle`

通用社交媒体术语，指“@ 后面那个名字”。在抖音语境下就是 `unique_id` / 抖音号，不是独立字段。

### `short_id`

- 数字短 ID，用户可见的另一种账号标识。
- 当 `unique_id` 为空时，v5 用它填充 `Author.unique_id`。
- 也会变，不能当主键。

### `douyin_id`

中文口语“抖音号”的写法，通常对应 `unique_id`；不是 v5 的正式字段名。看到 `douyin_id` 时，先确认它指的是 handle 还是一串 `MS4w...`。

### `profile_url`

账号主页链接，形态：

```text
https://www.douyin.com/user/MS4wLjABAAAA...
```

v5 的 `url` 参数接受它，并从中解析出 `sec_uid`。这是最稳妥的账号输入形式之一。

### 账号标识对照表

| 名称 | 中文 | 形态 | 稳定？ | 能当主键？ | v5 字段/参数 |
|---|---|---|---|---|---|
| `uid`（raw） | 数值用户 ID | 数字 | v5 称会轮换 | ❌ | raw only |
| `sec_uid` | 安全用户 ID | `MS4w...` | ✅ | ✅ | `Author.sec_uid`；抖音同时填入 `Author.uid` |
| `sec_user_id` | 同上，请求参数名 | `MS4w...` | ✅ | ✅ | 请求参数 |
| `unique_id` | 抖音号 / handle | 短文本 | ❌ 可改 | ❌ | `Author.unique_id` |
| `short_id` | 数字短 ID | 数字 | ❌ 可改 | ❌ | `unique_id` 的回退 |
| `profile_url` | 主页链接 | URL | ✅（含 sec_uid） | ✅ | `url` 参数 |

---

## 3. 内容与评论标识

### `aweme_id`

- 抖音的**视频/作品 ID**，19 位数字字符串，例如 `7123456789012345678`。
- 视频 URL：`https://www.douyin.com/video/7123456789012345678`。
- 注意：它是字符串，不是数字；19 位超出 JavaScript 安全整数范围。

### `content_id`

v5 的**跨平台统一名称**：抖音叫 `aweme_id`，TikTok 是视频 ID，B站是 bvid。v5 的 `Content.content_id` 就是它。

### `comment_id` / `cid`

- 评论 ID。一级评论和回复都有自己的 `cid`。
- raw 里叫 `cid`；v5 标准化后叫 `comment_id`。
- 形态：长数字字符串，例如 `7000000000000001001`。

### `reply_id`

- raw 字段，表示“这条评论挂在哪个一级评论下”。
- 一级评论：`"0"`。
- 二级回复：**一级评论的 cid**（不是直接父回复的 cid）。
- v5 把它映射成 `Comment.parent_id`。

### `reply_to_reply_id`

- raw 字段，表示“这条回复直接回复的是哪条评论”。
- 直接回复一级评论：`"0"`。
- 回复另一条回复：**被回复的那条回复的 cid**。
- v5 **不解析、不落库**；只有 `include_raw=true` 时才能在 raw 里看到。
- 它是还原“回复的回复”直接父级的唯一依据。

### `parent_id`

v5 标准化字段，来自 raw 的 `reply_id`：

- 一级评论：`null`；
- 回复：**一级评论的 cid**。

所以 v5 的 `parent_id` 永远是“thread 的根”，不是“直接父级”。

### `thread_root_id`

本项目设计里的字段名：一条评论所属 thread 的**一级评论 ID**。

- 一级评论自身：`thread_root_id = comment_id`；
- 回复：`thread_root_id = parent_id`（即一级评论 ID）。

### `item_id`

抖音回复接口里对“视频 ID”的称呼，值等于 `aweme_id`。v5 请求回复接口时传 `item_id`；评论列表接口传 `aweme_id`。同一个值，两种拼写。

### `depth`

本项目设计里的层级：

- `1` = 一级评论；
- `2` = 直接回复一级评论；
- `3+` = 回复的回复。

v5 不提供，需要我们用 `reply_to_reply_id` 重建。

### 评论树示例

```text
1001  ← 一级评论（depth 1）
├── 1101  ← reply_id=1001, reply_to_reply_id=0     （depth 2）
│   └── 1102  ← reply_id=1001, reply_to_reply_id=1101（depth 3）
└── 1103  ← reply_id=1001, reply_to_reply_id=0     （depth 2）
```

- v5 的 `parent_id`：1101、1102、1103 都等于 `1001`。
- 我们的 `reply_to_comment_id`：1101→1001，1102→1101，1103→1001。
- 只有后者能还原 1102 是回复 1101 的。

### `reply_comment`

raw 里一级评论对象内嵌的“前几条回复预览”。v5 有解析函数但**没有通过 REST 暴露**；不要依赖它来省回复请求。

---

## 4. 评论结构与派生字段

### 一级评论 / top-level comment

直接挂在视频下的评论。`reply_id = "0"`，v5 `parent_id = null`，我们的 `depth = 1`。

### 二级回复 / reply

回复某条一级评论。`reply_id = 一级评论 cid`，`reply_to_reply_id = "0"`，我们的 `depth = 2`。

### 回复的回复 / nested reply

回复某条回复。`reply_to_reply_id = 被回复的回复 cid`，我们的 `depth >= 3`。

### 评论树 / comment tree

用 `reply_to_comment_id` 把评论连成的父子结构。v5 只保留两层（一级 + 回复），我们要从 raw 重建更深层。

### 平铺 / flattened

把评论当成一个列表，不保留父子关系。v5 的默认返回是“一级评论列表”和“某个一级评论下的回复列表”，本质是两层平铺；不是完整树。

### `is_author`

**本项目派生字段**：这条评论的作者是不是视频作者。

- 计算：`comment.author.sec_uid == video.author.sec_uid`。
- 抖音上 v5 的 `Author.uid` 就是 `sec_uid`，所以也可以比较 `uid`。
- 缺失时置 `null`，不要猜。
- 用于识别“作者回复”。

### `is_author_liked` / raw `is_author_digged`

**视频作者是否点赞了这条评论**。注意：这不是“作者回复”，也不是“评论者是作者”。

- raw 字段：`is_author_digged`；
- v5 标准化：`is_author_liked`。

### `is_creator_label`

raw `label_list` 里是否包含 `{"text": "Creator", ...}`。平台给“创作者/作者”打的标签，可作为 `is_author` 的交叉验证。v5 丢弃该字段。

### `ip_label`

raw 字段，评论者的 IP 属地，通常是省份名，例如 `"广东"`。v5 丢弃，只在 raw 里。

### `ip_province`

本项目字段：从 `ip_label` 规范化后的省份，只保留省级/地区级文本。缺失为 `null`。

### `reply_comment_total`

raw 字段：一条评论下的回复总数。v5 映射成 `reply_count`。

### `reply_count`

v5 标准化字段，来自 `reply_comment_total`。只对一级评论有意义；回复的该值通常为 0。

### `digg_count`

点赞数。视频和评论都有这个字段。

### `is_pinned` / raw `stick_position`

是否置顶评论。v5 把 `stick_position` 转成布尔 `is_pinned`。

### `status`

raw 评论状态字段（例如是否可见/被删）。v5 不解析；删除的评论通常直接不返回，无法区分“没有评论”和“评论被删”。

### `label_list`

raw 标签数组，可能包含 `Creator`（作者）、`Author` 等。v5 丢弃。

### `text_extra`

raw 里的表情、@、话题等结构化片段。v5 只保留纯文本 `text`，丢弃 `text_extra`。

---

## 5. 分页与抓取

### `cursor`

- 翻页游标，v5 统一用这个参数名。
- **不要自己构造**，也不要把抖音内部的 `max_cursor` 直接传给 v5。
- 第一次请求不传；之后传上一页返回的 `cursor`。
- 没有 `cursor` 或 `has_more=false` 表示最后一页。

### `max_cursor`

抖音内部对视频列表游标的叫法（时间戳）。v5 对外统一暴露为 `cursor`。

### `has_more`

是否还有下一页。翻页循环的终止条件。

### `count` / page size

每页条数：

- v5 默认 20；
- 抖音平台上限 50；
- 超过上限会被拒绝（不是自动截断）。

### offset cursor

评论翻页的游标本质是**偏移量**。热度排序变化时，偏移会错位，可能漏抓或重复抓。应对：按 `comment_id` 去重，记录重复率，必要时二次扫描。

### timestamp cursor

视频列表的游标本质是**时间戳**（`max_cursor`）。相对稳定，但不要跨查询复用。

### 热度排序 / `sort=hot`

抖音评论的默认排序，也是唯一可用排序。v5 接受 `hot` 但不会真正传给抖音（因为本来就是热度）。

### 时间排序 / `sort=new`

按时间排序。抖音**不支持**，传 `sort=new` 会返回 `400 INVALID_PARAM`。只有 B站支持。

### 翻页 / pagination

按 `cursor` + `has_more` 一页页取，直到没有下一页。v5 每个请求只返回一页，不会自动帮你翻完。

### 断点续爬 / resume

把每页的 `cursor`、页数、`has_more` 存进状态表；进程重启后从断开处继续，不从头再来。

### `total`

raw 评论页可能带的“总条数”。v5 解析时忽略它；我们的 API 客户端也拿不到页面级 raw。能用的参考只有视频元数据里的 `comment_count`。

### `comment_count`

视频元数据里的平台评论计数。它可以作为“预期评论数”，但不保证等于实际能抓到的数量（可能含回复、可能被删、可能被风控截断）。pilot 要专门对比。

---

## 6. v5 / DTK 术语

| 术语 | 人话解释 | 在本项目中的角色 |
|---|---|---|
| **v5** | Evil0ctal 项目的第 5 代重写版 | 我们的上游抓取服务，固定 v5.1.7 |
| **DTK** | 该项目的包名/CLI 名（`dtk`） | 部署和运维时会出现 |
| **REST** | HTTP JSON API | 我们采集层与 v5 的交互方式 |
| **task** | 异步任务 | 评论/视频请求默认先排队 |
| **`task_id`** | 任务 ID | 轮询 `GET /api/v1/tasks/{task_id}` |
| **`202`** | HTTP 状态：已接受、排队中 | 拿到它就要轮询或重试 |
| **`wait`** | 请求参数：最多等 N 秒拿结果 | 用 `wait=30` 减少轮询 |
| **identity** | 发请求用的平台身份 | 一个 cookie jar 或一个游客身份 |
| **guest identity** | 未登录的游客身份 | 评论/回复通常游客可抓 |
| **imported identity** | 手工导入的 cookie 身份 | 视频列表后页必须用登录身份 |
| **mint** | 用无头浏览器“铸造”一个游客身份 | 需要 `browser-rpc` 容器 |
| **cookie jar** | 一组 cookie | 导入身份的载体 |
| **`ttwid`** | 抖音必需的 cookie 之一 | 导入时必须有 |
| **`sid_guard`** | 含会话签发时间/有效期的 cookie | 用来计算 cookie 到期 |
| **proxy** | 出口代理 | 身份与代理终身绑定 |
| **token bucket** | 令牌桶限速 | 每个身份/端点有独立速率 |
| **risk control / 风控** | 平台拒绝或验证 | 会触发身份冷却 |
| **cooldown** | 身份临时不可用 | 等待或换身份 |
| **circuit breaker** | 端点熔断 | 连续失败后暂停该端点 |
| **`include_raw`** | 返回平台原始 JSON | 取 `ip_label`/`reply_to_reply_id` 必须开 |
| **normalized model** | v5 的跨平台标准化模型 | `Content`/`Comment`/`Author` |
| **archive** | v5 的视频/作者归档 | 不包含评论 |
| **snapshot** | 指标时间序列 | v5 只做视频/作者指标 |
| **TimescaleDB** | Postgres 的时间序列扩展 | v5 用；研究库不强制 |
| **Redis** | 队列/缓存/限流存储 | v5 内部使用 |
| **`guest_fallback`** | 游客返回的残缺视频列表标记 | 出现就说明列表不可信 |

### 常见错误码

| 错误码 | 含义 | 你该做什么 |
|---|---|---|
| `RATE_LIMITED` | API key 超限 | 按 `retry_after` 等待 |
| `IDENTITY_LOGIN_REQUIRED` | 需要登录身份 | 导入/续期 cookie，不要重试 |
| `IDENTITY_POOL_EXHAUSTED` | 没有空闲身份 | 等待，降低并发 |
| `QUEUE_FULL` | 队列满 | 降低提交速度 |
| `ENDPOINT_CIRCUIT_OPEN` | 端点熔断 | 等 5–10 分钟 |
| `UPSTREAM_RISK_CONTROL` | 触发平台风控 | 等待，记录，让 v5 换身份 |
| `UPSTREAM_CHANGED` | 平台响应结构变了 | 停止，保留日志，修 parser |
| `UPSTREAM_UNREACHABLE` | 网络/代理不可达 | 检查出口/代理 |

---

## 7. 隐私与数据

### HMAC-SHA256

带密钥的哈希函数。同一个输入 + 同一个 salt，永远得到同一个输出；没有 salt 无法反推原值。

本项目用它把评论者 `sec_uid` 变成 `author_hash`：

```text
author_hash = HMAC-SHA256(salt, "douyin:" + sec_uid)
```

### salt

HMAC 的密钥。必须：

- 随机生成，至少 32 字节；
- 存放在仓库外（文件或密钥管理），权限 600；
- 不写进 `.env` 示例、不写进 git、不写进 manifest。

### `hash_version`

salt/算法的版本号。换 salt 就升版本；不同版本的数据不能直接对齐。

### `PII`

Personally Identifiable Information，可识别个人身份的信息。评论者 UID、昵称、头像、签名、IP 都属于 PII。

### data minimization / 数据最小化

只收集研究必需的数据。本项目对评论者只保留：

- `author_hash`（稳定假名）；
- `ip_province`（省份）；
- 评论正文、时间、点赞数等研究字段。

不保留：原始 UID、昵称、头像、签名、精确 IP。

### 脱敏 / 假名化

- **脱敏**：去掉或遮蔽敏感字段。
- **假名化**：用稳定假名替换原始标识（如 HMAC 哈希）。假名化后仍可能被重新识别，不等同于匿名化。

### `raw_min`

本项目设计的“脱敏 raw 快照”：只保留研究需要的原始字段，用户对象缩减为 `uid_hash` + `ip_label`，并保存原始对象的 `raw_sha256` 用于完整性校验。

### `raw_sha256`

对原始 raw JSON 计算的 SHA-256，用来证明“我们确实看到过这个响应”，但不保存原始 PII。

---

## 8. 存储与导出

| 术语 | 解释 | 在本项目中的用途 |
|---|---|---|
| **Postgres** | 关系型数据库 | 研究库 `douyin_research` |
| **TimescaleDB** | Postgres 的时间序列扩展 | v5 使用；研究库非必需 |
| **Redis** | 内存键值库 | v5 的队列/缓存/限流 |
| **Parquet** | 列式存储格式 | 主要导出格式，适合 pandas/polars |
| **CSV** | 逗号分隔文本 | 辅助导出，方便 Excel |
| **JSONL** | 每行一个 JSON 对象 | 脱敏 raw 快照 |
| **zstd** | 压缩算法 | 压缩 JSONL，省磁盘 |
| **manifest** | 运行清单 | 记录参数、版本、行数、校验和 |
| **data dictionary** | 数据字典 | 解释每个字段的来源和含义 |
| **quality report** | 质量报告 | 抓取数 vs 平台计数、重复/漏抓/孤儿回复 |
| **研究库** | 我们自己的数据库 | 存评论、状态、日志、指标 |
| **v5 库** | v5 自带的 Postgres | 只存视频/作者归档，不存评论 |

---

## 9. 常见混淆速查

| 容易混淆 | 区别 |
|---|---|
| `uid` vs `sec_uid` vs `unique_id` | raw `uid` 是数字内部 ID；`sec_uid` 是稳定对外 ID（`MS4w...`）；`unique_id` 是可改的抖音号。v5 在抖音上把 `Author.uid` 填成 `sec_uid`。 |
| `reply_id` vs `reply_to_reply_id` | `reply_id` 指向一级评论（thread 根）；`reply_to_reply_id` 指向直接父评论。v5 只解析前者。 |
| `parent_id` vs `thread_root_id` | v5 的 `parent_id` 就是 thread 根；我们的 `thread_root_id` 是同一概念。直接父级看 `reply_to_comment_id`。 |
| `comment_count` vs 实际抓到数 | 平台计数可能含回复/已删/风控截断；实际抓到数由我们统计。两者不相等是正常的。 |
| `guest` vs `imported/logged-in` | 游客能抓评论，但视频列表只有第一页且缺最新；登录身份才能翻视频列表。 |
| `raw` vs 标准化模型 | raw 是平台原始 JSON（字段全）；标准化模型是 v5 清洗后的固定字段（只有 12 个评论字段）。 |
| `task result` vs 研究库 | task result 只保留 24 小时；研究库是我们永久保存的语料。 |
| `is_author` vs `is_author_liked` | 前者是“评论者是视频作者”；后者是“视频作者点赞了这条评论”。 |
| `sec_uid` vs `sec_user_id` | 同一个值；响应字段叫 `sec_uid`，请求参数叫 `sec_user_id`。 |
| `aweme_id` vs `item_id` | 同一个值；评论列表接口叫 `aweme_id`，回复接口叫 `item_id`。 |

---

## 10. 一条评论的字段映射示例

下面是一个**结构真实、内容虚构**的 raw 评论对象（简化版）：

```json
{
  "cid": "7000000000000001001",
  "aweme_id": "7123456789012345678",
  "text": "这个观点很有意思",
  "create_time": 1690000000,
  "digg_count": 123,
  "reply_comment_total": 2,
  "reply_id": "0",
  "reply_to_reply_id": "0",
  "ip_label": "广东",
  "label_list": [{"text": "Creator", "type": 1}],
  "is_author_digged": true,
  "stick_position": 0,
  "user": {
    "uid": "1234567890",
    "sec_uid": "MS4wLjABAAAA...",
    "unique_id": "some_handle",
    "nickname": "某个昵称"
  }
}
```

映射到我们的研究表：

| raw 字段 | v5 标准化字段 | 我们的输出列 | 说明 |
|---|---|---|---|
| `cid` | `comment_id` | `comment_id` | 评论主键 |
| `aweme_id` | `content_id` | `aweme_id` | 所属视频 |
| `reply_id` | `parent_id` | `thread_root_id` | `"0"` → `null` |
| `reply_to_reply_id` | ❌ 丢弃 | `reply_to_comment_id` | 直接父级；`"0"` 时回退 thread root |
| `ip_label` | ❌ 丢弃 | `ip_province` | 只留省份 |
| `label_list` | ❌ 丢弃 | `is_creator_label` | 含 `Creator` 则为 true |
| `user.sec_uid` | `author.uid` / `author.sec_uid` | `author_hash` | HMAC 后入库 |
| `user.uid` | ❌ 只在 raw | — | 数值 ID，不用 |
| `user.unique_id` | `author.unique_id` | — | 可改，不用作键 |
| `is_author_digged` | `is_author_liked` | `is_author_liked` | 作者赞过 ≠ 作者回复 |
| `reply_comment_total` | `reply_count` | `reply_count` | 一级评论的回复数 |
| `stick_position` | `is_pinned` | `is_pinned` | 是否置顶 |

派生字段：

```text
thread_root_id      = comment_id（如果是一级评论）
                      否则 = v5 parent_id
reply_to_comment_id = raw.reply_to_reply_id（有效时）
                      否则 = thread_root_id
depth               = 1（一级）
                      2（直接回复一级）
                      3+（回复的回复，父级已知时）
is_author           = (comment.user.sec_uid == video.author.sec_uid)
ip_province         = normalize(raw.ip_label)
author_hash         = HMAC-SHA256(salt, "douyin:" + raw.user.sec_uid)
```

---

## 11. 参考

- 模型定义：`Douyin_TikTok_Download_API/src/dtk/models/content.py:108-199`
- 抖音作者解析：`Douyin_TikTok_Download_API/src/dtk/platforms/douyin/parser.py:161-184`
- 抖音评论解析：`Douyin_TikTok_Download_API/src/dtk/platforms/douyin/parser.py:880-945`
- 评论请求参数：`Douyin_TikTok_Download_API/src/dtk/platforms/douyin/params.py:532-578`
- 评论/回复 REST 路由：`Douyin_TikTok_Download_API/src/dtk/api/routes/content.py:525-674`
- API 文档：`Douyin_TikTok_Download_API/documents/en/11-api.md`
- 本项目的设计与背景：[DESIGN.md](DESIGN.md)、[HANDOFF.md](HANDOFF.md)

> 术语和平台字段会变化；正式引用前请用 pilot 的真实响应复核。
