#!/usr/bin/env python3
import argparse
import email
import re
import imaplib
import json
import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

# 兼容映射：email_reader.py 重写后去除了函数名前的下划线
# 这里统一做映射，避免修改 email_pipeline.py 的大量调用
import email_reader as _er
for _old, _new in [
    ('_extract_best_body', 'extract_best_body'),
    ('_extract_articles_from_html', 'extract_articles_from_html'),
    ('_html_to_text', 'html_to_text'),
    ('_is_journal_email', 'is_journal_email'),
    ('_extract_journal_from_subject', 'extract_journal_from_subject'),
    ('_normalize_url', 'normalize_url'),
    ('_unwrap_tracking_link', 'unwrap_tracking_link'),
]:
    if not hasattr(_er, _old) and hasattr(_er, _new):
        setattr(_er, _old, getattr(_er, _new))
# 让后续代码能用 email_reader.xxx 访问
import email_reader  # noqa: F401


SCRIPT_DIR = Path(__file__).resolve().parent
ROOT_DIR = SCRIPT_DIR.parent
ENV_FILE = ROOT_DIR / ".env"

SCHOLAR_SENDERS = ["scholaralerts-noreply@google.com"]
SCHOLAR_EXCLUDE_SUBJECTS = ["confirm your scholar alert"]

EXCLUDE_SUBJECT_KEYWORDS = [
    "Security alert",
    "Login",
    "Careers",
    "Career Path",
    "Speak up for science",
    "Unsubscribe",
    "In Other Journals",
]

JOURNAL_SUBJECT_KEYWORDS = [
    "Nature",
    "Science",
    "Cell",
    "PNAS",
    "Translational",
    "Immunology",
    "Advances",
    "Cancer",
    "Communications",
    "Computational",
    "Biotechnology",
    "Methods",
    "Genetics",
    "Medicine",
    "Molecular",
    "Reports",
    "Metabolism",
    "Trends",
]


def load_env(path: Path) -> Dict[str, str]:
    env: Dict[str, str] = {}
    if path.exists():
        for raw in path.read_text().splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def _decode_header_value(value: Optional[str]) -> str:
    if not value:
        return ""
    try:
        from email.header import decode_header

        parts = decode_header(value)
        out: List[str] = []
        for part, charset in parts:
            if isinstance(part, bytes):
                cs = charset or "utf-8"
                try:
                    out.append(part.decode(cs, errors="replace"))
                except Exception:
                    out.append(part.decode("utf-8", errors="replace"))
            else:
                out.append(str(part))
        return "".join(out)
    except Exception:
        return value


def _safe_parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except Exception:
        return None


def _matches_any(text: str, keywords: List[str]) -> bool:
    lower = (text or "").lower()
    return any(k.lower() in lower for k in keywords)


def _dedup_papers(papers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen: Dict[str, int] = {}
    out: List[Dict[str, Any]] = []
    for p in papers:
        link = (p.get("link") or "").split("?", 1)[0].lower().strip()
        doi = (p.get("doi") or "").split("?", 1)[0].lower().strip()
        if link or doi:
            key = f"{link}|{doi}"
        else:
            title = (p.get("title") or "").lower()
            title_key = "".join([c for c in title if c.isalnum()])[:60]
            key = f"T:{title_key}"

        idx = seen.get(key)
        if idx is None:
            seen[key] = len(out)
            out.append(p)
            continue
        prev = out[idx]
        if len(p.get("title") or "") > len(prev.get("title") or ""):
            out[idx] = p
    return out


def _read_message_bytes(imap: imaplib.IMAP4_SSL, uid: bytes) -> Optional[bytes]:
    try:
        status, msg_data = imap.fetch(uid, "(RFC822)")
        if status != "OK" or not msg_data:
            return None
        return msg_data[0][1]
    except Exception:
        return None


def _import_local_modules():
    sys.path.insert(0, str(SCRIPT_DIR))
    import email_reader  # type: ignore
    import parse_scholar_emails  # type: ignore

    return email_reader, parse_scholar_emails


def _extract_pseudo_abstract(email_text: str, title: str, link: str) -> str:
    """从邮件正文中提取伪摘要（v3.9.0）
    策略：找到标题所在位置，向后取1-3段描述性文字，过滤元信息和无关内容。
    """
    if not email_text or not title:
        return ''
    
    # 找标题在正文中的位置
    title_lower = title.lower()
    lines = email_text.split('\n')
    title_idx = -1
    for i, line in enumerate(lines):
        # 标题行通常完整出现或部分匹配
        line_clean = re.sub(r'[^a-z0-9\s]', '', line.lower())
        title_clean = re.sub(r'[^a-z0-9\s]', '', title_lower)
        if len(title_clean) > 15 and title_clean[:40] in line_clean:
            title_idx = i
            break
    
    if title_idx < 0:
        return ''
    
    # 收集标题后的1-3段文字
    abstract_parts = []
    skip_count = 0  # 跳过空行计数
    
    for i in range(title_idx + 1, min(title_idx + 20, len(lines))):
        line = lines[i].strip()
        
        # 跳过：空行、URL、元信息
        if not line:
            skip_count += 1
            if skip_count > 1:  # 超过1个空行则停止
                break
            continue
        skip_count = 0
        
        lower_line = line.lower()
        
        # 跳过无关内容
        if any(k in lower_line for k in [
            'click here', 'unsubscribe', 'view in browser',
            'advertisement', 'you are receiving',
            'brought to you', 'follow us', 'twitter', 'facebook',
            'image:', 'figure', 'fig.', 'table',
            '©', 'copyright', 'all rights reserved',
            'website:', 'visit:', 'read more',
        ]):
            continue
        
        # 跳过纯标题（ALL CAPS 短行）
        if line.isupper() and len(line) < 80:
            continue
        
        # 跳过引用/转发标记
        if re.match(r'^>\s*', line):
            continue
        
        # 跳过过短或过长的行
        if len(line) < 40 or len(line) > 500:
            continue
        
        # 这是描述性文字（包含动词或研究术语）
        abstract_parts.append(line)
        if len(abstract_parts) >= 3:
            break
    
    if not abstract_parts:
        return ''
    
    result = ' '.join(abstract_parts)
    # 清理多余空格
    result = re.sub(r'\s+', ' ', result).strip()
    # 截断过长内容
    if len(result) > 600:
        result = result[:600] + '...'
    return result


def build_papers(hours: int, max_emails: int) -> List[Dict[str, Any]]:
    env = load_env(ENV_FILE)
    host = env.get("IMAP_HOST", "imap.gmail.com")
    user = env.get("IMAP_USER", "")
    password = env.get("IMAP_PASS", "")
    port = int(env.get("IMAP_PORT", "993") or "993")

    if not user or not password:
        raise RuntimeError("missing IMAP_USER/IMAP_PASS in .env")

    email_reader, parse_scholar_emails = _import_local_modules()

    now = datetime.now().astimezone()
    since = now - timedelta(hours=hours)
    imap_since = (now - timedelta(days=max(1, int(hours / 24) + 1))).strftime("%d-%b-%Y")

    imap = imaplib.IMAP4_SSL(host, port)
    imap.login(user, password)
    try:
        imap.select("INBOX")
        status, uids = imap.search(None, f"SINCE {imap_since}")
        if status != "OK":
            return []
        uid_list = uids[0].split()
        if not uid_list:
            return []

        uid_list = uid_list[-max_emails:]
        papers: List[Dict[str, Any]] = []

        for uid in uid_list:
            raw = _read_message_bytes(imap, uid)
            if not raw:
                continue
            msg = email.message_from_bytes(raw)

            sender = _decode_header_value(msg.get("From", ""))
            subject = _decode_header_value(msg.get("Subject", ""))
            msg_date = msg.get("Date", "") or ""

            dt = _safe_parse_date(msg_date)
            if dt and dt < since:
                continue

            lower_sender = sender.lower()
            lower_subject = subject.lower()

            if _matches_any(subject, EXCLUDE_SUBJECT_KEYWORDS):
                continue

            is_scholar = any(s in lower_sender for s in SCHOLAR_SENDERS)
            if is_scholar and _matches_any(lower_subject, SCHOLAR_EXCLUDE_SUBJECTS):
                continue

            html, plain = email_reader._extract_best_body(msg)
            text = email_reader.html_to_text(html) if html else (plain or "")

            if is_scholar:
                extracted = parse_scholar_emails.parse_scholar_email(text, subject)
                for p in extracted:
                    papers.append(
                        {
                            "id": str(uuid4()),
                            "title": p.get("title") or "",
                            "authors": p.get("authors") or "",
                            "journal": p.get("journal") or "",
                            "date": p.get("year") or "",
                            "link": p.get("url") or "",
                            "doi": p.get("doi") or "",
                            "source": "scholar",
                            "researcher": p.get("researcher") or "Unknown",
                            "abstract": p.get("abstract") or "",
                        }
                    )
                continue

            is_journal = email_reader.is_journal_email(sender) or _matches_any(subject, JOURNAL_SUBJECT_KEYWORDS)
            if not is_journal:
                continue

            articles = email_reader._extract_articles_from_html(html, subject)
            if not articles:
                articles = email_reader.extract_articles_from_text(text, subject)

            for a in articles:
                # v3.9.0: 从邮件正文中提取伪摘要（用于 API 失败的兜底）
                # 策略：找标题后第1-3段的描述性文字，过滤掉元信息
                pseudo_abstract = _extract_pseudo_abstract(text, a.get('title') or '', a.get('url') or '')
                papers.append(
                    {
                        "id": str(uuid4()),
                        "title": a.get("title") or "",
                        "authors": "见原文",
                        "journal": a.get("journal") or email_reader.extract_journal_from_subject(subject),
                        "date": a.get("date") or "",
                        "link": a.get("url") or "",
                        "doi": "",
                        "source": "email",
                        "researcher": "",
                        "abstract": "",
                        "email_body": pseudo_abstract,  # v3.9.0: 邮件正文伪摘要
                    }
                )

        return _dedup_papers(papers)
    finally:
        try:
            imap.logout()
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=48)
    parser.add_argument("--max-emails", type=int, default=60)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    papers = build_papers(hours=args.hours, max_emails=args.max_emails)
    payload = {
        "version": "1.0",
        "generated_at": datetime.now().isoformat(),
        "hours": args.hours,
        "total_papers": len(papers),
        "papers": papers,
    }

    if args.json:
        sys.stdout.write(json.dumps(payload, ensure_ascii=False))
        return

    sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
