---
name: ealert-tracker
description: "科研期刊追踪器 v3.8.6。通过 Gmail IMAP 读取最近 48 小时的期刊目录邮件（Nature、Science、Science Translational Medicine、Science Immunology、Science Advances、PNAS、Cell Press 等），提取所有文章标题，生成 Markdown 格式的完整期刊摘要报告。⚠️ 准确性优先原则：绝不捏造任何字段，无法确认时明确标注占位符。由 AI 发送 QQ + 推送 GitHub。"
metadata:
  openclaw:
    emoji: "📚"
    version: "3.8.6"
    requires:
      bins:
        - python3
      env:
        - IMAP_USER
        - IMAP_PASS
---

# EAlert Tracker v3.8.6 - 科研期刊追踪器

> ⚠️ **准确性原则（最高优先级）**：提供的信息必须经过确认，绝不捏造任何字段。所有字段（DOI、作者、日期、摘要）必须从可靠 API 验证获取，无法提取时明确标注「（XXX信息无法确认）」，绝不猜测。

> 通过 Gmail IMAP 自动读取订阅期刊的 Table of Contents 邮件，提取所有文章，生成完整摘要报告。准确性优先——不捏造任何字段。

## 核心特点

- 📅 **最近 48 小时**：每天早上读取最近两天的期刊邮件
- 📰 **全部内容**：研究论文 + 科学新闻，不过滤
- 🤖 **AI 辅助**：自动提取标题和关键信息
- 📱 **多渠道发送**：QQ 推送 + GitHub 同步（由 AI 负责）
- 📊 **每周汇总**：周日上午综合评述 + 领域趋势

## 快速开始

### 运行每日追踪

```bash
cd ~/.qclaw/workspace/ealert-tracker
node scripts/tracker.js
```

这会自动：
1. 连接 Gmail IMAP
2. 读取最近 48 小时的期刊邮件
3. 提取每封邮件中的文章标题和元数据
4. 生成 Markdown 报告保存到 `reports/YYYY/MM/YYYY-Wxx/`

### 发送报告

AI 读取生成的报告，通过 message 工具发送到 QQ，并推送到 GitHub。

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
│     ↓ (读取最近 48h 期刊邮件)               │
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
├── SKILL.md                    # 本文档 (v3.8.6)
├── .env                        # 邮箱配置
├── template.md                 # 每日报告模板（生成前必读）
├── scripts/
│   ├── email_reader.py         # ⭐ Python 邮件读取脚本
│   └── tracker.js              # 旧版 Node.js 脚本 (备用)
├── references/
│   └── keywords.md             # 领域关键词参考
├── reports/                    # 本地报告备份
├── node_modules/               # (不再使用)
└── assets/

| 任务 | ID | 时间 | 功能 |
|------|-----|------|------|
| 每日期刊追踪 | `d7e631a3-be6c-422f-a74a-f61c5641c23e` | 每天 9:00 AM | 读取 48h 邮件 → 生成报告 → QQ + GitHub |
| 每周综合汇总 | `weekly-journal-summary` | 每周日 10:00 AM | 汇总一周 → 综合评述 → QQ + GitHub |

## Python 脚本详解

### email_reader.py

**功能**：
- 连接 Gmail IMAP (SSL 端口 993)
- 搜索最近 **48 小时**期刊邮件
- 支持的域名：nature.com, aaas.org, sciencepubs.org, cell.com, pnas.org, elsevier.com
- 优先解析 HTML 结构（`<a href>`）提取「标题 + 链接」，文本启发式作为兜底
- HTML → 纯文本（仅用于预览与兜底）
- 保存 JSON 和 TXT 两种格式

**关键配置**：
```python
# 读取最近 48 小时
since = datetime.now() - timedelta(days=2)
```

**输出**：
- `/tmp/journal_emails.json` - 结构化 JSON
- `/tmp/journal_emails.txt` - 纯文本预览

### Gmail 邮件结构化解析（重点）

目标：把 Gmail 邮件的「半结构化 HTML」稳定转换成可用于下游生成报告的结构化 JSON，并在无法确认时输出空字符串而不是猜测。

推荐解析顺序：
1. **解析 MIME**：优先选择 `text/html`，没有再退回 `text/plain`。
2. **HTML 结构提取**：遍历所有 `<a href="...">anchor_text</a>`：
   - `anchor_text` 满足长度范围（避免导航按钮 / “Read more”）
   - `href` 必须是 http(s) 链接
   - 域名在允许列表内（或 `doi.org`）
3. **URL 规范化**：尽量去掉跟踪参数并解包常见跳转参数（例如 `url=` / `redirect=`），得到更稳定的去重键。
4. **兜底策略**：若 HTML 结构提取为空，再使用纯文本启发式：识别疑似标题行 + 向后查找紧邻链接行。

输出字段约束：
- `title`：必须来自邮件正文（HTML anchor 文本或文本行），禁止改写、禁止猜测。
- `url`：必须来自邮件正文中的可见链接或 href，无法确认时输出空字符串。
- `date`：邮件中无法确认时输出空字符串（报告阶段再从 DOI/官网/API 验证）。

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

**版本**: 3.7.0
**更新**: 2026-05-08

> **⚠️ 准确性原则（v3.7.0 — 最高优先级）**:
> 提供的信息必须经过确认，绝不捏造任何字段。所有字段（DOI、作者、日期、摘要）必须从可靠 API 验证获取，无法提取时明确标注占位符，绝不猜测。
>
> v3.7.0:
> - 删除 extractDOI 捏造假 DOI 逻辑（abc123、def456 等格式不再出现）
> - 新增 validateDOI() 通过 CrossRef API 验证 DOI 真实性
> - ensureFields → ensureAccurateFields：无确认字段时明确标注「（作者信息无法确认）」
> - 无 DOI 时显示 Google 学术搜索链接替代，不再显示假 DOI
> v3.6.2: 删除重复的 assets/template.md，整理目录结构
> v3.6.1: 修复去重逻辑（URL+DOI 双重比对）、点评套话、日期/摘要问题
