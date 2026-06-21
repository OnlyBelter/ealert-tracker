#!/usr/bin/env python3
"""
检查今天的期刊报告中的论文是否已发送过
"""
import json
import re

# 读取已发送论文列表
with open('/Users/belter/.qclaw/workspace/ealert-tracker/sent-papers.json', 'r') as f:
    sent_data = json.load(f)
    sent_titles = set()
    for paper in sent_data['papers']:
        # 标准化标题：转小写，去除标点和额外空格
        title = paper['title'].lower().strip()
        title = re.sub(r'[^\w\s]', '', title)
        title = re.sub(r'\s+', ' ', title)
        sent_titles.add(title)

# 读取今天的报告
with open('/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing.md', 'r') as f:
    content = f.read()

# 提取论文标题（从 ### 🔬 论文 格式）
import re
pattern = r'### 🔬 论文\d+:(.+?)\n'
titles = re.findall(pattern, content)

print(f"今天报告中的论文数量: {len(titles)}")
print("\n=== 检查重复 ===")

new_papers = []
duplicate_papers = []

for i, title in enumerate(titles, 1):
    title_clean = title.strip().lower()
    title_clean = re.sub(r'[^\w\s]', '', title_clean)
    title_clean = re.sub(r'\s+', ' ', title_clean)
    
    # 检查是否相似（允许一定的模糊匹配）
    is_duplicate = False
    for sent_title in sent_titles:
        # 简单相似度：如果80%的词匹配
        words_title = set(title_clean.split())
        words_sent = set(sent_title.split())
        if len(words_title) > 0 and len(words_sent) > 0:
            overlap = len(words_title & words_sent)
            similarity = overlap / max(len(words_title), len(words_sent))
            if similarity > 0.7:  # 70%相似度阈值
                is_duplicate = True
                print(f"  ❌ 重复: {title.strip()} <-匹配-> {paper['title']}")
                break
    
    if is_duplicate:
        duplicate_papers.append(title.strip())
    else:
        new_papers.append(title.strip())
        print(f"  ✅ 新论文: {title.strip()}")

print(f"\n=== 统计 ===")
print(f"新论文: {len(new_papers)} 篇")
print(f"重复论文: {len(duplicate_papers)} 篇")
print(f"重复率: {len(duplicate_papers)/len(titles)*100:.1f}%")

# 保存结果
result = {
    'new_papers': new_papers,
    'duplicate_papers': duplicate_papers,
    'total': len(titles),
    'new_count': len(new_papers),
    'duplicate_count': len(duplicate_papers)
}

with open('/Users/belter/.qclaw/workspace/ealert-tracker/dedup-result.json', 'w') as f:
    json.dump(result, f, indent=2, ensure_ascii=False)

print("\n结果已保存到 dedup-result.json")
