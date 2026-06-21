#!/usr/bin/env python3
"""
将今天的新论文添加到 sent-papers.json 去重列表
"""
import json
import re
from datetime import datetime

# 读取今天的过滤后报告
with open('/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing-filtered.md', 'r') as f:
    content = f.read()

# 读取现有的 sent-papers.json
with open('/Users/belter/.qclaw/workspace/ealert-tracker/sent-papers.json', 'r') as f:
    sent_data = json.load(f)

# 提取论文信息
papers_to_add = []

# 按论文分割
parts = re.split(r'### 🔬 论文\d+:', content)

for i in range(1, len(parts)):
    paper_content = parts[i]
    
    # 提取标题
    title_match = re.search(r'\*\*(.+?)\*\*', paper_content)
    if not title_match:
        continue
    title = title_match.group(1).strip()
    
    # 提取期刊
    journal_match = re.search(r'\*\*平台\*\*: (.+)', paper_content)
    journal = journal_match.group(1).strip() if journal_match else "Unknown"
    
    # 添加到列表
    paper_entry = {
        "title": title,
        "journal": journal,
        "sent_date": "2026-06-12",
        "reason": "EAlert Tracker 2026-06-12 daily tracking"
    }
    papers_to_add.append(paper_entry)

# 添加到 sent-papers.json
sent_data['papers'].extend(papers_to_add)

# 保存
with open('/Users/belter/.qclaw/workspace/ealert-tracker/sent-papers.json', 'w') as f:
    json.dump(sent_data, f, indent=2, ensure_ascii=False)

print(f"✅ 成功添加 {len(papers_to_add)} 篇论文到去重列表")
print(f"去重列表现有 {len(sent_data['papers'])} 篇论文")

# 显示前3篇和后3篇作为验证
print("\n前3篇:")
for p in papers_to_add[:3]:
    print(f"  - {p['title'][:60]}...")

print("\n后3篇:")
for p in papers_to_add[-3:]:
    print(f"  - {p['title'][:60]}...")
