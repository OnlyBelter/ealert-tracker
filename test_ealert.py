"""Offline regression tests for the EAlert Tracker Skill."""

from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.utils import format_datetime
import json
import os
from pathlib import Path
import ssl
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent
SCRIPTS = ROOT / "scripts"
import sys

sys.path.insert(0, str(SCRIPTS))

import email_pipeline
import email_reader
from migrate_state import migrate
from state_store import (
    convert_legacy_state,
    filter_sent,
    load_state,
    record_reported_papers,
    save_state,
)


def make_message(sender, subject, date, body, html=True):
    message = EmailMessage()
    message["From"] = sender
    message["To"] = "researcher@example.com"
    message["Subject"] = subject
    message["Date"] = format_datetime(date)
    if html:
        message.set_content("Plain-text fallback for this alert.")
        message.add_alternative(body, subtype="html")
    else:
        message.set_content(body)
    return message.as_bytes()


class FakeIMAP:
    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def login(self, user, password):
        self.calls.append(("login", user, password))
        return "OK", [b"authenticated"]

    def select(self, mailbox, readonly=False):
        self.calls.append(("select", mailbox, readonly))
        return "OK", [b"1"]

    def uid(self, command, *args):
        self.calls.append(("uid", command, args))
        if command == "SEARCH":
            return "OK", [b"101 102 103"]
        if command == "FETCH":
            raw = self.messages[args[0].decode("ascii")]
            return "OK", [(b"BODY[]", raw)]
        raise AssertionError(f"Unexpected IMAP UID command: {command}")

    def logout(self):
        self.calls.append(("logout",))
        return "BYE", [b"logged out"]


class ParserTests(unittest.TestCase):
    def test_sender_matching_rejects_lookalike_domains(self):
        config = email_pipeline.load_config(ROOT / "config.example.json")
        self.assertEqual(email_pipeline.sender_kind("Alerts <alerts@nature.com>", config), "journal")
        self.assertEqual(email_pipeline.sender_kind("alerts@sub.nature.com", config), "journal")
        self.assertEqual(email_pipeline.sender_kind("alerts@nature.com.attacker.org", config), "")
        self.assertEqual(
            email_pipeline.sender_kind("Google Alerts <scholaralerts-noreply@google.com>", config),
            "scholar",
        )

    def test_html_article_extraction_keeps_verified_hosts_and_unwraps_tracking(self):
        html = """
        <div><a href="https://www.nature.com/articles/10.1038/example?utm_source=mail">
        A single-cell atlas reveals tumor immune states</a></div>
        <a href="https://attacker-nature.com/phishing">
        Another computational biology paper title</a>
        <a href="https://click.science.org/?url=https%3A%2F%2Fwww.science.org%2Fdoi%2F10.1126%2Fscience.abc123">
        A translational genomics study links cell states and outcome</a>
        """
        papers = email_reader.extract_articles_from_html(
            html,
            "Nature Communications: Contents",
        )
        self.assertEqual(len(papers), 2)
        self.assertEqual(
            papers[0]["title"],
            "A single-cell atlas reveals tumor immune states",
        )
        self.assertEqual(
            papers[0]["url"],
            "https://www.nature.com/articles/10.1038/example",
        )
        self.assertEqual(
            papers[1]["url"],
            "https://www.science.org/doi/10.1126/science.abc123",
        )

    def test_scholar_parser_preserves_source_title_and_extracts_real_doi(self):
        body = """SINGLE-CELL FOUNDATION MODELS FOR TUMOR IMMUNOLOGY
https://scholar.google.com/scholar_url?url=https%3A%2F%2Fdoi.org%2F10.1234%2Freal-paper
A. Author, B. Author - Nature 2026
A long enough alert snippet that describes a study of tumor immune cells.
"""
        papers = email_pipeline.parse_scholar_email(
            body,
            "Researcher Name - 1 new articles",
        )
        self.assertEqual(len(papers), 1)
        self.assertEqual(papers[0]["title"], "SINGLE-CELL FOUNDATION MODELS FOR TUMOR IMMUNOLOGY")
        self.assertEqual(papers[0]["doi"], "10.1234/real-paper")
        self.assertEqual(papers[0]["authors"], "A. Author, B. Author")

    def test_config_requires_explicit_existing_file(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing.json"
            with self.assertRaisesRegex(FileNotFoundError, str(missing)):
                email_pipeline.load_config(missing)


class CollectorTests(unittest.TestCase):
    def test_collection_uses_read_only_imap_and_strict_48_hour_window(self):
        now = datetime(2026, 10, 21, 8, 0, tzinfo=timezone.utc)
        journal_html = """
        <a href="https://www.nature.com/articles/10.1038/example">
        A single-cell atlas reveals tumor immune states</a>
        """
        scholar_text = """SINGLE-CELL FOUNDATION MODELS FOR TUMOR IMMUNOLOGY
https://scholar.google.com/scholar_url?url=https%3A%2F%2Fdoi.org%2F10.1234%2Fscholar-paper
A. Author, B. Author - Nature 2026
A long enough alert snippet that describes a study of tumor immune cells.
"""
        messages = {
            "101": make_message(
                "alerts@nature.com",
                "Nature Communications: Contents",
                now - timedelta(hours=47),
                journal_html,
            ),
            "102": make_message(
                "scholaralerts-noreply@google.com",
                "Researcher - 1 new articles",
                now - timedelta(hours=12),
                scholar_text,
                html=False,
            ),
            "103": make_message(
                "alerts@nature.com.attacker.org",
                "Nature: Contents",
                now - timedelta(hours=1),
                journal_html,
            ),
            "104": make_message(
                "alerts@nature.com",
                "Nature: Contents",
                now - timedelta(hours=49),
                """
                <a href="https://www.nature.com/articles/10.1038/too-old">
                A separate paper outside the exact rolling time window</a>
                """,
            ),
        }
        fake = FakeIMAP(messages)
        config = email_pipeline.load_config(ROOT / "config.example.json")
        imap_options = {}

        def fake_imap_factory(host, port, ssl_context, timeout):
            imap_options.update({
                "host": host,
                "port": port,
                "ssl_context": ssl_context,
                "timeout": timeout,
            })
            return fake

        with tempfile.TemporaryDirectory() as directory:
            config["state_file"] = str(Path(directory) / "no-state.json")
            with patch.object(
                email_pipeline.imaplib,
                "IMAP4_SSL",
                side_effect=fake_imap_factory,
            ):
                output = email_pipeline.collect_papers(
                    config,
                    {"user": "reader@example.com", "password": "not-logged"},
                    now=now,
                )

        self.assertEqual(output["candidate_count"], 2)
        self.assertEqual(len(output["papers"]), 2)
        self.assertEqual(output["source_status"]["imap"]["status"], "ok")
        self.assertEqual(output["source_status"]["journal_alerts"]["count"], 1)
        self.assertEqual(output["source_status"]["scholar_alerts"]["count"], 1)
        self.assertTrue(imap_options["ssl_context"].check_hostname)
        self.assertEqual(imap_options["ssl_context"].verify_mode, ssl.CERT_REQUIRED)
        self.assertIn(("select", "INBOX", True), fake.calls)
        self.assertTrue(any(
            call[1] == "FETCH" and "(BODY.PEEK[])" in call[2]
            for call in fake.calls if call[0] == "uid"
        ))
        self.assertIn(("logout",), fake.calls)

    def test_collector_filters_previously_sent_doi_and_title(self):
        candidates = [
            {"title": "Known paper with a different display title", "doi": "10.1234/known"},
            {"title": "New research on spatial biology", "doi": "10.1234/new"},
        ]
        state = {
            "papers": [{
                "title": "Old title",
                "doi": "https://doi.org/10.1234/known",
                "sent_date": "2026-01-01",
            }]
        }
        self.assertEqual(
            [paper["doi"] for paper in filter_sent(candidates, state)],
            ["10.1234/new"],
        )


class StateTests(unittest.TestCase):
    def test_state_is_written_atomically_with_private_permissions(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "sent-papers.json"
            state = {"papers": [{"title": "A reported paper", "doi": "10.1234/a"}]}
            save_state(path, state)
            loaded = load_state(path)
            self.assertEqual(loaded["papers"][0]["doi"], "10.1234/a")
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(list(path.parent.glob(".sent-papers-*")), [])

    def test_legacy_migration_deduplicates_and_preserves_distinct_dois(self):
        legacy = {
            "papers": [
                {"title": "Same title", "doi": "10.1234/one", "sent_date": "2026-01-01"},
                {"title": "Same title", "doi": "10.1234/one", "sent_date": "2026-01-02"},
                {"title": "Same title", "doi": "10.1234/two", "sent_date": "2026-01-03"},
                {"title": "A distinct title without DOI", "sent_date": "2026-01-04"},
            ]
        }
        migrated = convert_legacy_state(legacy)
        self.assertEqual(len(migrated["papers"]), 3)
        self.assertEqual(
            {paper["doi"] for paper in migrated["papers"]},
            {"10.1234/one", "10.1234/two", ""},
        )

    def test_migration_refuses_to_overwrite_existing_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            legacy = root / "legacy.json"
            state = root / "state.json"
            legacy.write_text('{"papers":[{"title":"Paper"}]}', encoding="utf-8")
            original = legacy.read_bytes()
            state.write_text('{"version":1,"papers":[]}', encoding="utf-8")
            with self.assertRaisesRegex(FileExistsError, "will not be overwritten"):
                migrate(legacy, state)
            self.assertEqual(legacy.read_bytes(), original)

    def test_only_papers_cited_in_saved_report_are_recorded(self):
        state = {"papers": []}
        candidates = [
            {"title": "Selected single-cell tumor atlas", "doi": "10.1234/selected"},
            {"title": "Unselected genomics paper", "doi": "10.1234/unselected"},
        ]
        added = record_reported_papers(
            candidates,
            "# Briefing\nSelected single-cell tumor atlas\n",
            state,
        )
        self.assertEqual(len(added), 1)
        self.assertEqual(added[0]["doi"], "10.1234/selected")

    def test_same_title_with_distinct_verified_dois_is_not_collapsed(self):
        state = {"papers": [{"title": "Same title", "doi": "10.1234/one"}]}
        candidates = [{"title": "Same title", "doi": "10.1234/two"}]
        self.assertEqual(filter_sent(candidates, state), candidates)


class PublishTests(unittest.TestCase):
    def run_git(self, cwd, *args):
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "EAlert Test",
            "GIT_AUTHOR_EMAIL": "ealert-test@example.invalid",
            "GIT_COMMITTER_NAME": "EAlert Test",
            "GIT_COMMITTER_EMAIL": "ealert-test@example.invalid",
            "GIT_TERMINAL_PROMPT": "0",
        }
        return subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )

    def initialize_repo(self, base):
        bare = base / "remote.git"
        repo = base / "repo"
        self.run_git(base, "init", "--bare", str(bare))
        repo.mkdir()
        self.run_git(repo, "init", "-b", "main")
        self.run_git(repo, "remote", "add", "origin", str(bare))
        (repo / "tracked.txt").write_text("base\n", encoding="utf-8")
        self.run_git(repo, "add", "tracked.txt")
        self.run_git(repo, "commit", "-m", "test: initialize")
        self.run_git(repo, "push", "-u", "origin", "main")
        return repo, bare

    def invoke_publisher(self, report, repo):
        return subprocess.run(
            [
                "bash", str(SCRIPTS / "publish-report.sh"),
                "--report", str(report), "--repo", str(repo),
            ],
            capture_output=True,
            text=True,
            env={
                **os.environ,
                "GIT_AUTHOR_NAME": "EAlert Test",
                "GIT_AUTHOR_EMAIL": "ealert-test@example.invalid",
                "GIT_COMMITTER_NAME": "EAlert Test",
                "GIT_COMMITTER_EMAIL": "ealert-test@example.invalid",
                "GIT_TERMINAL_PROMPT": "0",
            },
        )

    def test_publisher_commits_report_only_and_preserves_other_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, _ = self.initialize_repo(base)
            unrelated = repo / "unrelated.txt"
            unrelated.write_text("keep staged\n", encoding="utf-8")
            self.run_git(repo, "add", "unrelated.txt")
            report = repo / "reports/2026/10/2026-W43/2026-10-21-journal-briefing.md"
            report.parent.mkdir(parents=True)
            report.write_text("# Verified report\n", encoding="utf-8")

            result = self.invoke_publisher(report, repo)
            self.assertEqual(result.returncode, 0, result.stderr)
            committed = self.run_git(
                repo, "show", "--pretty=format:", "--name-only", "HEAD"
            ).stdout.splitlines()
            staged = self.run_git(repo, "diff", "--cached", "--name-only").stdout.splitlines()
            self.assertEqual(
                committed,
                ["reports/2026/10/2026-W43/2026-10-21-journal-briefing.md"],
            )
            self.assertEqual(staged, ["unrelated.txt"])

    def test_publisher_rejects_report_outside_repository(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, _ = self.initialize_repo(base)
            report = base / "outside.md"
            report.write_text("outside\n", encoding="utf-8")
            result = self.invoke_publisher(report, repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("inside the target Git repository", result.stderr)

    def test_publisher_refuses_preexisting_unpublished_commits(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repo, bare = self.initialize_repo(base)
            (repo / "private-change.txt").write_text("local commit\n", encoding="utf-8")
            self.run_git(repo, "add", "private-change.txt")
            self.run_git(repo, "commit", "-m", "test: local unpublished commit")
            local_head = self.run_git(repo, "rev-parse", "HEAD").stdout.strip()
            remote_head = self.run_git(bare, "rev-parse", "refs/heads/main").stdout.strip()
            report = repo / "reports/briefing.md"
            report.parent.mkdir()
            report.write_text("# Report\n", encoding="utf-8")

            result = self.invoke_publisher(report, repo)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unpublished commit", result.stderr)
            self.assertEqual(
                self.run_git(repo, "rev-parse", "HEAD").stdout.strip(),
                local_head,
            )
            self.assertEqual(
                self.run_git(bare, "rev-parse", "refs/heads/main").stdout.strip(),
                remote_head,
            )


if __name__ == "__main__":
    unittest.main()
