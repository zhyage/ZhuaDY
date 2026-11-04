# 多账号原始采集报告 — 3 账号 × 10 视频

> 日期：2026-11-04
> run_id：`multi-20261104-01`
> 账号：绍兴文旅、杭州文旅、丽水文旅
> 结论：30/30 视频、5,182 一级评论、1,362 回复已合并；229/229 回复线程 complete。11 条视频没有回复 thread，保留视频+一级评论。

## 1. 样本

| 项目 | 结果 |
|---|---:|
| 账号 | 3 |
| 视频 | 30（每账号 10） |
| 选样 | 随机；target author 且 `comment_count>=1`；绍兴排除旧 pilot 50 条 |
| 视频下载 | 30/30 成功；159,359,343 bytes（159 MB） |
| codec | HEVC 22 / H.264 8 |
| 一级评论 | 5,182 unique |
| thread 候选 | 298 |
| 回复任务 | 19 jobs（3 深 + 16 浅） |
| 回复线程 | 229；**229 complete** |
| 回复 | 1,362 unique |
| 合并后 comment | 6,544 |

11 条视频没有回复 thread，保留视频 + 一级评论，不补采（已确认）。因此实际是 3 深 + 16 浅，而不是原计划的 3 深 + 27 浅。

## 2. 回复质量

| 口径 | expected | unique | coverage |
|---|---:|---:|---:|
| 全部 229 threads | 1,371 | 1,362 | **99.34%** |
| complete threads | 1,371 | 1,362 | 99.34% |

- 5 个线程合计缺 9 条；其中一条平台 `expected=1, unique=0`。
- orphan edges：8；depth null：8；最大 depth：10。
- `is_author=true`：7 条，全部带 `作者` 标签。
- `ip_province`：一级 4,889/5,182（94.3%）；回复 1,324/1,362（97.2%）。
- `author_hash` 100% 非空；salt 与一级评论一致。

## 3. Windows 两轮

### 第一轮 `20261104T084358Z-multi-replies`

- 第一次尝试：首个线程 0 字节 → risk_control，停止。
- 受控诊断：已知正常视频/线程 200、125,080 字节、n=45 → 会话正常。
- 重试：处理 178/229 threads，1,125 replies；在视频 `7241526932624477477` 遇到 `window.fetch` 30 秒仍 native → `wrapper_not_ready`，blocked。
- 没有验证码；没有 cookie/header 泄露。

### 补采 `20261104T104804Z-multi-replies-retry`

- 先手动打开 `7241526932624477477`，确认 wrapper 非 native。
- 8 jobs / 51 threads；**51/51 complete**；237 replies；0 重复；0 孤儿。
- expected 238，unique 237（1 条平台缺口）。
- status=success。

合计：1,125 + 237 = **1,362** 回复。

## 4. 导出

`exports/multi-20261104-01/`

| 文件 | 行数 |
|---|---:|
| `parquet/videos.parquet` | 30 |
| `parquet/comments.parquet` | 6,544 |
| `parquet/reply_edges.parquet` | 1,362 |
| `parquet/quality.parquet` | 278 |
| `parquet/media_downloads.parquet` | 30 |
| `parquet/account.parquet` | 3 |
| `samples/selected_videos.csv` | 30 |
| `samples/comments_sample.csv` | 865 |
| `samples/replies_sample.csv` | 940 |

- `manifest.json` 含 schema、覆盖率、下载统计、文件 SHA256；10 个文件哈希全部匹配。
- 导出不含 `account_id/sec_uid`、昵称、raw page、签名 URL、cookie、header。
- 旧 pilot 未修改。

## 5. 结论

- 3 个账号的原始素材采集已完成：30 mp4 + 5,182 一级评论 + 1,362 回复。
- 11 条无回复视频是样本限制，不是采集失败；报告已记录。
- 回复覆盖率 99.34%；缺口 9 条，属平台计数/隐藏现象。
- 下一步是决定是否扩大账号数、做视频分析，或进入 LLD/自动化；当前原始数据采集阶段可以收尾。
