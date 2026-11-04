# Phase 0 可行性实验报告

> 日期：2026-10-28（2026-10-30 更新）
> 状态：**Phase 0 评论字段/翻页已验证**；服务器浏览器路径失败；**Phase 0.5 + Round 001/002/003/004 通过**：页面 wrapper 自动签名，page-context 必需；`count=50` 可用；同页 3 线程；worker 原型端到端通过（112/112 normalized）；113 线程 108/113（95.58%），短线程 100%。见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)、[初测分析](spike/resultFromWindows/ANALYSIS.md)
> 环境：Ubuntu 24.04 / 32 CPU / 15 GiB RAM / 217 GB 可用磁盘 / Docker 29.2.1 / Compose v5.0.2
> v5：Docker 镜像 `evil0ctal/douyin_tiktok_download_api:5.1.7`（发布镜像），Postgres/TimescaleDB pg17 + Redis 8
> 回复方案：v5 负责视频/一级评论；Windows worker 用页面内 `fetch` + `count=50` 只补回复；不写无浏览器 HTTP worker。

---

## 1. 环境与网络

| 项目 | 结果 |
|---|---|
| 核心栈 | `postgres`、`redis`、`migrate`、`api`、`worker` 全部 healthy |
| API | `http://127.0.0.1:8000`，`/healthz` 与 `/readyz` 均 ok |
| v5 版本 | 5.1.7（发布镜像） |
| 国内出口 | `115.204.182.43`，中国 浙江 杭州 电信 |
| 国外出口 | 美国洛杉矶（ShellCrash 按域名分流） |
| 抖音域名 | `www.douyin.com`、`www.iesdouyin.com`、`sso.douyin.com`、`live.douyin.com` 均解析到浙江 IP，HTTP 200/301，0.1–0.7s → **国内直连，不走 VPN** |
| 结论 | 登录 cookie 与 v5 对抖音的出口一致（同一公网 IP），不需要中国代理 |

---

## 2. 身份

### 登录身份

| 项目 | 结果 |
|---|---|
| 导入 | `POST /api/v1/admin/identities/import`，格式 header，74 个 cookie |
| `authenticated` | true |
| 必需 cookie | `ttwid` 存在，`missing_required: []` |
| 会话 cookie | `sessionid`、`sessionid_ss`、`sid_guard`、`sid_tt`、`passport_auth_status` |
| 过期时间 | `2026-12-26T10:26:07Z`（约 59 天） |
| 浏览器 | Chrome 154 |
| rotation | 限制为 `douyin.author_posts`（登录只服务视频列表） |
| 状态 | 曾因回复接口触发风控而 cooling；冷却结束后可继续用于 `author_posts` |

### 游客身份

- 策略：`browser-rpc`
- 状态：镜像构建中（`dtk-browser-rpc:dev`）
- 构建备注：默认 Debian 源过慢，使用临时 Dockerfile 换阿里云 Debian 源 + 清华 PyPI 源；未修改仓库内 `docker/Dockerfile.browser`

---

## 3. 已确认的实验结果

### 3.1 账号与视频列表

测试账号：**绍兴文旅**（`unique_id = yujianshaoxing`）

| 项目 | 结果 |
|---|---|
| `sec_uid` | `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c` |
| 粉丝 / 作品 | 369,577 / 730 |
| 视频列表第 1 页 | 21 条，`has_more=true`，`cursor=1789806600000` |
| 视频列表第 2 页 | 20 条，`has_more=true`，`cursor=1784275283000` |
| `meta.guest_fallback` | 第 1、2 页均为 `null` |
| 结论 | **登录身份可以完整翻页**；第 2 页没有 `IDENTITY_LOGIN_REQUIRED` |

### 3.2 测试视频

| 项目 | 结果 |
|---|---|
| `aweme_id` | `7681929945538497843` |
| 标题 | 当现实版葫芦爷爷照进现实…… #绍兴葫芦爷爷 #双向奔赴 #葫芦娃爷爷 #充能计划 |
| 发布时间 | 2026-09-05T09:00:00Z |
| 时长 | 23,126 ms |
| 点赞 / 评论 / 转发 / 收藏 | 21,045 / **896** / 1,488 / 7,919 |
| 作者 | 葫芦兄弟和朋友们（`MS4wLjABAAAA3GxMp6xMue3IxJmxkWtyprb3YUtKs9mrBnJcPvzKxjM`） |

> 注意：该视频作者不是「绍兴文旅」账号本身，但评论数据完整，适合 Phase 0 字段验证。

### 3.3 一级评论

| 项目 | 结果 |
|---|---|
| 第 1 页 | 46 条，`has_more=true`，`cursor="50"` |
| 第 2 页 | 47 条，`has_more=true`，`cursor="100"` |
| 两页重复 | **0 条**（按 `comment_id` 对比） |
| `ip_label` 存在率 | 第 1 页 45/46；第 2 页 47/47 |
| `reply_to_reply_id` 存在率 | 第 1 页 46/46（值多为 `"0"`） |
| `label_list` | 一级评论中未出现（0/46） |
| 结论 | **`ip_label` 和 `reply_to_reply_id` 在真实响应中存在**，fixture 的假设成立 |

真实 raw 样例（脱敏，仅保留关键字段）：

```json
{
  "cid": "7682054941225698091",
  "aweme_id": "7681929945538497843",
  "reply_id": "0",
  "reply_to_reply_id": "0",
  "ip_label": null,
  "label_list": null,
  "reply_comment_total": 106,
  "is_author_digged": false,
  "stick_position": 0
}
```

### 3.3.1 评论翻页与完整性（视频 `7692023073838790646`，平台计数 557）

| 指标 | 结果 |
|---|---|
| 页数 | 11（第 1–10 页有数据，第 11 页空） |
| 抓到条数 | 464 |
| 唯一 `comment_id` | 442 |
| 重复 | 22（4.7%） |
| `ip_label` 存在 | 约 462/464（99.6%） |
| 耗时 | 7 秒（3 个游客的令牌桶 burst；单页上游 0.3–2.6s） |
| 结束原因 | 第 11 页返回 0 条 + `UPSTREAM_CHANGED`（`has_more` 与 `cursor` 不一致） |
| 平台计数 vs 抓到 | **557 vs 464（83.3%）** |
| 风控 | 本次无风控，所有页面 `ok` |

**结论：**

- 抖音 web 评论分页在 offset ~500 附近被截断/返回空页；不是正常的 `has_more=false` 结束，而是 `has_more=true` + cursor 0/缺失，v5 判为 `UPSTREAM_CHANGED`。
- 抓取数不可能等于平台 `comment_count`（本例 83.3%）；研究设计必须接受覆盖率缺口并记录。
- 热度排序 + offset 导致 4.7% 重复；必须按 `comment_id` 去重。
- 采集层应把“空页 + `UPSTREAM_CHANGED`”视为**软结束/平台上限**，记录为 `cap_reached`，不要当致命错误。

### 3.4 回复接口：发现问题

| 项目 | 结果 |
|---|---|
| 请求 | `GET /api/v1/douyin/video/comments/replies?comment_id=7682054941225698091&aweme_id=7681929945538497843&count=50&include_raw=true` |
| 上游响应 | **HTTP 200，0 字节** |
| v5 分类 | `risk_control`，规则 `body.empty`，signer `native` |
| 身份状态 | `cooling`，`consecutive_fails=1` → 冷却 90 秒；第二次尝试（冷却结束前 5 秒，`count=20`）再次触发 → `consecutive_fails=2`，冷却到 180 秒 |
| 对照 | 同一 native 签名下，`comments`、`content_detail`、`author_posts` 全部 ok |
| `count=20` | 同样触发，排除“50 太大” |
| 结论 | **回复接口不是页大小问题，而是对签名/身份更敏感**；需要 browser-rpc 浏览器签名，或游客身份，或别的参数差异 |

**当前假设（待验证）：**

1. 回复接口可能需要 browser-rpc 的浏览器签名（`signing.mode=rpc` 或 `auto`）；
2. 也可能需要游客身份而不是登录身份；
3. 也可能是 `item_id`/`item_type` 参数或平台对该视频的回复限制；
4. v5 把 200 + 0 字节默认判为风控，因此一次失败就会冷却身份——在 pilot 中要避免用登录身份试探回复接口。

### 3.4.1 外部证据：reply 端点的 a_bogus 校验更严

2026-10-28 搜索到一篇逆向复盘，与我们的现象完全吻合：

- 《某音 web 评论回复(reply)接口逆向复盘》：<http://mp.weixin.qq.com/s?__biz=MzkzOTYxOTgzMg==&mid=2247484028&idx=1&sn=e3a301313d04e5fac0f5e0dba4619444>
- 关键结论：
  - `/aweme/v1/web/comment/list/reply/` 对 `a_bogus` 做**字节级严格校验**；
  - 同一个 native 签名对 `comment/list/`、`aweme/detail/` 能通，对 reply 返回 0 字节；
  - 浏览器真实 `a_bogus` → 约 8KB 真实数据；移植的 native 签名 → 空 body；
  - 线上 SDK 已升级到 v1.0.1.20，native 移植 v1.0.1.19 过不了；
  - 参数 `item_id`、`comment_id`、`cursor`、`count` 是正确的。
- 参数参考：<https://raw.githubusercontent.com/mafqla/douyin-api/master/docs/video-api.md>、<https://github.com/XieWxx/maxhub-api-skills/blob/main/maxhub-douyin/references/comments.md>
- 对我们的含义：`signing.mode=rpc`（浏览器真实签名）是首选修复；`auto` 可能因 reply 端点风险率上升后切换，但 pilot 用 `rpc` 更确定。

### 3.4.2 复测结果：所有组合都失败

browser-rpc 构建并启动后，按以下组合复测（2026-10-28 02:15–02:23）：

| 组合 | 结果 |
|---|---|
| 登录身份 + native | 200 + 0 字节，`body.empty`，冷却 90s |
| 游客身份 + native | 200 + 0 字节，`body.empty`，冷却 90s |
| 游客身份 + browser/rpc | 200 + 0 字节，`signer=browser`，冷却 180s |
| 登录身份 + browser/rpc | 200 + 0 字节，`signer=browser` |
| v4 完整参数（8 个额外参数）+ browser/rpc | 200 + 0 字节 |
| 换视频/评论（`7692023073838790646`，557 条评论） | 200 + 0 字节 |

**结论：** 不是身份、不是视频、不是 native/browser 签名开关、也不是 v4 那 8 个参数。reply 端点在我们的请求形态下始终返回 0 字节。

**剩余假设：**

1. 真实浏览器请求的方法/URL/额外请求头（`Referer`、`Origin`、`x-secsdk-csrf-*` 等）与 v5 不同；
2. reply 端点要求 `a_bogus` 与发送请求的浏览器上下文是**同一个会话**（同一 cookie/UA/指纹），而 v5 是“browser-rpc 签名 + Python 发送”，签名和实际请求的 cookie/UA 不完全一致；
3. CloakBrowser 免费二进制是 Chrome146，登录 cookie 是 Chrome154；虽然游客与签名都是 146，仍可能被专项校验识别；
4. 平台已对 web reply 端点做更严格的自动化拦截。

### 3.4.3 真实浏览器抓包对照（2026-10-28，debug.md / debug2.md）

**第一页请求（debug.md）：**

- GET；`item_id` + `comment_id`；`cursor=0`；**`count=3`**
- `cut_version=1`、`update_version_code=170400`、`pc_libra_divert=Windows`、`support_h265=1`、`support_dash=1`
- `webid=<webid>`、`uifid=<UIFID>`、`verifyFp=<s_v_web_id>`、`fp=<s_v_web_id>`
- `msToken`、`a_bogus` 在 query
- 请求头：`referer`、`accept`、`accept-language`、`bd-ticket-guard-client-data`、`bd-ticket-guard-ree-public-key`、`bd-ticket-guard-version`、`bd-ticket-guard-web-sign-type`、`bd-ticket-guard-web-version`、`uifid`、`sec-ch-ua*`、`sec-fetch-*`、`priority`

**“展开更多”请求（debug2.md）：**

- `cursor=3`、**`count=10`**、`whale_cut_token=`
- 其余参数/头相同

**v5 的差异：**

- v5 **完全没有 `bd-ticket-guard-*` 的实现**（全仓库 grep 无命中）；
- v5 的 native 签名只对 `DOUYIN_SIGNED_PATHS` 添加 `uifid` / `x-secsdk-web-signature` 头；`/comment/list/reply/` 不在该列表；
- v5 的 rpc 签名会把 `uifid`、`verifyFp`、`fp`、`msToken` 等放进 query，但不会生成 `bd-ticket-guard-client-data`（带 `req_sign` 的签名头）。

**结论：** 回复接口很可能要求浏览器 SDK 生成的 `bd-ticket-guard` 请求头；仅靠 a_bogus + 参数无法通过。需要在浏览器上下文里发请求（Playwright/CloakBrowser），或用商业工具。

**下一步：**

- 做一个最小原型：在 browser-rpc 的 CloakBrowser 里加载登录 cookie，打开视频页，在页面上下文 `fetch` 回复接口，看 SDK 是否自动补上 `bd-ticket-guard` 头并返回数据；
- 如果成功，pilot 可以用“浏览器只抓回复、其他用快速 API”的混合方案；
- 如果失败，评估商业工具或一级评论版本。

**抓包文件安全提醒：** `debug.md` / `debug2.md` 含完整 session cookie，不能提交 git；建议移到 `.secrets/` 或使用后删除。

### 3.4.4 浏览器上下文原型（browser-rpc CloakBrowser）

2026-10-28 在 browser-rpc 容器里直接启动 CloakBrowser，加载登录 cookie，打开视频页，在页面上下文调用接口：

| 测试 | 结果 |
|---|---|
| 页面内 `comment/list` | ✅ 200 / 72KB |
| 页面内 `comment/list/reply` | ❌ 请求挂起 20s 后被 abort；fetch/XHR 均超时 |
| 视频页正文 | “视频数据加载中”，评论未渲染 |
| 浏览器 UA 改成登录的 Chrome154 | 一样失败；`navigator.userAgent` 已是 154 |
| 用户真实浏览器 Console `fetch` | ✅ 200 / 5882 bytes |

**结论：** CloakBrowser 的 headless 环境过不了 reply 端点的 ticket-guard 检测；不是参数、签名或 UA 问题。要抓回复，需要：

- 有头真实 Chrome（Xvfb）或用户真实浏览器；
- 或商业工具；
- 或 UI 自动化——但 headless 下视频页本身也没加载评论，UI 路径同样受阻。

**建议：** pilot 先做一级评论；回复作为单独的技术验证/商业工具对照，不阻塞主流程。

### 3.4.5 Chrome 148 + Xvfb spike（2026-10-28，失败）

详细报告：[CHROME_SPIKE.md](CHROME_SPIKE.md)

| 变体 | 页面 | reply |
|---|---|---|
| Chrome148 + UA154 | 标题空/加载中 | 超时 |
| Chrome148 原生 UA148 | 标题正常 | 超时 |
| 服务器 QR 新 session（62 cookies） | 标题空/加载中 | 超时 |
| + WebGL SwiftShader | 视频页数据正常 | 超时 |
| + 页面实时 148/Linux 参数 | 再次加载中 | 超时 |
| + 最终 WebGL 环境重新扫码（57 cookies） | 再次加载中 | 超时 |
| UI 点击“展开106条回复” | 按钮可点 | 30s 无 response |

**关键发现：**

- Chrome 日志 `WebGL1/WebGL2 blocklisted`；加 SwiftShader 参数后 WebGL 可用（ANGLE SwiftShader），视频页能加载；
- 但 reply 端点仍被挂起；
- 服务器 QR 新 session 也失败，排除 session/设备绑定；
- 页面实时 148/Linux 参数也失败，排除查询参数；
- 最终 WebGL 环境内重新扫码（57 cookies）也失败，结论确定：平台检测服务器 Xvfb/SwiftShader 环境；
- 不是 UA/版本/session/参数。

**影响：** 服务器自托管浏览器抓回复不可行；一级评论 v5 API 不受影响。

### 3.4.6 Windows 桌面探针（Phase 0.5 初测，2026-10-29）

执行机：Windows 10 Enterprise LTSC 2021，RDP，无 GPU；Chrome 156，专用 profile + 人工扫码；Python 3.13 / Playwright 1.64；locale `en-US`。

| 测试 | 结果 | 关键数据 | 边界 |
|---|---|---|---|
| A UI 点击 + 监听 | PASS | 3 页 `n=2/7/10`，`cursor=3→13→23`，`has_more=1`，`total=113`，6.7 s | `max_pages=3`，只抓 19/113 |
| B 页面内 bare fetch | PASS | 深评论 200，2987 bytes，1 条回复 | 页面可能自动补签名 |
| C 改参重放 | PASS | unchanged / cursor / comment_id 均 200；cursor 23→33 | 同上，不能证明免签 |
| D globals | 信息项 | `byted_acrawler` 存在 | — |

**结论：**

- Windows 真实 Chrome 可以拿到 reply；服务器 Xvfb 失败不是“端点对所有自动化关闭”。
- **线程级 / comment_id 级 page-context worker 可行**：B 不滚动就拿到深评论回复；C 改 cursor 拿到下一页。
- **“接口免签”已被 Round 001 否定**：S1 确认 `window.fetch` / `XMLHttpRequest.open` 都被页面重写；S2 实际请求自动出现 `a_bogus`/`msToken`/`verifyFp`/`fp` 和 `bd-ticket-guard-*`；S3 同源无 app JS 页面、S4 `context.request` 都是 200 + 0 字节。
- **生产必须保留完整加载的页面 + 页面内 `fetch`**；不要写无浏览器 HTTP worker，也不要用 `context.request`。
- 剩余：worker 生产集成、真实目标账号 `is_author` 验证、中文 locale/真实桌面复测（可选）；见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8/§4.9。
- 完整证据与数据卫生核对：[spike/resultFromWindows/ANALYSIS.md](spike/resultFromWindows/ANALYSIS.md) §7.1。

**Round 002（full-thread，2026-10-30）：**

| 指标 | 结果 |
|---|---|
| `count=50` | 接受；3 页 45/50/13 |
| unique / duplicates | 108 / 0 |
| 平台 `total` / coverage | 113 / **95.58%** |
| `stop_reason` | `complete` |
| `ip_label` / `reply_to_reply_id` 非 0 | 108/108 / 21 |
| 单页 fetch 耗时 | 0.01 / 0.62 / 0.37 s；命令总耗时 16 s |

- page 1 返回 45，但 cursor=50：**cursor 按请求 count 前进，不按返回条数**。
- 缺 5 条（offset 45–49）是平台缺口；`complete` + coverage<1 时记录，不要无限重跑。
- `count=50` 是生产页大小；复用视频页、按请求/线程做节奏。

**Round 003（multi-thread，2026-10-30）：**

| thread | expected | unique | coverage | dup | ip_label | rtr | depth3 | orphans | stop |
|---|---|---|---|---|---|---|---|---|---|
| `7682054941225698091` | 113 | 108 | 0.9558 | 0 | 108 | 21 | 10 | 7 | complete |
| `7682239605306819385` | 3 | 3 | 1.0 | 0 | 3 | 1 | 1 | 0 | complete |
| `7682223064176395049` | 1 | 1 | 1.0 | 0 | 1 | 0 | 0 | 0 | complete |

- 同一视频页复用 3 个线程；`global_stop=null`；命令 33 s；无验证码/wrapper 丢失/风控。
- 大线程 7 条孤儿边（3 个父 id 不在 108 条内）；孤儿保留 raw 边，`depth` 可为 null。
- `creator_label`/`label_text`/`label_list` 均为 0；`is_author` 必须用 `sec_uid` 比较。
- worker 循环验证通过：同页多线程 + `count=50` + 节奏 + 断点。

**Round 004（worker smoke，2026-10-30）：**

- 1 视频 / 3 线程；`count=50`；同页复用；命令 32 s。
- totals：fetched/unique 112/112，duplicates 0；orphans 7；depth3 11。
- 113 线程 108/113；3 条/1 条线程 100%；`author_hash_non_null=112`。
- `is_author_true=0`：jobs 的 `author_sec_uid` 已用 v5 核对（视频作者 `葫芦兄弟和朋友们`）；测试视频作者未回复，0 是预期。若需要“一级评论作者是否回复”，另加 `is_thread_author`。
- worker 原型（job → raw → normalized → state → summary）端到端通过。

**Round 005（pilot replies，2026-10-30）：**

- 17 jobs / 804 threads；4,199 unique 回复；801/804 `complete`，3 个浅抓 `max_pages=3`。
- 完整线程 coverage 99.79%；整体 86.85%；43 孤儿边、72 depth-null（43 孤儿 + 29 后代）；57 条作者回复。
- **2 次人工人机验证**：用户在 Windows 浏览器中手动通过；worker 未记录 `risk_control`/0 字节，未发现数据损失。
- 影响：长跑（约 82 分钟）会出现验证码；生产不能假设完全无人值守，需要验证码检测、暂停/恢复和人工值守。

---

## 4. 对 DESIGN.md 的影响

| 假设 | 现状 |
|---|---|
| `ip_label` 只在 raw 中 | ✅ 确认存在，约 99.6% 一级评论有值；回复待测 |
| `reply_to_reply_id` 只在 raw 中 | ✅ 确认存在；需要找到非 `"0"` 的回复边来验证 depth≥3 |
| 评论完整性 | ⚠️ 557 平台计数 vs 464 抓到（83.3%）；offset ~500 截断；4.7% 重复 |
| `is_author` 可派生 | ✅ 用 `sec_uid` 比较；Round 004 测试视频作者未回复，`is_author=0` 是预期；真实目标账号需验证非 0 |
| 回复接口游客可抓 | ❌ 未确认；登录/游客、native/browser、Chrome148+Xvfb 均失败 |
| reply 端点（v5 REST） | ❌ 200 + 0 字节；浏览器抓包显示需要 `bd-ticket-guard-*` 头，v5 未实现；CloakBrowser headless 和服务器 Chrome148+Xvfb 都被挂起；详见 §3.4.3/§3.4.4/§3.4.5 |
| Windows 桌面 page-context | ✅ 初测 A/B/C PASS：UI 监听、深评论 bare fetch、改 cursor/comment_id 均 200；线程级可行；详见 §3.4.6 |
| 免签 HTTP / `context.request` | ❌ Round 001 确认：页面 wrapper 自动补签名；无 app JS 页面和 `context.request` 都是 200 + 0 字节；生产必须保留完整页面 |
| 完整线程 / `count=50` | ✅ Round 002：3 页 45/50/13；unique 108/113；coverage 95.58%；0 重复；缺 5 条为平台缺口 |
| 多线程 / page reuse / 孤儿 | ✅ Round 003：3 线程同页；113 线程 108/113、orphans 7、depth3 10；短线程 100%；`global_stop=null` |
| `label_list` / `is_author` | ⚠️ Round 003 回复的 `label_text`/`label_list`/`creator_label` 均为 0；`is_author` 必须用 `sec_uid`，不能依赖 label |
| Worker 原型 | ✅ Round 004：job → raw → normalized → state → summary 端到端；112/112 normalized；32 s |
| `is_author` 测试值 | ⚠️ 测试视频作者 `葫芦兄弟和朋友们` 未回复，`is_author=0` 是预期；一级评论作者（绍兴文旅）是否回复需独立 `is_thread_author` |
| Chrome 148 + Xvfb spike | ❌ 失败；服务器环境被 reply 端点阻断；详见 [CHROME_SPIKE.md](CHROME_SPIKE.md) |
| 登录身份专用于 `author_posts` | ✅ 已设置 rotation |
| 服务器出口与登录地一致 | ✅ 国内直连，`115.204.182.43` |

---

## 5. 待办

- [x] 完成 browser-rpc 构建并启动
- [x] mint 游客身份
- [x] 游客 + `count=20` 重试回复接口（失败：0 字节）
- [x] `signing.mode=rpc` 重试（失败：0 字节）
- [x] 抓取真实浏览器 reply 请求，对比 method / URL / headers（发现 `bd-ticket-guard-*`，v5 未实现）
- [x] 原型：在浏览器上下文 `fetch` 回复接口（失败：CloakBrowser headless 被挂起）
- [x] Chrome 148 + Xvfb spike（失败：服务器环境被 reply 端点阻断；见 [CHROME_SPIKE.md](CHROME_SPIKE.md)）
- [x] 最终 WebGL 环境重新扫码复测（失败：57 cookies，仍被 reply 挂起）
- [x] 决定方向：先做 Windows 桌面 worker 可行性实验（A/B/C/D）；见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)
- [x] 执行 Windows 实验：A/B/C PASS；线程级 page-context 可行；见 [初测分析](spike/resultFromWindows/ANALYSIS.md)
- [x] 决定方向：线程级 page-context worker；免签 HTTP worker 不考虑
- [x] 补充实验 S1–S4：页面 wrapper 自动签名；同源无 app JS / `context.request` 均 0 字节；见 [初测分析](spike/resultFromWindows/ANALYSIS.md) §7.1
- [x] 完整线程 `has_more=0`；`count=50`：3 页 45/50/13，108/113，95.58%，0 重复
- [x] 多线程 + 孤儿数 + page reuse + 节奏：3 线程同页；113 线程 108/113、orphans 7、depth3 10；短线程 100%；`global_stop=null`
- [ ] 中文 locale / 真实桌面（非 RDP）复测（可选）
- [ ] 如果回复长期不可得，更新研究设计（一级评论为主）
- [x] 测量一级评论翻页与完整性（464/557，83.3%；22 重复）
- [ ] 处理评论空页 + `UPSTREAM_CHANGED`（视为 `cap_reached`）
- [x] 找到 `reply_to_reply_id != "0"` 的 depth≥3 边：Round 003 depth3=10
- [x] 验证 `label_list` 的 `Creator` 与 `is_author`：回复的 label_text/label_list=0；`is_author` 用 `sec_uid`
- [x] 回复翻页超过 20 条：Round 002/003 108/113
- [x] 测量单视频评论 + 回复耗时：Round 002 16 s；Round 003 33 s（3 线程）
- [ ] 测量风控阈值（连续页面数）
- [x] Windows reply worker 原型：Round 004 1 视频/3 线程，112/112 normalized，`status=success`
- [ ] 生产集成：job queue、normalized → 研究库/隐私转换、真实目标账号 `is_author` 非 0、可选 `is_thread_author`
- [ ] 更新本报告与 DESIGN.md

### 5.1 回复方案决策（2026-10-30）

- 服务器自托管浏览器（Xvfb/SwiftShader）关闭；结论不变。
- anotherImplement 证明真实 Windows 桌面 + 有头 Chromium 可以拿到回复；它不是可直接套用的架构，但提供了可复用的浏览器/点击/监听/解析零件。
- Phase 0.5 初测（2026-10-29）：A/B/C PASS；线程级 page-context 可行。
- Round 001 签名检查（2026-10-30）：页面 wrapper 自动签名；同源无 app JS / `context.request` 都是 200 + 0 字节；免签 HTTP worker 否定。
- Round 002 完整线程（2026-10-30）：`count=50`；3 页 45/50/13；108/113，95.58%，0 重复；缺 5 条为平台缺口。
- Round 003 多线程（2026-10-30）：3 线程同页；113 线程 108/113、orphans 7、depth3 10；短线程 100%；`global_stop=null`；命令 33 s。
- 下一步：生产集成（job queue、normalized → 研究库/隐私转换、真实目标账号 `is_author` 非 0、可选 `is_thread_author`）→ pilot；中文 locale 复测可选。
- v5 继续负责视频/一级评论；Windows worker 只补回复，且必须保留完整加载的页面。

---

## 6. 复盘：踩过的坑

1. **`ipinfo.io` 显示美国不代表抖音走美国**：ShellCrash 按域名分流，国外域名走 VPN，国内直连。用 `myip.ipip.net` 和实际抖音域名验证。
2. **v5 把 200 + 0 字节判为风控**：默认规则 `body.empty`；回复接口正好返回空 body，导致登录身份被冷却。这是 v5 的保守设计，不是 bug。
3. **不要用登录身份试探回复接口**：一次失败就冷却 90–180 秒，影响 `author_posts`。应先 mint 游客，用游客做评论/回复实验。
4. **`docker compose` 的相对路径**：`-f docker/compose.yml` 必须在仓库根目录执行；在项目根目录运行会找不到文件。
5. **构建 browser-rpc 要用国内镜像**：默认 `deb.debian.org` 走 VPN，apt 更新极慢；临时 Dockerfile 换阿里云/清华源。
6. **评论翻页到 offset ~500 会返回空页 + `UPSTREAM_CHANGED`**：这是平台上限，不是解析 bug；采集层要当软结束。
7. **令牌桶 burst 会让前几页很快**：3 个游客的容量用完之前，10 页可能 7 秒完成；不要用这个速度估算总吞吐。
8. **服务器 Chrome 的 WebGL 默认被 blocklist**：`WebGL1/WebGL2 blocklisted`；加 `--enable-unsafe-swiftshader --ignore-gpu-blocklist --use-gl=angle --use-angle=swiftshader --enable-webgl` 后 WebGL 可用（ANGLE SwiftShader），视频页才能加载。
9. **WebGL 修好后 reply 仍被阻断**：服务器 QR 新 session、148/Linux 参数、UI 点击都失败；说明平台检测的是服务器 Xvfb/SwiftShader 环境，不是 session/参数/版本。
10. **最终环境重新扫码也失败**：WebGL 已启用、session 在最终 WebGL 环境创建（57 cookies）、查询参数为 148/Linux，reply 仍挂起；服务器自托管回复方案可以关闭。
8. **v5 不实现 `bd-ticket-guard-*`**：浏览器请求带这套头，v5 全仓库没有；reply 端点 0 字节很可能就是这个原因。
9. **回复接口第一页 `count=3`，后续 `count=10`**：不要用 `count=50` 请求回复。
10. **抓包文件含 session cookie**：`debug.md` / `debug2.md` 不能提交 git；使用后删除或移到 `.secrets/`。
11. **CloakBrowser headless 在 reply 端点被挂起**：页面内 `comment/list` 正常，`comment/list/reply` 被 SDK 挂起/中止；用户真实浏览器 Console `fetch` 成功。回复需要真实浏览器/有头 Chrome 或商业工具，不能依赖当前 headless 方案。
