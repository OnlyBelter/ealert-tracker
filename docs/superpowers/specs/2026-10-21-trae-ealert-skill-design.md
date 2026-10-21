# EAlert Tracker standalone TRAE Skill design

## Status

Design approved. This specification is ready for user review. Implementation
must not start until the user approves this document.

## Goal

Turn the existing EAlert Tracker repository into a portable TRAE Skill that
users can install from GitHub, configure with their own Gmail account, and
explicitly schedule with TRAE Schedule. Preserve the useful journal Table of
Contents (ToC) and Google Scholar Alert workflows while removing QClaw-specific
paths, personal defaults, and unnecessary runtime dependencies.

## Scope

The daily tracker reads journal alert and Google Scholar Alert emails received
within a rolling 48-hour window. It selects research papers relevant to the
user-configured research topics, verifies bibliographic details against
reliable sources, writes a Chinese Markdown report, and returns the report in
the TRAE task result.

The tracker excludes news, promotions, corrections, replies, and other
non-research items. It does not create a recurring task during a one-time run.
TRAE Schedule creates a recurring task only after an explicit user request.
The default schedule is daily at 08:00 in `Asia/Shanghai`, matching the
existing EAlert task configuration. The separate weekly research-summary
automation remains out of scope.

QQ delivery and outbound email are not part of the portable Skill. GitHub
report publishing remains optional and requires an explicit local repository
configuration.

## Architecture

The repository has two responsibilities:

1. A Python standard-library collector connects to Gmail over IMAP SSL/TLS in
   read-only mode, retrieves a bounded set of recent messages, and extracts
   candidate metadata from journal ToC and Google Scholar Alert emails.
2. The TRAE Skill reviews collector output, filters for the configured topics,
   verifies title, authors, journal, date, DOI, link, and abstract from
   publisher pages or trusted metadata services, and writes the final report.

The collector emits structured JSON and per-source status. It does not
generate interpretive prose, update sent-paper state, or publish files. The
Skill updates state only after it saves a non-empty report.

## Configuration and credentials

The repository provides non-secret configuration examples. Users keep their
own files outside the Skill checkout:

- General settings include research topics, the 48-hour window, allowed
  journal sender domains, output directory, timezone, and optional publishing
  repository.
- Gmail credentials use a private App Password file or environment variables.
  The App Password is never stored in repository configuration or logs.
- The default IMAP connection uses SSL/TLS certificate validation and
  read-only mailbox selection. The workflow does not configure SMTP.

Configuration validation fails with a clear message for missing explicit
files, invalid values, or absent credentials. It does not silently substitute
defaults for an explicitly requested but missing configuration.

## Collection and reporting

The collector validates sender domains as exact domains or their subdomains,
recognizes the configured journal subject patterns, and matches the Scholar
sender explicitly. IMAP's date search is only a coarse server-side filter;
the collector applies a strict timestamp check to enforce the rolling window.
It normalizes MIME headers, extracts article links from HTML, unwraps known
publisher tracking links where possible, and falls back to plain-text parsing.
It does not guess titles, DOI values, or other bibliographic fields.

The Skill treats email content as untrusted input. It does not follow
instructions found in email bodies. It uses DOI, canonical title, and
normalized URL to identify duplicates across sources and prior reports. The
report follows the repository template, uses the configured local archive path,
and labels unconfirmed metadata instead of inferring it as fact.

If there are no relevant new papers, the Skill returns a short no-results
status, does not create an empty report, and does not update deduplication
state. If all configured email sources fail, it reports an error rather than
claiming that no papers were found. Partial source or message parsing failures
are disclosed alongside usable results.

## State migration

The current repository tracks a personal `sent-papers.json` file containing
approximately 1,300 records. The new repository version removes this file
from its current tree and does not rewrite Git history. New installations
start with an empty user-local state file and do not inherit this history.

Existing users can copy their current `sent-papers.json` to the documented
user state path before updating the Skill. A migration utility converts the
legacy format, writes state atomically with restrictive file permissions, and
leaves the source file unchanged. The Skill never writes user state back into
the repository.

## Report publishing

Publishing is disabled by default. When enabled, a local publisher accepts one
report path and one target repository. It rejects paths outside the repository,
detached or diverged branches, and pre-existing unpublished local commits. It
stages and commits only the generated report; it never stages the whole
working tree. The report directory must be inside the configured publishing
repository.

## Installation and scheduling

The README documents direct installation from the repository into a TRAE Skill
directory, Python requirements, private Gmail setup, configuration, one-time
execution, and updates. It also includes a prompt users can give TRAE to create
a self-contained daily Schedule task.

Before creating a Schedule, the Skill checks for an equivalent existing task
and validates the collector, configuration, output directory, and optional
publishing repository. The scheduled prompt includes absolute paths and does
not rely on the creating conversation. Creating a schedule does not trigger an
immediate report run.

## Repository changes

The implementation is expected to:

- Replace the OpenClaw/QClaw Skill frontmatter and instructions with standard
  TRAE Skill metadata and workflow guidance.
- Refactor the active collector and parsers into a Python-standard-library
  workflow and retire the Node.js entrypoint and runtime dependencies.
- Add safe example configuration, external state handling, state migration,
  and optional report-only Git publishing.
- Remove tracked personal state from the current repository tree, tracked
  bytecode, and outdated runtime artifacts that are not needed to install the
  Skill.
- Rewrite installation and scheduling documentation and update the report
  template.
- Add offline tests for IMAP/MIME parsing, sender and time-window filters,
  Scholar alerts, deduplication, state migration, and report-only publishing.

## Verification and acceptance criteria

The implementation is ready when:

- A fresh clone installs without Node.js or third-party Python packages.
- Missing credentials and invalid explicit configuration fail clearly.
- IMAP remains read-only and uses validated TLS.
- Fixtures cover journal ToC and Scholar Alert parsing without real mailbox
  access.
- Tests verify strict 48-hour filtering, sender validation, topic filtering,
  duplicate detection, and state updates only after a saved report.
- A no-results run and a source-failure run are distinguishable.
- A temporary Git repository test confirms that publishing commits only the
  requested report and rejects unsafe branch states.
- Skill metadata, configuration examples, and documentation are internally
  consistent, and no credentials or personal state are included in new files.

## Decisions

- Use Gmail App Password authentication; OAuth is not part of this version.
- Use Python standard-library collection and TRAE Skill report orchestration.
- Report only configured-topic research papers; exclude non-research content.
- Keep user credentials and mutable state outside the Skill checkout.
- Do not distribute the existing personal sent-paper history in the new tree.
- Preserve daily scheduling at 08:00 `Asia/Shanghai` as the documented
  default; require explicit user intent before Schedule creation.
- Keep GitHub publishing optional and QQ/email delivery out of scope.
