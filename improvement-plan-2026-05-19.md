# 2026-05-19 问题排查报告

## 问题发现

### 问题1：期刊邮件未处理（严重）
今天早上EAlert只处理了2篇Scholar论文，但漏掉了多个Science期刊通知。

过去7天Gmail中有以下期刊邮件**未被处理**：
- `[218] 05/16` "In Other Journals"（Science） → 被excludeKeywords拦截
- `[214] 05/15` "In Science Journals"（Science TOC）→ 可能被"In Other Journals"字符串匹配误杀
- `[216] 05/15` Science Immunology Notification → 检测到但可能返回0篇论文
- `[217] 05/15` Science Advances Notification → 同上
- `[210] 05/14` Science Table of Contents → 应该处理但未在报告中出现

### 问题2：Scholar论文筛选过宽（严重）
今天2篇论文：
- 论文1：2019年EMBO organoids论文（"Long-term expanding human airway organoids"）
- 论文2：美国专利（US20260109944A1）

原因：
- "organoid"是targetKeywords之一，匹配了Fei Chen和Meritxell Huch的Scholar Alert
- 这些研究者做organoid相关工作，任何organoid论文都会被推送
- 没有日期过滤（2019年的论文也被推送）
- 没有过滤非学术内容（专利）
- EMBO Journal不是用户订阅的期刊，属于研究者自己的文献

### 问题3：Science期刊通知无法提取论文
Science Immunology/Advances通知邮件只包含目录页链接，不含具体论文信息。tracker检测到了这些邮件，但从中提取不到论文，只能返回"0篇"。

## 改进计划

### 紧急修复
1. **修复excludeKeywords误杀**：`"In Other Journals"` → 改为更精确匹配 `"In Other Journals\"`（末尾加引号或改用正则）
2. **增加Scholar论文日期过滤**：忽略超过6个月的Scholar推送论文
3. **增加Scholar论文类型过滤**：排除专利（patent.google.com）
4. **增加Scholar论文来源过滤**：Scholar论文的journal如果不是用户订阅期刊，需要有DOI才发送

### 中期改进
5. **修复Science期刊通知解析**：从通知邮件的HTML中提取论文标题列表（或从目录页抓取）
6. **去重逻辑升级**：跨源去重（同一个DOI可能同时出现在期刊邮件和Scholar Alert中）
7. **Scholar论文质量阈值**：必须有DOI + 摘要才发送，否则标记为"元数据不完整，跳过"

### 可选改进
8. **支持用户主动搜索**：用户可以告诉tracker"帮我查X期刊的最新文章"，触发一次性搜索
9. **报告质量提示**：当论文数量<3篇时，在报告中说明"仅Scholar Alert推送，无期刊目录邮件"

## 执行优先级
P0（今天修复）：
- 修复excludeKeywords误杀（改精确匹配）
- Scholar论文：排除专利 + 过滤6个月前的论文
- Scholar论文：必须有DOI才发送

P1（明天修复）：
- 调试Science期刊通知解析（检查为何返回0篇）
- 添加"论文数量<3时说明来源"提示

P2（本周修复）：
- 完整测试7天邮件处理
- 增加手动补跑功能（用户可以触发特定日期的报告生成）