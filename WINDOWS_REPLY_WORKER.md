# Windows 回复 Worker — 评审、混合架构与可行性实验

> 日期：2026-10-29
> 状态：Phase 0.5 + Round 001–004 完成；**页面 wrapper 自动签名，page-context 必需；`count=50` 可用；同页 3 线程；113 线程 108/113（95.6%），短线程 100%；worker 原型端到端通过（112/112 normalized）**
> 初测分析：[spike/resultFromWindows/ANALYSIS.md](spike/resultFromWindows/ANALYSIS.md)
> 关联：[DESIGN.md](DESIGN.md)、[ROADMAP.md](ROADMAP.md)、[FEASIBILITY.md](FEASIBILITY.md)、[CHROME_SPIKE.md](CHROME_SPIKE.md)
> 参考项目：[anotherImplement/commentCapture-win](anotherImplement/commentCapture-win)

---

## 0. 一句话结论

**anotherImplement 证明了“真实 Windows 桌面 + 有头 Chromium + 页面自己的 XHR”可以拿到回复；但它不是可直接套用的架构。** 它是“滚到哪、点到哪”的全视频碰运气式展开，不是按 `comment_id` 定向；不读 `cursor`/`has_more`，没有 per-thread 断点，而且把关键 raw 字段丢了。

我们的方案：**v5 负责视频和一级评论；Windows worker 只补回复。** 作业单位先按“视频”，等 Windows 实验验证了页面内定向请求后，再降为“线程”。

**2026-10-29 初测更新：** 在 Windows 10 RDP、无 GPU、Chrome 156 的专用 profile 上，A（UI 点击 + 监听）、B（页面内 bare fetch 深评论）、C（改 `cursor`/`comment_id` 重放）均 PASS。结论升级为：**线程级 page-context worker 可行**。

**2026-10-30 Round 001 更新：** S1–S4 已确认抖音页面重写了 `window.fetch` 和 `XMLHttpRequest.open`，自动补 `a_bogus`/`msToken`/`verifyFp`/`fp` 和 `bd-ticket-guard-*`；同源无 app JS 页面和 `context.request` 都是 **200 + 0 字节**。因此“接口免签”被否定；生产必须保留完整加载的页面，并用页面内 `fetch`。

**2026-10-30 Round 002 更新：** 完整线程用 `count=50` 跑了 3 页（45/50/13），unique 108/113，coverage 95.58%，0 重复，`stop_reason=complete`；缺 5 条是平台缺口。**cursor 按请求 count 前进，不按返回条数**（page 1 返回 45，但 cursor=50）；不要自己算 offset。详见 §4.8 与 [初测分析](spike/resultFromWindows/ANALYSIS.md) §7.2。

**2026-10-30 Round 003 更新：** 同一视频页复用 3 个线程；113 线程仍 108/113（95.58%）、orphans 7、depth3 10；3 条和 1 条线程均 100%；`global_stop=null`，无验证码/wrapper 丢失/风控；命令 33 s。worker 循环（同页多线程 + count=50 + 节奏）可行。详见 §4.8 与 [初测分析](spike/resultFromWindows/ANALYSIS.md) §7.3。

---

## 1. anotherImplement 评审

### 1.1 它是什么

这不是通用下载器，而是一个研究项目的采集工程：地方文旅账号“活人感”（OTAHI）→ 旅游意愿（ETI），需要 caption、作者、统计、评论/回复、视频、ASR、视觉。工程上分三件套：

| 工具 | 作用 | 与本项目的关系 |
|---|---|---|
| tool1 `smfetch` | 采集原始数据：视频详情、评论/回复、视频文件、ASR、视觉 | 回复抓取的主要参考 |
| tool2 `smsearch` | 关键词/抖音号搜索 → 硬过滤 + LLM 语义过滤 → `urls.txt` | handle→sec_uid 解析可复用 |
| tool3 `smanalyze` | 指标、标注、报告 | 研究侧，不是采集重点 |

legacy 是单视频试点：`step1_login.py` → `step2_scrape.py` → `step3_download_asr.py`。v1 已记录 23 个视频、22,162 条评论的实绩。

### 1.2 抓取机制：可复用的核心

一句话：**常驻有头 Chromium + Playwright CDP + 监听页面自己的 XHR；不逆向签名。**

- 浏览器由 tool2 启动：`--remote-debugging-port=9222 --user-data-dir=.profile`，有头、常驻；tool1 用 `connect_over_cdp` 连上去，每个任务新开 tab，不关浏览器。见 [service.py](anotherImplement/commentCapture-win/v1/tool2-search/smsearch/service.py)。
- 视频详情：打开 `https://www.douyin.com/video/{id}`，监听 `/aweme/v1/web/aweme/detail/` 的 response。
- 一级评论：滚动 `.route-scroll-container`，让页面自己发懒加载请求；监听任何包含 `/aweme/v1/web/comment/` 的 response。这个子串同时覆盖一级列表和 `/comment/list/reply/`。见 [douyin.py](anotherImplement/commentCapture-win/v1/tool1-collect/smfetch/adapters/douyin.py)。
- 回复：用真实 `locator.click()` 点 `.comment-reply-expand-btn`，再点“展开更多”；**合成 JS click 会被前端忽略**。它不构造 reply URL，不处理 `a_bogus`、`msToken`、`bd-ticket-guard`，这些都由页面 SDK 自动带。
- response listener 必须在 `goto` 之前挂上，否则第一屏的评论/详情响应会漏掉。

这正好解释了我们服务器 spike 的失败：不是签名算法问题，而是“请求必须由真实浏览器页面自己发”。它在 Windows 桌面 + 有头 Chromium 上的成功，是这条路的直接证据。

### 1.3 数据模型：必须修正的语义冲突

`comments.json` 是扁平数组，靠 `parent_id` 表示父子。它的推导在 [schema.py](anotherImplement/commentCapture-win/v1/tool1-collect/smfetch/schema.py)：

```text
reply_to_reply_id 非 0 → parent_id = reply_to_reply_id
否则 reply_id 非 0 → parent_id = reply_id
否则 → None
```

| 评论类型 | raw `reply_id` | raw `reply_to_reply_id` | anotherImplement `parent_id` | v5 `parent_id` |
|---|---|---|---|---|
| 一级评论 | `"0"` | `"0"` | `null` | `null` |
| 直接回复一级 | 一级 cid | `"0"` | 一级 cid | 一级 cid |
| 回复的回复 | 一级 cid（线程根） | 直接父回复 cid | **直接父回复 cid** | **一级 cid（线程根）** |

也就是说，它的 `parent_id` 是“直接父节点”，v5 的 `parent_id` 是“线程根”。**两边同名字段语义不同，直接合并会把树弄错。** 正确做法是同时存：

- `thread_root_id` = raw `reply_id`（非 0 时）
- `reply_to_comment_id` = raw `reply_to_reply_id`（非 0 时）
- `depth` 单独存；不要再让 `parent_id` 承担两种含义。

它保存了 `ip_label`、`is_author`、`reply_count`，但丢掉了：

- `reply_id`（线程根）
- `reply_to_reply_id`（直接父级）
- `level`、`label_list`、`label_text`
- `aweme_id`（评论记录和 CSV 都没有，多视频导出后无法回溯）
- `user.sec_uid`、`user.unique_id`
- 完整 raw 对象

其它坑：

- `is_author` 用数值 `uid` 比较；v5 的 author id 是 `sec_uid`。直接复用会让所有 `is_author` 变成 false。应比较 `user.sec_uid`，`label_text == "作者"` 作为交叉验证。
- `ip_label` 不是每条都有：fixture 里一级评论 252/254，回复只有 42/68。研究里不能假设回复也有 IP 省份，缺失要记录，不要插补。
- `top_level_coverage` 的分母是平台总评论数（含回复），不是真正的一级覆盖率。应改为一级评论数 / 平台一级评论数，并另外记录每线程 expected vs fetched。
- 它自己的 `AGENTS.md` 说 raw 平台数据优先，但评论 schema 把 raw 丢了。这是它最大的数据模型问题。

### 1.4 风控与效率：它自己承认的问题

- 节奏：滚动 6–12 秒，每 5 轮长暂停 15–25 秒，回复点击 2–4 秒；上限 2000 条/250 轮；连续 5 轮无新数据就停。
- 单账号、单 profile、无代理、无轮换、无并发；验证码靠人工。
- 每日限额在内存里，进程重启就归零；没有 429/空 body 分类，没有退避。
- 速度：6–13 分钟/视频；200 个视频约 20–45 小时，评论滚动是瓶颈。
- 覆盖率：爆款视频网页端上限约 85%（748 一级 + 889 声明回复 ≈ 1637 / 1937）；实际抓到 984（748 一级 + 236 回复）。普通视频可接近 100%。这和我们 v5 测到的 83.3% 很接近，说明可能是平台网页端的上限，而不是某一个工具的问题。
- 评论只在整段抓完后才写盘，崩溃全丢；不读 `cursor`/`has_more`，靠“5 轮无新数据”判断结束；没有按线程断点。
- 搜索跑 6 小时后被限流、一次 0 结果。

### 1.5 可复用清单

| 组件 | 用途 |
|---|---|
| 常驻 CDP 浏览器 + 每任务新 tab | Windows worker 的浏览器生命周期 |
| `_find_user_by_did` + 三级验证 | 抖音号 → `sec_uid`；处理“抖音号+粉丝数粘连”和“抖音号不渲染” |
| trusted click + `展开更多` | 回复线程展开；合成点击无效 |
| response interception | 不逆向签名的核心 |
| JSONL 队列 / checkpoint / notifier | 长跑、断点、告警的工程模式 |
| golden fixture 测试 | 锁定 raw 字段映射 |

handle 解析链在 [search.py](anotherImplement/commentCapture-win/v1/tool2-search/smsearch/search.py)：搜索框输入 → 用户 tab → 卡片精确/前缀匹配 → 进主页三级验证（抖音号文本、认证徽章、昵称），并等待最多 25 秒。如果输入是抖音号而不是 `sec_uid`，这是最有价值的现成代码。

### 1.6 不可复用清单

- 全局点第一个“展开回复”/“展开更多”，不是按 `(aweme_id, root_comment_id)` 定位；线程和响应没有绑定。
- 不读 `has_more`/`cursor`，靠 stall 判断结束；不知道线程是否完整，也无法续抓。
- 评论只在最后写盘，没有 per-page/per-thread checkpoint。
- 数据模型丢 raw 和关键字段；`parent_id` 语义与 v5 冲突；`is_author` 的 uid/sec_uid 不匹配。
- 单账号、无代理、无轮换、无并发；每日限额不持久；没有错误分类/退避。
- 硬编码 Windows 路径；legacy 脚本会关浏览器；CDP 连接上不要随便 `ctx.close()`，可能把常驻 context 关掉；时区硬编码 `+08:00`。
- 文档与代码有漂移（cursor、merge、quota 等）。

---

## 2. 混合架构

### 2.1 职责边界

| 组件 | 负责 | 不负责 |
|---|---|---|
| v5.1.7 | 视频列表、视频详情、一级评论、身份/代理/限速、REST 任务 | 回复（当前端点被阻断）、研究库 |
| 采集编排层（服务器） | 账号解析、过滤、评论分页、任务队列、合并、隐私、导出、质量报告 | 直接驱动 Windows 浏览器 |
| Windows worker | 打开视频页、滚动评论、展开目标线程、抓 reply 响应、每页落盘 | 视频列表、一级评论主抓取、研究分析 |
| 研究库 | 统一评论/回复表、断点状态、质量指标 | 依赖 v5 的 24 小时任务结果 |

v5 仍然是视频和一级评论的主客户端；**它不再是“唯一与抖音通信的组件”**，因为回复由 Windows worker 直接通过浏览器页面采集。

### 2.2 作业粒度：视频级 / 线程级 / comment_id 级

| 粒度 | 做法 | 是否需要滚评论列表 | 可靠性 | 适用 |
|---|---|---|---|---|
| **视频级** | 打开一次视频页，滚动一级评论，逐个展开目标线程 | 是，滚到目标 | 高（anotherImplement 已验证） | 默认方案 |
| **线程级** | 评论可见后，只展开它的回复并翻页 | 是，先让评论可见 | 高 | 目标线程少、评论靠前 |
| **comment_id 级** | 页面内直接请求 `/comment/list/reply/?comment_id=...`，不依赖评论可见 | 否 | **未验证** | 实验通过后的最优方案 |

关键事实：

- **网页 UI 没有 per-comment deep link。** 不能输入 `comment_id` 直接跳到那条评论；要让它可见，只能滚动加载到它。
- **reply 接口本身是按 `comment_id` 的。** 如果能拿到页面 SDK 签名的请求，就可以不滚动、直接抓任意评论的回复。服务器上 page-context `fetch` 失败；Windows 上还没试过。
- **一旦评论可见，就可以只展开它的线程。** 不需要展开别的线程；这是线程级定向，不是视频级全量。

推荐：**默认视频级；实验验证 comment_id 级后再切换。** 不要按“每条评论打开一次视频页”的方式工作。

### 2.3 数据流

```text
v5 comments (include_raw=true)
        ↓
筛选目标 thread：reply_count > 0；按 digg_count / 抽样 / 研究设计
        ↓
任务：{aweme_id, [root_comment_id...], max_pages, deadline}
        ↓
Windows worker：打开视频页 → 滚动 → 展开目标 thread → 监听 reply 响应
        ↓
每页立即写：raw JSONL + normalized row + fetch_state
        ↓
服务器：按 (aweme_id, comment_id) upsert；更新 coverage；脱敏；导出
```

实现要点：

1. response listener 在 `goto` 之前挂。
2. 从**请求 URL** 读 `comment_id`、`cursor`、`count`；从**响应**读 `comments`、`has_more`、`cursor`、`total`。这样每次响应都能绑定到线程和页，不靠猜。
3. 每页立即写 raw（JSONL/zstd）和标准化行；不要等整段抓完。
4. 断点键：`(aweme_id, root_comment_id, cursor)`；状态：`pending/running/done/blocked/skipped`。
5. 停止条件：`has_more=false`、`max_pages`、`deadline`、空 body/验证码/登录墙等风险信号。
6. 记录 `stop_reason`：`complete` / `cap_reached` / `risk_control` / `login_wall` / `captcha` / `timeout` / `error`。
7. 不重复抓已 `done` 的线程；跨运行按 `comment_id` 去重合并。

### 2.4 数据模型扩展

在 v5 的 `Comment` 之外，至少保留：

| 字段 | 来源 | 说明 |
|---|---|---|
| `aweme_id` | 任务 | 评论必须能回溯到视频 |
| `thread_root_id` | raw `reply_id` | 一级评论填自身 `comment_id` |
| `reply_to_comment_id` | raw `reply_to_reply_id` | 直接父级；无效值回退 `thread_root_id` |
| `depth` | 计算 | 一级=1；直接回复=2；回复的回复=3+ |
| `ip_label` | raw | 缺失保留 null，不插补 |
| `label_list` / `label_text` | raw | `Creator`/`作者` 标记；与 `is_author` 交叉验证 |
| `is_author` | 派生 | 比较 `user.sec_uid` 与视频作者 `sec_uid`；raw numeric uid 作为后备 |
| `raw` / `raw_sha256` | 原始响应 | 脱敏后保存，保留字段证据 |
| `fetched_at` / `page` / `cursor` / `has_more` | worker | 抓取状态与可复现性 |
| `expected_reply_count` | raw `reply_comment_total` / `total` | 每线程覆盖率分母 |

**不要**把 `parent_id` 同时当作“线程根”和“直接父级”。对外可以保留一个派生的 `parent_id` 方便查询，但底层必须分开存。

### 2.5 队列、风控与多账号

- 持久化日限额/请求预算；不要放内存。
- 错误分类：`login_wall`、`captcha`、`rate_limit`、`empty_body`、`upstream_changed`、`deleted`、`timeout`；不同错误不同冷却。
- 每个账号一个独立 Chrome profile；worker 池；服务器只发任务，worker 主动出站轮询，不暴露 CDP。
- 同一 profile 同一时刻只发一个上游请求；不要在同一 profile 上并发开多个视频页。
- 首次出现空 body/验证码/登录墙就停，记录证据；不要连续重试。
- 合并策略：upsert by `(aweme_id, comment_id)`；raw 只追加不覆盖；重复计数。

---

## 3. 效率模型

### 3.1 成本公式

```text
T_video ≈ T_load
        + T_scroll_to_targets
        + Σ_threads (T_expand + pages × T_page)
```

| 项 | 量级 | 说明 |
|---|---|---|
| `T_load` | 10–20 秒 | 视频页 + 评论组件加载 |
| `T_scroll_to_targets` | 取决于目标位置 | 全量 748 条一级评论约 4–7 分钟；前 N 条热评几十秒 |
| `T_expand` | 2–4 秒/线程 | trusted click + 等待 |
| `T_page` | 2–4 秒/页 | UI 回复分页首屏 `count=3`，之后 `count=10` |
| 深线程 | 261 条回复 ≈ 27 页 ≈ 1–2 分钟 | UI 页大小是主要成本 |

### 3.2 实测/估算基线

| 场景 | 估算 | 依据 |
|---|---|---|
| 全量视频（一级评论 + 所有回复） | 6–13 分钟/视频 | anotherImplement 实测 |
| 200 个视频全量 | 20–45 小时 | 同上 |
| 只抓前 20 条热评的回复 | 1–3 分钟/视频 | 估算，取决于页面加载 |
| 单条 106 回复线程 | 约 11 页（count=10） | 浏览器抓包 + 1–2 分钟量级 |
| v5 一级评论 10 页 | 7 秒 | 令牌桶 burst，不代表长期吞吐 |

### 3.3 优化手段

1. **只抓需要的线程**：`reply_count > 0` 且属于研究样本；按 `digg_count` 取前 N，或按视频抽样。
2. **按视频批量**：一个视频只打开一次，所有目标线程一起处理；不要每条评论开一次页面。
3. **目标评论靠前时成本低**：如果研究只关心热评，滚到前 N 条就停。
4. **多 profile/多机**：每个账号一个 profile，横向扩展；但每个 profile 的风控独立计算。
5. **断点合并**：已 `done` 的线程不重抓；跨运行按 `comment_id` 去重。
6. **浏览器补一级评论**：v5 在 offset ~500 截断时，浏览器页面可能加载更多；如果已经打开视频页，可以顺便把超出 v5 的一级评论也收下，但不要把它当主要来源。
7. **定向请求**：如果 Windows 实验证明 comment_id 级可用，改成线程级作业，减少滚动和无效展开。

### 3.4 结论

- **回复采集的瓶颈在 Windows worker，不在 v5。**
- 成本是“每个视频的页面扫描 + 每个线程的回复页”，不是“每条评论都从头翻”。
- 如果研究要求“所有视频的所有回复”，成本会很高，必须抽样或接受覆盖上限；这是平台网页端的产品限制，不是 worker 实现问题。

---

## 4. Windows 可行性实验

### 4.1 目标

用一台真实 Windows 桌面机回答四个问题：

1. Windows 真实 Chrome 能否稳定拿到 reply 响应？（A）
2. 能否**不滚动到评论**、直接按 `comment_id` 请求回复？（B/C/D）
3. reply 请求的页大小、请求头、响应结构是什么？
4. 单线程/单视频的耗时和风险信号是什么？

### 4.2 环境与前置条件

| 项目 | 要求 |
|---|---|
| 机器 | Windows 10/11，真实 GPU + 显示器，不休眠 |
| 浏览器 | 用户日常 Chrome 或独立 Chrome；开启 CDP `127.0.0.1:9222` |
| 账号 | 专用测试账号（不要用主账号）；独立 profile |
| 网络 | 国内直连抖音；`https://www.ip.cn` 显示国内 IP；不要走国外 VPN |
| 自动化 | Python 3.10+ + Playwright，或 Node + CDP；优先 Python |
| 测试视频 | `7681929945538497843`（FEASIBILITY 的测试视频） |
| 测试线程 | `7682054941225698091`（106 条回复） |
| 深评论 | `7682223064176395049`（v5 评论第 5 页，首屏不可见；1 条回复） |
| 安全 | 只读；不点赞/不关注/不评论；低频；不把 cookie 写入仓库 |
| 探针脚本 | `spike/windows-reply/probe_reply.py`；启动与输出说明见同目录 `README.md` |

### 4.3 测试矩阵

| # | 方法 | 目标 | 证明什么 |
|---|---|---|---|
| **A** | UI 点击 + 监听 response | 可见线程，翻到 `has_more=false` | 基线：Windows 能拿到回复；字段/页大小/耗时 |
| **B** | 页面内 bare `fetch`（完整 query，无手工签名） | **首屏不可见**的 `comment_id` | 页面 fetch 是否自动带签名；能否跳过滚动 |
| **C** | 重放 A 抓到的真实签名 URL | 同线程下一页；再换 `comment_id` | `a_bogus`/ticket 是否绑定 cursor/comment_id |
| **D** | 页面 SDK 签名函数/内部 API | 不可见 `comment_id` | 是否能做真正的 comment_id 级定向 |
| **E** | 可选：`count=50` | 同线程 | UI/接口是否允许更大页，减少页数 |
| **F** | 可选：DOM 检查 | 目标评论元素 | 是否有 `data-*` 暴露 `cid`；能否稳定定位 |

### 4.4 实验步骤

1. 启动 Chrome（独立 profile，CDP 9222），确认：
   - `navigator.userAgent`
   - `navigator.webdriver`
   - WebGL renderer（`WEBGL_debug_renderer_info`）
   - 当前出口 IP（`https://www.ip.cn`）
2. 新建 tab，**先挂 response/request listener，再 `goto`** 视频页；记录所有包含 `/comment/list/reply/` 的请求 URL（值可脱敏，保留参数名）。
3. **A（基线）**：
   - 滚动到目标线程；
   - 点击 `.comment-reply-expand-btn`（trusted click）；
   - 循环点击“展开更多”，直到 `has_more=false` 或达到 `max_pages`；
   - 每次响应保存原始 body；记录 `comments` 数、`has_more`、`cursor`、`total`、耗时。
4. **B（定向 bare fetch）**：
   - 选一条首屏不可见的评论；
   - 在页面上下文 `fetch` 完整 reply URL（`item_id`、`comment_id`、`cursor=0`、`count=3`，加页面常用参数）；
   - 记录 status、bytes、body 前 200 字符；不要连续重试超过 2 次。
5. **C（重放签名 URL）**：
   - 从 A 的请求中取一条真实 URL；
   - 重放时带原始请求头；头值只在本机使用，不写入日志/仓库；
   - 原样重放一次（sanity check）；
   - 只改 `cursor` 重放；
   - 只改 `comment_id` 重放；
   - 记录三者结果。若原样成功、改参数失败，说明签名绑定参数。
6. **D（页面 SDK）**：
   - 检查 `window` 上常见的签名对象/函数（只记录名字，不 dump 值）；
   - 在页面 JS 中搜索 `comment/list/reply`、`bd-ticket-guard`，看是否有可调用的内部方法；
   - 若找到，按 `comment_id` 调一次，记录结果；找不到就记录“不可用”，不要逆向到底。
7. **E/F（可选）**：
   - 尝试 `count=50`，看是否被接受；
   - 检查目标评论 DOM 是否有 `data-*` 包含 `cid`；保存脱敏后的 HTML 片段。
8. 每步后检查风险信号：HTTP 200 + 0 字节、空 body、验证码、登录弹窗、回复按钮消失。出现即停，记录。
9. 输出到 `spike/windows-reply/out/`：
   - `responses/*.json`（原始 body，脱敏）
   - `requests.log`（URL 参数名 + 状态 + 耗时；不记录 cookie 值）
   - `report.md`（结论表 + 证据 + 时间）
   - `dom_sample.html`（脱敏，可选）

### 4.5 指标

| 类别 | 指标 |
|---|---|
| 成功 | A/B/C/D 各自 status、bytes、JSON 解析、`comments` 数 |
| 翻页 | `has_more`、`cursor`、`total`、页数、每页条数 |
| 字段 | `ip_label` 存在率、`reply_to_reply_id` 非 0 数、`label_list`/`label_text`、`reply_comment_total` |
| 性能 | 首字节、单页耗时、单线程耗时、滚动轮数 |
| 定位 | 目标评论在 v5 列表中的位置；滚了多少轮才可见；DOM 是否有 cid |
| 风控 | 空 body/0 字节/验证码/登录墙/冷却；第几次请求开始 |
| 覆盖 | fetched / expected；重复；孤儿；stop_reason |

### 4.6 通过标准与决策

| 结果 | 决策 |
|---|---|
| **A 通过**（至少 1 个 20+ 回复线程，`has_more=false`，字段完整） | Windows worker 可行；进入视频级设计 |
| **B 或 C 或 D 通过**（不可见评论也能拿到回复） | 可做线程级/comment_id 级；设计按线程作业 |
| **只有 A 通过** | 做视频级 worker；按视频批量、只展开目标线程；接受滚动成本 |
| **A 也失败** | 停止浏览器路线；评估商业工具或一级评论版本 |

**额外门槛：**

- 如果 A 通过但单视频 > 15 分钟，或 10 个线程就触发风控 → 先调整范围/节奏，不要直接进 pilot。
- 如果 B/C/D 通过但 `count` 只能 10、每页 2–4 秒 → 仍然比 UI 滚动可控，但要做时间预算。
- 如果 D 需要大量逆向页面 JS → 不作为主方案，最多作为实验结论记录。

### 4.7 安全与清理

- 专用测试账号；独立 Chrome profile；不要用主账号。
- 不把 cookie、`bd-ticket-guard-*` 值、`a_bogus` 值写入仓库或日志；只记录头名。
- 只读；不点赞/关注/评论；低频；出现风控立即停。
- 实验结束后删除独立 profile；如使用服务器扫码 session，确认设备管理里没有遗留。
- 原始响应脱敏后再提交到 `spike/windows-reply/out/`；用户昵称/头像/签名不入库。

### 4.8 Phase 0.5 初测结果（2026-10-29）

执行环境：

| 项目 | 值 |
|---|---|
| OS | Windows 10 Enterprise LTSC 2021（10.0.19044），RDP 会话，**无 GPU** |
| 浏览器 | Chrome 156.0.8078.74，专用 profile，人工扫码 |
| WebGL | Microsoft Basic Render Driver（D3D11） |
| 自动化 | Python 3.13.9 / Playwright 1.64.1 |
| locale | `en-US` |
| 登录 | `login=true`，`modal=null`，`captcha=null` |

结果：

| 测试 | 结果 | 关键数据 | 边界 |
|---|---|---|---|
| A UI 点击 + 监听 | PASS（基线） | 目标评论一次定位（非 fallback）；3 页 `n=2/7/10`，`cursor=3→13→23`，`has_more=1`，`total=113`，6.7 s | `stop_reason=max_pages`；只抓 19/113，不是完整线程 |
| B 页面内 bare fetch | PASS | 深评论 `7682223064176395049`，200，2987 bytes，`status_code=0`，拿到 1 条回复 | 请求从抖音页面上下文发出；页面可能自动补签名 |
| C 重放签名 URL | PASS | unchanged / cursor_changed / comment_id_changed 均 200；cursor 23→33；改 comment_id 后拿到深评论回复 | 同样走页面上下文 `fetch`；改参后可能被页面重新签名 |
| D 页面 globals | 信息项 | `byted_acrawler` 存在（object）；`_webmsxyw` / `frontierSign` 未定义 | 不能据此判断请求是否自动签名 |

**A 的边界：** `has_more=1` 说明线程还有下一页；它只是被 `--max-pages 3` 安全上限截断，不是完整抓取。B 的深评论只有 1 条回复，所以 B 证明“定向请求”成立，不证明“深线程翻页”成立；深线程翻页由 C 的 cursor 变体证明了一部分。

**签名边界（Round 001 已确认）：** B/C 都在抖音页面上下文里执行；Round 001 证明页面确实重写了 `window.fetch` / `XMLHttpRequest.open`，在请求前自动补 `a_bogus`/`msToken`/`verifyFp`/`fp` 和 `bd-ticket-guard-*`。同源无 app JS 页面和 `context.request` 都是 **200 + 0 字节**。因此：

| 项 | 判定 |
|---|---|
| Windows worker 可行 | **GO** |
| 线程级 / `comment_id` 级定向（page-context fetch） | **GO** |
| 页面 wrapper 自动签名 | **已确认** |
| 免签 HTTP worker（无浏览器） | **NO-GO（已确认）** |
| UI 基线（fallback） | **GO** |

**决策：** 按“真实 Windows Chrome + 完整加载的视频页 + 页面内 `fetch` + `cursor` 翻页”设计线程级 worker；不要写“无浏览器 HTTP 客户端”。

**Round 001 结果（2026-10-30，round `20261030T053205Z-signature-check`）：**

| # | 测试 | 结果 | 证据 |
|---|---|---|---|
| S1 | fetch/XHR 是否 native | **否，均被包裹** | `window.fetch` 含 `ucProxyParam`；`XMLHttpRequest.open` 含 `secureOpenArgs` |
| S2 | 页面内 bare fetch 的实际请求 | **自动签名** | 实际 query 出现 `a_bogus`/`msToken`/`verifyFp`/`fp`；header 出现 `bd-ticket-guard-*`；200 / 2987 bytes |
| S3 | 同源无 app JS 页面 | **0 字节** | `robots.txt` 和 blocked-app 页面都是 native fetch，200 / 0 bytes |
| S4 | `context.request` | **0 字节** | 200 / 0 bytes |
| S5 | 完整线程 / 多线程 | **已完成（Round 002/003）** | 108/113；3 线程同页；短线程 100%；`global_stop=null` |

Round 001 的 `signature_report.md` / `signature_summary.json` 已通过 `result/READY` 和 SHA256 校验；无 cookie/header 值泄漏。

Round 002 的 `full_thread_report.md` / `full_thread_summary.json` 同样通过 `result/READY` 和 SHA256 校验；无 cookie/header 值泄漏。

Round 003 的 `multi_thread_report.md` / `multi_thread_summary.json` 同样通过 `result/READY` 和 SHA256 校验；无 cookie/header 值泄漏。

**Round 002 关键细节：**

- `count=50` 被接受，3 次请求拿到 108 条；比 UI 每页 10 条高效。
- page 1 返回 45 条，但 `cursor=50`；**cursor 按请求 count 前进，不按返回条数**。不要用 `cursor = previous + n`。
- `total=113`，`has_more=false` 时只有 108；缺的 5 条（offset 45–49）是平台缺口（隐藏/删除/过滤），记录为 `coverage=0.9558`，不要无限重跑。
- 单页 fetch 0.01/0.62/0.37 s；命令总耗时 16 s，主要是页面加载/wrapper 等待/页间 sleep。生产应复用页面，按请求/线程做节奏。
- 108/108 有 `ip_label`；21 条 `reply_to_reply_id` 非 0。

**Round 003 关键细节（multi-thread）：**

| thread | expected | unique | coverage | dup | ip_label | rtr | depth3 | orphans | stop | 秒 |
|---|---|---|---|---|---|---|---|---|---|---|
| `7682054941225698091` | 113 | 108 | 0.9558 | 0 | 108 | 21 | 10 | 7 | complete | 6.71 |
| `7682239605306819385` | 3 | 3 | 1.0 | 0 | 3 | 1 | 1 | 0 | complete | 0.31 |
| `7682223064176395049` | 1 | 1 | 1.0 | 0 | 1 | 0 | 0 | 0 | complete | 0.29 |

- 同页复用 3 个线程，不重新导航；`global_stop=null`，无验证码/wrapper 丢失/风控；命令 33 s。
- 大线程仍有 7 条孤儿边（3 个父 id 不在 108 条内）；孤儿不能丢，保留 `thread_root_id`/`reply_to_reply_id`，`depth` 可为 null。
- `creator_label=0`、`label_text=0`、`label_list=0`；**`is_author` 必须用 `user.sec_uid` 比较，不要依赖 label**。
- 短线程 3/1 条均 100%，说明 `count=50`/cursor 在小线程上正常。

**对 worker 的要求：** 打开视频页后先检查 `window.fetch.toString()` 不是 `[native code]`；不是 native 才发请求；用页面内 `fetch`，不用 `context.request`；页面保持加载，wrapper 掉失时等待/重载。同页处理多个线程；用 `count=50`；按响应 `cursor` 翻页；每线程记录 `expected_total`/`unique`/`coverage`/`duplicates`/`orphan_edges`/`depth3`/`stop_reason`；按 `cid` 去重；孤儿保留 raw 边；请求间 1–3 s、线程间 4–7 s 节奏；`is_author` 用 `sec_uid`。完整证据见 [初测分析](spike/resultFromWindows/ANALYSIS.md) §7.1–§7.3。

### 4.9 Worker 原型（Round 004 smoke）

脚本：[spike/windows-reply/reply_worker.py](spike/windows-reply/reply_worker.py)

- 输入：`jobs.json`（1 视频、3 线程；可扩展多视频/多线程）。
- 同页复用：一个视频页处理多个线程；先检查 `window.fetch` wrapper。
- 请求：页面内 `fetch`，`count=50`，按响应 cursor 翻页；不用 `context.request`。
- 落盘：每页 raw；每线程 normalized JSONL；每页 state checkpoint，可 resume。
- 字段：`thread_root_id`、`reply_to_comment_id`、`depth`、`is_orphan`、`ip_province`、`is_author`（sec_uid）、`author_hash`（HMAC，可选 salt）、`label_text(s)`、`raw_sha256`。
- 风控：请求 1.5–3 s、线程 4–7 s；0 字节/验证码/登录/wrapper 丢失立即停。
- 输出：`worker_report.md`、`worker_summary.json`、`normalized_sample.jsonl`（text 截断）；raw/normalized 全量留在本地。
- 自检：`python reply_worker.py --self-test` 已通过（depth 2/3/null、orphan、is_author、author_hash）。
- 状态：Round 004 `20261030T111313Z-worker-smoke` **success**：1 视频/3 线程，fetched/unique 112/112，113 线程 108/113，短线程 100%，`orphan_edges=7`、`depth3=11`，`author_hash_non_null=112`，命令 32 s；raw/normalized/state 本地保留。
- `is_author_true=0`：`jobs.json` 的 `author_sec_uid` 已用 v5 核对为视频作者 `葫芦兄弟和朋友们`；测试视频作者没有在这 112 条回复里出现，所以 0 是预期。若研究需要“一级评论作者是否回复”，另加 `is_thread_author`，不要复用 `is_author`。
- 输入卫生：Round 004 的 `require` 里出现过 Linux 侧 `__pycache__`（复制后在共享目录跑 self-test 导致）；已从源目录删除，后续按 `SHARE_PROTOCOL.md` §13 排除 `__pycache__/`、`*.pyc`、`out/`。

### 4.10 Pilot 回复轮次（Round 005）

- Round id：`20261030T125114Z-pilot-replies`
- 输入：`jobs.pilot.json`，17 jobs（3 深 / 14 浅），804 threads，4,810 expected replies。
- 深抓：每视频所有 `reply_count>0` thread，`max_pages=10`；浅抓：每视频前 10 个 thread，`max_pages=3`。
- 3 个视频没有回复 thread，已跳过。
- salt：Linux `.secrets/dtk-hmac-salt` 不进共享目录；Windows 本地文件通过 `--hash-salt-file` 读取。
- 回传：`worker_report.md`、`worker_summary.json`、`normalized_sample.jsonl`、`normalized/`；不回传 raw/state。
- 结果（2026-10-30）：`status=partial`，数据可用；4,199 unique 回复、0 重复；801/804 线程 `complete`，3 个浅抓线程 `max_pages=3`。
- 覆盖：全部线程 4,199/4,835 = 86.85%；801 个 `complete` 线程 3,751/3,759 = 99.79%；完整线程仅 7 个缺口、合计 10 条。
- 结构：`orphan_edges=43`；`depth is null=72`（43 孤儿 + 29 后代）；最大 depth=14；父子关系 0 矛盾。
- 作者：`is_author=true` 57 条，全部带 `label_text='作者'`；`is_creator_label=true` 57；`is_thread_author` 仍为 null。
- 隐私：`author_hash` 100% 非空；554 个回复作者哈希与一级评论重合，salt 一致；normalized 无昵称/UID/cookie/header。
- **风控：用户手动通过 2 次人机验证**；worker 未记录 `risk_control`/0 字节，未发现数据损失；生产需验证码检测/暂停/人工值守。
- 入库：`comment=27,211`（23,012 top_level + 4,199 reply）、`quality_metric=841`、`worker_job=17`；回复 raw/state 留在 Windows 本地。

### 4.11 `wrapper_not_ready` 的代码处理（2026-11-04 修复）

之前：`wrapper_ready(page, timeout_s=30)` 等 30 秒；仍是 native 就 `global_stop` 并 `break`，一个视频会中断整个 batch。多账号 round 就因此在 `7241526932624477477` 停掉，剩余 51 threads 未跑。

现在 `reply_worker.py` 增加：

- `--wrapper-timeout`：单次等待秒数，默认 45；
- `--wrapper-retries`：最多尝试次数，默认 2（首次 + 1 次重开页面）；
- `--wrapper-policy skip|stop`：默认 `skip`；
- `ensure_wrapper()`：失败后关闭页面、重新 `open_video`、再次检查；
- `job_failures`：写进 `worker_summary.json` 和 `worker_report.md`，列出失败视频、thread 数、reload 次数；
- `skip` 模式下单个视频失败不再中断后续 jobs，最终 status 为 `partial`；Linux 只需为 `job_failures` 中的视频补采。

mock 测试已验证：首次 native → 重开页面 → ready；`retries=1` 时不会重开。  
注意：这只能提高恢复能力，不能保证抖音页面一定安装 wrapper；如果仍失败，保留 `blocked/partial` 并人工预检。

---

## 5. 对现有文档的影响

| 文档 | 变更 |
|---|---|
| [DESIGN.md](DESIGN.md) | v5 不再是“唯一与抖音通信的组件”；回复可由 Windows worker 采集；Stage 5 增加实现路径 B |
| [ROADMAP.md](ROADMAP.md) | 增加 Phase 0.5（Windows worker 实验）和 Gate W |
| [FEASIBILITY.md](FEASIBILITY.md) | 更新回复方案状态；链接本文 |
| [CHROME_SPIKE.md](CHROME_SPIKE.md) | 保留服务器失败结论；增加 Windows 先验证据链接 |

---

## 6. 参考

- anotherImplement 采集适配器：`anotherImplement/commentCapture-win/v1/tool1-collect/smfetch/adapters/douyin.py`
- anotherImplement 数据模型：`anotherImplement/commentCapture-win/v1/tool1-collect/smfetch/schema.py`
- anotherImplement 风控：`anotherImplement/commentCapture-win/v1/tool1-collect/smfetch/risk.py`
- anotherImplement handle 解析：`anotherImplement/commentCapture-win/v1/tool2-search/smsearch/search.py`
- anotherImplement 覆盖率结论：`anotherImplement/commentCapture-win/v1/tool1-collect/DESIGN.md`
- 服务器 Chrome spike：[CHROME_SPIKE.md](CHROME_SPIKE.md)
- v5 回复端点失败记录：[FEASIBILITY.md](FEASIBILITY.md) §3.4
