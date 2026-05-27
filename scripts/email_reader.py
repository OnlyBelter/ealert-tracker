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
from email.utils import parsedate_to_datetime
from html.parser import HTMLParser
import json
import os
import re
from urllib.parse import parse_qs, unquote, urlencode, urlparse, urlunparse
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
    'science.org',
    'sciencepubs.org',
    'cell.com',
    'pnas.org',
    'elsevier.com',
]

# Science 系列邮件的跟踪链接域名（这些链接指向真实文章）
SCIENCE_TRACKING_DOMAINS = [
    'click.science.org',
    'science.10sr9c.cn',
    'science.1bo8ae.cn',
    'staging.science.org',
    'prod.science.org',
    'em.science.org',
    'email.science.org',
    'link.immunology.org',
    'link.aaas.org',
    'daily.science.org',
    'advances.sciencemag.org',
    'stm.sciencemag.org',
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


class _LinkExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._in_a = False
        self._href = ''
        self._text_chunks = []
        self.links = []
        self._a_stack = 0  # 跟踪 <a> 嵌套层级

    def handle_starttag(self, tag, attrs):
        if tag.lower() == 'a':
            href = ''
            for k, v in attrs:
                if k.lower() == 'href':
                    href = v or ''
                    break
            if not self._in_a:
                self._in_a = True
                self._href = href
                self._text_chunks = []
            self._a_stack += 1
        elif self._in_a:
            # 在 <a> 内的标签（如 <span>、<em>）不截断文本
            pass

    def handle_data(self, data):
        if not self._in_a:
            return
        if data:
            self._text_chunks.append(data)

    def handle_endtag(self, tag):
        if tag.lower() == 'a':
            self._a_stack = max(0, self._a_stack - 1)
            if self._a_stack == 0 and self._in_a:
                text = re.sub(r'\s+', ' ', ''.join(self._text_chunks)).strip()
                href = (self._href or '').strip()
                if href:
                    self.links.append((text, href))
                self._in_a = False
                self._href = ''
                self._text_chunks = []


def _unwrap_tracking_link(url):
    """解包各类期刊加密跟踪链接：Nature (links.springernature.com) 和 Science (click.science.org 等)"""
    url_lower = url.lower()
    
    # 解包 Nature 加密跟踪链接
    if 'links.springernature.com' in url_lower:
        try:
            import urllib.request
            class RedirectHandler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = urllib.request.build_opener(RedirectHandler)
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            try:
                response = opener.open(url, timeout=5)
                final_url = response.geturl()
                if final_url and 'links.springernature.com' not in final_url.lower():
                    return final_url
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and 'Location' in e.headers:
                    final_url = e.headers['Location']
                    if final_url and 'links.springernature.com' not in final_url.lower():
                        return final_url
            except Exception:
                pass
        except Exception:
            pass
        return url
    
    # 解包 Science 点击跟踪链接 (click.science.org 等)
    # Science 链接格式: https://click.science.org/...?url=https://www.science.org/...
    # AAAS/Science Pubs 格式: https://click.aaas.sciencepubs.org/?qs=...&dest=...
    for tracking_prefix in ('click.science.org', 'click.aaas.sciencepubs.org', 'science.10sr9c.cn', 
                            'science.1bo8ae.cn', 'staging.science.org', 'prod.science.org', 
                            'em.science.org', 'email.science.org', 'daily.science.org', 
                            'link.aaas.org', 'go.aaas.org'):
        if tracking_prefix in url_lower:
            try:
                from urllib.parse import parse_qs, unquote, urlparse
                parsed = urlparse(url)
                qs = parse_qs(parsed.query or '')
                
                # 方式1: 标准 url 参数
                for k in ('url', 'u', 'redirect', 'r', 'dest', 'destination', 'target', 'goto', 'link'):
                    if k in qs and qs[k]:
                        candidate = unquote(qs[k][0])
                        if candidate.lower().startswith(('http://', 'https://')):
                            return candidate
                
                # 方式2: AAAS 的 qs=base64 或 qs=json 格式（dest 参数）
                # 格式: click.aaas.sciencepubs.org/?qs=...&dest=base64_encoded_url
                if 'dest' in qs:
                    for dest_val in qs['dest']:
                        # 尝试直接解码
                        candidate = unquote(dest_val)
                        if candidate.lower().startswith(('http://', 'https://')):
                            return candidate
                        # 尝试 base64 解码
                        try:
                            import base64
                            decoded = base64.b64decode(candidate).decode('utf-8', errors='replace')
                            if decoded.lower().startswith(('http://', 'https://')):
                                return decoded.strip()
                        except Exception:
                            pass
                
                # 方式3: 从完整 URL 路径中找真实链接
                import re
                match = re.search(r'https?://[^\s"\'<>]{10,200}', url)
                if match:
                    candidate = unquote(match.group(0))
                    if any(t in candidate.lower() for t in ('science.org', 'aaas.org', 'nature.com', 'cell.com', 'pnas.org', 'doi.org')):
                        return candidate
                        
            except Exception:
                pass
    
    return url


def _unwrap_springernature_link(url):
    """解包 Nature 加密跟踪链接 (links.springernature.com) — 保留旧函数名兼容"""
    return _unwrap_tracking_link(url)
    try:
        import urllib.request
        # 只跟随重定向，不下载内容
        class RedirectHandler(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):
                return None  # 停止跟随，返回最终 URL
        opener = urllib.request.build_opener(RedirectHandler)
        opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
        try:
            response = opener.open(url, timeout=5)
            final_url = response.geturl()
            if final_url and 'links.springernature.com' not in final_url.lower():
                return final_url
        except urllib.error.HTTPError as e:
            # 302 重定向时，从 Location 头获取目标
            if e.code in (301, 302, 303, 307, 308) and 'Location' in e.headers:
                final_url = e.headers['Location']
                if final_url and 'links.springernature.com' not in final_url.lower():
                    return final_url
        except Exception:
            pass
    except Exception:
        pass
    return url


def _normalize_url(url):
    if not url:
        return ''
    url = url.strip()
    if url.startswith('www.'):
        url = 'https://' + url
    if not url.lower().startswith(('http://', 'https://')):
        return ''

    # 解包各类期刊跟踪链接（Nature + Science）
    url = _unwrap_tracking_link(url)

    parsed = urlparse(url)
    qs = parse_qs(parsed.query or '')

    for k in ('url', 'u', 'redirect', 'redirectUrl', 'target', 'dest', 'destination'):
        if k in qs and qs[k]:
            candidate = unquote(qs[k][0])
            if candidate.lower().startswith(('http://', 'https://')):
                url = candidate
                parsed = urlparse(url)
                break

    drop_prefixes = (
        'utm_',
        'WT.',
        'wt_',
        'spm',
        'cmpid',
        'cid',
        'mc_cid',
        'mc_eid',
        'mkt_tok',
    )
    kept_pairs = []
    for k, v in parse_qs(parsed.query or '', keep_blank_values=True).items():
        if any(k.startswith(p) for p in drop_prefixes):
            continue
        for vv in v:
            kept_pairs.append((k, vv))

    new_query = urlencode(kept_pairs, doseq=True) if kept_pairs else ''
    parsed = parsed._replace(query=new_query, fragment='')
    return urlunparse(parsed)


def _extract_articles_from_html(html, subject):
    if not html:
        return []
    parser = _LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    journal = extract_journal_from_subject(subject)
    articles = []
    seen = set()
    for text, href in parser.links:
        title = re.sub(r'\s+', ' ', (text or '')).strip()
        if len(title) < 20 or len(title) > 250:
            continue
        lower_title = title.lower()
        if any(
            x in lower_title
            for x in (
                'read more',
                'view article',
                'full text',
                'abstract',
                'pdf',
                'table of contents',
                'unsubscribe',
                'privacy',
                'manage preferences',
                'sign up',
                'register',
                'log in',
                'contact us',
            )
        ):
            continue
        if not re.search(r'[a-z]{3,}', title):
            continue

        # v3.9.0: 先解包跟踪链接，再过滤
        url = _unwrap_tracking_link(href)
        if not url:
            continue
        url = _normalize_url(url)
        if not url:
            continue
        lower_url = url.lower()
        if 'unsubscribe' in lower_url:
            continue
        
        # 检查是否为有效期刊链接：
        # 1. 直接匹配期刊域名（解包后）
        # 2. DOI 链接
        # 3. Science 跟踪链接（保留原始跟踪链接，tracker.js 会直接抓取摘要）
        is_valid_url = any(d in lower_url for d in JOURNAL_DOMAINS)
        has_doi = 'doi.org/' in lower_url
        is_science_tracking = any(d in lower_url for d in SCIENCE_TRACKING_DOMAINS)
        
        if not is_valid_url and not has_doi and not is_science_tracking:
            continue

        title_key = re.sub(r'\s+', '', lower_title)[:80]
        url_key = lower_url.split('?', 1)[0][:160]
        key = (title_key, url_key)
        if key in seen:
            continue
        seen.add(key)
        articles.append({'title': title, 'url': url, 'date': '', 'journal': journal})

    return articles


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
    改进版提取逻辑（v2.1）
    
    修复 PNAS 邮件标题截断问题：
    - 标题可能跨多行（被 <br> 或 \n 分割）
    - 合并多行标题（直到遇到 URL 或日期行）
    - 改进 URL 提取（支持 doi.org 链接）
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
        # 1. 长度 15-300 字符（降低阈值，允许跨行合并）
        # 2. 包含小写字母（不是全大写缩写）
        # 3. 不以 http/www/@ 开头
        if (15 <= len(line) <= 300 
                and re.search(r'[a-z]{3,}', line)
                and not lower_line.startswith('http')
                and not lower_line.startswith('www.')
                and '@' not in line):
            
            # 清理标题
            title = re.sub(r'\s+', ' ', line).strip()
            title = re.sub(r'^[\s\-\*\."|•\[\]:]+', '', title).strip()
            
            # v2.1: 尝试向后合并多行标题（PNAS 邮件常见格式）
            # 合并条件：下一行是小写开头（标题 continuation）
            j = i + 1
            while j < min(i + 5, len(lines)):
                next_line = lines[j].strip()
                next_lower = next_line.lower()
                
                # 停止合并的条件
                if (not next_line or
                    next_lower.startswith('http') or 
                    next_lower.startswith('www.') or
                    next_lower.startswith('doi:') or
                    'doi.org/' in next_lower or
                    next_lower.startswith('10.') or
                    re.match(r'^\d{4}\\s', next_line) or  # 日期开头
                    len(next_line) < 5 or  # 太短
                    is_skip_line(next_line, next_lower) or
                    (next_line and next_line[0].isupper())):  # 大写开头（新标题或作者）
                    break
                
                # 合并小写开头的行（标题 continuation）
                if next_line and not next_line[0].isupper():
                    title = title + ' ' + next_line
                    j += 1
                else:
                    break
            
            # 标题去重
            title_key = re.sub(r'\s+', '', title.lower())[:80]
            if len(title) < 15 or title_key in seen_titles:
                i = max(i + 1, j)
                continue
            seen_titles.add(title_key)
            
            # 向前看几行提取日期
            date = extract_date_from_line(line, lines[max(0, i-5):i])
            
            # 向后找 URL（最多看8行，适应合并后的位置）
            url = ''
            for k in range(j, min(j + 8, len(lines))):
                next_line = lines[k].strip()
                next_lower = next_line.lower()
                
                # 处理 markdown 链接格式: [title](url) 或 [title](url "title")
                md_match = re.match(r'\[(?:[^\]]*)\]\(([^)\s"\']+)\)', next_line)
                if md_match:
                    url = md_match.group(1).strip()
                    break
                
                # 跳过非链接行
                if next_lower.startswith('http'):
                    url = next_line.strip()
                    # 截断 URL 后的多余内容
                    url = re.split(r'[\s<>"\']', url)[0]
                    break
                elif next_lower.startswith('www.'):
                    url = 'https://' + next_line.strip().split()[0]
                    break
                elif 'doi.org/' in next_lower:
                    doi_match = re.search(r'doi\.org/[\S]+', next_line)
                    if doi_match:
                        url = 'https://' + doi_match.group(0)
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
            
            i = j  # 跳到合并后的位置
            continue
        
        i += 1

    return articles

def _extract_best_body(msg):
    if msg is None:
        return '', ''

    best_html = ''
    best_text = ''

    if msg.is_multipart():
        for part in msg.walk():
            ct = (part.get_content_type() or '').lower()
            if ct.startswith('multipart/'):
                continue
            if part.get('Content-Disposition', '').lower().startswith('attachment'):
                continue

            payload = part.get_payload(decode=True)
            if payload is None:
                continue
            charset = part.get_content_charset() or 'utf-8'
            try:
                decoded = payload.decode(charset, errors='replace')
            except Exception:
                decoded = payload.decode('utf-8', errors='replace')

            if ct == 'text/html' and len(decoded) > len(best_html):
                best_html = decoded
            elif ct == 'text/plain' and len(decoded) > len(best_text):
                best_text = decoded
    else:
        payload = msg.get_payload(decode=True)
        if payload is not None:
            charset = msg.get_content_charset() or 'utf-8'
            try:
                decoded = payload.decode(charset, errors='replace')
            except Exception:
                decoded = payload.decode('utf-8', errors='replace')
            if (msg.get_content_type() or '').lower() == 'text/html':
                best_html = decoded
            else:
                best_text = decoded

    return best_html, best_text


def fetch_emails():
    """连接 Gmail，读取最近期刊邮件"""
    if not IMAP_PASS:
        print("错误：需要 IMAP_PASS，在 .env 文件中设置")
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

        # 搜索最近 48 小时邮件（IMAP SINCE 只有日期粒度，需后续再按 Date 精确过滤）
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

                try:
                    msg_dt = parsedate_to_datetime(msg_date) if msg_date else None
                except Exception:
                    msg_dt = None
                if msg_dt and msg_dt < since:
                    continue

                print(f"  处理: {subject[:60]}")

                html, plain_text = _extract_best_body(msg)
                text = html_to_text(html) if html else (plain_text or '')

                articles = _extract_articles_from_html(html, subject)
                if not articles:
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
