#!/usr/bin/env python3
"""
journal_email_reader.py
v2.0 — 重写版（2026-05-08）

准确性原则：提取的每个字段都必须真实存在，绝不捏造。
- 标题: 从邮件正文中提取，保留原文
- URL: 从标题后紧跟的链接行提取，作为论文链接
- 日期: 从邮件正文或标题行中提取
- 期刊: 从邮件 Subject 中识别

输出: /tmp/journal_emails.json
"""

import imaplib
import email
from email.header import decode_header
import json
import os
import re
from datetime import datetime, timedelta

# ============ 从 .env 读取配置 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, '..', '.env')


def load_env(path):
    env = {}
    if os.path.exists(path):
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip().strip('"').strip("'")
    return env


env_vars = load_env(ENV_FILE)
IMAP_HOST = env_vars.get('IMAP_HOST', 'imap.gmail.com')
IMAP_USER = env_vars.get('IMAP_USER', '')
IMAP_PASS = env_vars.get('IMAP_PASS', '')

OUTPUT_JSON = '/tmp/journal_emails.json'
OUTPUT_TXT = '/tmp/journal_emails.txt'

# 期刊发件人域名
JOURNAL_DOMAINS = [
    'nature.com',
    'aaas.org',
    'sciencepubs.org',
    'cell.com',
    'pnas.org',
    'elsevier.com',
]

# ============ 工具函数 ============


def decode_str(s):
    """解码 email 头部的编码字符串"""
    if not s:
        return ''
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            charset = charset or 'utf-8'
            try:
                result.append(part.decode(charset, errors='replace'))
            except Exception:
                result.append(part.decode('utf-8', errors='replace'))
        else:
            result.append(str(part))
    return ''.join(result)


def html_to_text(html):
    """HTML 转纯文本"""
    if not html:
        return ''
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p\s*>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</div\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</li\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</h[1-6]\s*>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>', r'\2\n\1', html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = re.sub(r'&#[0-9]+;', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def is_journal_email(sender):
    """判断是否为期刊邮件"""
    if not sender:
        return False
    sender = sender.lower()
    return any(d in sender for d in JOURNAL_DOMAINS)


def extract_journal_from_subject(subject):
    """从邮件 Subject 识别期刊名"""
    s = subject.lower()
    if 'nature cancer' in s:
        return 'Nature Cancer'
    if 'nature communications' in s:
        return 'Nature Communications'
    if 'nature computational' in s:
        return 'Nature Computational Science'
    if 'nature methods' in s:
        return 'Nature Methods'
    if 'nature genetics' in s:
        return 'Nature Genetics'
    if 'nature medicine' in s:
        return 'Nature Medicine'
    if 'nature biotechnology' in s:
        return 'Nature Biotechnology'
    if 'nature' in s:
        return 'Nature'
    if 'science translational medicine' in s:
        return 'Science Translational Medicine'
    if 'science immunology' in s:
        return 'Science Immunology'
    if 'science advances' in s:
        return 'Science Advances'
    if 'science' in s:
        return 'Science'
    if 'cell metabolism' in s:
        return 'Cell Metabolism'
    if 'cell reports' in s:
        return 'Cell Reports'
    if 'molecular cell' in s:
        return 'Molecular Cell'
    if 'trends in biotechnology' in s:
        return 'Trends in Biotechnology'
    if 'trends in' in s:
        return 'Trends'
    if 'cell' in s:
        return 'Cell'
    if 'pnas' in s:
        return 'PNAS'
    return 'Journal'


def extract_date_from_line(line, context_before):
    """从行内容或前文提取日期"""
    # 常见日期格式: 06 May 2026, May 6, 2026, 06 May 2026, 2026-05-06
    patterns = [
        r'\b(\d{1,2}\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})\b',
        r'\b((Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})\b',
        r'\b(20\d{2}-\d{2}-\d{2})\b',
    ]
    for pat in patterns:
        m = re.search(pat, line, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    # 在前3行中查找
    for prev in context_before[-3:]:
        for pat in patterns:
            m = re.search(pat, prev, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return ''


def is_skip_line(line, lower_line):
    """判断是否为应跳过的行（非标题）"""
    skip_patterns = [
        r'^volume\s+\d', r'^issue\s+\d', r'^date\s+',
        r'^page\s+\d', r'^doi:', r'^read more',
        r'^view\s+all', r'^click\s+here',
        r'^brought\s+to\s+you', r'^sent\s+to\s+',
        r'^update\s+your\s+', r'^table\s+of\s+contents',
        r'^first\s+release', r'^sign\s+up\s+',
        r'^\d+\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d',
        r'^(article|review|news|perspective|comment|letter|archive|advisory|board)',
        r'^(advertisement|website|facebook|twitter|youtube|weibo|follow|join)',
        r'^(circularity|multi-journal|highlights|announcements|editorial)',
        r'^copyright', r'^doi\s', r'^\s*-+\s*$',
    ]
    if any(re.match(p, lower_line) for p in skip_patterns):
        return True
    if 'unsubscribe' in lower_line or 'copyright' in lower_line:
        return True
    # 纯链接行跳过
    if lower_line.strip().startswith('http') or lower_line.strip().startswith('www.'):
        return True
    # 邮箱行跳过
    if '@' in line and '.' in line and not re.search(r'[a-z]{4,}', line):
        return True
    # 太短的行
    if len(line.strip()) < 20:
        return True
    # 大写元信息行
    if line.isupper() and len(line) < 80 and not ' ' in line:
        return True
    return False


def extract_articles_from_text(text, subject):
    """
    重写版提取逻辑（v2.0）
    
    准确性原则：
    - 每个字段必须从邮件内容中真实提取，绝不捏造
    - 标题: 找到论文标题行
    - URL: 标题行后面紧跟的链接行（视为该论文的链接）
    - 日期: 在标题附近或前文中提取
    - 期刊: 从 subject 识别
    """
    articles = []
    if not text:
        return articles

    seen_titles = set()
    lines = text.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        lower_line = line.lower()
        
        # 判断是否为跳过行
        if is_skip_line(line, lower_line):
            i += 1
            continue
        
        # 判断是否为论文标题特征：
        # 1. 长度 30-250 字符
        # 2. 包含小写字母（不是全大写缩写）
        # 3. 不以 http/www/@ 开头
        if (30 <= len(line) <= 250 
                and re.search(r'[a-z]{3,}', line)
                and not lower_line.startswith('http')
                and not lower_line.startswith('www.')
                and '@' not in line):
            
            # 清理标题
            title = re.sub(r'\s+', ' ', line).strip()
            title = re.sub(r'^[\s\-\*\.\|•\[\]:]+', '', title).strip()
            
            # 标题去重
            title_key = re.sub(r'\s+', '', title.lower())[:50]
            if len(title) < 15 or title_key in seen_titles:
                i += 1
                continue
            seen_titles.add(title_key)
            
            # 向前看几行提取日期
            date = extract_date_from_line(line, lines[max(0, i-5):i])
            
            # 向后找 URL（最多看3行）
            url = ''
            for j in range(i + 1, min(i + 4, len(lines))):
                next_line = lines[j].strip()
                next_lower = next_line.lower()
                
                # 跳过非链接行
                if next_lower.startswith('http'):
                    url = next_line.strip()
                    # 截断 URL 后的多余内容
                    url = re.split(r'[\s<>"\']', url)[0]
                    break
                elif next_lower.startswith('www.'):
                    url = 'https://' + next_line.strip().split()[0]
                    break
                elif len(next_line) > 0 and len(next_line) < 15:
                    # 很短的行可能是序号，跳过继续
                    continue
                else:
                    # 遇到其他内容行，停止查找
                    break
            
            articles.append({
                'title': title,
                'url': url,          # 可能为空字符串（无法确认）
                'date': date,        # 可能为空字符串（无法确认）
                'journal': extract_journal_from_subject(subject),
            })
        
        i += 1

    return articles


def fetch_emails():
    """连接 Gmail，读取最近期刊邮件"""
    if not IMAP_PASS:
        print("错误：需要 GMAIL_PASS，在 .env 文件中设置")
        return []

    print(f"连接 Gmail: {IMAP_USER}")

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        mail.login(IMAP_USER, IMAP_PASS)
        print("登录成功")
    except Exception as e:
        print(f"登录失败: {e}")
        return []

    try:
        mail.select('INBOX')

        # 搜索最近 48 小时邮件
        since = datetime.now() - timedelta(days=2)
        date_str = since.strftime('%d-%b-%Y')

        print(f"搜索最近 48 小时邮件 (since {date_str})...")
        status, uids = mail.search(None, f'SINCE {date_str}')

        if status != 'OK':
            print(f"搜索失败: {status}")
            return []

        uid_list = uids[0].split()
        print(f"找到 {len(uid_list)} 封邮件")

        results = []

        for uid in uid_list[-30:]:
            try:
                status, msg_data = mail.fetch(uid, '(RFC822)')
                if status != 'OK':
                    continue

                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)

                sender = decode_str(msg.get('From', ''))
                if not is_journal_email(sender):
                    continue

                subject = decode_str(msg.get('Subject', ''))
                msg_date = msg.get('Date', '')
                journal = extract_journal_from_subject(subject)

                print(f"  处理: {subject[:60]}")

                text = ''
                if msg.is_multipart():
                    for part in msg.walk():
                        ct = part.get_content_type()
                        if ct == 'text/html':
                            try:
                                charset = part.get_content_charset() or 'utf-8'
                                html = part.get_payload(decode=True).decode(charset, errors='replace')
                                text = html_to_text(html)
                                if len(text) > 200:
                                    break
                            except Exception:
                                pass
                else:
                    try:
                        charset = msg.get_content_charset() or 'utf-8'
                        html = msg.get_payload(decode=True).decode(charset, errors='replace')
                        text = html_to_text(html)
                    except Exception:
                        pass

                # v2.0: 提取带 URL 的文章列表
                articles = extract_articles_from_text(text, subject)

                if articles:
                    results.append({
                        'uid': uid.decode(),
                        'from': sender,
                        'subject': subject,
                        'date': msg_date,
                        'journal': journal,
                        'articles': articles,  # [{title, url, date, journal}, ...]
                        'text_preview': text[:500] if text else '',
                    })

            except Exception as e:
                print(f"  读取失败: {e}")
                continue

        print(f"\n共读取 {len(results)} 封期刊邮件")
        for r in results:
            print(f"  - {r['subject'][:60]} ({len(r['articles'])} 篇, {sum(1 for a in r['articles'] if a['url']) } 篇含链接)")

        return results

    finally:
        try:
            mail.logout()
        except Exception:
            pass


def main():
    print(f"{'=' * 60}")
    print(f"期刊邮件读取器 v2.0 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'=' * 60}")

    results = fetch_emails()

    # 保存 JSON（v2.0 格式：每篇文章含 title/url/date/journal）
    output = {
        'version': '2.0',
        'date': datetime.now().isoformat(),
        'total_emails': len(results),
        'total_articles': sum(len(r['articles']) for r in results),
        'emails': results
    }

    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 已保存: {OUTPUT_JSON}")

    # 保存文本摘要
    txt_lines = []
    txt_lines.append(f"期刊邮件摘要 v2.0 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    txt_lines.append(f"共 {len(results)} 封期刊邮件，{output['total_articles']} 篇文章\n")
    txt_lines.append('=' * 60)

    for i, r in enumerate(results, 1):
        txt_lines.append(f"\n{i}. [{r['journal']}] {r['subject']}")
        if r['articles']:
            for j, a in enumerate(r['articles'], 1):
                url_info = f" 🔗 {a['url']}" if a['url'] else " ⚠️ 无链接"
                date_info = f" 📅 {a['date']}" if a['date'] else ""
                txt_lines.append(f"   {i}.{j}. {a['title'][:100]}{date_info}{url_info}")

    txt_content = '\n'.join(txt_lines)
    with open(OUTPUT_TXT, 'w') as f:
        f.write(txt_content)
    print(f"文本已保存: {OUTPUT_TXT}")
    print(f"\n完成！")


if __name__ == '__main__':
    main()
