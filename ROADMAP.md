# 抖音数据采集 — 实施路线图（Roadmap）

> 日期：2026-10-29
> 状态：Phase 0 完成；Phase 0.5 + Round 001/002/003/004 完成；**page-context 线程级可行，`count=50` 可用，同页 3 线程，worker 原型端到端通过（112/112 normalized）**；下一步生产集成/pilot（中文 locale 复测可选）
> 关联：[DESIGN.md](DESIGN.md)（高层设计）、[HANDOFF.md](HANDOFF.md)（背景与决策）、[GLOSSARY.md](GLOSSARY.md)（术语表）、[WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)（回复 worker 评审与实验）
> 本地 v5：`Douyin_TikTok_Download_API/`，v5.1.7（`main` `3d540db`）

---

## 0. 一句话结论

**先做 Phase 0 可行性实验，再做 Phase 0.5 Windows 回复 worker 实验，再做 Phase 1 Pilot，再写 Phase 2 正式 LLD，最后 Phase 3 规模化实现。**

```text
idea.md + HANDOFF.md
        ↓
DESIGN.md（HLD，已完成）
        ↓
ROADMAP.md（本文件）
        ↓
Phase 0  可行性实验（2–4 天，手工探测；已完成大部分）
        ↓ Gate 0
Phase 0.5 Windows 回复 worker 实验（0.5–1 天）
        ↓ Gate W
Phase 1  Pilot（先写 1 页 pilot spec，再跑 1 个账号，1–2 周）
        ↓ Gate 1
Phase 2  正式 LLD（3–5 天，基于 pilot 数据）
        ↓ Gate 2
Phase 3  规模化实现（1 → 10 → 50 个账号，2–6 周）
```

---

## 1. 为什么是这个顺序

### 为什么不先写正式 LLD

现在缺的不是设计，而是**事实**：

- `ip_label`、`reply_to_reply_id` 是否真的存在？仓库里的 fixture 是手写的，不能证明。
- 评论到底能翻多少页？有没有隐藏上限？
- 回复翻页到底有多慢？会不会一抓就风控？
- 登录 cookie 能否稳定翻视频列表？游客评论是否稳定？
- 单视频真实耗时、失败率、冷却频率是多少？

这些答案会直接改变 LLD 里的表结构、解析器、重试策略和回复范围。先写 LLD 等于把猜测固化成代码，返工成本更高。

### 为什么不直接上 Pilot

Pilot 是端到端薄切片，需要配置、数据库、导出，成本比手工探测高一个量级。如果连字段是否存在、评论能不能翻页都没确认，pilot 可能白跑。

### 为什么加 Phase 0

Phase 0 用 curl / 几十行脚本，只回答是非题，不追求工程化。它的成本是 2–4 天，但能把 pilot 的范围和 LLD 的内容钉在真实数据上。

### 为什么加 Phase 0.5

Phase 0 已经确认服务器浏览器路径不可行；anotherImplement 又证明 Windows 桌面路径可行。Phase 0.5 只回答一个问题：**Windows worker 能否按 `comment_id` 定向，以及成本多少。** 它决定 pilot 的回复范围和作业粒度。

### Pilot 代码的定位

**Pilot 代码是 spike，不是最终架构。** 可以用脚本、单文件、草表结构；目的是验证字段、翻页、耗时、风控。Pilot 结束后，LLD 再决定正式模块划分；pilot 代码可以重写，但**真实脱敏 fixture、耗时数据、风控记录必须保留**。

---

## 2. 当前状态与前置条件

### 已完成

- [x] 需求与背景：[idea.md](idea.md)、[HANDOFF.md](HANDOFF.md)
- [x] v5 调研与高层设计：[DESIGN.md](DESIGN.md)
- [x] 术语表：[GLOSSARY.md](GLOSSARY.md)
- [x] v5 源码克隆到 `Douyin_TikTok_Download_API/`（v5.1.7）
- [x] 风控机制调研（分类、冷却、熔断、限速）
- [x] v5 核心栈部署（Docker Compose，5.1.7 发布镜像）
- [x] 登录身份导入（rotation 限制为 `douyin.author_posts`）
- [x] 游客身份（browser-rpc）mint
- [x] 测试账号与测试视频确定（绍兴文旅；视频 `7681929945538497843`）
- [x] 一级评论字段与翻页测量（`ip_label`/`reply_to_reply_id` 真实存在；464/557，83.3%）
- [x] 服务器浏览器 spike（结论：Xvfb/SwiftShader 环境被 reply 端点阻断；见 [CHROME_SPIKE.md](CHROME_SPIKE.md)）
- [x] anotherImplement 评审（Windows 桌面路径可行；见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)）
- [x] Phase 0.5 初测：A/B/C PASS（Windows 真实 Chrome，page-context 线程级可行）；见 [初测分析](spike/resultFromWindows/ANALYSIS.md)
- [x] Round 001 签名检查：页面 wrapper 自动签名；同源无 app JS / `context.request` 均 200 + 0 字节；免签 HTTP worker 否定
- [x] Round 002 完整线程 + `count=50`：3 页 45/50/13，unique 108/113，coverage 95.58%，0 重复；缺 5 条为平台缺口
- [x] Round 003 多线程 + page reuse：3 线程同页；113 线程 108/113、orphans 7、depth3 10；短线程 100%；`global_stop=null`
- [x] depth≥3：Round 003 确认 10 条可还原 depth≥3；孤儿 7 条边
- [x] `label_list`/`label_text`：本轮回复均为 0；`is_author` 必须用 `sec_uid`，不能依赖 label
- [x] Round 004 worker 原型 smoke：1 视频/3 线程，112/112 normalized，113 线程 108/113，短线程 100%，`status=success`；`is_author=0` 为测试视频作者未回复

### 尚未完成

- [ ] 中文 locale / 真实桌面（非 RDP）复测（可选）
- [ ] 生产集成：job queue、normalized → 研究库/隐私转换、真实目标账号验证 `is_author` 非 0、可选 `is_thread_author`
- [ ] 回复方案最终参数（线程截断/页数/速率）
- [ ] Pilot（Stage 1–6 完成：765 视频 / 730 target；20 个已选；23,012 一级评论；804 threads / 17 jobs；4,199 回复；完整线程 coverage 99.79%；Parquet/CSV/manifest 已导出）
- [ ] 正式 LLD
- [ ] 生产实现

### 当前阻塞项（需要你提供）

| 阻塞项 | 需要什么 | 用途 |
|---|---|---|
| Windows 测试机 | 已提供（RDP 初测）；补测可复用 | Phase 0.5 初测已完成 |
| Windows 专用账号 | 已提供（专用 profile + 人工扫码） | 初测已完成 |
| 深线程评论 | 已提供（`7682223064176395049`） | comment_id 级定向已验证 |
| 中文 locale / 真实桌面 | 一台中文 Windows 真实桌面（非 RDP），用于生产前复测 | 指纹/locale 差异验证 |
| 伦理审查 | IRB/伦理委员会的状态 | 数据保留、字段最小化、发表限制 |

---

# Phase 0：可行性实验（2–4 天）

## 3.1 目标

用最小成本回答 13 个问题，产出一份 `FEASIBILITY.md`。

**不写正式代码，不建正式表，不做导出。** 手工探测 + 记录。

## 3.2 前置条件

### 3.2.1 部署 v5 核心栈

```bash
cd /home/vdmc34/my/douyin/Douyin_TikTok_Download_API
cp .env.example .env
# 至少设置：
#   DTK_SECRET_KEY=<32+ 随机字符>
#   POSTGRES_PASSWORD=<强密码>
#   REDIS_PASSWORD=<强密码>
docker compose -p dtk -f docker/compose.yml up -d
docker compose -p dtk -f docker/compose.yml logs api | tail -50
```

首次启动后，用 setup token 创建管理员，然后创建 API key。

### 3.2.2 设置环境变量

```bash
export DTK_BASE="http://127.0.0.1:8000"
export DTK_API_KEY="dtk_..."
export SEC_UID="MS4wLjABAAAA..."
export AWEME_ID="7123456789012345678"
export COMMENT_ID="7000000000000001001"
export LOGIN_ID="<导入后的 identity uuid>"
```

### 3.2.3 验证实例

```bash
curl -s "$DTK_BASE/healthz"
curl -s -H "Authorization: Bearer $DTK_API_KEY" "$DTK_BASE/api/v1/system/status" | jq
```

## 3.3 实验清单

| # | 问题 | 动作 | 通过标准 |
|---|---|---|---|
| 1 | v5 能启动、身份能导入 | 导入登录 cookie（先 `dry_run`）；`GET /api/v1/admin/identities?platform=douyin` | `state=active`，`authenticated=true`，有 `expires_at` |
| 2 | 登录身份能翻视频列表 | 视频列表第 1 页 + 第 2 页 | 第 2 页有数据；`meta.guest_fallback` 不为 true |
| 3 | 游客能抓评论 | 导入 1 个游客 cookie 或 mint 1 个游客；抓 1 页评论 | 200 + items；`has_more` 正常 |
| 4 | raw 有 `ip_label` | 评论请求 `include_raw=true`，检查一条 | 字段存在；记录路径与空值率 |
| 5 | raw 有 `reply_to_reply_id` | 同上，找一条回复 | 字段存在；能指出直接父评论 |
| 6 | 评论能翻多少页 | 100+ 评论视频，循环 cursor 到底 | 记录页数、条数、`has_more` 行为 |
| 7 | 回复能翻多少页 | 20+ 回复的评论，循环 cursor 到底 | 记录页数、条数 |
| 8 | 回复树能否还原 | 对比同一 thread 的 `reply_to_reply_id` | 至少找到一条 depth=3 的边 |
| 9 | `is_author` 能否派生 | 找作者回复，比较 `sec_uid` 与 `label_list` 的 Creator | 两者一致 |
| 10 | 风控阈值 | 用 1 个游客连续抓 50 页评论 | 记录第几页开始冷却、冷却多久 |
| 11 | 单视频耗时 | 给第 6/7 步计时 | 得到“每视频分钟数”基线 |
| 12 | cookie 有效期 | 读 `sid_guard` / `expires_at` | 知道多久需要重导 |
| 13 | handle 能否解析 | 试一个裸抖音号 | 确认失败；决定是否人工整理 |

## 3.4 命令模板

> 说明：v5 的数据端点默认可能返回 `202 + task_id`。加 `?wait=30` 会最多等 30 秒；若仍返回 202，轮询 `GET /api/v1/tasks/{task_id}`，结果在 `data.data`（注意是两层 `data`）。

### 3.4.1 导入登录 cookie

先写一个不提交到 git 的 `import-login.json`：

```json
{
  "platform": "douyin",
  "cookies": "ttwid=...; sessionid=...; sid_guard=...; odin_tt=...",
  "user_agent": "Mozilla/5.0 (...) ...",
  "language": "zh-CN",
  "timezone": "Asia/Shanghai",
  "note": "phase0 author-feed login",
  "dry_run": true
}
```

先 dry run：

```bash
curl -s -X POST "$DTK_BASE/api/v1/admin/identities/import" \
  -H "Authorization: Bearer $DTK_API_KEY" \
  -H "Content-Type: application/json" \
  -d @import-login.json | jq
```

确认无误后，把 `dry_run` 改成 `false`，再执行一次。记下返回的 identity id。

### 3.4.2 查看身份与池子

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/admin/identities?platform=douyin" | jq

curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/admin/identities/pool" | jq

curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/admin/identities/coverage" | jq
```

检查：`state`、`authenticated`、`expires_at`、`consecutive_fails`、`cooldown_until`、`health`。

### 3.4.3 检查登录是否仍有效

```bash
curl -s -X POST "$DTK_BASE/api/v1/admin/identities/$LOGIN_ID/session" \
  -H "Authorization: Bearer $DTK_API_KEY" | jq
# 返回 202 + task_id
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/tasks/<task_id>" | jq
```

### 3.4.4 单身份真实请求测试

```bash
curl -s -X POST "$DTK_BASE/api/v1/admin/identities/$LOGIN_ID/test" \
  -H "Authorization: Bearer $DTK_API_KEY" | jq
# 同样返回 202 + task_id，轮询任务结果
```

### 3.4.5 账号资料

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/user?sec_user_id=$SEC_UID&wait=30" | jq
```

### 3.4.6 视频列表第 1 页

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/user/posts?sec_user_id=$SEC_UID&count=20&wait=30" \
  | jq '{has_more: .data.has_more, cursor: .data.cursor, n: (.data.items|length), guest_fallback: .meta.guest_fallback}'
```

### 3.4.7 视频列表第 2 页（登录身份的关键验证）

```bash
CURSOR=$(curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/user/posts?sec_user_id=$SEC_UID&count=20&wait=30" \
  | jq -r '.data.cursor')

curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/user/posts?sec_user_id=$SEC_UID&count=20&cursor=$CURSOR&wait=30" \
  | jq '{has_more: .data.has_more, cursor: .data.cursor, n: (.data.items|length), error: .error}'
```

**通过标准：** 第 2 页 `items` 非空；`error` 不是 `IDENTITY_LOGIN_REQUIRED`。

### 3.4.8 一级评论第 1 页 + raw 字段检查

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/video/comments?aweme_id=$AWEME_ID&count=50&include_raw=true&wait=30" \
  | jq '{n: (.data.items|length), has_more: .data.has_more, cursor: .data.cursor}'

curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/video/comments?aweme_id=$AWEME_ID&count=50&include_raw=true&wait=30" \
  | jq '.data.items[0].raw | {cid, aweme_id, reply_id, reply_to_reply_id, ip_label, label_list, reply_comment_total, is_author_digged, stick_position}'
```

**通过标准：** `ip_label` 和 `reply_to_reply_id` 存在（不是 `null`）；记录空值率。

### 3.4.9 回复第 1 页 + raw 字段检查

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/video/comments/replies?comment_id=$COMMENT_ID&aweme_id=$AWEME_ID&count=50&include_raw=true&wait=30" \
  | jq '{n: (.data.items|length), has_more: .data.has_more, cursor: .data.cursor}'

curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/douyin/video/comments/replies?comment_id=$COMMENT_ID&aweme_id=$AWEME_ID&count=50&include_raw=true&wait=30" \
  | jq '[.data.items[].raw | {cid, reply_id, reply_to_reply_id, ip_label}]'
```

### 3.4.10 评论翻页循环（测页数与耗时）

```bash
CURSOR=""
PAGES=0
TOTAL=0
while :; do
  URL="$DTK_BASE/api/v1/douyin/video/comments?aweme_id=$AWEME_ID&count=50&include_raw=true&wait=30"
  if [ -n "$CURSOR" ]; then URL="$URL&cursor=$CURSOR"; fi
  RESP=$(curl -s -H "Authorization: Bearer $DTK_API_KEY" "$URL")
  N=$(echo "$RESP" | jq -r '.data.items | length // 0')
  HAS_MORE=$(echo "$RESP" | jq -r '.data.has_more // false')
  CURSOR=$(echo "$RESP" | jq -r '.data.cursor // empty')
  echo "page=$((PAGES+1)) items=$N has_more=$HAS_MORE cursor=$CURSOR"
  PAGES=$((PAGES+1)); TOTAL=$((TOTAL+N))
  [ "$HAS_MORE" = "true" ] && [ -n "$CURSOR" ] || break
done
echo "pages=$PAGES total=$TOTAL"
```

对回复接口做同样的循环，把 URL 换成 `/video/comments/replies?comment_id=...&aweme_id=...`。

### 3.4.11 风控观察

每抓一段，检查：

```bash
curl -s -H "Authorization: Bearer $DTK_API_KEY" \
  "$DTK_BASE/api/v1/admin/identities?platform=douyin" \
  | jq '[.[] | {id, state, consecutive_fails, cooldown_until, health}]'
```

记录：第几页开始出现 `cooling`、冷却多久、哪个身份先触发。

## 3.5 产出：`FEASIBILITY.md`

建议结构：

```markdown
# Phase 0 可行性实验报告

## 环境
- v5 版本/commit、OS、CPU/内存、身份数量

## 结论表
| # | 问题 | 结果 | 证据 |
|---|---|---|---|
| 1 | 登录身份可用 | pass/fail | ... |
...

## 真实 raw 样本（脱敏）
一段评论 JSON，证明字段存在

## 翻页测量
- 评论：页数、总条数、has_more 行为
- 回复：页数、总条数

## 耗时
- 单视频评论抓取：X 分钟
- 单 thread 回复抓取：X 分钟

## 风控
- 触发页数、冷却时长、涉及身份

## 对 DESIGN.md 的修正
- 哪些假设被推翻/确认

## 决策
- 是否进入 pilot；需要调整什么
```

## 3.6 Gate 0：Phase 0 是否通过

| 条件 | 结果 |
|---|---|
| 1–4 全部通过 | 可以进入 pilot |
| 5–8 通过 | 可以进入 pilot（回复树方案可行） |
| 9–10 显示风控严重或耗时不可接受 | 先调整回复范围/身份数量，再 pilot |
| `ip_label` 或 `reply_to_reply_id` 不存在 | 隐私/评论树方案要改；考虑 patch v5 或商业工具对照 |
| 登录身份无法翻第 2 页 | 停止；检查 cookie/身份，不要进入 pilot |

---

# Phase 0.5：Windows 回复 Worker 可行性实验（0.5–1 天）

> 详细方案、指标和安全要求见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)。

## 3.7 目标

用一台真实 Windows 桌面机回答：

1. Windows 真实 Chrome 能否稳定拿到 reply 响应？（A）
2. 能否不滚动到评论、直接按 `comment_id` 请求回复？（B/C/D）
3. reply 请求的页大小、请求头、响应结构是什么？
4. 单线程/单视频的耗时和风险信号是什么？

## 3.8 测试矩阵

| # | 方法 | 目标 | 证明什么 |
|---|---|---|---|
| A | UI 点击 + 监听 response | 可见线程，翻到 `has_more=false` | 基线：Windows 能拿到回复 |
| B | 页面内 bare `fetch` | 首屏不可见的 `comment_id` | 页面 fetch 是否自动带签名 |
| C | 重放真实签名 URL | 改 `cursor`/`comment_id` | 签名是否绑定参数 |
| D | 页面 SDK 签名/内部 API | 不可见 `comment_id` | 能否做 comment_id 级定向 |
| E | 可选：`count=50` | 同线程 | 是否能减少页数 |
| F | 可选：DOM 检查 | 目标评论元素 | 是否有 `data-*` 暴露 cid |

## 3.9 通过标准与 Gate W

| 结果 | 决策 |
|---|---|
| A 通过（20+ 回复线程，`has_more=false`，字段完整） | Windows worker 可行；进入视频级设计 |
| B/C/D 通过（不可见评论也能拿到回复） | 可做线程级/comment_id 级；优先线程级 |
| 只有 A 通过 | 视频级 worker；按视频批量、只展开目标线程 |
| A 也失败 | 停浏览器路线；商业工具或一级评论 |

**额外门槛：** 单视频 >15 分钟，或 10 个线程就触发风控 → 先调整范围/节奏，不要直接进 pilot。

## 3.10 初测 + Round 001 结果（2026-10-29 / 2026-10-30）

执行：Windows 10 LTSC 2021，RDP，无 GPU；Chrome 156，专用 profile + 人工扫码；Python 3.13 / Playwright 1.64；locale `en-US`。详见 [初测分析](spike/resultFromWindows/ANALYSIS.md)。

| 测试 | 结果 | 关键数据 |
|---|---|---|
| A UI 点击 | PASS（基线） | 3 页 `n=2/7/10`，`cursor=3→13→23`，`has_more=1`，`total=113`，6.7 s；`stop_reason=max_pages`（只抓 19/113） |
| B 页面内 bare fetch | PASS | 深评论 200，2987 bytes，1 条回复 |
| C 改参重放 | PASS | unchanged / cursor / comment_id 均 200；cursor 23→33 |
| D globals | 信息项 | `byted_acrawler` 存在 |

**Gate W 判定：**

| 项 | 判定 |
|---|---|
| Windows worker 可行 | **GO** |
| 线程级 / `comment_id` 级定向（page-context fetch） | **GO** |
| 页面 wrapper 自动签名 | **已确认（Round 001）** |
| 免签 HTTP worker（无浏览器） | **NO-GO（已确认）** |
| UI 基线 | **GO（fallback）** |

**Round 001 结果：** S1 确认 `window.fetch` / `XMLHttpRequest.open` 都被页面重写；S2 实际请求自动出现 `a_bogus`/`msToken`/`verifyFp`/`fp` 和 `bd-ticket-guard-*`，200 / 2987 bytes；S3 同源无 app JS 页面、S4 `context.request` 都是 200 + 0 字节。**结论：reply 端点依赖页面 wrapper，生产必须保留完整加载的页面 + 页面内 `fetch`。** 详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8、[初测分析](spike/resultFromWindows/ANALYSIS.md) §7.1。

**Round 002 结果（full-thread）：** `count=50` 被接受；3 页 45/50/13；unique 108/113；coverage 95.58%；0 重复；`stop_reason=complete`；`ip_label` 108/108；`reply_to_reply_id` 非 0 21；单页 fetch 0.01/0.62/0.37 s，命令总耗时 16 s。page 1 返回 45 但 cursor=50，**cursor 按请求 count 前进，不按返回条数**；缺 5 条是平台缺口。详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8、[初测分析](spike/resultFromWindows/ANALYSIS.md) §7.2。

**Round 003 结果（multi-thread）：** 同一视频页复用 3 个线程；113 线程 108/113（95.58%）、orphans 7、depth3 10；3 条和 1 条线程均 100%；`global_stop=null`；命令 33 s；`creator_label`/`label_text`/`label_list` 均为 0，`is_author` 必须用 `sec_uid`。详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8、[初测分析](spike/resultFromWindows/ANALYSIS.md) §7.3。

**Round 004 结果（worker smoke）：** 1 视频/3 线程；fetched/unique 112/112；113 线程 108/113；短线程 100%；orphans 7、depth3 11；`author_hash_non_null=112`；`is_author=0`（测试视频作者未回复，sec_uid 已核对）；命令 32 s。worker 原型端到端通过。详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.9、[初测分析](spike/resultFromWindows/ANALYSIS.md) §7.4。

---

# Phase 1：Pilot（1–2 周）

## 4.1 Pilot spec（先写 1–2 页）

> 完整规格：[PILOT_SPEC.md](PILOT_SPEC.md)（绍兴文旅；20 视频；3 深 + 17 浅；Postgres + Parquet + CSV 样本；pilot 尽量多存）。

在写 pilot 代码之前，先确定：

- 跑哪个账号（1 个，20+ 视频）；
- 跑哪条视频（1 条，100+ 一级评论）；
- 跑哪个 thread（1 条，20+ 回复）；
- 抓多少：一级评论全量；回复按 thread 截断（Phase 0 决定上限）；
- 存在哪：研究库草表（可以先不建正式迁移）；
- 导出什么：Parquet/CSV + 质量报告；
- 验收标准：见 §4.5。

## 4.2 Pilot 范围

- 1 个账号，20+ 视频；
- 视频列表完整翻页；
- 本地过滤：时长、点赞、发布时间、评论数；
- 1 条 100+ 评论的视频：一级评论全量；
- 1 条 20+ 回复的评论：回复全量或截断（记录）；
- 评论/回复请求 `include_raw=true`；
- 提取 `ip_label`、`reply_to_reply_id`、`label_list`；
- 派生 `is_author`、`ip_province`、`depth`、`reply_to_comment_id`；
- 评论者 `sec_uid` HMAC 哈希后入库；
- 写研究库草表；
- 导出 Parquet/CSV + `quality_report.json`。

## 4.3 Pilot 薄切片模块

Pilot 可以用简单脚本，但建议按这 8 个职责分文件，方便 LLD 重写：

1. `config`：读 accounts/filters/runtime；
2. `dtk_client`：REST 封装、`wait`/轮询、错误分类；
3. `paginator`：cursor 循环、去重、断点状态；
4. `extractor`：raw → 字段（`ip_label`、`reply_to_reply_id`、`label_list`）；
5. `privacy`：HMAC、`raw_min`、`raw_sha256`；
6. `store`：Postgres 草表 upsert；
7. `export`：Parquet/CSV + manifest；
8. `report`：质量指标（覆盖、重复、孤儿、风控）。

## 4.4 Pilot 产出

- 一份 `PILOT.md`：数据质量、覆盖率、耗时、风控、问题清单；
- 一套**真实脱敏 fixture**（评论/回复 raw 样本），供 LLD 的测试使用；
- 一份草版研究库数据（可丢弃）；
- 对 DESIGN.md 的修正。
## 4.5 Pilot 验收标准

沿用 [HANDOFF.md](HANDOFF.md) §10 + [DESIGN.md](DESIGN.md) §11：

- [ ] 视频列表完整翻页，数量与页面一致（记录差值）。
- [ ] 视频字段含时长、点赞、评论、转发、收藏、发布时间。
- [ ] 一级评论能翻页超过 100 条。
- [ ] 回复能翻页超过 20 条。
- [ ] 评论字段含 `comment_id`、`parent_id`、点赞数、发布时间、作者身份。
- [ ] `ip_label`、`reply_to_reply_id` 能从 raw 取出（或确认不存在）。
- [ ] `is_author` 能派生。
- [ ] `reply_to_comment_id`/`depth` 能把“回复的回复”还原到 depth ≥ 3。
- [ ] 导出 Parquet/CSV，字段完整、编码正常。
- [ ] 记录单视频耗时、请求失败率、风控/冷却次数。
- [ ] 记录评论抓取数与页面显示数的差距。
- [ ] 评论者原始 UID/昵称/头像/签名不在研究库中。

## 4.6 Gate 1：是否进入 LLD

- 验收标准全部通过或缺口可接受 → 进入 LLD。
- 覆盖率过低、风控过重、耗时不可接受 → 先调整范围（采样、回复截断、更多身份），再决定是否继续。
- 字段缺失 → 重新评估方案（patch v5 / 商业工具 / 缩小研究问题）。

---

# Phase 2：正式 LLD（3–5 天）

Pilot 数据出来后再写 `LLD.md`，内容包括：

| LLD 内容 | 依赖的 pilot 结果 |
|---|---|
| 数据库 DDL / 迁移 / 索引 | 实际评论量、字段类型、raw 存储大小 |
| API 客户端状态机 | 实际错误码、重试行为、翻页上限 |
| raw → 字段提取规则 | 真实 raw 字段路径、空值率 |
| 隐私转换与 `raw_min` schema | `ip_label` 是否存在、PII 分布 |
| 回复树重建算法 | `reply_to_reply_id` 的实际行为 |
| 导出 schema / 数据字典 | 实际字段和缺失情况 |
| 并发与限速预算 | 实测每页耗时、风控阈值 |
| 测试计划 | 真实脱敏 fixture |
| 运维手册 | cookie 到期、身份冷却、恢复流程 |
| 备份/保留策略 | 实际数据量与 IRB 要求 |

**LLD 的交付物是文档，不是代码。** 代码在 Phase 3 写。

## 5.1 LLD 必须回答的问题

1. 研究库的最终表结构、主键、索引、快照策略；
2. 评论/回复的抓取状态机（cursor、重试、断点、去重）；
3. `raw_min` 的最终字段集和脱敏规则；
4. `is_author`、`ip_province`、`depth`、`reply_to_comment_id` 的最终算法；
5. 导出文件的 schema、manifest、数据字典；
6. 并发/限速/退避参数；
7. 测试策略（真实 fixture + mock v5 + 集成测试）；
8. 运维流程（cookie 导入/刷新、身份轮换、监控、备份、删除）。

---

# Phase 3：规模化实现（2–6 周）

## 6.1 生产实现

- 按 LLD 实现模块；
- 单元测试 + 集成测试（mock v5）+ replay 测试（真实 fixture）；
- 幂等 upsert、断点续爬、失败重试；
- 日志、指标、告警。

## 6.2 5–10 个账号（校准）

- 2 个登录身份（`author_posts`）+ 3–5 个游客（评论/回复）；
- 每个身份独立代理；
- 校准时间预算、风控频率、回复覆盖率；
- 调整 `max_threads_per_video` / `max_pages_per_comment`。

## 6.3 10–50 个账号（规模化）

- 身份/代理矩阵；
- 分账号串行、低并发；
- 回复补抓（单独运行，慢慢补齐）；
- 监控：身份池、冷却、队列、失败率；
- 备份、保留策略、删除流程；
- 可选：视频下载、ASR、画面分析。

## 6.4 扩展其他平台（以后）

- 小红书、B站、微博：v5 支持 B站/TikTok；其他平台需要另做评估，不在本路线图范围。

---

# 7. 时间线（粗略）

| 阶段 | 时间 | 主要风险 |
|---|---|---|
| Phase 0 可行性 | 2–4 天（已完成大部分） | cookie 获取、browser-rpc 构建 |
| Phase 0.5 Windows worker | 完成（初测/签名/完整线程/多线程/worker smoke） | 生产集成/pilot；中文 locale 可选 |
| Phase 1 Pilot | 1–2 周 | 风控、回复耗时 |
| Phase 2 LLD | 3–5 天 | pilot 数据不足 |
| Phase 3 实现 | 2–6 周 | 规模化风控、数据量 |

> 这些是量级估计，不是承诺；实际取决于 Phase 0 的风控和耗时结果。

---

# 8. 角色分工

| 任务 | 你 | Claude |
|---|---|---|
| 提供 Windows 测试机 + 专用账号 + profile | ✅ | — |
| 提供首屏不可见评论的 `comment_id` | ✅ | 可从 v5 评论第 5 页取 |
| Windows 实验脚本 | 运行 | ✅ 编写、分析 |
| v5 核心栈部署 / Phase 0 探测 | 已完成 | — |
| `FEASIBILITY.md` | 审阅 | ✅ 撰写 |
| `WINDOWS_REPLY_WORKER.md` | 审阅 | ✅ 撰写 |
| Pilot spec | 确认范围 | ✅ 撰写 |
| Pilot 代码 | 审阅 | ✅ 实现 |
| `PILOT.md` | 审阅 | ✅ 撰写 |
| `LLD.md` | 审阅/确认 | ✅ 撰写 |
| 生产实现 | 验收 | ✅ 实现 |
| IRB/伦理 | ✅ | 提供材料清单 |

---

# 9. 风险与应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| `ip_label` / `reply_to_reply_id` 在真实响应中不存在 | 中 | 高 | Phase 0 先验证；不存在则改隐私/评论树方案 |
| 登录 cookie 无法翻第 2 页 | 中 | 高 | 检查 cookie 完整性、UA、ttwid；换账号 |
| 风控触发过快 | 中 | 高 | 多游客身份、代理、降低速率、回复截断 |
| Windows worker 被 reply 端点/风控收紧 | 中 | 高 | page-context 初测通过；保留 UI fallback；补充 S1–S5；低频 |
| 页面 wrapper / DOM 改版导致 fetch 失效 | 中 | 高 | 每版本回归；保留 A 基线；监控空 body |
| Windows worker 吞吐不足 | 高 | 中 | 多 profile/多机；抽样；线程/页数截断 |
| Windows 测试机不能常开 | 中 | 高 | 专用小主机；任务队列断点；失败重试 |
| 回复抓取耗时不可接受 | 高 | 中 | `max_threads_per_video` 截断；分批补抓 |
| 评论覆盖率低 | 中 | 中 | 记录 gap；二次扫描；调整研究设计 |
| cookie 过期 | 高 | 中 | 记录 `sid_guard`；提前 3 天告警；定期重导 |
| v5 升级导致行为变化 | 低 | 中 | 固定 tag/commit；升级前跑回归 |
| IRB 要求限制字段/保留期 | 中 | 高 | 尽早启动审查；数据最小化；可配置保留期 |
| pilot 代码变成“事实架构” | 中 | 中 | 明确 pilot 是 spike；LLD 重写模块划分 |

---

# 10. 下一步（现在就能做）

## 需要你提供

1. **Windows 测试机**：Windows 10/11，真实 GPU/显示器，Chrome，Python 3.10+ + Playwright；国内直连抖音。
2. **Windows 专用抖音账号**：独立账号 + 独立 Chrome profile；不要用主账号。
3. **一条首屏不可见的评论**：`comment_id` 可从 v5 评论第 5 页取；用来测试 comment_id 级定向。
4. **伦理审查状态**：IRB/伦理委员会进度；决定数据保留与字段范围。

## Claude 可以立即做

1. 编写 Windows 实验脚本（`spike/windows-reply/`）；
2. 准备 A/B/C/D 测试矩阵与记录模板；
3. 实验完成后更新 `WINDOWS_REPLY_WORKER.md`、`FEASIBILITY.md`、`DESIGN.md`；
4. 根据 Gate W 结果决定视频级/线程级 worker 设计。

---

# 11. 参考

- 高层设计：[DESIGN.md](DESIGN.md)
- 背景与决策：[HANDOFF.md](HANDOFF.md)
- 术语表：[GLOSSARY.md](GLOSSARY.md)
- 回复 worker 评审与实验：[WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)
- v5 源码：`Douyin_TikTok_Download_API/`
- v5 API 文档：`Douyin_TikTok_Download_API/documents/en/11-api.md`
- v5 身份/代理：`Douyin_TikTok_Download_API/documents/en/06-identities-and-proxies.md`
- v5 部署：`Douyin_TikTok_Download_API/documents/en/02-installation.md`

---

## 文档状态

- 版本：v7（2026-10-30）
- 下一步：生产集成（job queue、normalized → 研究库/隐私转换、真实目标账号 `is_author` 非 0、可选 `is_thread_author`）→ pilot；中文 locale 复测可选。
- 本文件是执行计划，不是 LLD；LLD 在 Phase 2 单独写。
