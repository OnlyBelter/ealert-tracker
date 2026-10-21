# EAlert Tracker

EAlert Tracker is a portable TRAE Skill for finding research papers in recent
journal Table of Contents and Google Scholar Alert email. It collects candidate
metadata with Python's standard library, then uses the Skill to select papers
for your configured research topics, verify citations, and write a Chinese
report.

## Features

- Reads journal and Scholar Alert email from Gmail over read-only IMAP.
- Searches a rolling 48-hour window and checks message timestamps precisely.
- Filters out non-research items and papers unrelated to your configured topics.
- Verifies bibliographic details before including them in a report.
- Stores deduplication state outside the Skill checkout.
- Optionally publishes one generated report to a configured Git repository.
- Uses no Node.js packages or third-party Python dependencies.

## Install

Clone the repository into your TRAE Skill directory:

```bash
mkdir -p "$HOME/.trae/skills"
git clone https://github.com/OnlyBelter/ealert-tracker.git \
  "$HOME/.trae/skills/ealert-tracker"
```

Reload TRAE or the current workspace so it can discover the Skill. The
collector requires Python 3.9 or later.

## Configure Gmail

Create a Gmail App Password for the account that receives your journal and
Google Scholar Alerts. See [Google's App Password guide](https://myaccount.google.com/apppasswords).
Keep it private; never commit it to this repository.

```bash
mkdir -p "$HOME/.config/ealert-tracker"
cp -n "$HOME/.trae/skills/ealert-tracker/config.example.json" \
  "$HOME/.config/ealert-tracker/config.json"
cp -n "$HOME/.trae/skills/ealert-tracker/credentials.example.env" \
  "$HOME/.config/ealert-tracker/credentials.env"
chmod 600 "$HOME/.config/ealert-tracker/credentials.env"
```

Edit `credentials.env` with your Gmail address and App Password. Edit
`config.json` to set your research topics and report directory. The credential
file and mutable state stay outside the Skill checkout. The collector uses
validated SSL/TLS, opens the mailbox read-only, and does not configure SMTP.

The sample configuration documents its fields here:

| Setting | Purpose |
| --- | --- |
| `hours` | Rolling email search window; defaults to 48 hours. |
| `max_emails` | Maximum recent messages to inspect per run. |
| `journal_sender_domains` | Exact journal domains and their subdomains to accept. |
| `scholar_senders` | Exact Google Scholar Alert sender addresses to accept. |
| `target_topics` | Research areas the Skill uses for relevance decisions. |
| `timezone` | Timezone for report dates, archive paths, and Schedule defaults. |
| `reports_dir` | Local root directory for generated reports. |
| `state_file` | User-local DOI/title/URL deduplication history. |
| `publish_repo` | Optional local Git repository for report-only publishing. |
| `git_remote`, `git_branch` | Remote and checked-out branch used for publishing. |

The collector also accepts `IMAP_USER` and `IMAP_PASS` from the process
environment. Environment values take precedence over the private credentials
file. You can set `EALERT_CONFIG` and `EALERT_CREDENTIALS` to use other paths.

## Update

For an existing installation, back up or migrate its personal `sent-papers.json`
before updating. Then fast-forward the Skill checkout:

```bash
git -C "$HOME/.trae/skills/ealert-tracker" pull --ff-only
```

See [Existing installations](#existing-installations) for the state migration
command.

## Run once

Ask TRAE to use the `ealert-tracker` Skill for a one-time report. A one-time
request does not create or change a Schedule. The Skill returns the complete
report in the task result. It only writes a report when it finds new,
topic-relevant research papers.

To test the collector directly, run:

```bash
python3 "$HOME/.trae/skills/ealert-tracker/scripts/email_pipeline.py" \
  --config "$HOME/.config/ealert-tracker/config.json" \
  --credentials "$HOME/.config/ealert-tracker/credentials.env" \
  --output /tmp/ealert-candidates.json
```

This command connects to Gmail and reads the configured mailbox. The JSON
contains candidate metadata, per-source status, and no complete email bodies.
Remove the temporary file after inspection.

## Create a daily Schedule

Ask TRAE to create a Schedule only when you want recurring runs. For example:

> Use the `ealert-tracker` Skill to create a daily task at 08:00
> (`Asia/Shanghai`). Check for an equivalent task first. Use my configured
> Gmail credentials, report directory, and state file. Return the complete
> report in the task result. If Git publishing is configured, publish only the
> newly generated report. Do not send QQ messages or email.

TRAE uses its built-in Schedule capability. The default time is 08:00 in
`Asia/Shanghai`; the example configuration can set a different timezone.
Creating a Schedule does not run the tracker immediately. The scheduled prompt
must include absolute paths so it works without the setup conversation.

## Reports and publishing

Reports use this archive layout under `reports_dir`:

```text
YYYY/MM/YYYY-Www/YYYY-MM-DD-journal-briefing.md
```

Git publishing is disabled when `publish_repo` is empty. To enable it, set
`publish_repo` to a local Git repository and make sure `reports_dir` is inside
that repository. The publisher refuses unsafe branch states and commits only
the generated report. It never runs `git add .`.

## Existing installations

The repository no longer includes the historical personal `sent-papers.json`.
Before updating an older checkout, copy that file to a private backup outside
the checkout. After installing the new Skill, migrate the backup:

```bash
python3 "$HOME/.trae/skills/ealert-tracker/scripts/migrate_state.py" \
  --legacy-state "$HOME/.config/ealert-tracker/sent-papers-legacy.json" \
  --state-file "$HOME/.local/state/ealert-tracker/sent-papers.json"
```

Migration creates a private user-local state file and refuses to overwrite an
existing one. Fresh installations start empty.

## Tests

Run the offline tests from the repository root. They mock IMAP responses and
use temporary Git repositories; they do not access your Gmail account or push
to GitHub.

```bash
python3 -m unittest -v test_ealert
python3 -m py_compile scripts/*.py test_ealert.py
bash -n scripts/publish-report.sh
```

## License

This project is licensed under the MIT License.
