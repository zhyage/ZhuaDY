# Chrome Spike 报告 — 服务器浏览器抓回复

> 日期：2026-10-28
> 结论：**未达成**。服务器 Xvfb + Chrome 148 + SwiftShader 能打开视频页，但 `comment/list/reply` 仍被挂起；最终 WebGL 环境内重新扫码也失败。不是 UA、版本、session 或参数问题。
>
> **2026-10-29 补充：** anotherImplement 证明真实 Windows 桌面 Chrome 可抓回复；同日 Phase 0.5 初测在 Windows 10 RDP（无 GPU）上 A/B/C PASS：页面上下文可按 `comment_id` 定向、按 `cursor` 翻页。
>
> **2026-10-30 补充：** Round 001 确认抖音页面重写了 `window.fetch` / `XMLHttpRequest.open`，自动补 `a_bogus`/`msToken`/`verifyFp`/`fp` 和 `bd-ticket-guard-*`；同源无 app JS 页面和 `context.request` 都是 **200 + 0 字节**。这解释了服务器 Xvfb 的 0 字节：不是网络问题，而是页面 app 未完成初始化/签名。服务器自托管结论不变；Windows page-context worker 可行。详见 [spike/resultFromWindows/ANALYSIS.md](spike/resultFromWindows/ANALYSIS.md) §7.1 与 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8。

---

## 1. 目标

验证一个假设：

> 用真实有头 Chrome + 登录 cookie，在页面上下文直接 `fetch` reply 接口，能否稳定拿到回复？

如果可行，pilot 可以采用“v5 快速 API 抓视频/一级评论 + 浏览器只补回复”的混合方案。

---

## 2. 环境

| 项目 | 值 |
|---|---|
| OS | Ubuntu 24.04 |
| 浏览器 | Google Chrome **148.0.7778.178**（`/usr/bin/google-chrome`） |
| 虚拟显示器 | Xvfb `:99`，1537×960 |
| 自动化 | Playwright 1.64.1，CDP `127.0.0.1:9222` |
| 网络 | 国内直连（抖音域名不走 VPN） |
| 登录 | 导入 `import-login.json`；后来在服务器 Chrome 扫码新建 session |

---

## 3. 测试矩阵

| # | 浏览器 / UA | session | 页面 | reply |
|---|---|---|---|---|
| A | Chrome148 + 覆盖 UA154 | 导入 cookie | 标题空，视频数据加载中 | 40s 超时 |
| B | Chrome148 原生 UA（Linux 148） | 导入 cookie | **标题正常** | 40s 超时 |
| C | Chrome148 原生 UA | **服务器 QR 新 session（62 cookies）** | 标题空，视频数据加载中 | 40s 超时 |
| D | C + WebGL SwiftShader | 服务器 QR session | **视频页数据正常加载** | 40s 超时 |
| E | D + 页面实时参数（148/Linux/32核/16GB） | 服务器 QR session | 再次加载中 | 40s 超时 |
| F | D + **最终 WebGL 环境内重新扫码**（57 cookies） | 最终环境 session | 再次加载中 | 40s 超时 |
| UI | 点击“展开106条回复” | 服务器 QR session | 按钮可点 | 30s 无 response |

所有变体都没有拿到回复 body。

---

## 4. 关键发现

### 4.1 WebGL 是页面加载的必要条件

Chrome 日志：

```text
ERROR:gpu/command_buffer/service/context_group.cc:138]
ContextResult::kFatalFailure: WebGL1 blocklisted
ContextResult::kFatalFailure: WebGL2 blocklisted
```

加上以下参数后 WebGL 可用：

```text
--enable-unsafe-swiftshader
--ignore-gpu-blocklist
--use-gl=angle
--use-angle=swiftshader
--enable-webgl
```

WebGL 报告：

```text
ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero) (0x0000C0DE)), SwiftShader driver)
```

效果：视频页标题和视频数据能正常加载（之前一直停在“视频数据加载中”）。

### 4.2 但 reply 仍然被阻断

WebGL 修复后：

- 页面能加载；
- “展开106条回复”按钮能点；
- 页面内 ad-hoc `fetch` 40s 超时；
- 点击 UI 后 30s 没有 `comment/list/reply` response；
- `REQFAIL` 明确指向 reply URL。

### 4.3 已排除的因素

| 因素 | 结论 |
|---|---|
| UA 覆盖 / 版本不一致 | 原生 148 UA 页面更好，但 reply 仍失败 |
| 登录 session / 设备绑定 | 服务器 Chrome 扫码新建 session 仍失败 |
| session 在最终 WebGL 环境创建 | 重新扫码（57 cookies）仍失败；环境级检测确认 |
| 查询参数（154/Windows vs 148/Linux） | 页面实时读取 148/Linux 参数仍失败 |
| WebGL 缺失 | 修复后页面正常，reply 仍失败 |
| 广告/视频资源失败 | 与 reply 无关 |

**剩余解释：** 平台在 reply 端点对服务器 Xvfb/SwiftShader/自动化环境做了更严格的检测/阻断；这是环境级问题，不是请求级问题。

---

## 5. 影响

- **服务器自托管浏览器抓回复：不可行**（Xvfb + Chrome148 + SwiftShader；最终 WebGL 环境内重新扫码 57 cookies 仍失败）。
- **一级评论 v5 API：不受影响**，已验证 464/557（83.3%）、`ip_label` 99.6%。
- 服务器 Chrome 扫码 session 已删除；Chrome profile 和 QR 截图已清理。

---

## 6. 可选后续

1. **一级评论 pilot（推荐）**：先用 v5 API 交付可用语料；回复作为第二阶段。
2. **真实桌面浏览器 reply worker（Phase 0.5 + Round 001 通过）**：Windows 10 RDP（无 GPU）+ Chrome 156 上 A/B/C PASS；页面上下文可按 `comment_id` 定向、按 `cursor` 翻页；Round 001 确认页面 wrapper 自动签名，必须保留完整加载的页面。详见 [WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md) §4.8。需要一台常开的机器；10–50 账号要多 profile/实例。
3. **商业工具补回复**：社媒助手/八爪鱼；需要确认是否提供 `ip_label`、`reply_to_reply_id`、`label_list` 这些字段。
4. **只做一级评论**：研究设计接受没有二级回复。

---

## 7. 复现与环境

脚本在 `spike/chrome-reply/`：

- `launch_chrome.sh`：Xvfb + 有头 Chrome + CDP
- `login_qr.py`：登录二维码截图 / 等待扫码
- `fetch_replies.py`：页面内 fetch reply + 翻页
- `run_spike.sh`：一键启动并运行

关键参数：

```text
UA_MODE=native
CHROME_PROFILE=spike/chrome-profile
--enable-unsafe-swiftshader --ignore-gpu-blocklist
--use-gl=angle --use-angle=swiftshader --enable-webgl
```

---

## 8. 安全提醒

- `debug.md` / `debug2.md` 含完整 session cookie，现在在 `.secrets/`；使用后删除。
- 本 spike 生成的 QR 截图、服务器 session、Chrome profile 已删除。
- 服务器 Chrome 扫码使用的专用账号，请确认没有其他设备登录异常。
