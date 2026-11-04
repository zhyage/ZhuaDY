# 共享文件夹 Agent 协作协议（v1.0）

> 日期：2026-10-30
> 参与方：Linux agent、Windows agent、人类通知者
> 共享目录：Linux `/data/shareFolder/douYin`；Windows `Z:\douYin`（`\\192.168.199.193\shareFolder`）
> 高层说明：[agentsCooperation.md](agentsCooperation.md)
> 状态：协议草案；双方对齐后按本文件执行

---

## 0. 一句话

**把共享目录当成信箱：每一轮实验是一个独立、不可变的文件夹；Linux 写 `require/`，Windows 写 `result/`；人类只负责通知，不搬运文件。**

```text
Linux agent                          Windows agent
    |                                     |
    | 1. mkdir douYin/<round>/require/    |
    | 2. 写 README + task.json + inputs   |
    | 3. 写 require/READY（最后）         |
    | 4. 通知你 -------------------------> | 5. 你通知它
    |                                     | 6. 读 require/，复制 inputs 到本地
    |                                     | 7. 执行实验
    |                                     | 8. 写 result/，最后写 result/READY
    | 10. 你通知它 <---------------------- | 9. 通知你
    | 11. 读 result/，决定下一轮          |
```

**不打 zip。** `require/inputs/` 直接放目录和文件；Windows 直接复制目录到本地工作区，不解压。

---

## 1. 环境与路径

| 项目 | 值 |
|---|---|
| Linux 共享根 | `/data/shareFolder` |
| Linux 协作根 | `/data/shareFolder/douYin` |
| Windows 映射 | `Z:` → `\\192.168.199.193\shareFolder` |
| Windows 协作根 | `Z:\douYin` |
| 当前权限 | `douYin` 为 `777`；Linux 以 `vdmc34` 写入；Windows 以 Samba guest 写入 |
| 编码 | JSON/Markdown 一律 UTF-8（无 BOM）；`.ps1` 保持 ASCII，中文放 JSON/MD |
| 时间 | round id 和元数据用 UTC，ISO 8601，例如 `2026-10-30T05:20:00Z` |

**权限注意：**

- Linux 创建 round 目录后执行 `chmod 777 <round>`，确保 Windows guest 能创建 `result/`。
- `require/` 对 Windows 只读：Linux 写完执行 `chmod -R a+rX require`。
- 如果 Windows 写出的 `result/` 让 Linux 读不了，优先在 Samba 配置里启用 `force user = vdmc34` / `force group = vdmc34`，而不是反复 chmod。

---

## 2. 目录结构

每一轮一个文件夹，**round id 全局唯一，永不复用**：

```text
/data/shareFolder/douYin/
  20261030T052000Z-signature-check/
    require/                    # Linux 写；Windows 只读
      READY                     # Linux 最后写；提交标记
      README.md                 # 给人看：目标、步骤、输入、输出、安全
      task.json                 # 给 agent 看：机器可读任务单
      inputs/                   # 直接放目录/文件，不打 zip
        windows-reply/
          probe_reply.py
          probe_signature.py
          run_probe.ps1
          targets.json
          common_params.json
          README.md
          WINDOWS_AGENT_RUNBOOK.md
          ANALYSIS.md
    result/                     # Windows 写；Linux 只读
      READY                     # Windows 最后写；提交标记
      result.json               # 机器可读结果
      outputs/                  # 期望输出
        signature_report.md
        signature_summary.json
```

规则：

- `require/` 和 `result/` 是**只读边界**：Windows 不改 `require/`，Linux 不改 `result/`。
- 一轮完成后不再修改；需要重跑或补充，创建新的 round。
- 不使用符号链接；不在共享目录里跑会产生大量临时文件的程序。
- Windows **必须先把 `require/inputs/...` 复制到本地工作区**再运行，避免 Python 在 `require/` 里生成 `__pycache__`、`out/` 等写入。

---

## 3. 轮次命名与选择

格式：

```text
YYYYMMDDTHHMMSSZ-<slug>
```

示例：

```text
20261030T052000Z-signature-check
20261030T061500Z-full-thread
20261030T073000Z-locale-retest
```

- `YYYYMMDDTHHMMSSZ` 是 UTC；Linux 用 `date -u +%Y%m%dT%H%M%SZ` 生成。
- `slug` 只用小写字母、数字、连字符；不要空格/中文。
- 人类通知里必须带**完整 round id**；Windows 以通知里的 id 为准，不要自己猜“最新”。
- 如果 Windows 必须自己发现：选择字典序最大、存在 `require/READY`、且不存在 `result/READY` 的 round；仍要用 `task.json` 的 `request_id` 校验。
- **一次只允许一个 in-flight round**。Linux 在上一轮 `result/READY` 出现前，不创建下一轮（除非明确标记为并行任务）。

---

## 4. 写权限与职责

| 角色 | 可写 | 只读 | 禁止 |
|---|---|---|---|
| Linux agent | `require/`、round 目录本身 | `result/`（等 `result/READY` 后） | 写 `result/`、改已完成轮次 |
| Windows agent | `result/` | `require/` | 写 `require/`、改 `require/`、在 `require/` 里跑程序 |
| 人类 | 无（只通知） | 全部 | 手工搬文件（除非协议失败） |

Linux 创建 round 后：

```bash
chmod 777 /data/shareFolder/douYin/<round>
chmod -R a+rX /data/shareFolder/douYin/<round>/require
```

---

## 5. 任务单：`require/task.json`

Linux 写，Windows 读。最小字段：

```json
{
  "protocol_version": "1.0",
  "request_id": "20261030T052000Z-signature-check",
  "created_at": "2026-10-30T05:20:00Z",
  "from": "linux-agent",
  "to": "windows-agent",
  "task": "signature-check",
  "summary": "运行 probe_signature.py，确认页面是否自动补签名",
  "instructions": "README.md",
  "inputs_dir": "inputs/windows-reply",
  "entrypoint": "inputs/windows-reply/WINDOWS_AGENT_RUNBOOK.md#0",
  "expected_outputs": [
    "outputs/signature_report.md",
    "outputs/signature_summary.json"
  ],
  "constraints": {
    "read_only": true,
    "no_cookies_in_share": true,
    "no_raw_responses": true,
    "max_runtime_minutes": 10,
    "max_retries": 1
  },
  "acceptance": [
    "signature_report.md 存在且非空",
    "signature_summary.json 可解析为 JSON",
    "outputs 中无 cookie/header 值"
  ]
}
```

字段约定：

| 字段 | 说明 |
|---|---|
| `protocol_version` | 双方校验；主版本不匹配就拒绝执行并写 `blocked` |
| `request_id` | 必须与 round id 一致 |
| `task` | 短任务名，用于日志/下一轮引用 |
| `instructions` | 人读说明，相对 `require/` |
| `inputs_dir` | 输入目录，相对 `require/` |
| `entrypoint` | Windows 具体先读哪个文件/章节 |
| `expected_outputs` | 期望输出，相对 `result/` |
| `constraints` | 只读、是否允许 raw、时限、重试次数 |
| `acceptance` | Linux 验收条件 |

---

## 6. 人读说明：`require/README.md`

Linux 写，**必须自包含**，至少包含：

1. 本轮目标（一句话）；
2. Windows 要读的入口（例如 `WINDOWS_AGENT_RUNBOOK.md` §0）；
3. 输入目录和是否需要复制到本地；
4. 精确命令；
5. 期望输出文件；
6. 安全约束（只读、不点赞/关注/评论、不带 cookie）；
7. 失败时怎么写 `result/`；
8. 明确“不要做什么”（不要重跑上一轮、不要改 `require/`、不要上传 `responses/`）。

`README.md` 给人看；`task.json` 给机器看；两者内容不能矛盾。

---

## 7. 结果：`result/result.json`

Windows 写，Linux 读。**即使失败也必须写。** 最小字段：

```json
{
  "protocol_version": "1.0",
  "request_id": "20261030T052000Z-signature-check",
  "status": "success",
  "started_at": "2026-10-30T05:21:10Z",
  "finished_at": "2026-10-30T05:23:40Z",
  "agent": "windows-agent",
  "host": "windows-vm",
  "commands": [
    {
      "cmd": "python probe_signature.py --targets targets.json --common-params common_params.json",
      "exit_code": 0,
      "duration_s": 145.2
    }
  ],
  "outputs": [
    {
      "path": "outputs/signature_report.md",
      "bytes": 2048,
      "sha256": "..."
    },
    {
      "path": "outputs/signature_summary.json",
      "bytes": 8192,
      "sha256": "..."
    }
  ],
  "errors": [],
  "notes": "Chrome 156 / Windows 10 / en-US; no captcha",
  "next_round_hint": "可进入 full-thread 或 count=50"
}
```

`status` 取值：

| 状态 | 含义 |
|---|---|
| `success` | 全部期望输出存在，验收通过 |
| `failed` | 执行了，但没有可用输出 |
| `partial` | 部分输出，缺少期望文件 |
| `blocked` | 没能开始（登录、CDP、权限、输入缺失） |

规则：

- `request_id` 必须与 `task.json`/round id 一致。
- `outputs[].path` 相对 `result/`；文件必须真实存在、非空。
- `sha256` 可选；Windows 可用 `Get-FileHash`。
- `errors` 放错误摘要，不放大段日志；完整日志可在 `result/outputs/` 里，但不得含 cookie/header 值。
- 不要写 `raw_url`、cookie、`a_bogus`、`msToken`、`bd-ticket-guard-*` 的值。

---

## 8. READY 标记与写入顺序

### Linux 写 `require/`

1. 创建 round 目录；
2. 写 `README.md`、`task.json`、`inputs/`；
3. 校验 `task.json` 可解析、所有 `inputs` 存在；
4. 执行 `chmod -R a+rX require`；
5. **最后**写 `require/READY`：

```json
{
  "request_id": "20261030T052000Z-signature-check",
  "ready_at": "2026-10-30T05:20:30Z",
  "role": "linux"
}
```

### Windows 读 `require/`

- 只有 `require/READY` 存在时才开始；
- 读取 `task.json`，校验 `request_id` 与 READY/round id 一致；
- 若 READY 不存在或 JSON 不完整：等待 10 秒重试一次；仍不行则写 `result/result.json`（`status=blocked`，`errors=["require/READY missing"]`），最后写 `result/READY`。

### Windows 写 `result/`

1. 创建 `result/`、`result/outputs/`；
2. 执行实验，把输出复制到 `result/outputs/`；
3. 写 `result/result.json`；
4. 校验 JSON 可解析、期望输出存在；
5. **最后**写 `result/READY`：

```json
{
  "request_id": "20261030T052000Z-signature-check",
  "status": "success",
  "ready_at": "2026-10-30T05:23:45Z",
  "role": "windows"
}
```

### Linux 读 `result/`

- 只有 `result/READY` 存在时才读；
- 校验 `request_id` 与当前 round 一致；
- 校验 `status`、`outputs`、`acceptance`；
- 如果 `result/` 存在但没有 READY：视为进行中/不完整，不解析部分输出。

---

## 9. 人类通知模板

### Linux → 人类

```text
Round <round_id> ready.
Task: <task>
Path: /data/shareFolder/douYin/<round_id>
Please ask the Windows agent to process this exact round.
```

### 人类 → Windows agent

```text
Process round <round_id> at Z:\douYin\<round_id>.
Read require\README.md and require\task.json first.
Copy require\inputs\... to a local work dir; do not write inside require\.
Write only result\; write result\result.json and result\READY last.
```

### Windows agent → 人类

```text
Round <round_id> done.
Status: <success|failed|partial|blocked>
Result: Z:\douYin\<round_id>\result
```

### 人类 → Linux agent

```text
Round <round_id> done.
```

**通知必须带 round id。** 不要说“最新那个”，避免双方看到不同轮次。

---

## 10. 失败、重试与下一轮

- Windows 失败：仍写 `result/result.json` + `result/READY`，`status=failed` 或 `blocked`，`errors` 写原因。
- Windows 最多重试 `constraints.max_retries` 次（默认 1）；不要无限重跑。
- Linux 读到失败：
  - 输入/权限/登录问题 → 人类修复后，创建新的 `...-retry` round；
  - 实验本身失败（例如签名检查 0 字节）→ 记录为结果，不自动重跑；决定下一轮任务。
- 不在旧 round 上改文件；所有补充都是新 round。
- 历史 round 保留用于审计；清理需双方确认。

---

## 11. 安全与数据卫生

- 共享目录**不放**：cookie、`.secrets`、`sessionid`、`a_bogus`、`msToken`、`bd-ticket-guard-*` 值、完整 raw 响应中的用户 PII。
- `require/` 只放：脚本、配置、公开 ID、脱敏说明。
- `result/` 只放：摘要、报告、聚合结果；如确需 raw，必须在 `task.json` 里显式允许并写保留期限。
- Windows 不得把 `out/responses/` 复制进 `result/`，除非 `task.json` 明确要求。
- Samba 是 LAN 共享；当前 `guest ok = yes`、`douYin` 777。建议后续启用 `force user = vdmc34`、限制 `valid users` 或防火墙，减少误写/越权。
- 不在共享目录里存放与该项目无关的文件。

---

## 12. 当前第一轮示例：`signature-check`

建议 round id：

```text
20261030T<HHMMSS>Z-signature-check
```

`require/README.md` 核心内容：

```text
你已经跑完第一次 probe_reply.py（A/B/C PASS）。本轮只做签名机制补充实验。

工作目录（复制到本地后运行）：
  require\inputs\windows-reply

入口：
  WINDOWS_AGENT_RUNBOOK.md 的 §0（只执行 §0，不要重跑 §3–§6）

命令：
  python probe_signature.py --targets targets.json --common-params common_params.json

输出（复制到 result\outputs\）：
  signature_report.md
  signature_summary.json

然后写 result\result.json 和 result\READY。
不要写 require\；不要回传 cookie/header/responses。
```

`require/task.json` 关键字段：

```json
{
  "protocol_version": "1.0",
  "request_id": "20261030T<HHMMSS>Z-signature-check",
  "from": "linux-agent",
  "to": "windows-agent",
  "task": "signature-check",
  "summary": "运行 probe_signature.py S1-S4，确认页面是否自动补签名",
  "instructions": "README.md",
  "inputs_dir": "inputs/windows-reply",
  "entrypoint": "inputs/windows-reply/WINDOWS_AGENT_RUNBOOK.md#0",
  "expected_outputs": [
    "outputs/signature_report.md",
    "outputs/signature_summary.json"
  ],
  "constraints": {
    "read_only": true,
    "no_cookies_in_share": true,
    "no_raw_responses": true,
    "max_runtime_minutes": 10,
    "max_retries": 1
  }
}
```

Linux 侧创建顺序：

```bash
ROUND=20261030T<HHMMSS>Z-signature-check
mkdir -p /data/shareFolder/douYin/$ROUND/require/inputs
cp -a spike/windows-reply /data/shareFolder/douYin/$ROUND/require/inputs/
# 写 README.md、task.json
chmod 777 /data/shareFolder/douYin/$ROUND
chmod -R a+rX /data/shareFolder/douYin/$ROUND/require
# 最后写 require/READY
```

Windows 侧流程：

1. 把 `Z:\douYin\<round>\require\inputs\windows-reply` 复制到本地，例如 `C:\work\douyin-reply-<round>`；
2. 在本地目录运行 `probe_signature.py`；
3. 把 `out\signature-*\signature_report.md`、`signature_summary.json` 复制到 `Z:\douYin\<round>\result\outputs\`；
4. 写 `result\result.json`；
5. 最后写 `result\READY`。

---

## 13. 双方对齐检查清单

### Linux 写 READY 前

- [ ] round id 是 UTC、ASCII、唯一
- [ ] `require/README.md` 自包含
- [ ] `require/task.json` 可解析，`request_id` 与 round id 一致
- [ ] `inputs/` 完整（目录直接放，不打 zip）
- [ ] 没有 `__pycache__/`、`*.pyc`、`out/`、`chrome-profile/`
- [ ] 没有 cookie/secret/raw PII
- [ ] `chmod 777 <round>`；`chmod -R a+rX require`
- [ ] `require/READY` 最后写

**打包卫生：** 用 `rsync -a --exclude '__pycache__' --exclude '*.pyc' --exclude 'out' ...`；不要在 `require/` 里运行 Python；自测用 `PYTHONDONTWRITEBYTECODE=1` 或在 `/tmp` 副本运行。

### Windows 写 READY 前

- [ ] 只处理通知里的 round id
- [ ] 先复制 `require/inputs/...` 到本地，未写 `require/`
- [ ] `result/outputs/` 里期望文件存在且非空
- [ ] `result/result.json` 可解析，`request_id` 一致
- [ ] 没有 cookie/header/`a_bogus`/`msToken` 值
- [ ] `result/READY` 最后写

### Linux 读 result 后

- [ ] `result/READY` 存在
- [ ] `request_id` 一致
- [ ] `status` 合法
- [ ] `outputs` 与 `acceptance` 通过
- [ ] 记录本轮；决定下一轮（新 round）

---

## 14. 版本与变更

- 当前 `protocol_version: "1.0"`。
- 任何字段/目录结构变更都要升版本，并在 `task.json` 里声明。
- 双方只接受 `1.x`；主版本不匹配时，Windows 写 `status=blocked`，Linux 不读结果。
- 本文件是权威协议；[agentsCooperation.md](agentsCooperation.md) 是高层背景说明。
