# Windows Agent Runbook — 抖音回复探针

> 给 Windows 上的 agent / 操作者。目标：运行只读探针，产出 `report.md` + `summary.json`。
> **不要修改 `probe_reply.py`；不要使用主账号；不要把 cookie / header 值写进报告或聊天。**

> **如果你已经跑完第一次探针（A/B/C PASS）**：只需要执行 **§0**。§3–§6 是第一次探针的完整流程，**不要重跑**；也不需要重新登录。运行 `probe_signature.py`，把 `signature_report.md` + `signature_summary.json` 回传。

---

## 0. 现在只需要做这一件事（如果第一次探针已完成）

0. 如果你在共享目录里（例如 `Z:\douYin\<round>\require\inputs\windows-reply`），先把整个 `windows-reply` 目录复制到本地（例如 `C:\work\douyin-reply-<round>`），在本地运行；**不要写 `require\`**，也不要在 `require\` 里留下 `out/`、`__pycache__`。
1. 确认专用 Chrome 还在运行，`http://127.0.0.1:9222/json/version` 可访问，登录态还在。
2. 在本地目录运行：

```powershell
python probe_signature.py --targets targets.json --common-params common_params.json
```

3. 找到最新的 `out/signature-<timestamp>/`，把这两个文件复制到 `handoff/`：

```text
signature_report.md
signature_summary.json
```

4. 回传 `handoff/` 里的这两个文件。**不要重跑 `probe_reply.py`，不要重新扫码，不要改脚本。**
5. 如果命令失败：记录退出码和错误；最多重试 1 次，不要连续重试。

**这个补充实验回答什么：** 第一次 B/C 都是在抖音页面上下文里 `fetch`；如果页面自动补了 `a_bogus`/`bd-ticket-guard`，B/C 的成功就不是“接口免签”的证据。`probe_signature.py` 会检查 `window.fetch` 是否被包裹、实际请求是否带签名参数/头，以及不带页面 JS 的 `context.request` 是否能拿到数据。

背景分析（可选阅读，不是操作指令）：`ANALYSIS.md`。

---

## 0.1 你的角色与边界

你在 Windows 10/11 上，有 PowerShell 和文件访问权限。你只需要做本 runbook 的事：

- 运行只读探针；**不点赞、不关注、不评论**；
- 只操作**专用 Chrome profile**，不要关闭用户正在使用的主 Chrome；
- 登录必须由用户人工扫码；不要询问或保存密码；
- 遇到验证码、登录墙、连续空 body，停止并报告；
- 不要在日志、聊天、报告里粘贴 cookie、`a_bogus`、`bd-ticket-guard-*` 的值。

---

## 1. 交付物

完成后应存在：

```text
out/run-<timestamp>/
  report.md
  summary.json
  env.json
  A_metrics.json
  B_metrics.json
  C_metrics.json
  D_globals.json
  responses/          # 原始响应；含用户内容，不要回传

out/signature-<timestamp>/
  signature_report.md
  signature_summary.json
```

**回传给用户/Claude 的只有：** `report.md`、`summary.json`、`env.json`、`signature_report.md`、`signature_summary.json`，以及一段执行记录（命令、退出码、错误）。

---

## 2. 目录与输入

工作目录：

```text
spike/windows-reply/
  probe_reply.py
  run_probe.ps1
  README.md
  WINDOWS_AGENT_RUNBOOK.md
```

默认测试对象：

| 项目 | 值 |
|---|---|
| 视频 | `7681929945538497843` |
| 106 条回复的线程 | `7682054941225698091` |
| 首屏不可见的深评论 | `7682223064176395049`（v5 评论第 5 页） |
| 目标评论文本片段 | `爷爷考虑到大家太热情会有安全隐患` |

账号：用户提供的**专用测试账号**。不要用主账号，不要用用户日常 Chrome profile。

---

## 3. 预检

在 PowerShell 中运行并记录结果：

```powershell
$PSVersionTable.PSVersion
[System.Environment]::OSVersion.VersionString
python --version
python -c "import playwright; print('playwright ok')"
Test-Path "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

判断：

- Python 不存在：报告给用户，**不要擅自安装**。
- Playwright 不存在：只有在用户允许时才运行 `python -m pip install playwright`。
- Chrome 不在默认路径：找到 `chrome.exe`，后面用 `-ChromePath` 传入。
- 检查 9222 是否已占用：

```powershell
try { Invoke-RestMethod http://127.0.0.1:9222/json/version } catch { "CDP not running" }
```

---

## 4. 启动 Chrome + CDP

推荐用脚本：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_probe.ps1 -StartChromeOnly
```

如果 Chrome 路径不同：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_probe.ps1 -StartChromeOnly -ChromePath "D:\path\to\chrome.exe"
```

手动方式：

```powershell
$chrome = "C:\Program Files\Google\Chrome\Application\chrome.exe"
$profile = "$env:USERPROFILE\douyin-reply-profile"

& $chrome `
  --remote-debugging-port=9222 `
  --user-data-dir="$profile" `
  --no-first-run `
  --no-default-browser-check `
  --start-maximized `
  "https://www.douyin.com/"
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version
```

注意：

- 不要 kill 用户的主 Chrome；只用独立 `--user-data-dir`。
- 如果专用 profile 已经开着但没有 CDP，**只关闭这个专用窗口**，再重新启动。
- 如果 9222 被别的程序占用，换端口并给 `probe_reply.py` 传 `--cdp http://127.0.0.1:<port>`。

---

## 5. 登录（必须人工扫码）

1. 把专用 Chrome 窗口切到前台。
2. 请用户用**专用测试账号**扫码登录。
3. 不要自动登录，不要询问密码，不要读取/导出 cookie。
4. 登录后页面应显示已登录状态；不需要手动打开开发者工具。

如果探针返回：

- exit 4：未检测到登录态 → 请用户扫码后重跑；
- exit 5：检测到登录弹窗 → 请用户关闭/扫码后重跑。

---

## 6. 运行探针

```powershell
powershell -ExecutionPolicy Bypass -File .\run_probe.ps1
```

或直接：

```powershell
python probe_reply.py --targets targets.json
```

`targets.json` 已包含默认的视频/评论/深评论；这样避免 Windows PowerShell 5.1 对中文字符串的编码问题。若手动指定，也可以用 `--video-id` / `--comment-id` / `--comment-text` / `--deep-comment-id`。

如果 Python 在另一个 venv：

```powershell
powershell -ExecutionPolicy Bypass -File .\run_probe.ps1 -Python "D:\zhy\抖音\.venv\Scripts\python.exe"
```

规则：

- 第一次运行**不要**改 `--max-pages`（默认 3）。
- 目标评论找不到时，允许重试一次：`--max-scrolls 80`，或把 `--comment-text` 换成更短的独特片段。
- 不要连续重跑超过 2 次；先看 `report.md` 的 `stop_reason`。
- B/C 返回 0 字节是可能的结果，不要反复重试。

### 6.1 签名机制补充实验（S1–S4）

如果 A/B/C 已通过，再跑一次签名检查：

```powershell
python probe_signature.py --targets targets.json --common-params common_params.json
```

- 只读，大约 4–5 个请求；复用当前 Chrome/profile，不需要重新登录。
- `common_params.json` 来自第一次成功运行；如果换了机器/Chrome 版本，可以不传，脚本会用最小参数。
- 输出：`out/signature-*/signature_report.md` 和 `signature_summary.json`。
- 判读：
  - S2 实际请求出现 `a_bogus`/`msToken`/`bd-ticket-guard` → 页面 wrapper 自动签名；生产必须保留完整加载的抖音页面。
  - S4 `context.request` 也能拿到数据 → 更接近“接口不依赖页面 JS”；但仍建议用页面上下文降低风险。
  - S3 同源无 app JS 页面成功 → 进一步支持免签；失败则不能单独定论。

---

## 7. 验证输出

```powershell
$latest = Get-ChildItem -Directory .\out |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

Get-ChildItem $latest.FullName
Get-Content "$($latest.FullName)\summary.json" -Raw |
  ConvertFrom-Json | ConvertTo-Json -Depth 8
```

检查：

- `login` 为 `true`；
- `env.modal`、`env.captcha` 为 `null`；
- `a.pages` 非空；`a.stop_reason` 为 `complete` 或 `max_pages`；
- `b`、`c`、`d` 字段存在（即使失败也应记录）；
- `report.md` 存在且包含 A/B/C/D 四节。

如果 A 失败：

- 记录 `stop_reason`；
- 确认 B/C/D 仍然执行了；
- 不要为了“跑通 A”反复重试。

---

## 8. 打包回传

```powershell
$latest = Get-ChildItem -Directory .\out |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1

New-Item -ItemType Directory -Force .\handoff | Out-Null
Copy-Item "$($latest.FullName)\report.md" .\handoff\
Copy-Item "$($latest.FullName)\summary.json" .\handoff\
Copy-Item "$($latest.FullName)\env.json" .\handoff\
Copy-Item "$($latest.FullName)\A_metrics.json" .\handoff\
Copy-Item "$($latest.FullName)\B_metrics.json" .\handoff\
Copy-Item "$($latest.FullName)\C_metrics.json" .\handoff\
Copy-Item "$($latest.FullName)\D_globals.json" .\handoff\

$sig = Get-ChildItem -Directory .\out |
  Where-Object Name -like 'signature-*' |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1
if ($sig) {
  Copy-Item "$($sig.FullName)\signature_report.md" .\handoff\
  Copy-Item "$($sig.FullName)\signature_summary.json" .\handoff\
}
```

**不要复制 `responses/`**（含用户内容），除非用户明确要求。不要复制 cookie、header、`a_bogus`、`msToken`。

执行记录请写清楚：

```text
时间：
Windows 版本：
Chrome 版本：
Python / Playwright 版本：
使用的命令：
退出码：
输出目录：
错误/异常：
是否扫码登录：
```

---

## 9. 故障处理

| 现象 | 处理 |
|---|---|
| `CDP is not reachable` | 确认专用 Chrome 用 `--remote-debugging-port=9222` 启动；只关闭专用窗口重试；不要 kill 主 Chrome |
| exit 2 | 浏览器没有 context；确认 `--user-data-dir` 启动成功 |
| exit 3 | 验证码；停止，报告，不要自动破解 |
| exit 4 | 未登录；请用户扫码后重跑 |
| exit 5 | 登录弹窗；请用户关闭/扫码后重跑 |
| `target_not_found` | 加大 `--max-scrolls` 或换更短文本；最多重试一次 |
| `no_reply_response` | 记录；继续 B/C/D；不要连续点按钮 |
| B/C 0 bytes | 记录为结果；不要重试超过 2 次 |
| Playwright 缺失 | 经用户同意后 `python -m pip install playwright` |
| Python 缺失 | 报告；不要擅自安装 |

---

## 10. 安全与清理

- 专用账号、专用 profile；只读；低频。
- 出现验证码、登录墙、连续空 body 立即停。
- 不把 cookie、请求头值、`a_bogus`、`msToken` 写入报告/聊天/仓库。
- 不关闭用户的主 Chrome；专用窗口是否关闭由用户决定。
- 实验结束后，用户可删除 `%USERPROFILE%\douyin-reply-profile`；如果用过扫码登录，确认设备管理里没有遗留。
- `out/` 已 gitignore；不要提交 `responses/`。

---

## 11. 一页检查清单

- [ ] Windows / Chrome / Python / Playwright 已检查
- [ ] 专用 profile 的 Chrome 已用 CDP 9222 启动
- [ ] 专用测试账号已人工扫码登录
- [ ] 探针至少运行一次
- [ ] `report.md`、`summary.json`、`env.json` 存在
- [ ] `summary.json` 中 `login=true`，无 captcha/modal
- [ ] A/B/C/D 四节都存在
- [ ] `probe_signature.py` 已运行
- [ ] `signature_report.md`、`signature_summary.json` 存在
- [ ] `handoff/` 中没有 cookie/header/`responses/`
- [ ] 执行记录已写
