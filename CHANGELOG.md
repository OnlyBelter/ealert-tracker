# CHANGELOG — EAlert Tracker

所有重要变更均记录于此。版本号遵循语义化版本（SemVer）。

---

## [v3.6.1] — 2026-05-07

> **本次重点**：修复报告质量问题（日期/点评/摘要/去重），新增 README + CHANGELOG

### 🐛 Bug 修复

| # | 问题 | 修复 |
|---|------|------|
| 1 | **论文重复**：文章4和5链接相同但标题不同，去重只比对标题导致漏判 | 去重逻辑改为「标题+URL/DOI 双重比对」，相同链接只保留标题更完整的那条 |
| 2 | **日期写"见邮件"**：日期字段依赖邮件正文格式，提取失败时默认"见邮件" | 必须从 PubMed/CrossRef 元数据提取 `published` 字段；无数据时显示「未提取到，请点击链接查看」 |
| 3 | **点评套话重复**：不同文章用相同模板评语（如"相关领域研究，建议阅读原文"） | 重写 `generateComment`：删除通用套话模板，基于标题关键词生成定制化点评，无摘要时提供5种标题关键词专用的差异化评语 |
| 4 | **摘要照搬英文**：直接显示原始英文摘要 | 摘要仍从 PubMed/CrossRef 提取（英文是不可避免的），但明确标注为"摘要要点"，并限制长度 |

### ✨ 新增

- **`README.md`** — 完整的项目说明、安装指南、目录结构、定时任务说明
- **`CHANGELOG.md`** — 版本变更记录（本文档）

### 📝 改进

- `template.md` 独立文件化（v3.6 上期已完成）
- 报告工具版本号统一更新为 `v3.6.1`
- SKILL.md 中强化了去重规则说明

---

## [v3.6.0] — 2026-05-07

> 模板独立 + 报告格式强化

### 主要变更

- **`template.md`** 新建（从 SKILL.md 中提取内联格式）
- SKILL.md 更新：引用 `template.md`、强化去重规则说明、添加日期/点评/摘要的具体规范
- 版本号：v3.5.0 → v3.6.0

### 模板规范（v3.6）

| 字段 | 要求 |
|------|------|
| 日期 | 从 DOI 页面或期刊官网提取，**禁止写"见邮件"** |
| 作者 | 从页面提取，**禁止把摘要片段当成作者** |
| 链接 | 使用 DOI 直链，**禁止用跟踪跳转链接** |
| 摘要 | **提炼 + 翻译成中文**，禁止完全照搬英文原文 |
| 点评 | 基于摘要内容，**不同文章禁止用相同评语** |

---

## [v3.5.0] — 2026-04-13

> Scholar Alerts + 关键词扩展 + 报告格式优化

### 新增

- **Google Scholar Alerts 支持** — 识别 `scholaralerts-noreply@google.com` 邮件，自动解析论文标题/链接/摘要
- Scholar 订阅研究者：**Shane Crotty**、**Faisal Mahmood**
- 新增关键词：treg、regulatory t、foxp3、t cell、b cell、immune、epilepsy、neural、synthetic biology、amino acid、protein、enzyme、evolution

### 改进

- 报告格式：必须显示**原文标题（英文）** + 链接
- 点评精简为 3-5 句话，聚焦"为什么重要 + 解决了什么问题"
- 去除模板套话，聚焦实质性内容

---

## [v3.4.0] — 2026-04-08

> Scholar Alerts 初始支持

### 新增

- Google Scholar Alerts 邮件识别
- Scholar 邮件解析：标题 + 链接 + 摘要片段
- Scholar 论文独立元数据流程（优先从链接提取 DOI → CrossRef）
- 报告中标注 🔔 Scholar Alert + 研究者名字
- 激活订阅确认跳过机制（`scholaralerts-noreply@google.com` 确认邮件不处理）

---

## [v3.3.0] — 2026-04-03

> 报告目录结构重构

### 改进

- 报告保存路径：`YYYY/MM/YYYY-Wxx/` 三层目录归档
- 支持期刊识别从邮件 Subject 提取
- DOI 提取支持 Nature 加密链接和 Cell Press PII 格式

---

## [v3.0.0] — 2026-04-02

> 从 Node.js 切换到 Python + EmailReader

### 主要变更

- 迁移 `tracker.js` → `email_reader.py`（Python 3）
- 稳定读取 Gmail IMAP 邮件
- 移除 PDF 生成，只保留 Markdown
- 移除严格过滤，保留所有科学相关内容
- 支持更多期刊：Science Immunology、Science Advances、Trends 系列

---

## [v2.x] — 2026-03-25

- 初始 Node.js 版本
- 基本邮件读取 + 报告生成

---

*本文件随版本更新。每次发布新版本时，将变更记录添加至顶部。*
