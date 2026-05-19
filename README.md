# EAlert Tracker

> 科研期刊追踪器 — 自动追踪 Nature、Science、Cell 等主流期刊最新论文，生成结构化报告。

[![Version](https://img.shields.io/badge/version-v3.8.6-blue.svg)](./CHANGELOG.md)

---

## 功能特点

- 📅 **每日自动追踪** — 通过 Gmail IMAP 读取最近 24 小时期刊目录邮件
- 📰 **多期刊覆盖** — Nature、Science、Science Translational Medicine、Science Immunology、Science Advances、PNAS、Cell Press 等
- 🔔 **Google Scholar Alerts** — 自动追踪指定研究者新发表论文（Shane Crotty、Faisal Mahmood 等）
- 🤖 **AI 辅助摘要** — 自动提取标题、作者、期刊、链接、研究问题、主要贡献、专家点评
- 🔍 **元数据补全** — 通过 PubMed / CrossRef API 自动补全摘要和作者信息
- 📱 **多渠道发送** — QQ Bot 推送 + GitHub 归档
- 📊 **每周综合评述** — 周日自动汇总本周论文，生成领域趋势分析

---

## 目录结构

```
ealert-tracker/
├── README.md              # 本文件
├── CHANGELOG.md           # 版本变更记录
├── SKILL.md               # OpenClaw Skill 定义（含报告模板 + 使用说明）
├── template.md            # 每日报告模板（生成报告前必读）
├── config.json            # Skill 配置
├── package.json
├── .env                   # 邮箱 IMAP 凭证（不提交 Git）
├── sent-papers.json       # 已发送论文记录（防重复发送）
├── scripts/
│   ├── tracker.js         # Node.js 主脚本（v3.8.6）
│   └── email_reader.py    # Python 邮件读取脚本（备用）
├── references/
│   ├── INSTALL.md         # 安装说明
│   └── keywords.md        # 领域关键词参考
├── assets/
│   └── template.md        # 报告模板资源
└── reports/               # 本地报告备份
    └── YYYY/MM/YYYY-Wxx/  # 按年月/周归档
```

---

## 快速开始

### 1. 配置环境变量

在 `~/.qclaw/workspace/ealert-tracker/.env` 中添加：

```bash
IMAP_HOST=imap.gmail.com
IMAP_PORT=993
IMAP_USER=your_email@gmail.com
IMAP_PASS=xxxx xxxx xxxx xxxx   # Gmail App Password（不带空格）
```

**Gmail App Password 设置**：
1. 访问 https://myaccount.google.com/apppasswords
2. 创建 App Password（16位，带空格）
3. 在 `.env` 中填入不带空格的版本

### 2. 测试运行

```bash
cd ~/.qclaw/workspace/ealert-tracker
node scripts/tracker.js
```

### 3. 订阅期刊邮件

在对应期刊官网注册 Table of Contents（ToC）提醒：
- Nature: https://www.nature.com/alerts
- Science: https://www.science.org/content/my-science
- Cell Press: https://www.cell.com/cell/awayfrom keyboard

---

## 定时任务

| 任务 | 时间 | 功能 |
|------|------|------|
| 每日期刊追踪 | 每天 08:30 (Asia/Hong_Kong) | 读取 24h 邮件 → 生成报告 → QQ + GitHub |
| 每周期刊汇总 | 每周日 11:00 (Asia/Hong_Kong) | 汇总一周 → 综合评述 → QQ + GitHub |

**Cron Task ID**: `d7e631a3-be6c-422f-a74a-f61c5641c23e`

---

## 报告格式

详见 [`template.md`](./template.md)。

每篇论文包含：
1. **标题**（英文原文）
2. **期刊 / 日期 / 作者 / 机构**
3. **一句话概要**（≤40字）
4. **主要贡献**（2-3条）
5. **Critical 简评**（3-5句专家点评：背景→动机→突破→局限→future work）

---

## 追踪的研究者

当前通过 Google Scholar Alerts 追踪：
- **Shane Crotty** — La Jolla Institute for Immunology（疫苗/免疫学）
- **Faisal Mahmood** — Harvard TH Chan School of Public Health（计算病理学/AI for Medicine）

---

## 故障排除

| 问题 | 解决方案 |
|------|---------|
| "登录失败" | 检查 IMAP_PASS 是否正确（Gmail App Password，不带空格） |
| 邮件数量为 0 | 确认期刊 ToC 提醒已订阅；检查垃圾邮件文件夹 |
| 报告重复发送 | 检查 `sent-papers.json`；去重逻辑基于标题+URL/DOI |
| GitHub 推送失败 | 确认 Git 凭证有效；检查仓库权限 |

---

## 相关仓库

- **bioinformatics-frontier**（报告归档）: https://github.com/OnlyPandaX/bioinformatics-frontier
- **multi-omics-briefing**（多组学简报）: https://github.com/OnlyBelter/multi-omics-briefing
- **bioinfo-weekly-summary**（每周综合汇总）: https://github.com/OnlyBelter/bioinfo-weekly-summary

---

*EAlert Tracker 由 [胖达 🐼] 自动维护*
