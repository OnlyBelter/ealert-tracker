#!/usr/bin/env python3
"""
journal_email_reader.py
稳定读取 Gmail 最近 48 小时的期刊邮件，提取文章标题，保存为 JSON
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
    if not s:
        return ''
    parts = decode_header(s)
    result = []
    for part, charset in parts:
        if isinstance(part, bytes):
            charset = charset or 'utf-8'
            try:
                result.append(part.decode(charset, errors='replace'))
            except:
                result.append(part.decode('utf-8', errors='replace'))
        else:
            result.append(str(part))
    return ''.join(result)

def html_to_text(html):
    if not html:
        return ''
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL|re.IGNORECASE)
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p\s*>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</div\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</li\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</h[1-6]\s*>', '\n\n', html, flags=re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', html)
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')
    text = text.replace('&quot;', '"')
    text = text.replace('&#39;', "'")
    text = re.sub(r'&#[0-9]+;', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()

def is_journal_email(sender):
    if not sender:
        return False
    sender = sender.lower()
    return any(d in sender for d in JOURNAL_DOMAINS)

def extract_articles_from_text(text, subject):
    articles = []
    if not text:
        return articles
    
    seen_titles = set()
    lines = text.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if 20 <= len(line) <= 280:
            skip_patterns = [
                r'^volume\s+\d', r'^issue\s+\d', r'^date\s+',
                r'^page\s+\d', r'^doi\s+', r'^read more',
                r'^view\s+all', r'^click\s+here',
                r'^brought\s+to\s+you', r'^sent\s+to\s+',
                r'^update\s+your\s+', r'^table\s+of\s+contents',
                r'^first\s+release', r'^sign\s+up\s+',
                r'^\d+\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)\s+\d',
            ]
            lower_line = line.lower()
            if any(re.match(p, lower_line) for p in skip_patterns):
                continue
            if 'unsubscribe' in lower_line or 'copyright' in lower_line:
                continue
            if '@' in line or line.startswith('http') or line.startswith('www.'):
                continue
            
            # 清理
            title = re.sub(r'\s+', ' ', line).strip()
            title = re.sub(r'^[\s\-\*\.\|•]+', '', title).strip()
            if len(title) >= 15 and title not in seen_titles:
                seen_titles.add(title)
                articles.append({'title': title, 'url': ''})
    
    return articles

def fetch_emails():
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
        
        since = datetime.now() - timedelta(days=1)
        date_str = since.strftime('%d-%b-%Y')
        
        print(f"搜索最近 24 小时邮件 (since {date_str})...")
        status, uids = mail.search(None, f'SINCE {date_str}')
        
        if status != 'OK':
            print(f"搜索失败: {status}")
            return []
        
        uid_list = uids[0].split()
        print(f"找到 {len(uid_list)} 封邮件")
        
        results = []
        
        for uid in uid_list[-25:]:
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
                            except:
                                pass
                else:
                    try:
                        charset = msg.get_content_charset() or 'utf-8'
                        html = msg.get_payload(decode=True).decode(charset, errors='replace')
                        text = html_to_text(html)
                    except:
                        pass
                
                articles = extract_articles_from_text(text, subject)
                
                results.append({
                    'uid': uid.decode(),
                    'from': sender,
                    'subject': subject,
                    'date': msg_date,
                    'articles': articles[:10],
                    'text_preview': text[:800] if text else '',
                })
                
            except Exception as e:
                print(f"  读取失败: {e}")
                continue
        
        print(f"\n共读取 {len(results)} 封期刊邮件")
        for r in results:
            print(f"  - {r['subject'][:60]} ({len(r['articles'])} 篇文章)")
        
        return results
        
    finally:
        try:
            mail.logout()
        except:
            pass

def main():
    print(f"{'='*60}")
    print(f"期刊邮件读取器 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'='*60}")
    
    results = fetch_emails()
    
    output = {
        'date': datetime.now().isoformat(),
        'total_emails': len(results),
        'emails': results
    }
    
    with open(OUTPUT_JSON, 'w') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f"\nJSON 已保存: {OUTPUT_JSON}")
    
    txt_lines = []
    txt_lines.append(f"期刊邮件摘要 - {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    txt_lines.append(f"共 {len(results)} 封期刊邮件\n")
    txt_lines.append('='*60)
    
    for i, r in enumerate(results, 1):
        txt_lines.append(f"\n{i}. [{r['from'][:50]}]")
        txt_lines.append(f"   主题: {r['subject']}")
        txt_lines.append(f"   日期: {r['date']}")
        if r['articles']:
            txt_lines.append(f"   文章 ({len(r['articles'])} 篇):")
            for j, a in enumerate(r['articles'], 1):
                txt_lines.append(f"   {i}.{j}. {a['title'][:120]}")
    
    txt_content = '\n'.join(txt_lines)
    with open(OUTPUT_TXT, 'w') as f:
        f.write(txt_content)
    print(f"文本已保存: {OUTPUT_TXT}")
    print(f"\n完成！")

if __name__ == '__main__':
    main()
