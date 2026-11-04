# Phase 1 Pilot Spec — 绍兴文旅

> 日期：2026-10-30
> 状态：Stage 1–6 完成（视频列表 + 20 个视频 + 一级评论 + 回复入库 + Parquet/CSV 导出）；IRB/保留期按 §9
> 账号：绍兴文旅 `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c`
> 关联：[ROADMAP.md](ROADMAP.md)、[DESIGN.md](DESIGN.md)、[FEASIBILITY.md](FEASIBILITY.md)、[WINDOWS_REPLY_WORKER.md](WINDOWS_REPLY_WORKER.md)

---

## 1. 目标与非目标

**目标：** 用 1 个账号、20 个视频跑通端到端采集：

```text
v5：账号 + 全量视频列表 + 20 个视频的一级评论
Windows worker：3 个深抓视频的全部 thread + 17 个浅抓视频的前 10 个 thread
Linux：入库、去重、隐私转换、Parquet/CSV 导出、质量报告
```

**非目标（本轮不做）：**

- 10–50 个账号；
- 正式研究抽样与统计推断；
- 视频下载、ASR、画面分析；
- 生产级任务队列/多 worker 调度；
- 最终字段删减和长期保留策略。

> 2026-10-31 更新：视频下载从“后续可选”提升为**下一轮 P5a**（只下载选中视频，不做 ASR/字幕）；本 pilot 仍未下载视频文件。画面分析（人物/室内外）属于后续 P5b。

---

## 2. 账号与视频宇宙

| 项目 | 值 |
|---|---|
| 账号 | 绍兴文旅 |
| `sec_uid` | `MS4wLjABAAAAiMZ9g1K7M-5mxJboftrs_g_aKwMml8wf5gXFd-r4U0c` |
| `unique_id` | `yujianshaoxing` |
| 已知规模（2026-10-30 快照） | 730 个作品，369,507 粉丝 |

**第一步：拉全量视频列表。** 用 v5 `author_posts` 翻完所有页，存全部视频元数据（不是只存 20 条），用于：

- 记录平台总数 vs 实际抓到；
- 后续正式研究重新抽样；
- 检查视频是否被删除/私密。

**已知污染（2026-10-30 实测）：** `author_posts` 返回 **765 条 unique**，其中：

- **730 条** 作者是绍兴文旅本人（与 profile `content_count=730` 一致）；
- **35 条** 是其他作者（合作/品牌账号，约 4.6%）。

所以 `video` 表保存 `author_sec_uid` 和 `is_target_author`；**选 20 个 pilot 视频时只取 `is_target_author=true`**。其他作者的视频保留在表里用于审计，但不进入 pilot 样本。

**过滤（仅用于选 20 个 pilot 视频）：**

- `is_target_author = true`；
- 排除 deleted / private；
- `comment_count >= 1`；
- 不按 duration/likes 过滤（pilot 不追求代表性，只追求跑通）。

**选 20 个视频（pilot 专用，不是最终研究样本）：**

1. **10 个高评论视频**：按 `comment_count` 降序（tie 用 `digg_count`）。
2. **10 个时间跨度视频**：剩余视频按发布时间排序，等距取 10 个。
3. 去重；如果过滤后不足 20 个，取全部。
4. 一级评论抓完后，从 20 个中选 **3 个深抓视频**：优先选“有回复的 thread 数”最多的 3 个；其余 17 个为浅抓。

---

## 3. 抓取范围

| 数据 | 来源 | 范围 | 说明 |
|---|---|---|---|
| 账号资料 | v5 `/douyin/user` | 1 个 | 存 raw |
| 视频列表 | v5 `/douyin/user/posts` | 全部 765（730 target + 35 other） | 全部页；记录 `has_more`/`guest_fallback`/`author_sec_uid` |
| 一级评论 | v5 `/douyin/video/comments` | 20 个视频，全部 | `count=50`、`include_raw=true`；翻到 `cap_reached`/`UPSTREAM_CHANGED` |
| 深抓回复 | Windows worker | 3 个视频，所有 `reply_count > 0` 的 thread | `count=50`；每 thread 最多 10 页；翻到 `has_more=false` |
| 浅抓回复 | Windows worker | 17 个视频，每视频前 10 个 thread（按 `reply_count` 降序，tie `digg_count`） | `count=50`；每 thread 最多 3 页 |
| 视频文件 | Windows/Linux 下载 | 下一轮 P5a：只下载选中视频 | 本 pilot 未下载；不做 ASR/字幕 |

**Thread 选择顺序：**

1. 先抓 20 个视频的一级评论；
2. 用一级评论的 `reply_count` 选 thread；
3. 生成 `jobs.json`（每个视频一组 thread，标注 deep/shallow、max_pages）；
4. Windows worker 按 job 执行；
5. Linux 合并结果。

---

## 4. 输出与存储（pilot 阶段“尽量多存”）

### 4.1 Postgres 草表（`douyin_research`）

pilot 阶段保留尽量多的字段，不提前删减：

| 表 | 关键字段 |
|---|---|
| `run` | run_id、account、started/finished、v5 version、worker version |
| `account` | sec_uid、unique_id、nickname、follower_count、raw |
| `video` | aweme_id、account_id、author_sec_uid、author_nickname、is_target_author、caption、created_at、duration、stats、raw |
| `comment` | comment_id、aweme_id、thread_root_id、reply_to_comment_id、depth、is_orphan、text、created_at、digg_count、ip_province、is_author、is_thread_author（pilot 预留 null）、author_hash、label_text(s)、source、raw_sha256 |
| `comment_raw` | comment_id、raw_json（仅 pilot，限制访问） |
| `comment_fetch_state` | run_id、thread_id、cursor、pages_done、has_more、expected_total、fetched、coverage、stop_reason |
| `quality_metric` | expected/fetched/unique/duplicates/orphans/depth3/coverage/stop_reason |
| `worker_job` | job_id、aweme_id、threads、status、attempt、lease、result_path |

**原则：**

- 分析表（`comment`）**保留完整评论文本**；只移除/哈希直接身份字段（昵称/头像/签名/UID），存 `author_hash`；
- `comment_raw` 只在 pilot 保留，访问受限，不导出到 Parquet/CSV；
- 按 `(aweme_id, comment_id)` upsert 去重；
- 所有 raw 文件路径和 `raw_sha256` 记录在案。

### 4.1.1 文本、身份、发表三层

| 层 | 存什么 | 用途 | 访问 |
|---|---|---|---|
| Raw vault | 完整原始 JSON（含昵称/头像/UID/文本） | 复核、重跑、抽检 | 仅研究负责人，本地加密/受限 |
| Analysis DB | **文本** + 评论/线程结构 + `author_hash` + `ip_province` + 时间/点赞；无昵称/头像/UID | 态度/意愿编码、统计 | 研究团队 |
| Publication | 聚合统计；短引用脱敏/改写 | 论文/报告 | 公开 |

- **文本是核心研究数据，完整保留**；不要为了“隐私”删文本。
- 身份字段只从分析/发表层移除；raw vault 里仍可保留用于复核，但不共享。
- `author_hash` 用于“同一个人/同一作者”的关联；不需要知道真实身份。
- **伪名化不等于匿名化**：文本里可能有姓名、地点、电话、罕见经历；发表前要脱敏/改写。

### 4.2 Raw 文件

- Linux：`data/raw/<run_id>/...`，保存 v5 原始响应（视频列表、一级评论）；
- Windows：`out/.../raw/`，保存 reply 原始页；
- raw 只留在本地受控目录，不放进共享目录、不进 git；
- pilot 阶段尽量全量保存，待 IRB/需求稳定后再做保留期和字段删减。

### 4.3 Parquet

每次 run 结束导出：

```text
exports/<run_id>/
  videos.parquet
  comments.parquet
  reply_edges.parquet
  quality.parquet
  manifest.json
```

- `comments.parquet` 含分析字段 + `raw_sha256`，不含原始 PII；
- `reply_edges.parquet` 含 `child_id, parent_id, thread_root_id, depth, orphan`；
- `manifest.json` 含 schema、row counts、coverage、字段字典、生成时间。

### 4.4 CSV

只做小样本/QA/Stata/SPSS/Excel：

```text
exports/<run_id>/samples/
  comments_sample.csv      # 每视频前 100 条，UTF-8-sig
  replies_sample.csv       # 每 thread 前 50 条
```

- 不作为全量语料库；
- 导出前再次检查无昵称/头像/签名/原始 UID。

---

## 5. 隐私与保留

- 共享目录只放脚本、job、summary；不放 raw、cookie、原始用户对象。
- 分析表**保留文本**，只存 `author_hash`（HMAC-SHA256 + salt）；昵称/头像/签名/UID 不进入分析表。salt 在 Linux 环境变量，不进仓库/共享目录。
- `comment_raw` 仅 pilot 保留，DB 权限限制；Parquet/CSV 不含。raw vault 用于复核，不对外。
- 发表层只放聚合统计或短引用；引用要改写/遮蔽姓名、地点、联系方式、罕见事件；不附用户主页链接，不公开全量文本 dump。
- 保留期：按 §9 已确认计划，pilot 结束后保留 90 天再复核，不提前删除，也不对外共享。文本和 raw 的保留期可以不同：分析文本按研究需要保留，raw vault 按 IRB 最短必要保留。
- 如 IRB 要求更短保留期或字段限制，在 pilot 前调整。

---

## 6. 执行阶段

| 阶段 | 内容 | 负责 |
|---|---|---|
| 0 | v5/DB/共享目录/Windows worker 就绪 | Linux + Windows |
| 1 | 拉全量视频列表（765：730 target + 35 other） | Linux/v5 |
| 2 | 选 20 个视频；抓一级评论；存 raw | Linux/v5 |
| 3 | 选 3 深 + 17 浅 thread；生成 `jobs.json` | Linux |
| 4 | Windows worker 抓回复；写 raw/normalized/state | Windows |
| 5 | 合并/upsert；隐私转换；质量报告 | Linux |
| 6 | Parquet/CSV 导出；`PILOT.md` | Linux |

**时间预估：** 采集 2–5 个工作日（取决于评论量/风控），加修复 1–2 周。

### 6.1 Stage 1 实际结果（2026-10-30）

- 19 页；765 unique；**730 target author + 35 other author**；0 deleted/private；`guest_fallback=null`。
- 时间范围：2020-09-30 至 2026-10-20；target profile `content_count=730`，与 730 一致。
- `douyin_research`：`account=1`、`video=765`、`run=1`；raw 页 19 个，account raw 1 个。
- 20 个 pilot 视频已选：10 个高评论 + 10 个时间跨度；见 `data/pilot/pilot-20261030-01/selected_videos.csv` 和 `sql/select_pilot_videos.sql`。

**Stage 2 实际结果（2026-10-30）：**

- 20/20 视频 `stop_reason=complete`；0 风控；0 `guest_fallback`。
- 23,012 条 unique 一级评论；24,847 次返回；1,835 条重复（7.4%）。
- 1,702 个 thread 候选（`reply_count>0`）。
- `ip_province` 非空 20,711 / 23,012（约 90%）；`is_author=true` 7 条（绍兴文旅回复了 7 条一级评论）。
- 入库：`comment=23,012`、`comment_raw=23,012`、`comment_fetch_state=20`、`quality_metric=20`。
- 重要说明：`coverage = unique / platform_comment_count` 在 7k 评论视频上只有 33–69%，因为分母包含回复；**`complete` 表示 v5 的一级评论列表已经耗尽**，不能把 33% 当作“一级评论只抓了三分之一”。

**Stage 3 实际结果（2026-10-30）：**

- 3 个深抓视频：`7681660984184153322`（215 threads）、`7572040672217333163`（278）、`7483476437522025738`（201）；共 694 threads，expected replies 2,408。
- 14 个浅抓视频：每视频前 10 个 thread（不足 10 个则全部）；共 110 threads，expected replies 2,402。
- 3 个视频没有 `reply_count>0` 的 thread，跳过：`7046569627224182024`、`7119897729882475812`、`7555457713829711146`。
- 合计 17 jobs、804 threads；Stage 3 基于一级评论 `reply_count` 估算 4,810 expected replies；见 `data/pilot/pilot-20261030-01/jobs.json`。

**Stage 4 实际结果（2026-10-30）：**

- Round 005 `20261030T125114Z-pilot-replies` 回传：17 个 normalized JSONL、4,199 条 unique 回复、0 重复、0 空文本。
- 801/804 线程 `complete`；3 个浅抓线程按设计在 `max_pages=3` 停止（均为 shallow）。
- 全部 804 threads 的端点 `total` 合计 4,835（Stage 3 估算 4,810，+25 为平台计数漂移）；整体 coverage 4,199/4,835 = 86.85%。
- 801 个 `complete` 线程：3,751/3,759 = 99.79%；793 个完全相等，7 个合计缺 10 条，1 个多 2 条。
- `orphan_edges=43`；`depth is null=72`（43 个孤儿 + 29 个孤儿后代）；最大 depth=14；父子关系 0 矛盾。
- `ip_province` 非空 4,109/4,199 = 97.86%；`is_author=true` 57 条，与 `label_text='作者'` 完全一致；`author_hash` 100% 非空，554 个哈希与一级评论作者重合，salt 一致。
- **两次人工人机验证**：用户在 Windows 浏览器中手动通过；worker 未记录 `risk_control`/0 字节，801 个完整线程的缺口只有 10 条，未发现验证导致的数据损失。该事件已记入 `run.notes`，生产需验证码检测/人工值守。
- 入库：`comment=27,211`（23,012 top_level + 4,199 reply）、`quality_metric=841`（20 一级 + 804 线程 + 17 视频汇总）、`worker_job=17`（15 success + 2 partial）；回复 raw/state 留在 Windows 本地，`comment_raw` 仍只含一级评论。
- 质量报告：`data/pilot/pilot-20261030-01/replies_import/STAGE5_REPORT.md`；指标：`stage5_metrics.json`。

**Stage 6 实际结果（2026-10-30）：**

- 导出目录：`exports/pilot-20261030-01/`。
- Parquet：`videos.parquet` 765 行、`comments.parquet` 27,211 行、`reply_edges.parquet` 4,199 行、`quality.parquet` 841 行；zstd 压缩。
- CSV samples：`comments_sample.csv` 1,336 行（每视频前 100 条）、`replies_sample.csv` 3,311 行（每 thread 前 50 条），UTF-8-sig。
- `manifest.json`：schema、行数、覆盖率、字段字典、文件 SHA256；`README.md` 说明导出层与隐私边界。
- 字段缺口：`videos.play_count` 全 NULL、`duration_ms` 3 个 NULL；回复的 `reply_count`/`is_pinned`/`is_author_liked` 未采集。
- 导出不含昵称/头像/签名/sec_uid/raw_json/cookie/header；`text` 保留，分析层使用，发表前脱敏。

---

## 7. 验收标准

### 视频与一级评论

- [ ] 全量视频列表条数与平台显示一致（记录差值）：target 730 与 profile 一致；other 35 单独记录。
- [ ] 20/20 pilot 视频均为 `is_target_author=true`；other-author 视频不进入 pilot 样本。
- [ ] 20/20 视频元数据完整（时长、点赞、评论、转发、收藏、发布时间）。
- [ ] 每个视频记录 `fetched_top_level / platform_comment_count / coverage / stop_reason`。
- [ ] 每个视频 `stop_reason=complete`（v5 一级评论列表耗尽）；`coverage_platform` 记录但不设 70% 门槛，因为分母 `platform_comment_count` 包含回复；<500 条评论的视频可接近 100%。
- [ ] 重复率要记录（本次 7.4%）；按 `comment_id` 去重。

### 回复

- [ ] 3 个深抓视频的所有 `reply_count>0` thread 都尝试过；每 thread 记录 `expected_total/unique/coverage/orphans/depth3/stop_reason`。
- [ ] 17 个浅抓视频各尝试前 10 个 thread；记录同上。
- [ ] 大 thread 的 5 条平台缺口、7 条孤儿边要记录，不静默丢。
- [ ] `depth`/`is_orphan` 可还原；孤儿保留 `reply_to_reply_id`/`thread_root_id`。
- [ ] `is_author` 在目标账号自己的视频上至少出现一次 true（账号回复）；如果全为 0，先排查而不是直接接受。

### 字段/隐私/风控

- [ ] `ip_label` 存在率 ≥ 95%（一级评论和回复分别统计）。
- [ ] `reply_to_reply_id` 存在；非 0 边可还原 depth≥3。
- [ ] `author_hash` 非空率 = 100%（salt 设置后）。
- [ ] 共享目录/Parquet/CSV 无昵称、头像、签名、原始 UID、cookie、header 值。
- [ ] 无未处理验证码/登录墙；冷却和失败有记录。
- [ ] 记录总请求数、耗时、行数、raw 体积。

### 报告

- [ ] `PILOT.md`：数据质量、覆盖、重复、孤儿、耗时、风控、问题清单。
- [ ] 真实脱敏 fixture（评论/回复 raw 样本）供 LLD 测试。
- [ ] 对 DESIGN/ROADMAP 的修正清单。

---

## 8. 停止与重试

- 出现验证码、登录墙、wrapper 丢失、连续 0 字节：立即停，记录，冷却后新 run 继续。
- 单 thread 达到 `max_pages`：记录 `max_pages`，不无限翻。
- 不因平台缺口（`complete` + coverage<1）自动重跑；记录后由人决定是否二次扫描。
- 每个 run 有独立 `run_id`；不覆盖旧 raw。

---

## 9. 角色与已确认事项

| 事项 | 谁 |
|---|---|
| 账号/视频范围 | 已确认：绍兴文旅；全量 730 视频列表，20 个 pilot 视频 |
| 回复范围 | 已确认：3 深 + 17 浅 |
| Postgres/Parquet/CSV | 已确认：pilot 尽量多存，后续删减 |
| IRB/保留期 | 已确认：按 §5 执行（raw 本地受控、分析表伪名化、发表脱敏、90 天复核）；正式 IRB 批件/豁免号待补 |
| `author_hash` salt | 已确认：Linux 生成 32+ 字节随机值，存 `.secrets/dtk-hmac-salt`（600）；不进共享目录/仓库；`hash_version=v1` |
| `is_thread_author` | 已确认：pilot 先不做；schema 预留 nullable 字段 |
| 深/浅 `max_pages` | 已确认：深 10、浅 3 |
| v5/DB/编排/导出/报告 | Claude/Linux |
| Windows worker 执行 | Windows agent |
| 正式研究抽样 | pilot 后单独设计 |

**已确认（2026-10-30）：**

1. 伦理/保留期按本 spec 执行；正式 IRB 文件补齐后追加到 `run` 表。
2. salt 由 Linux 生成并保管；Windows 通过本地文件/环境变量使用，不放进共享目录。
3. `is_thread_author` pilot 不做，保留字段。
4. 深抓 10 页/thread、浅抓 3 页/thread。
