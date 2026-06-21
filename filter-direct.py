#!/usr/bin/env python3
"""
直接根据已知重复标题过滤报告
"""
import re

# 已知的6篇重复论文标题（从去重检查结果）
duplicate_titles = [
    "Cell Press Symposia: Hallmarks of cancer",
    "Hallmarks of Cancer: 25 years guiding discovery and therapy",
    "Cell Press Symposia: Hallmarks of aging",
    "Bang! Exploding immune cells splatter potent toxins everywhere",
    "Nests in an egg cell: structures of protein-storage units in oocytes",
    "Analysis of trade-offs of post-sorting plastic packaging"
]

# 读取原始报告
with open('/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing.md', 'r') as f:
    content = f.read()

# 按论文分割
parts = re.split(r'(### 🔬 论文\d+:)', content)

# 重建内容，跳过重复论文
filtered = []
filtered.append(parts[0])  # 头部

new_count = 0
skip_next = False

for i in range(1, len(parts)):
    if i % 2 == 1:  # 这是标记 (### 🔬 论文X:)
        # 检查下一部分（论文内容）是否包含重复标题
        if i + 1 < len(parts):
            paper_content = parts[i + 1]
            is_duplicate = False
            for dup_title in duplicate_titles:
                if dup_title.lower() in paper_content.lower():
                    is_duplicate = True
                    print(f"  跳过重复论文: {dup_title}")
                    break
            
            if not is_duplicate:
                filtered.append(parts[i])  # 添加标记
                skip_next = False
            else:
                skip_next = True  # 跳过下一部分
        
    elif not skip_next:  # 这是论文内容
        filtered.append(parts[i])

# 重新组合
filtered_content = ''.join(filtered)

# 更新统计
filtered_content = re.sub(r'\*\*今日相关论文\*\*: \d+ 篇', f'**今日相关论文**: {42 - len(duplicate_titles)} 篇', filtered_content)

# 保存
output_path = '/Users/belter/Documents/bioinformatics-frontier/reports/2026/06/2026-W24/2026-06-12-journal-briefing-filtered.md'
with open(output_path, 'w') as f:
    f.write(filtered_content)

print(f"\n✅ 过滤完成！")
print(f"原报告: 42 篇")
print(f"移除重复: {len(duplicate_titles)} 篇")
print(f"新报告: {42 - len(duplicate_titles)} 篇")
print(f"已保存: {output_path}")
