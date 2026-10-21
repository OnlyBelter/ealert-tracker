"""Read, match, migrate, and atomically write user-local paper state."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import re

from email_reader import normalize_url


def canonical_title(value):
    return re.sub(r"\W+", " ", (value or "").casefold()).strip()


def normalize_doi(value):
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(
        r"^https?://(?:dx\.)?doi\.org/",
        "",
        text,
        flags=re.IGNORECASE,
    )
    match = re.search(
        r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
        text,
        flags=re.IGNORECASE,
    )
    return match.group(0).rstrip(".,;)") if match else ""


def empty_state():
    return {"version": 1, "updated_at": None, "papers": []}


def load_state(path):
    state_path = Path(path).expanduser()
    if not state_path.exists():
        return empty_state()
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"Cannot read paper state file: {state_path}") from error
    if not isinstance(state, dict) or not isinstance(state.get("papers"), list):
        raise ValueError(f"Invalid paper state format: {state_path}")
    return state


def paper_identifiers(paper):
    identifiers = set()
    doi = normalize_doi(paper.get("doi", "")).casefold()
    title = canonical_title(paper.get("title", ""))
    url = normalize_url(paper.get("url") or paper.get("link") or "").casefold()
    if doi:
        identifiers.add("doi:" + doi)
    if title:
        identifiers.add("title:" + title)
    if url:
        identifiers.add("url:" + url)
    return identifiers


def _empty_index():
    return {"dois": set(), "urls": set(), "titles": {}}


def _index_paper(index, paper):
    doi = normalize_doi(paper.get("doi", "")).casefold()
    title = canonical_title(paper.get("title", ""))
    url = normalize_url(paper.get("url") or paper.get("link") or "").casefold()
    if doi:
        index["dois"].add(doi)
    if url:
        index["urls"].add(url)
    if title:
        index["titles"].setdefault(title, set()).add(doi)


def _is_duplicate(index, paper):
    doi = normalize_doi(paper.get("doi", "")).casefold()
    title = canonical_title(paper.get("title", ""))
    url = normalize_url(paper.get("url") or paper.get("link") or "").casefold()
    if doi and doi in index["dois"]:
        return True
    if url and url in index["urls"]:
        return True
    known_dois = index["titles"].get(title, set()) if title else set()
    if known_dois:
        return not doi or "" in known_dois or doi in known_dois
    return False


def filter_sent(papers, state):
    index = _empty_index()
    for paper in state.get("papers", []):
        if isinstance(paper, dict):
            _index_paper(index, paper)

    fresh = []
    for paper in papers:
        if not paper_identifiers(paper) or _is_duplicate(index, paper):
            continue
        fresh.append(paper)
        _index_paper(index, paper)
    return fresh


def save_state(path, state):
    state_path = Path(path).expanduser()
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state["version"] = 1
    state["updated_at"] = datetime.now(timezone.utc).isoformat()
    descriptor, temporary_path = tempfile.mkstemp(
        prefix=".sent-papers-", suffix=".json", dir=state_path.parent
    )
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(state, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temporary_path, state_path)
        os.chmod(state_path, 0o600)
    finally:
        if os.path.exists(temporary_path):
            os.unlink(temporary_path)


def report_contains_paper(report, paper):
    normalized_report = canonical_title(report)
    title = canonical_title(paper.get("title", ""))
    if title and title in normalized_report:
        return True
    doi = normalize_doi(paper.get("doi", "")).casefold()
    return bool(doi and doi in report.casefold())


def record_reported_papers(candidates, report_text, state):
    index = _empty_index()
    for paper in state.get("papers", []):
        if isinstance(paper, dict):
            _index_paper(index, paper)

    added = []
    sent_date = datetime.now(timezone.utc).date().isoformat()
    for paper in candidates:
        if not report_contains_paper(report_text, paper):
            continue
        if not paper_identifiers(paper) or _is_duplicate(index, paper):
            continue
        record = {
            "title": paper.get("title", ""),
            "doi": normalize_doi(paper.get("doi", "")),
            "url": normalize_url(paper.get("url", "")),
            "journal": paper.get("journal", ""),
            "source": paper.get("source", ""),
            "sent_date": sent_date,
        }
        added.append(record)
        _index_paper(index, record)
    return added


def convert_legacy_state(value):
    """Convert old nested sent-papers JSON without mutating its source."""
    records = []

    def visit(node):
        if isinstance(node, dict):
            if isinstance(node.get("title"), str) and node["title"].strip():
                records.append(node)
                return
            for key, child in node.items():
                if key not in ("_comment", "_format", "_last_updated"):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    state = empty_state()
    index = _empty_index()
    for record in records:
        paper = {
            "title": record.get("title", "").strip(),
            "doi": normalize_doi(record.get("doi", "")),
            "url": normalize_url(record.get("url") or record.get("link") or ""),
            "journal": record.get("journal", ""),
            "source": record.get("source", ""),
            "sent_date": str(record.get("sent_date", "")),
        }
        if not paper_identifiers(paper) or _is_duplicate(index, paper):
            continue
        state["papers"].append(paper)
        _index_paper(index, paper)
    return state
