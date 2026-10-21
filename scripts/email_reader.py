"""Pure helpers for parsing journal-alert MIME and HTML content."""

from html.parser import HTMLParser
import re
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse


JOURNAL_NAMES = (
    ("science translational medicine", "Science Translational Medicine"),
    ("nature computational science", "Nature Computational Science"),
    ("nature communications", "Nature Communications"),
    ("nature biotechnology", "Nature Biotechnology"),
    ("nature methods", "Nature Methods"),
    ("nature genetics", "Nature Genetics"),
    ("nature medicine", "Nature Medicine"),
    ("nature cancer", "Nature Cancer"),
    ("science immunology", "Science Immunology"),
    ("science advances", "Science Advances"),
    ("cell metabolism", "Cell Metabolism"),
    ("molecular cell", "Molecular Cell"),
    ("cell systems", "Cell Systems"),
    ("cell reports", "Cell Reports"),
    ("trends in biotechnology", "Trends in Biotechnology"),
    ("trends in molecular medicine", "Trends in Molecular Medicine"),
    ("pnas", "PNAS"),
    ("nature", "Nature"),
    ("science", "Science"),
    ("cell", "Cell"),
)

DEFAULT_JOURNAL_DOMAINS = (
    "nature.com",
    "springernature.com",
    "science.org",
    "aaas.org",
    "sciencepubs.org",
    "cell.com",
    "pnas.org",
    "elsevier.com",
)

TRACKING_DOMAINS = (
    "links.springernature.com",
    "click.science.org",
    "click.aaas.sciencepubs.org",
    "link.aaas.org",
    "go.aaas.org",
    "email.science.org",
)
DOI_PATTERN = re.compile(
    r"10\.\d{4,9}/[-._;()/:A-Z0-9]+",
    flags=re.IGNORECASE,
)

SKIP_TEXT = (
    "unsubscribe",
    "privacy policy",
    "manage preferences",
    "view in browser",
    "read more",
    "click here",
    "advertisement",
    "follow us",
    "all rights reserved",
    "table of contents",
    "sign up",
    "log in",
)


def domain_matches(hostname, allowed_domains):
    """Match a sender or link host to an exact domain or its subdomain."""
    host = (hostname or "").lower().rstrip(".")
    return any(
        host == domain.lower().rstrip(".")
        or host.endswith("." + domain.lower().rstrip("."))
        for domain in allowed_domains
        if domain
    )


def extract_journal_from_subject(subject):
    lowered = (subject or "").casefold()
    for needle, journal in JOURNAL_NAMES:
        if needle in lowered:
            return journal
    return ""


def normalize_url(url, allowed_domains=DEFAULT_JOURNAL_DOMAINS):
    """Remove tracking parameters and unwrap known query-based redirects."""
    value = (url or "").strip()
    if value.startswith("www."):
        value = "https://" + value
    parsed = urlparse(value)
    if parsed.scheme.lower() not in ("http", "https") or not parsed.hostname:
        return ""

    if domain_matches(parsed.hostname, TRACKING_DOMAINS):
        query = parse_qs(parsed.query)
        for key in ("url", "u", "redirect", "r", "dest", "destination", "target", "link"):
            for candidate in query.get(key, []):
                nested = urlparse(candidate)
                if (
                    nested.scheme.lower() in ("http", "https")
                    and nested.hostname
                    and (
                        domain_matches(
                            nested.hostname,
                            tuple(allowed_domains) + ("doi.org", "dx.doi.org"),
                        )
                    )
                    and candidate != value
                ):
                    parsed = nested
                    value = candidate
                    break
            else:
                continue
            break

    query = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {
        key: values for key, values in query.items()
        if not key.casefold().startswith(
            ("utm_", "wt.", "wt_", "spm", "cmpid", "mc_cid", "mc_eid", "mkt_tok")
        )
    }
    return urlunparse(parsed._replace(
        query=urlencode(
            [(key, item) for key, values in filtered.items() for item in values],
            doseq=True,
        ),
        fragment="",
    ))


def is_allowed_article_url(url, journal_domains=DEFAULT_JOURNAL_DOMAINS):
    normalized = normalize_url(url, journal_domains)
    if not normalized:
        return False
    host = urlparse(normalized).hostname
    return host == "doi.org" or host == "dx.doi.org" or domain_matches(
        host, tuple(journal_domains) + TRACKING_DOMAINS
    )


class LinkExtractor(HTMLParser):
    """Extract anchor text and href pairs, including nested inline tags."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = ""
        self._text = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag == "a":
            if self._depth == 0:
                self._href = dict(attrs).get("href", "")
                self._text = []
            self._depth += 1

    def handle_data(self, data):
        if self._depth:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag.casefold() == "a" and self._depth:
            self._depth -= 1
            if self._depth == 0:
                text = re.sub(r"\s+", " ", "".join(self._text)).strip()
                if text and self._href:
                    self.links.append((text, self._href))
                self._href = ""
                self._text = []


class TextExtractor(HTMLParser):
    """Convert HTML to readable text while retaining article links."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self._skip_depth = 0
        self._anchor_depth = 0
        self._anchor_href = ""

    def handle_starttag(self, tag, attrs):
        tag = tag.casefold()
        if tag in ("script", "style", "head"):
            self._skip_depth += 1
        elif not self._skip_depth and tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")
        elif not self._skip_depth and tag == "a":
            if self._anchor_depth == 0:
                self._anchor_href = dict(attrs).get("href", "")
            self._anchor_depth += 1

    def handle_data(self, data):
        if not self._skip_depth:
            self.parts.append(data)

    def handle_endtag(self, tag):
        tag = tag.casefold()
        if tag in ("script", "style", "head") and self._skip_depth:
            self._skip_depth -= 1
        elif not self._skip_depth and tag == "a" and self._anchor_depth:
            self._anchor_depth -= 1
            if self._anchor_depth == 0:
                if self._anchor_href:
                    self.parts.extend(("\n", self._anchor_href, "\n"))
                self._anchor_href = ""
        elif not self._skip_depth and tag in ("p", "div", "li", "tr", "h1", "h2", "h3"):
            self.parts.append("\n")


def html_to_text(html):
    parser = TextExtractor()
    try:
        parser.feed(html or "")
    except (ValueError, AssertionError):
        return ""
    text = "".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def is_skip_line(line):
    value = (line or "").strip()
    lowered = value.casefold()
    if len(value) < 4 or lowered.startswith(("http://", "https://", "www.")):
        return True
    if any(keyword in lowered for keyword in SKIP_TEXT):
        return True
    return bool(re.fullmatch(r"[\s\-–—=*_#.|•\[\]:]+", value))


def _valid_title(value):
    title = re.sub(r"\s+", " ", (value or "")).strip()
    if not 18 <= len(title) <= 300 or is_skip_line(title):
        return ""
    if not re.search(r"[A-Za-z]{3,}", title):
        return ""
    return title


def extract_articles_from_html(html, subject, journal_domains=DEFAULT_JOURNAL_DOMAINS):
    if not html:
        return []
    parser = LinkExtractor()
    try:
        parser.feed(html)
    except (ValueError, AssertionError):
        return []

    journal = extract_journal_from_subject(subject)
    results = []
    seen = set()
    for text, href in parser.links:
        title = _valid_title(text)
        url = normalize_url(href, journal_domains)
        if not title or not url or not is_allowed_article_url(url, journal_domains):
            continue
        key = (title.casefold(), url.casefold())
        if key in seen:
            continue
        seen.add(key)
        results.append({
            "title": title,
            "url": url,
            "journal": journal,
        })
    return results


def extract_articles_from_text(text, subject, journal_domains=DEFAULT_JOURNAL_DOMAINS):
    """Extract explicit Markdown links and title/URL pairs from plain text."""
    if not text:
        return []
    journal = extract_journal_from_subject(subject)
    results = []
    seen = set()

    for title_text, href in re.findall(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", text):
        title = _valid_title(title_text)
        url = normalize_url(href, journal_domains)
        key = (title.casefold(), url.casefold())
        if title and url and is_allowed_article_url(url, journal_domains) and key not in seen:
            seen.add(key)
            results.append({"title": title, "url": url, "journal": journal})

    lines = [line.strip() for line in text.splitlines()]
    for index, line in enumerate(lines):
        title = _valid_title(line)
        if not title:
            continue
        for candidate in lines[index + 1:index + 5]:
            if not candidate:
                continue
            url_match = re.search(r"https?://[^\s<>\])]+", candidate)
            if url_match:
                raw_url = url_match.group(0).rstrip(".,;)>")
            else:
                doi_match = DOI_PATTERN.search(candidate)
                if not doi_match:
                    continue
                raw_url = "https://doi.org/" + doi_match.group(0).rstrip(".,;)")
            url = normalize_url(raw_url, journal_domains)
            key = (title.casefold(), url.casefold())
            if url and is_allowed_article_url(url, journal_domains) and key not in seen:
                seen.add(key)
                results.append({"title": title, "url": url, "journal": journal})
            break
    return results


def extract_best_body(message):
    """Return the longest non-attachment HTML and plain-text body parts."""
    best_html = ""
    best_text = ""
    for part in message.walk():
        content_type = part.get_content_type().casefold()
        disposition = (part.get_content_disposition() or "").casefold()
        if content_type.startswith("multipart/") or disposition == "attachment":
            continue
        if content_type not in ("text/html", "text/plain"):
            continue
        try:
            content = part.get_content()
        except (LookupError, UnicodeError, AttributeError):
            payload = part.get_payload(decode=True) or b""
            content = payload.decode(part.get_content_charset() or "utf-8", errors="replace")
        if not isinstance(content, str):
            continue
        if content_type == "text/html" and len(content) > len(best_html):
            best_html = content
        elif content_type == "text/plain" and len(content) > len(best_text):
            best_text = content
    return best_html, best_text
