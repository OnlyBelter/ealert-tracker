#!/usr/bin/env python3
import argparse
import email
import imaplib
import json
import os
import sys
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4


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


def build_papers(hours: int, max_emails: int) -> List[Dict[str, Any]]:
    env = load_env(ENV_FILE)
    host = env.get("IMAP_HOST", "imap.gmail.com")
    user = env.get("IMAP_USER", "")
    password = env.get("IMAP_PASS", "")
    port = int(env.get("IMAP_PORT", "993") or "993")

    if not user or not password:
        raise RuntimeError("missing IMAP_USER/IMAP_PASS in .env")

    email_reader, parse_scholar_emails = _import_local_modules()

    now = datetime.now()
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
