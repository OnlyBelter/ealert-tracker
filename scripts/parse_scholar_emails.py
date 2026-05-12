#!/usr/bin/env python3
"""
Google Scholar Alert 邮件解析器 v2.1
专门解析 Scholar 邮件格式，提取论文信息

Scholar 邮件格式（已确认）：
- Subject: "研究者名字 - N new articles"
- 正文结构（每篇论文）：
  1. 标题行（全大写，可跨多行）
  2. [URL] 链接行
  3. 作者列表 - 期刊, 年份
  4. 摘要片段（1-3行）
  5. Save + 分享链接
  6. 空行分隔
"""

import re
import json
import sys
from pathlib import Path

def extract_doi_from_url(url):
    """从 URL 中提取 DOI/真实链接"""
    param_match = re.search(r'scholar_url\?url=([^&\s]+)', url)
    if param_match:
        decoded = param_match.group(1).replace('&amp;', '&')
        doi_match = re.search(r'(10\.\d+/[^\s&\)]+)', decoded)
        if doi_match:
            return doi_match.group(1), decoded
        return '', decoded
    return '', url

def title_case(s):
    """智能标题大小写转换"""
    lower_words = {'and','or','for','of','in','on','to','a','an','the','with','by','from','vs','via','based','using','towards','toward'}
    words = s.split()
    result = []
    for i, w in enumerate(words):
        if w.lower() in lower_words and i > 0:
            result.append(w.lower())
        else:
            result.append(w.capitalize())
    t = ' '.join(result)
    return t.replace("'S", "'s").replace("'T", "'t").replace("'Re", "'re")

def parse_scholar_email(text, subject=''):
    """解析 Scholar Alert 邮件，返回论文列表"""
    papers = []
    
    researcher_match = re.match(r'^([^\-]+)\s+-\s+(\d+)\s+new articles?', subject, re.I)
    researcher = researcher_match.group(1).strip() if researcher_match else 'Unknown'
    
    raw_lines = text.split('\n')
    lines = []
    for line in raw_lines:
        stripped = line.strip()
        if re.match(r'^(This message was sent|You are receiving|Google Scholar Alerts|List alerts|Cancel alert)', stripped, re.I):
            continue
        if 'cleardot.gif' in stripped:
            continue
        if stripped == 'Save':
            continue
        if re.match(r'^https://scholar\.google\.(com|co\.uk)/intl/en/scholar/', stripped):
            continue
        if re.match(r'^https://scholar\.google\.com/(citations|scientific|scientist)', stripped):
            continue
        lines.append(stripped)
    
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        
        title_prefix = ''
        title_text = ''
        
        pdf_m = re.match(r'^\[PDF\]\s+(.+)', line)
        html_m = re.match(r'^\[HTML\]\s+(.+)', line)
        
        if pdf_m:
            title_prefix = '[PDF] '
            title_text = pdf_m.group(1)
        elif html_m:
            title_prefix = '[HTML] '
            title_text = html_m.group(1)
        elif line.isupper() and len(line) > 15 and not line.startswith('HTTP'):
            title_text = line
        
        if title_text:
            full_title = title_text
            if line.isupper():
                while idx + 1 < len(lines):
                    next_l = lines[idx + 1]
                    if (next_l.isupper() and len(next_l) > 10 and len(next_l) < 80 and
                        not next_l.startswith('HTTP') and
                        'scholar_url' not in next_l and
                        not re.search(r'\b(AUTHOR|JOURNAL|VOLUME|ISSN|DOI|PAGE)\b', next_l)):
                        full_title += ' ' + next_l
                        idx += 1
                    else:
                        break
            
            paper = {
                'title': title_prefix + title_case(full_title),
                'authors': '',
                'journal': '',
                'year': '',
                'doi': '',
                'url': '',
                'abstract': [],
                'researcher': researcher,
                'source': 'scholar'
            }
            
            found_url = False
            found_author = False
            
            for j in range(idx + 1, min(idx + 12, len(lines))):
                next_line = lines[j]
                
                if not found_url and 'scholar_url' in next_line:
                    paper['url'] = next_line
                    doi, real_url = extract_doi_from_url(next_line)
                    paper['doi'] = doi
                    paper['url'] = real_url
                    found_url = True
                    continue
                
                if not found_author:
                    if (re.search(r'\b[A-Z][a-zA-Z]+\s+[-\u2013]\s+', next_line) or re.search(r'\s+-\s+[A-Z]', next_line)):
                        if (re.search(r'20\d{2}|19\d{2}', next_line) or 
                            any(k in next_line for k in ['Nature', 'Science', 'Cell', 'Research', 'Journal', 'arxiv', 'Advances', 'Letters', 'preprint'])):
                            dash_idx = max(next_line.rfind(' - '), next_line.rfind(' – '))
                            if dash_idx > 0:
                                paper['authors'] = next_line[:dash_idx].strip()
                                rest = next_line[dash_idx+3:].strip()
                                year_m = re.search(r'(20\d{2}|19\d{2})', rest)
                                if year_m:
                                    paper['year'] = year_m.group(1)
                                    paper['journal'] = rest[:year_m.start()].strip().rstrip(',').rstrip()
                                else:
                                    paper['journal'] = rest
                            else:
                                paper['authors'] = next_line
                            found_author = True
                            continue
                
                if found_author:
                    if (len(next_line) > 25 and
                        'scholar_url' not in next_line and
                        'scholar.google' not in next_line and
                        not next_line.startswith('http') and
                        next_line not in ['Save']):
                        paper['abstract'].append(next_line)
                    elif not next_line:
                        break
                    elif len(next_line) < 15:
                        break
            
            paper['abstract'] = ' '.join(paper['abstract'])[:500]
            if not paper['authors']:
                paper['authors'] = researcher + ' et al.'
            
            if paper['title'] and len(paper['title']) > 15:
                papers.append(paper)
        
        idx += 1
    
    return papers

def main():
    use_json = '--json' in sys.argv
    args = [a for a in sys.argv[1:] if a != '--json']
    
    subject = ''
    if len(args) > 1 and not Path(args[0]).exists():
        subject = args[1]
    
    text = open(args[0]).read() if args and Path(args[0]).exists() else (args[0] if args else '')
    
    papers = parse_scholar_email(text, subject)
    
    if use_json:
        # 仅输出 JSON（供 Node.js 调用）
        print(json.dumps(papers, ensure_ascii=False))
    else:
        # 人类可读格式
        print(f"=== Scholar 邮件解析结果 ===")
        print(f"提取论文数: {len(papers)}")
        print()
        for i, p in enumerate(papers, 1):
            print(f"--- 论文 {i} ---")
            print(f"标题: {p['title']}")
            print(f"作者: {p['authors']}")
            print(f"期刊: {p['journal']} {p['year']}")
            print(f"DOI: {p['doi'] or '（无）'}")
            print(f"链接: {p['url']}")
            print(f"研究者: {p['researcher']}")
            if p['abstract']:
                print(f"摘要: {p['abstract'][:200]}...")
            print()
        print(json.dumps(papers, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
