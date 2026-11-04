# Windows 回复 Worker 可行性实验

这个目录是 Phase 0.5 的最小探针，用来回答：

1. 真实 Windows 桌面 Chrome 能否稳定拿到 reply 响应？（A）
2. 能否不滚动到评论、直接按 `comment_id` 请求回复？（B/C/D）
3. reply 请求的页大小、请求头、响应结构是什么？
4. 单线程耗时和风险信号是什么？

**只读实验：** 不点赞、不关注、不评论；出现验证码/登录墙立即停。

---

## 1. 前置条件

| 项目 | 要求 |
|---|---|
| Windows | Windows 10/11，真实 GPU + 显示器 |
| Chrome | 已安装的 Google Chrome（不要用无头模式） |
| Python | 3.10+；`pip install playwright` |
| 网络 | 国内直连抖音；不要走国外 VPN |
| 账号 | 专用测试账号；不要用主账号 |
| 机器 | 不休眠；实验期间不要关闭 Chrome 窗口 |

如果 Windows 上已经有 anotherImplement 的 `.venv`，可以直接用它的 Python；它已经装了 Playwright。

---

## 2. 启动 Chrome（独立 profile + CDP 9222）

在 PowerShell 里：

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

然后在**这个 Chrome 窗口**里扫码登录专用账号。

验证 CDP：

```powershell
Invoke-RestMethod http://127.0.0.1:9222/json/version
```

如果 Chrome 已经用默认 profile 开着，直接加 `--remote-debugging-port` 通常不会生效；请用上面的独立 `--user-data-dir` 启动第二个实例。

---

## 3. 运行探针

把本目录复制到 Windows，进入目录：

```powershell
cd path\to\windows-reply
python -m pip install playwright

python probe_reply.py --targets targets.json
```

`targets.json` 里已经写好默认的视频/评论/深评论；这样避免 Windows PowerShell 5.1 对中文字符串的编码问题。

如果你要手动指定，也可以：

```powershell
python probe_reply.py `
  --video-id 7681929945538497843 `
  --comment-id 7682054941225698091 `
  --comment-text "爷爷考虑到大家太热情会有安全隐患" `
  --deep-comment-id 7682223064176395049
```

参数说明：

| 参数 | 默认 | 说明 |
|---|---|---|
| `--targets` | 无 | 从 UTF-8 JSON 读取目标；`run_probe.ps1` 默认传 `targets.json` |
| `--video-id` | `7681929945538497843` | 测试视频 |
| `--comment-id` | `7682054941225698091` | 106 条回复的目标线程 |
| `--comment-text` | `爷爷考虑到大家太热情会有安全隐患` | 用于在 DOM 里定位目标线程；找不到就换更短/更独特的子串 |
| `--deep-comment-id` | `7682223064176395049` | 第 5 页的一条评论，用来测试“首屏不可见也能定向请求” |
| `--max-scrolls` | `40` | 最多滚动多少轮；目标找不到时可加大 |
| `--max-pages` | `3` | 安全上限；A 只翻 3 页，避免一次跑太久 |
| `--skip-b` / `--skip-c` / `--skip-d` | — | 跳过某个实验 |

如果目标评论在页面上找不到，先确认视频页评论区已经加载；也可以把 `--comment-text` 换成更短的独特片段，或加大 `--max-scrolls`。

### 3.1 签名机制补充实验（推荐）

第一次探针通过后，再跑：

```powershell
python probe_signature.py --targets targets.json --common-params common_params.json
```

它回答：页面内 `fetch` 成功，是因为抖音页面自动补了 `a_bogus`/`bd-ticket-guard`，还是接口真的免签。输出在 `out/signature-<timestamp>/`：

```text
signature_report.md
signature_summary.json
```

`common_params.json` 来自第一次成功运行（RDP/Chrome 156/en-US）。换了机器或 Chrome 版本时可以不传，脚本会用最小参数；但用同一台机器复测更准确。

---

## 4. 输出

每次运行创建 `out/run-<timestamp>/`：

```text
out/run-20261029-120000/
  env.json              # UA / webdriver / WebGL / 登录态；无 cookie
  A_metrics.json        # UI 点击 + 监听的页数/条数/has_more/cursor
  B_metrics.json        # 页面内 bare fetch 结果
  C_metrics.json        # 重放签名 URL 的三个变体
  D_globals.json        # 页面 globals 名字（诊断）
  summary.json          # 机器可读汇总
  report.md             # 人读报告
  responses/            # 原始响应；含用户内容，不要提交 git
```

**回传给我：** `report.md`、`summary.json`，以及签名实验的 `signature_report.md` / `signature_summary.json`。不要回传 `out/responses/`、cookie、`bd-ticket-guard-*` 值或 `a_bogus` 值。

---

## 5. 结果怎么读

| 结果 | 含义 | 下一步 |
|---|---|---|
| A PASS | Windows 桌面 Chrome 能拿到回复 | Windows worker 可行 |
| B PASS | 页面内 bare fetch 可用，且能按 `comment_id` 定向 | 可做线程级 worker |
| C-unchanged PASS，C-cursor/comment_id FAIL | 签名绑定参数；只能 UI 触发 | 视频级 worker |
| C-cursor 或 C-comment_id PASS | 签名不绑定该参数；可直接翻页/定向 | 线程级 worker |
| A FAIL | Windows 桌面也被阻断 | 商业工具或一级评论 |

**注意：** B 很可能失败，因为 bare `fetch` 不会自动生成 `a_bogus`/`bd-ticket-guard`。B 失败不等于 Windows 路径失败；A 才是基线。

---

## 6. 安全

- 专用测试账号；独立 Chrome profile；不要用主账号。
- 只读；不点赞、不关注、不评论。
- 出现验证码、登录弹窗、连续空 body 立即停。
- 不把 cookie、请求头值、`a_bogus`、`mstoken` 写入仓库或报告。
- 实验结束后可以删除 `%USERPROFILE%\douyin-reply-profile`；如果用过扫码登录，确认设备管理里没有遗留。
- `out/` 已在 `.gitignore` 中；不要手动提交原始响应。

---

## 7. 常见问题

**`connect_over_cdp` 失败**
Chrome 没有用 `--remote-debugging-port=9222` 启动，或 9222 被占用。先访问 `http://127.0.0.1:9222/json/version`。

**`not logged in`**
在 Chrome 窗口里扫码登录，然后重新运行。脚本不会自动登录。

**A 没有 reply 响应**
可能目标线程已经展开、按钮被遮挡，或页面没有加载评论。先手动点一次“展开回复”，确认页面正常；再重跑。报告里的 `stop_reason` 会说明卡在哪一步。

**B/C 返回 0 字节**
这是有价值的结果，不是脚本错误。记录 `status`、`bytes`、`stop_reason`，回传报告即可。

**目标评论找不到**
Douyin 的评论列表是热度排序、懒加载；目标可能在更下面。加大 `--max-scrolls`，或换一条靠前的评论做 A。B/C/D 不依赖目标可见，仍然可以测。
