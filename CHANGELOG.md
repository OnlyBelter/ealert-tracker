# CHANGELOG — EAlert Tracker

所有重要变更均记录于此。版本号遵循语义化版本（SemVer）。

---

## [v3.8.7] — 2026-05-19

> **本次重点**：修复 Nature 加密跟踪链接（links.springernature.com）无法打开的问题。

### 🔧 修复

- `scripts/email_reader.py`：新增 `_unwrap_springernature_link()` 函数，通过 HTTP 请求解包 Nature 加密跟踪链接，获取真实论文 URL。
- 自动去除解包后 URL 中的跟踪参数（utm_* 等）。

### ⚠️ 已知限制

- Nature 跟踪链接有时效性，邮件中的链接过期后会重定向到 Google 搜索页。建议在邮件收到后尽快处理。

---

## [v3.8.6] — 2026-05-19

> **本次重点**：邮件抓取与解析流程升级为 “Python pipeline → papers JSON → Node 下游处理”，提升稳定性与结构化提取质量。

### ✨ 新增

- 新增 `scripts/email_pipeline.py`：统一抓取近 48 小时的期刊 ToC + Google Scholar Alerts 邮件，并直接输出 `papers` JSON（供 `tracker.js` 消费）。

### 🔧 改进

- `scripts/tracker.js`：主流程不再依赖 Node IMAP 抓取与解析，改为调用 Python pipeline 获取候选论文后再进行关键词过滤、PubMed/CrossRef 补全、报告生成与归档。
- `scripts/email_reader.py`：期刊邮件解析改为 **HTML 结构优先**（遍历 `<a href>` 提取标题+链接），并加入 URL 规范化（去跟踪参数/解包常见跳转参数）与域名覆盖补全（含 `science.org`）。
- 文档与元信息：版本号统一更新为 `v3.8.6`（README / SKILL / config / package）。

## [v3.7.0] — 2026-05-08

> **⚠️ 准确性原则（最高优先级）**：绝不捏造任何字段，无法提取时明确标注占位符。

### 🛡️ 准确性保障体系

| 问题 | 原因 | 修复 |
|------|------|------|
| DOI 捏造 | `extractDOI()` 通过 PII 格式生成 `10.1126/scitranslmed.abc123` 等假 DOI | 删除 PII→DOI 生成逻辑，只保留链接中真实存在的 DOI |
| 作者"待补充" | PubMed 查不到的论文直接回退，原始字段未清理 | 查不到时明确标注「（作者信息无法确认）」，不再留空 |
| 假 DOI 链接可点击 | 链接指向不存在的 DOI | 无真实 DOI 时显示 Google 学术搜索链接，不再显示假 DOI |

### 🔧 代码变更

- **删除** `extractDOI()` 中的 PII 格式转 DOI 逻辑（v3.6.x 遗留）
- **新增** `validateDOI()` 通过 CrossRef API 验证 DOI 真实性
- **重写** `ensureFields()` → `ensureAccurateFields()`：DOI 格式校验 + 无确认字段标注
- **重写** `fetchPaperDetails()`：三步准确性优先流程
- **更新** 报告模板：DOI 链接改为条件显示（无真实 DOI 则显示搜索链接）

### 📝 字段处理规则

| 字段 | 状态 | 处理 |
|------|------|------|
| DOI | 验证通过 | ✅ 显示 `https://doi.org/{doi}` |
| DOI | 验证失败/无 DOI | ⚠️ 显示 Google 学术搜索链接 |
| 作者 | 查不到 | ⚠️ 显示「（作者信息无法确认）」 |
| 日期 | 查不到 | ⚠️ 显示「（发表日期无法确认）」 |
| 期刊 | 有值 | ✅ 显示期刊名 |
| 期刊 | 无值 | ⚠️ 显示「（期刊信息无法确认）」 |
| 摘要/点评 | 无法提取 | 由 AI 基于标题推断，标注为推断而非事实 |

---

## [v3.6.2] — 2026-05-07

> **本次重点**：删除重复的旧模板文件，整理目录结构

### 🧹 代码整理

| # | 操作 |
|---|------|
| 1 | **删除 `assets/template.md`**：该文件与根目录 `template.md` 重复，功能已由根目录文件承接 |
| 2 | **更新 `SKILL.md` 目录结构**：移除 `assets/` 下旧模板描述，标注 `template.md` 引用路径 |
| 3 | **版本号同步**：SKILL.md 顶栏 / config.json / package.json 全部更新为 v3.6.1 |

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
