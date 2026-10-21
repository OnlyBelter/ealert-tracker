#!/usr/bin/env python3
"""Read recent journal and Google Scholar alert emails as candidate JSON."""

import argparse
from datetime import datetime, timedelta, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
import imaplib
import json
import os
from pathlib import Path
import re
import ssl
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import email_reader
from parse_scholar_emails import parse_scholar_email
from state_store import filter_sent, load_state, normalize_doi


DEFAULT_CONFIG_PATH = Path.home() / ".config/ealert-tracker/config.json"
DEFAULT_CREDENTIALS_PATH = Path.home() / ".config/ealert-tracker/credentials.env"
DEFAULT_STATE_PATH = Path.home() / ".local/state/ealert-tracker/sent-papers.json"
DOI_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    flags=re.IGNORECASE,
)


def load_env_file(path):
    values = {}
    env_path = Path(path).expanduser()
    if not env_path.is_file():
        return values
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def load_config(path):
    config_path = Path(path).expanduser()
    if not config_path.is_file():
        raise FileNotFoundError(f"Configuration file not found: {config_path}")
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid JSON configuration: {config_path}") from error
    if not isinstance(config, dict):
        raise ValueError("Configuration must be a JSON object")

    required_lists = (
        "journal_sender_domains",
        "scholar_senders",
        "journal_subject_keywords",
        "scholar_subject_keywords",
        "exclude_subject_keywords",
        "target_topics",
    )
    for key in required_lists:
        value = config.get(key)
        if not isinstance(value, list) or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise ValueError(f"{key} must be a list of non-empty strings")
    if not config["journal_sender_domains"] or not config["scholar_senders"]:
        raise ValueError("At least one journal domain and Scholar sender are required")
    if not config["target_topics"]:
        raise ValueError("target_topics must contain at least one research topic")

    for key, default, minimum, maximum in (
        ("hours", 48, 1, 168),
        ("max_emails", 200, 1, 5000),
        ("imap_port", 993, 1, 65535),
        ("timeout_seconds", 30, 1, 300),
    ):
        try:
            value = int(config.get(key, default))
        except (TypeError, ValueError) as error:
            raise ValueError(f"{key} must be an integer") from error
        if not minimum <= value <= maximum:
            raise ValueError(f"{key} must be between {minimum} and {maximum}")
        config[key] = value

    config.setdefault("imap_host", "imap.gmail.com")
    config.setdefault("mailbox", "INBOX")
    config.setdefault("state_file", str(DEFAULT_STATE_PATH))
    config.setdefault("timezone", "Asia/Shanghai")
    config.setdefault("reports_dir", "~/Documents/ealert-tracker/reports")
    config.setdefault("publish_repo", "")
    config.setdefault("git_remote", "origin")
    config.setdefault("git_branch", "main")
    if not isinstance(config["imap_host"], str) or not config["imap_host"].strip():
        raise ValueError("imap_host must be a non-empty string")
    if not isinstance(config["mailbox"], str) or not config["mailbox"].strip():
        raise ValueError("mailbox must be a non-empty string")
    if not isinstance(config["state_file"], str) or not config["state_file"].strip():
        raise ValueError("state_file must be a non-empty path")
    if not isinstance(config["reports_dir"], str) or not config["reports_dir"].strip():
        raise ValueError("reports_dir must be a non-empty path")
    if not isinstance(config["timezone"], str) or not config["timezone"].strip():
        raise ValueError("timezone must be a non-empty IANA timezone")
    try:
        ZoneInfo(config["timezone"])
    except ZoneInfoNotFoundError as error:
        raise ValueError(f"Unknown timezone: {config['timezone']}") from error
    for key in ("publish_repo", "git_remote", "git_branch"):
        if not isinstance(config[key], str):
            raise ValueError(f"{key} must be a string")
    return config


def load_credentials(credentials_path):
    values = load_env_file(credentials_path)
    user = os.environ.get("IMAP_USER") or values.get("IMAP_USER", "")
    password = os.environ.get("IMAP_PASS") or values.get("IMAP_PASS", "")
    password = "".join(password.split())
    if not user or not password:
        raise ValueError(
            "Missing IMAP_USER or IMAP_PASS. Set them in the private "
            "credentials file or environment."
        )
    return {"user": user, "password": password}


def parse_message_date(value):
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_doi(value):
    match = DOI_PATTERN.search(value or "")
    return normalize_doi(match.group(0)) if match else ""


def sender_kind(sender, config):
    address = parseaddr(sender or "")[1].casefold()
    if not address or "@" not in address:
        return ""
    _, domain = address.rsplit("@", 1)
    if address in {value.casefold() for value in config["scholar_senders"]}:
        return "scholar"
    if email_reader.domain_matches(domain, config["journal_sender_domains"]):
        return "journal"
    return ""


def subject_is_excluded(subject, config):
    value = (subject or "").casefold()
    return any(term.casefold() in value for term in config["exclude_subject_keywords"])


def _candidate(
    title,
    url,
    source,
    journal="",
    email_date="",
    authors="",
    doi="",
    abstract="",
    researcher="",
    reported_year="",
):
    title = " ".join((title or "").split()).strip()
    normalized_url = email_reader.normalize_url(url) if url else ""
    return {
        "title": title,
        "url": normalized_url,
        "doi": normalize_doi(doi) or extract_doi(normalized_url),
        "journal": (journal or "").strip(),
        "source": source,
        "email_date": email_date,
        "authors": (authors or "").strip(),
        "abstract": " ".join((abstract or "").split()).strip(),
        "researcher": (researcher or "").strip(),
        "reported_year": str(reported_year or "").strip(),
    }


def parse_alert_message(message, kind, config):
    subject = str(message.get("Subject", ""))
    sender = str(message.get("From", ""))
    if subject_is_excluded(subject, config):
        return []

    html, plain = email_reader.extract_best_body(message)
    text = email_reader.html_to_text(html) if html else (plain or "")
    date = parse_message_date(message.get("Date"))
    date_text = date.isoformat() if date else ""

    if kind == "scholar":
        if config["scholar_subject_keywords"] and not any(
            term.casefold() in subject.casefold()
            for term in config["scholar_subject_keywords"]
        ):
            return []
        papers = parse_scholar_email(text, subject)
        return [
            _candidate(
                paper.get("title", ""),
                paper.get("url", ""),
                "scholar_alert",
                paper.get("journal", ""),
                date_text,
                paper.get("authors", ""),
                paper.get("doi", ""),
                paper.get("abstract", ""),
                paper.get("researcher", ""),
                paper.get("year", ""),
            )
            for paper in papers
            if paper.get("title")
        ]

    if config["journal_subject_keywords"] and not any(
        term.casefold() in subject.casefold()
        for term in config["journal_subject_keywords"]
    ):
        return []
    journal = email_reader.extract_journal_from_subject(subject)
    allowed_domains = config["journal_sender_domains"]
    articles = email_reader.extract_articles_from_html(
        html, subject, allowed_domains
    ) if html else []
    if not articles:
        articles = email_reader.extract_articles_from_text(
            text, subject, allowed_domains
        )
    return [
        _candidate(
            article.get("title", ""),
            article.get("url", ""),
            "journal_alert",
            article.get("journal") or journal,
            date_text,
            doi=extract_doi(article.get("url", "")),
        )
        for article in articles
        if article.get("title")
    ]


def _message_bytes(fetch_data):
    for item in fetch_data or []:
        if isinstance(item, tuple) and len(item) > 1 and isinstance(item[1], bytes):
            return item[1]
    return None


def deduplicate_papers(papers):
    results = []
    by_identifier = {}
    for paper in papers:
        doi = normalize_doi(paper.get("doi", "")).casefold()
        url = email_reader.normalize_url(paper.get("url", "")).casefold()
        title = re.sub(r"\W+", " ", paper.get("title", "").casefold()).strip()
        key = "doi:" + doi if doi else ("url:" + url if url else "title:" + title)
        if key == "title:":
            continue
        if key not in by_identifier:
            by_identifier[key] = len(results)
            results.append(paper)
            continue
        existing = results[by_identifier[key]]
        for field in ("doi", "url", "journal", "authors", "abstract", "researcher"):
            if not existing.get(field) and paper.get(field):
                existing[field] = paper[field]
        if len(paper.get("title", "")) > len(existing.get("title", "")):
            existing["title"] = paper["title"]
    return results


def collect_papers(config, credentials, now=None, imap_factory=None):
    end = now or datetime.now(timezone.utc)
    if end.tzinfo is None:
        end = end.replace(tzinfo=timezone.utc)
    end = end.astimezone(timezone.utc)
    start = end - timedelta(hours=config["hours"])
    coarse_since = (start - timedelta(days=1)).strftime("%d-%b-%Y")
    factory = imap_factory or imaplib.IMAP4_SSL
    mailbox = factory(
        config["imap_host"],
        config["imap_port"],
        ssl_context=ssl.create_default_context(),
        timeout=config["timeout_seconds"],
    )
    status = {
        "imap": {"status": "error", "count": 0},
        "journal_alerts": {"status": "ok", "count": 0},
        "scholar_alerts": {"status": "ok", "count": 0},
    }
    parse_errors = 0
    invalid_dates = 0
    try:
        try:
            result, _ = mailbox.login(credentials["user"], credentials["password"])
        except imaplib.IMAP4.error as error:
            raise RuntimeError("IMAP login failed; verify the App Password and IMAP access") from error
        if result != "OK":
            raise RuntimeError("IMAP login failed; verify the App Password and IMAP access")

        result, _ = mailbox.select(config["mailbox"], readonly=True)
        if result != "OK":
            raise RuntimeError("Could not open the configured mailbox in read-only mode")
        result, search_data = mailbox.uid("SEARCH", None, "SINCE", coarse_since)
        if result != "OK":
            raise RuntimeError("IMAP message search failed")

        uid_list = (search_data[0] if search_data else b"").split()
        total_matches = len(uid_list)
        truncated = total_matches > config["max_emails"]
        uid_list = uid_list[-config["max_emails"]:]
        papers = []
        for uid in uid_list:
            try:
                result, fetch_data = mailbox.uid("FETCH", uid, "(BODY.PEEK[])")
                raw = _message_bytes(fetch_data)
                if result != "OK" or not raw:
                    parse_errors += 1
                    continue
                message = BytesParser(policy=policy.default).parsebytes(raw)
                message_date = parse_message_date(message.get("Date"))
                if message_date is None:
                    invalid_dates += 1
                    continue
                if not start <= message_date <= end:
                    continue
                kind = sender_kind(str(message.get("From", "")), config)
                if not kind:
                    continue
                parsed = parse_alert_message(message, kind, config)
                papers.extend(parsed)
                source_key = "scholar_alerts" if kind == "scholar" else "journal_alerts"
                status[source_key]["count"] += len(parsed)
            except Exception:
                parse_errors += 1

        status["imap"] = {
            "status": "ok",
            "count": total_matches,
            "processed": len(uid_list),
            "truncated": truncated,
            "parse_errors": parse_errors,
            "invalid_dates": invalid_dates,
        }
        unique = deduplicate_papers(papers)
        state = load_state(config["state_file"])
        return {
            "generated_at": end.isoformat(),
            "window": {
                "start_utc": start.isoformat(),
                "end_utc": end.isoformat(),
                "hours": config["hours"],
            },
            "source_status": status,
            "candidate_count": len(unique),
            "papers": filter_sent(unique, state),
            "state_file": str(Path(config["state_file"]).expanduser()),
        }
    finally:
        try:
            mailbox.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        default=os.environ.get("EALERT_CONFIG", str(DEFAULT_CONFIG_PATH)),
        help="Path to private JSON configuration",
    )
    parser.add_argument(
        "--credentials",
        default=os.environ.get("EALERT_CREDENTIALS", str(DEFAULT_CREDENTIALS_PATH)),
        help="Path to private IMAP credentials file",
    )
    parser.add_argument("--output", help="Optional path for candidate JSON")
    parser.add_argument("--now", help=argparse.SUPPRESS)
    args = parser.parse_args()
    try:
        config = load_config(args.config)
        credentials = load_credentials(args.credentials)
        now = parse_message_date(args.now) if args.now else None
        if args.now and now is None:
            raise ValueError("--now must be an RFC 2822 date")
        output = collect_papers(config, credentials, now=now)
        rendered = json.dumps(output, ensure_ascii=False, indent=2)
        if args.output:
            output_path = Path(args.output).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(rendered + "\n", encoding="utf-8")
        print(rendered)
        return 0
    except imaplib.IMAP4.error:
        error = "IMAP connection failed; check Gmail access and network connectivity"
        failure = {
            "source_status": {
                "imap": {"status": "error", "error": error}
            },
            "candidate_count": 0,
            "papers": [],
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1
    except (OSError, ValueError, RuntimeError) as error:
        failure = {
            "source_status": {
                "imap": {"status": "error", "error": str(error)}
            },
            "candidate_count": 0,
            "papers": [],
        }
        print(json.dumps(failure, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
