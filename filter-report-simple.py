#!/usr/bin/env python3
"""
从报告中过滤掉重复的论文，生成只包含新论文的报告（简化版）
"""
import json
import re

# 读取去重结果
with open('/Users/belter/.qclaw/workspace/ealert-tracker/dedup-result.json', 'r') as f:
    dedup = json.load(f)

new_titles = set(p.lower().strip() for p in dedup['new_papers'])

# 读取原始报告
with open('/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing.md', 'r') as f:
    lines = f.readlines()

# 过滤论文部分
filtered_lines = []
in_paper = False
current_paper_title = ""
skip_current = False
new_count = 0

i = 0
while i < len(lines):
    line = lines[i]
    
    # 检测论文开始
    if re.match(r'### 🔬 论文\d+:', line):
        in_paper = True
        # 读取接下来的几行找标题
        for j in range(i+1, min(i+10, len(lines))):
            title_match = re.search(r'\*\*(.+?)\*\*', lines[j])
            if title_match:
                current_paper_title = title_match.group(1).lower().strip()
                break
        
        # 检查是否在新论文中
        is_new = any(new_title in current_paper_title or current_paper_title in new_title for new_title in new_titles)
        
        if is_new:
            skip_current = False
            new_count += 1
            filtered_lines.append(line)
        else:
            skip_current = True
    
    elif skip_current:
        # 跳过这篇论文的所有内容，直到下一篇论文或新章节
        if line.startswith('###') or line.startswith('##') or line.startswith('#'):
            skip_current = False
            filtered_lines.append(line)
    
    elif in_paper and not skip_current:
        filtered_lines.append(line)
    
    elif not in_paper:
        filtered_lines.append(line)
    
    i += 1

# 更新统计信息
filtered_content = ''.join(filtered_lines)
filtered_content = re.sub(r'\*\*今日相关论文\*\*: \d+ 篇', f'**今日相关论文**: {new_count} 篇', filtered_content)

# 保存过滤后的报告
output_path = '/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing-filtered.md'
with open(output_path, 'w') as f:
    f.write(filtered_content)

print(f"✅ 过滤完成！")
print(f"原报告: 42 篇")
print(f"新论文: {new_count} 篇")
print(f"过滤后报告已保存: {output_path}")
