#!/usr/bin/env python3
"""
email_reader.py
v3.9.2 — 重写版（2026-05-27）

准确性原则：提取的每个字段都必须真实存在，绝不捏造。
- 标题: 从邮件正文中提取，保留原文
- URL: 从标题后紧跟的链接提取，作为论文链接
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
from datetime import datetime, timedelta, timezone

# ============ 配置 ============
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(SCRIPT_DIR, '..', '.env')


def load_env(path):
    """从 .env 文件加载环境变量"""
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

# 期刊发件人域名（用于过滤）
JOURNAL_DOMAINS = [
    'nature.com',
    'science.org',
    'aaas.org',
    'sciencepubs.org',
    'cell.com',
    'pnas.org',
    'elsevier.com',
]

# Science 系列跟踪链接域名
SCIENCE_TRACKING_DOMAINS = [
    'click.science.org',
    'science.10sr9c.cn',
    'science.1bo8ae.cn',
    'staging.science.org',
    'prod.science.org',
    'em.science.org',
    'email.science.org',
    'daily.science.org',
    'link.immunology.org',
    'link.aaas.org',
    'advances.sciencemag.org',
    'stm.sciencemag.org',
    'go.aaas.org',
]


# ============ 工具函数 ============

def decode_str(s):
    """解码 email 头部编码字符串"""
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
    """HTML 转纯文本（保留结构）"""
    if not html:
        return ''
    # 移除 style/script/head 标签
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<head[^>]*>.*?</head>', '', html, flags=re.DOTALL | re.IGNORECASE)
    # 保留换行
    html = re.sub(r'<br\s*/?>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</p\s*>', '\n\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</div\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</li\s*>', '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'</h[1-6]\s*>', '\n\n', html, flags=re.IGNORECASE)
    # 将 <a href="...">text</a> 替换为 text\nURL
    html = re.sub(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([^<]*)</a>',
                  r'\2\n\1', html, flags=re.IGNORECASE)
    # 去除所有其余 HTML 标签
    text = re.sub(r'<[^>]+>', ' ', html)
    # HTML 实体解码
    replacements = [
        ('&nbsp;', ' '), ('&amp;', '&'), ('&lt;', '<'), ('&gt;', '>'),
        ('&quot;', '"'), ('&#39;', "'")
    ]
    for ent, rep in replacements:
        text = text.replace(ent, rep)
    text = re.sub(r'&#[0-9]+;', ' ', text)
    text = re.sub(r'&[a-z]+;', ' ', text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


class LinkExtractor(HTMLParser):
    """
    从 HTML 中提取所有 <a> 链接。
    支持嵌套标签（如 <a ...><span>text</span></a>）。
    """
    def __init__(self):
        super().__init__()
        self.links = []
        self._in_a = False
        self._href = ''
        self._text_chunks = []
        self._a_depth = 0  # 嵌套深度

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag == 'a':
            href = next((v for k, v in attrs if k.lower() == 'href' and v), '')
            if not self._in_a:
                self._in_a = True
                self._href = href
                self._text_chunks = []
                self._a_depth = 1
            else:
                # 嵌套 <a>，增加深度但不重置
                self._a_depth += 1
        elif self._in_a:
            # 在 <a> 内的标签，不截断文本
            pass

    def handle_data(self, data):
        if self._in_a and data:
            self._text_chunks.append(data)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag == 'a' and self._in_a:
            self._a_depth = max(0, self._a_depth - 1)
            if self._a_depth == 0:
                text = re.sub(r'\s+', ' ', ''.join(self._text_chunks)).strip()
                href = (self._href or '').strip()
                if text and href:
                    self.links.append((text, href))
                self._in_a = False
                self._href = ''
                self._text_chunks = []


def unwrap_tracking_link(url):
    """
    解包期刊跟踪链接，返回真实 URL。
    支持 Nature (links.springernature.com) 和 Science 系列。
    """
    if not url:
        return url
    url_lower = url.lower()

    # —— Nature 加密跟踪链接 ——
    if 'links.springernature.com' in url_lower:
        try:
            import urllib.request
            # 只获取重定向 URL，不下载内容
            class _Handler(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    raise urllib.error.HTTPError(req.full_url, code, '', headers, None)
            opener = urllib.request.build_opener(_Handler)
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            try:
                opener.open(url, timeout=5)
            except urllib.error.HTTPError as e:
                if e.code in (301, 302, 303, 307, 308) and e.headers.get('Location'):
                    final = e.headers['Location']
                    if 'links.springernature.com' not in final.lower():
                        return final
        except Exception:
            pass
        return url

    # —— Science 系列跟踪链接 ——
    for prefix in SCIENCE_TRACKING_DOMAINS:
        if prefix in url_lower:
            try:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query or '')
                # 方式1: 标准 url 参数
                for key in ('url', 'u', 'redirect', 'r', 'dest', 'destination', 'target', 'goto', 'link'):
                    if key in qs and qs[key]:
                        candidate = unquote(qs[key][0])
                        if candidate.lower().startswith(('http://', 'https://')):
                            return candidate
                # 方式2: 从 URL 路径中直接提取真实链接
                match = re.search(r'https?://[^\s"\'<>]{10,200}', url)
                if match:
                    candidate = unquote(match.group(0))
                    if any(d in candidate.lower() for d in
                           ('science.org', 'aaas.org', 'nature.com', 'cell.com', 'pnas.org', 'doi.org')):
                        return candidate
            except Exception:
                pass
            break  # 匹配到一个前缀就够

    return url


def normalize_url(url):
    """清理 URL：去除跟踪参数、规范格式"""
    if not url:
        return ''
    url = url.strip()
    if url.startswith('www.'):
        url = 'https://' + url
    if not url.lower().startswith(('http://', 'https://')):
        return ''

    # 先解包跟踪链接
    url = unwrap_tracking_link(url)

    parsed = urlparse(url)
    qs = parse_qs(parsed.query or '', keep_blank_values=True)

    # 去掉已知跟踪参数
    drop_prefixes = ('utm_', 'WT.', 'wt_', 'spm', 'cmpid', 'cid', 'mc_cid', 'mc_eid', 'mkt_tok')
    kept = {k: v for k, v in qs.items() if not any(k.startswith(p) for p in drop_prefixes)}

    new_query = urlencode([(k, v) for k, vals in kept.items() for v in vals], doseq=True) if kept else ''
    parsed = parsed._replace(query=new_query, fragment='')
    return urlunparse(parsed)


def extract_journal_from_subject(subject):
    """从邮件 Subject 识别期刊名"""
    if not subject:
        return 'Journal'
    s = subject.lower()
    mapping = [
        ('nature cancer', 'Nature Cancer'),
        ('nature communications', 'Nature Communications'),
        ('nature computational', 'Nature Computational Science'),
        ('nature methods', 'Nature Methods'),
        ('nature genetics', 'Nature Genetics'),
        ('nature medicine', 'Nature Medicine'),
        ('nature biotechnology', 'Nature Biotechnology'),
        ('nature', 'Nature'),
        ('science translational medicine', 'Science Translational Medicine'),
        ('science immunology', 'Science Immunology'),
        ('science advances', 'Science Advances'),
        ('science', 'Science'),
        ('cell metabolism', 'Cell Metabolism'),
        ('cell reports', 'Cell Reports'),
        ('molecular cell', 'Molecular Cell'),
        ('trends in biotechnology', 'Trends in Biotechnology'),
        ('trends in', 'Trends'),
        ('cell', 'Cell'),
        ('pnas', 'PNAS'),
    ]
    for key, name in mapping:
        if key in s:
            return name
    return 'Journal'


def is_journal_email(sender):
    """判断发件人是否为期刊"""
    if not sender:
        return False
    sender_lower = sender.lower()
    return any(d in sender_lower for d in JOURNAL_DOMAINS)


def is_skip_line(line):
    """
    判断是否为应跳过的行（导航/页脚/按钮等）。
    返回 True 表示跳过。
    """
    if not line or len(line) < 3:
        return True
    lower = line.lower()

    # 纯链接行
    if lower.startswith(('http://', 'https://', 'www.')):
        return True
    # 邮箱地址
    if '@' in line and '.' in line and not re.search(r'[a-z]{4,}', line):
        return True
    # 全大写短行（可能是栏目名）
    if line.isupper() and len(line) < 60 and ' ' not in line:
        return True
    # 已知垃圾关键词
    skip_kws = [
        'read more', 'view article', 'full text', 'abstract', 'pdf',
        'table of contents', 'unsubscribe', 'privacy policy',
        'manage preferences', 'sign up', 'register', 'log in',
        'contact us', 'copyright', 'all rights reserved',
        'follow us', 'twitter', 'facebook', 'advertisement',
    ]
    if any(kw in lower for kw in skip_kws):
        return True
    return False


def is_author_line(line):
    """
    判断是否为作者行（PNAS/Science 邮件格式）。
    作者行特征：多个单词、大部分首字母大写、通常含 "and" 或逗号。
    """
    words = line.split()
    if len(words) < 2:
        return False
    capitalized = sum(1 for w in words if w and w[0].isupper())
    ratio = capitalized / len(words)

    lower = line.lower()
    # 条件1: >= 50% 首字母大写 且 含 "and" 或逗号
    if ratio >= 0.5 and (' and ' in lower or ',' in line):
        return True
    # 条件2: >= 70% 首字母大写（纯作者名列表）
    if ratio >= 0.7:
        return True
    return False


def extract_date_from_context(lines):
    """
    从给定行列表中提取日期字符串。
    支持格式: '06 May 2026', 'May 6, 2026', '2026-05-06'
    """
    patterns = [
        (r'\b(\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+20\d{2})\b',),
        (r'\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+20\d{2})\b',),
        (r'\b(20\d{2}-\d{2}-\d{2})\b',),
    ]
    for line in lines:
        for (pat,) in patterns:
            m = re.search(pat, line, re.IGNORECASE)
            if m:
                return m.group(1).strip()
    return ''


def extract_articles_from_html(html, subject):
    """
    从 HTML 邮件中提取文章列表。
    优先使用 <a> 标签的结构化提取。
    """
    if not html:
        return []

    parser = LinkExtractor()
    try:
        parser.feed(html)
    except Exception:
        return []

    journal = extract_journal_from_subject(subject)
    articles = []
    seen = set()

    for text, href in parser.links:
        title = re.sub(r'\s+', ' ', (text or '')).strip()
        # 过滤过短/过长的标题
        if len(title) < 20 or len(title) > 250:
            continue
        lower_title = title.lower()
        # 过滤导航/按钮文字
        if any(kw in lower_title for kw in
               ('read more', 'view article', 'full text', 'abstract', 'pdf',
                'table of contents', 'unsubscribe', 'privacy', 'manage preferences',
                'sign up', 'register', 'log in', 'contact us')):
            continue
        # 必须包含至少3个连续小写字母（排除全大写栏目名）
        if not re.search(r'[a-z]{3,}', title):
            continue

        # 解包跟踪链接
        url = normalize_url(href)
        if not url:
            continue
        lower_url = url.lower()
        if 'unsubscribe' in lower_url:
            continue

        # 验证 URL 是否为有效期刊链接
        is_journal_domain = any(d in lower_url for d in JOURNAL_DOMAINS)
        has_doi = 'doi.org/' in lower_url
        is_tracking = any(d in lower_url for d in SCIENCE_TRACKING_DOMAINS)
        if not (is_journal_domain or has_doi or is_tracking):
            continue

        # 去重
        title_key = re.sub(r'\s+', '', lower_title)[:80]
        url_key = lower_url.split('?')[0][:160]
        dedup_key = (title_key, url_key)
        if dedup_key in seen:
            continue
        seen.add(dedup_key)

        articles.append({'title': title, 'url': url, 'date': '', 'journal': journal})

    return articles


def extract_articles_from_text(text, subject):
    """
    从纯文本邮件中提取文章列表（HTML 提取失败时的兜底方案）。
    PNAS 邮件格式：标题（可能跨多行）→ 作者行 → DOI 链接
    """
    if not text:
        return []

    articles = []
    seen_titles = set()
    lines = text.split('\n')
    journal = extract_journal_from_subject(subject)

    i = 0
    while i < len(lines):
        line = lines[i].strip()
        lower_line = line.lower()

        # 跳过无意义行
        if not line or is_skip_line(line):
            i += 1
            continue

        # 不是有效标题行，跳过
        if not (15 <= len(line) <= 300
                and re.search(r'[a-z]{3,}', line)
                and not lower_line.startswith(('http://', 'https://', 'www.'))
                and '@' not in line):
            i += 1
            continue

        # 清理标题
        title = re.sub(r'\s+', ' ', line).strip()
        title = re.sub(r'^[\s\-\*\."|•\[\]:]+', '', title).strip()

        # 尝试向后合并多行标题（PNAS 格式：标题被 <br> 分割成多行）
        j = i + 1
        while j < min(i + 6, len(lines)):
            next_line = lines[j].strip()
            if not next_line:
                j += 1
                continue
            next_lower = next_line.lower()
            # 停止条件：空行、URL、日期、作者行、新标题
            if (next_lower.startswith(('http://', 'https://', 'www.', 'doi:'))
                    or 'doi.org/' in next_lower
                    or re.match(r'^\d{4}\s', next_line)
                    or len(next_line) < 5
                    or is_skip_line(next_line)
                    or (next_line[0].isupper() and not next_line[0].islower())):
                break
            # 合并小写开头的 continuation 行
            if not next_line[0].isupper():
                title = title + ' ' + next_line
                j += 1
            else:
                break

        # 去重检查
        title_key = re.sub(r'\s+', '', title.lower())[:80]
        if len(title) < 15 or title_key in seen_titles:
            i = max(i + 1, j)
            continue
        seen_titles.add(title_key)

        # 向前查找日期
        date = extract_date_from_context(lines[max(0, i - 5):i])

        # 向后查找 URL（从 j 开始，跳过作者行）
        url = ''
        for k in range(j, min(j + 10, len(lines))):
            next_line = lines[k].strip()
            if not next_line:
                continue
            next_lower = next_line.lower()

            # 跳过作者行
            if is_author_line(next_line) and not next_lower.startswith(('http', 'doi')):
                continue

            # Markdown 链接格式: [title](url)
            md_match = re.match(r'\[[^\]]*\]\(([^)\s"\']+)\)', next_line)
            if md_match:
                url = md_match.group(1).strip()
                break

            if next_lower.startswith('http'):
                url = re.split(r'[\s<>"\']', next_line.strip())[0]
                break
            elif next_lower.startswith('www.'):
                url = 'https://' + next_line.strip().split()[0]
                break
            elif 'doi.org/' in next_lower:
                doi_match = re.search(r'https?://(?:dx\.)?doi\.org/[\S]+', next_line)
                if not doi_match:
                    doi_match = re.search(r'doi\.org/[\S]+', next_line)
                if doi_match:
                    url = doi_match.group(0)
                    if not url.startswith('http'):
                        url = 'https://' + url
                    url = re.split(r'[\s<>"\']', url)[0]
                    break
                break
            elif next_lower.startswith('doi:'):
                doi_val = next_line.split(':', 1)[1].strip()
                url = f'https://doi.org/{doi_val}'
                break
            elif next_lower.startswith('10.'):
                # 可能是纯 DOI
                doi_val = next_line.strip().split()[0]
                url = f'https://doi.org/{doi_val}'
                break

            # 遇到明显非链接行，停止搜索
            if (len(next_line) < 5
                    or is_skip_line(next_line)
                    or (next_line[0].isupper() and not next_line[0].islower())):
                break

        # 规范化 URL
        if url:
            url = normalize_url(url)

        articles.append({
            'title': title,
            'url': url or '',
            'date': date,
            'journal': journal,
        })

        i = max(i + 1, j)

    return articles


def extract_best_body(msg):
    """从邮件消息中提取最佳 HTML 和纯文本正文"""
    best_html = ''
    best_text = ''

    if msg is None:
        return best_html, best_text

    if msg.is_multipart():
        for part in msg.walk():
            ct = (part.get_content_type() or '').lower()
            # 跳过附件和多部分容器
            if (ct.startswith('multipart/')
                    or (part.get('Content-Disposition') or '').lower().startswith('attachment')):
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
            ct = (msg.get_content_type() or '').lower()
            if ct == 'text/html':
                best_html = decoded
            else:
                best_text = decoded

    return best_html, best_text


def fetch_emails():
    """
    连接 Gmail IMAP，读取最近 48 小时的期刊邮件。
    返回结果列表，每项含 uid/subject/from/journal/articles 等。
    """
    if not IMAP_PASS:
        print('错误：需要 IMAP_PASS，在 .env 文件中设置')
        return []

    print(f'连接 Gmail: {IMAP_USER}')

    try:
        mail = imaplib.IMAP4_SSL(IMAP_HOST, 993)
        mail.login(IMAP_USER, IMAP_PASS)
        print('登录成功')
    except Exception as e:
        print(f'登录失败: {e}')
        return []

    try:
        mail.select('INBOX')

        # 搜索最近 48 小时（IMAP SINCE 只支持日期粒度，后续再精确过滤）
        since_dt = datetime.now(timezone.utc) - timedelta(hours=48)
        date_str = since_dt.strftime('%d-%b-%Y')
        print(f'搜索最近 48 小时邮件 (SINCE {date_str})...')

        status, uids = mail.search(None, f'SINCE {date_str}')
        if status != 'OK':
            print(f'搜索失败: {status}')
            return []

        uid_list = uids[0].split()
        print(f'找到 {len(uid_list)} 封邮件，处理最近 30 封...')

        results = []

        for uid in uid_list[-30:]:
            try:
                status, msg_data = mail.fetch(uid, '(RFC822)')
                if status != 'OK' or not msg_data or not msg_data[0]:
                    continue

                raw_email = msg_data[0][1]
                if not isinstance(raw_email, bytes):
                    raw_email = raw_email.encode('utf-8', errors='replace')
                msg = email.message_from_bytes(raw_email)

                sender = decode_str(msg.get('From', ''))
                if not is_journal_email(sender):
                    continue

                subject = decode_str(msg.get('Subject', ''))
                msg_date_str = msg.get('Date', '')

                # 精确过滤：解析邮件 Date 头，与 since_dt 比较
                try:
                    msg_dt = parsedate_to_datetime(msg_date_str) if msg_date_str else None
                    if msg_dt and msg_dt.tzinfo is None:
                        msg_dt = msg_dt.replace(tzinfo=timezone.utc)
                    if msg_dt and msg_dt < since_dt:
                        continue
                except Exception:
                    pass  # 无法解析日期时不过滤

                journal = extract_journal_from_subject(subject)
                print(f'  处理: {subject[:60]}')

                html, plain_text = extract_best_body(msg)
                text = html_to_text(html) if html else (plain_text or '')

                # 优先用 HTML 结构化提取，失败时用纯文本兜底
                articles = extract_articles_from_html(html, subject)
                if not articles:
                    articles = extract_articles_from_text(text, subject)

                if articles:
                    results.append({
                        'uid': uid.decode() if isinstance(uid, bytes) else str(uid),
                        'from': sender,
                        'subject': subject,
                        'date': msg_date_str,
                        'journal': journal,
                        'articles': articles,
                        'text_preview': (text or '')[:500],
                    })

            except Exception as e:
                print(f'  读取失败: {e}')
                continue

        print(f'\n共读取 {len(results)} 封期刊邮件')
        for r in results:
            n_url = sum(1 for a in r['articles'] if a.get('url'))
            print(f'  - {r["subject"][:60]} ({len(r["articles"])} 篇, {n_url} 篇含链接)')

        return results

    finally:
        try:
            mail.logout()
        except Exception:
            pass


def main():
    print('=' * 60)
    print(f'期刊邮件读取器 v3.9.2 — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    print('=' * 60)

    results = fetch_emails()

    output = {
        'version': '3.9.2',
        'date': datetime.now(timezone.utc).isoformat(),
        'total_emails': len(results),
        'total_articles': sum(len(r['articles']) for r in results),
        'emails': results,
    }

    with open(OUTPUT_JSON, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    print(f'\nJSON 已保存: {OUTPUT_JSON}')

    # 保存人类可读摘要
    lines = []
    lines.append(f'期刊邮件摘要 v3.9.2 — {datetime.now().strftime("%Y-%m-%d %H:%M")}')
    lines.append(f'共 {len(results)} 封期刊邮件，{output["total_articles"]} 篇文章\n')
    lines.append('=' * 60)

    for i, r in enumerate(results, 1):
        lines.append(f'\n{i}. [{r["journal"]}] {r["subject"]}')
        for j, a in enumerate(r['articles'], 1):
            url_info = f' 🔗 {a["url"][:80]}' if a.get('url') else ' ⚠️ 无链接'
            date_info = f' 📅 {a["date"]}' if a.get('date') else ''
            lines.append(f'   {i}.{j}. {a["title"][:100]}{date_info}{url_info}')

    txt_content = '\n'.join(lines)
    with open(OUTPUT_TXT, 'w', encoding='utf-8') as f:
        f.write(txt_content)
    print(f'文本已保存: {OUTPUT_TXT}')
    print('\n完成！')


if __name__ == '__main__':
    main()
