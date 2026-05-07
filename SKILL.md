---
name: ealert-tracker
description: "科研期刊追踪器 v3.6.0。通过 Gmail IMAP 读取最近 24 小时的期刊目录邮件（Nature、Science、Science Translational Medicine、Science Immunology、Science Advances、PNAS、Cell Press 等），提取所有文章标题，生成 Markdown 格式的完整期刊摘要报告并推送到 GitHub。取消邮件发送，改为 QQ 推送 + GitHub 同步。每周生成综合评述。"
metadata:
  openclaw:
    emoji: "📚"
    version: "3.6.0"
    requires:
      bins:
        - python3
      env:
        - IMAP_USER
        - IMAP_PASS
---

# EAlert Tracker v3.6.0 - 科研期刊追踪器

> 通过 Gmail IMAP 自动读取订阅期刊的 Table of Contents 邮件，提取所有文章，生成完整摘要报告。

## 核心特点

- 📅 **最近 24 小时**：每天早上 9:00 读取当日新邮件
- 📰 **全部内容**：研究论文 + 科学新闻，不过滤
- 🤖 **AI 辅助**：自动提取标题和关键信息
- 📱 **多渠道发送**：QQ 推送 + GitHub 同步
- 📊 **每周汇总**：周日上午综合评述 + 领域趋势

## 快速开始

### 运行每日追踪

```bash
cd ~/.qclaw/workspace/ealert-tracker
python3 scripts/email_reader.py
```

这会自动：
1. 连接 Gmail IMAP
2. 读取最近 24 小时的期刊邮件
3. 提取每封邮件中的文章标题
4. 保存到 `/tmp/journal_emails.json` 和 `/tmp/journal_emails.txt`

### 生成报告

让 AI 读取 `/tmp/journal_emails.json`，生成 Markdown 报告，发送到 QQ 并推送到 GitHub。

## 支持的期刊

| 期刊 | 类型 | 内容 |
|------|------|------|
| Nature | 新闻 + 研究 | 最新科学研究和新闻 |
| Nature Communications | 研究论文 | 生命科学和生物医学研究 |
| Science | 新闻 + 研究 | 综合科学新闻和研究 |
| Science Translational Medicine | 研究论文 | 转化医学研究 |
| Science Immunology | 研究论文 | 免疫学前沿研究 |
| Science Advances | 研究论文 | 跨学科研究 |
| PNAS | 研究论文 | 美国国家科学院院刊 |
| Trends in Molecular Medicine | 综述 | 分子医学综述 |
| Cell Press 系列 | 研究论文 | 各子刊最新研究 |

## 工作流程

### 每日期刊追踪（每天 9:00 AM）

```
┌─────────────────────────────────────────────┐
│  cron: 每天 9:00 AM (Asia/Hong_Kong)       │
├─────────────────────────────────────────────┤
│  1. 执行 Python 脚本                        │
│     python3 scripts/email_reader.py          │
│     ↓ (读取最近 24h 期刊邮件)               │
│  2. 保存 JSON → /tmp/journal_emails.json   │
│     ↓                                      │
│  3. AI 读取 JSON                          │
│     ↓                                      │
│  4. 生成 Markdown 报告                      │
│     - 所有期刊的所有文章                    │
│     - 包括研究论文和科学新闻                │
│     ↓                                      │
│  5. 发送报告                              │
│     ✅ QQ Bot (46482C7AEAC84A1D7BE63221F1E6A504) │
│     ✅ GitHub (bioinformatics-frontier)     │
│     ❌ 邮件发送（已取消）                   │
└─────────────────────────────────────────────┘
```

### 每周综合汇总（每周日 10:00 AM）

```
┌─────────────────────────────────────────────┐
│  cron: 每周日 10:00 AM (Asia/Hong_Kong)    │
├─────────────────────────────────────────────┤
│  1. 收集本周 7 天的 journal-briefing 文件  │
│  2. AI 读取所有报告                        │
│  3. 生成综合评述                           │
│     - 本周概览 + 研究领域分布             │
│     - 重点研究 Critical Thinking           │
│     - 领域趋势分析                        │
│     - 下周关注方向                        │
│  4. 发送报告                              │
│     ✅ QQ Bot                             │
│     ✅ GitHub                             │
└─────────────────────────────────────────────┘
```

## 目录结构

```
ealert-tracker/
├── SKILL.md                    # 本文档 (v3.6.0)
├── .env                        # 邮箱配置
├── template.md                 # 每日报告模板（独立文件，生成前必读）
├── scripts/
│   ├── email_reader.py         # ⭐ Python 邮件读取脚本
│   └── tracker.js              # 旧版 Node.js 脚本 (备用)
├── references/
│   └── keywords.md             # 领域关键词参考
├── reports/                    # 本地报告备份
├── node_modules/               # (不再使用)
└── assets/
```

## 定时任务

| 任务 | ID | 时间 | 功能 |
|------|-----|------|------|
| 每日期刊追踪 | `d7e631a3-be6c-422f-a74a-f61c5641c23e` | 每天 9:00 AM | 读取 24h 邮件 → 生成报告 → QQ + GitHub |
| 每周综合汇总 | `weekly-journal-summary` | 每周日 10:00 AM | 汇总一周 → 综合评述 → QQ + GitHub |

## Python 脚本详解

### email_reader.py

**功能**：
- 连接 Gmail IMAP (SSL 端口 993)
- 搜索最近 **24 小时**期刊邮件
- 支持的域名：nature.com, aaas.org, sciencepubs.org, cell.com, pnas.org, elsevier.com
- HTML 转纯文本
- 提取文章标题（通过分析文本行特征）
- 保存 JSON 和 TXT 两种格式

**关键配置**：
```python
# 读取最近 24 小时
since = datetime.now() - timedelta(days=1)
```

**输出**：
- `/tmp/journal_emails.json` - 结构化 JSON
- `/tmp/journal_emails.txt` - 纯文本预览

### journal_emails.json 结构

```json
{
  "date": "2026-04-12T11:24:00.000Z",
  "total_emails": 3,
  "emails": [
    {
      "uid": "12345",
      "from": "alerts@nature.com",
      "subject": "Nature alert for 12th April 2026",
      "date": "Sun, 12 Apr 2026 09:00:00 +0000",
      "articles": [
        {"title": "文章标题", "url": ""}
      ],
      "text_preview": "..."
    }
  ]
}
```

## 报告模板

模板保存在独立文件 [`template.md`](./template.md)。**生成报告前必须先读取该文件**，严格按其结构输出，版本号用 `{version}` 占位（运行时替换为当前版本）。

模板要点速查：
- **日期**：从 DOI 页面或期刊官网提取，**禁止写"见邮件"**
- **作者**：从页面提取，**禁止把摘要片段当成作者**
- **链接**：使用 DOI 直链，**禁止用跟踪跳转链接**
- **摘要要点**：**提炼 + 翻译成中文**，禁止完全照搬英文原文
- **点评**：基于摘要内容写，**不同文章禁止用相同评语**，必须包含 5 个维度（背景→动机→突破→局限→future work）

> ⚠️ 每次生成报告时，**必须读取本 SKILL.md 获取当前版本号**，并在报告末尾标注。版本号变更时自动跟随。

## 每日报告模板

模板保存在独立文件 [`template.md`](./template.md)，生成报告前必须先读取该文件作为参考基准。

## 报告保存位置

**必须** 按以下目录结构保存报告，**绝对不能** 放在 `reports/` 根目录：

```
~/Documents/bioinformatics-frontier/reports/
└── YYYY/           # 年份，如 2026
    └── MM/         # 月份，如 04
        └── YYYY-Wxx/   # ISO 周，如 2026-W17
            ├── YYYY-MM-DD-journal-briefing.md
            └── ...
```

**正确示例**: `reports/2026/04/2026-W17/2026-04-22-journal-briefing.md`
**❌ 错误示例**: `reports/2026-04-22-journal-briefing.md`（根目录）

路径计算规则：
- `YYYY` = 当前年份
- `MM` = 当前月份（两位，补零）
- `Wxx` = ISO 周号（两位，补零），通过 `date +%V` 获取
- 如需创建目录：`mkdir -p ~/Documents/bioinformatics-frontier/reports/YYYY/MM/YYYY-Wxx/`

> ⚠️ **v3.3 更新**：报告已迁移至按 `YYYY/MM/YYYY-Wxx/` 目录结构归档。所有报告必须存放在此结构下，禁止存放在 reports/ 根目录。
> ⚠️ **v3.6 更新**：模板独立为 template.md；日期/作者/链接必须从页面提取；摘要须提炼翻译，禁止照搬；不同文章禁止相同评语。

## GitHub 仓库

```
https://github.com/OnlyPandaX/bioinformatics-frontier
```

## 发送渠道对比

| 渠道 | 每日追踪 | 每周汇总 |
|------|---------|---------|
| QQ Bot | ✅ | ✅ |
| GitHub | ✅ | ✅ |
| 邮件 | ❌ 已取消 | ❌ |

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| "登录失败" | 检查 .env 中的 IMAP_PASS 是否正确（Gmail App Password，不带空格） |
| 邮件数量为 0 | 检查邮箱是否收到期刊邮件，今天是新的一天吗？ |
| GitHub 推送失败 | 检查 Git 凭证是否有效 |
| 周末汇总找不到文件 | 检查 reports/ 目录下是否有 journal-briefing 文件 |

### Gmail App Password 设置

1. 访问 https://myaccount.google.com/apppasswords
2. 创建 App Password（格式如 `abcd efgh ijkl mnop`，带空格）
3. 在 .env 中使用不带空格的密码：`IMAP_PASS=abcdefghijklmnop`

## 更新日志

### v2.1.0 (2026-04-12)
- 📅 读取时间从 48h 改为 **24h**（每天早上读取当日新邮件）
- 📧 **取消邮件发送**，只保留 QQ + GitHub
- 🆕 新增每周汇总任务（每周日 10:00 AM）
- 📝 每周汇总包含：Critical Thinking、领域趋势、下周关注方向

### v2.0.0 (2026-04-11)
- 完全重写，从 Node.js 切换到 Python 3
- 新增 email_reader.py 脚本，稳定读取 Gmail 邮件
- 移除 PDF 生成（只保留 Markdown）
- 移除严格过滤，保留所有科学相关内容
- 支持更多期刊：Science Immunology, Science Advances, Trends 等

### v1.x (2026-03-25)
- 初始版本，Node.js tracker.js

---

**版本**: 2.1.0
**更新**: 2026-04-12

---

## ⚠️ 去重机制（v3.6 强化）

> ⚠️ **v3.6 重要更新**：去重不能只看标题，必须同时比对 URL/DOI。
> - 标题不同但 URL/DOI 相同 → 判定为**重复**，只保留一篇（保留标题更完整的那条）
> - 标题相同但 URL/DOI 不同 → 保留两条（可能是不同期刊的同名文章）
> - 生成报告前先扫描 sent-papers.json，相同 URL/DOI 的论文跳过

### 工作原理

1. **URL/DOI 去重**：标题 + URL 双重比对，不能只靠标题
2. **发送前检查**：每次生成报告前，读取 `sent-papers.json`
3. **只发一次**：每篇文章只发送一次，除非有正当理由
4. **强制理由**：重新发送时必须说明原因

### 去重列表文件

```
~/.qclaw/workspace/ealert-tracker/sent-papers.json
```

**格式**：
```json
{
  "papers": [
    {
      "title": "文章标题",
      "journal": "Nature",
      "sent_date": "2026-04-13",
      "reason": "为什么选这篇",
      "republish_notes": ""
    }
  ]
}
```

### 重新发送的正当理由

| 理由 | 示例 |
|------|------|
| 后续进展 | 「本文上周发送，今天 Science 新报道了其临床试验结果」 |
| 被重要研究引用 | 「被另一篇 Nature 文章作为核心引用跟进」 |
| 趋势高度相关 | 「本周连续多篇相关论文发表，值得汇总」 |

---

**版本**: 3.6.0
**更新**: 2026-05-07

> v3.6.0: 模板独立为 template.md，修复报告问题：日期提取、点评质量、去重逻辑、摘要提炼
> v3.5.0: 强化报告保存路径说明，增加正确/错误示例，禁止存入 reports/ 根目录
