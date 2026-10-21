#!/usr/bin/env python3
"""Record only candidate papers cited in a saved report."""

import argparse
import json
from pathlib import Path

from state_store import load_state, record_reported_papers, save_state


def record(candidates_path, report_path, state_path):
    candidates = json.loads(Path(candidates_path).read_text(encoding="utf-8"))
    if not isinstance(candidates, dict) or not isinstance(candidates.get("papers"), list):
        raise ValueError("Candidates file must contain a papers array")
    report_file = Path(report_path)
    if not report_file.is_file():
        raise FileNotFoundError(f"Saved report not found: {report_file}")
    report = report_file.read_text(encoding="utf-8")
    if not report.strip():
        raise ValueError("Saved report is empty")

    state = load_state(state_path)
    added = record_reported_papers(candidates["papers"], report, state)
    if added:
        state["papers"].extend(added)
        save_state(state_path, state)
    return len(added)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidates", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument(
        "--state-file",
        required=True,
        type=Path,
        help="User-local sent-paper state JSON",
    )
    args = parser.parse_args()
    if not args.candidates.is_file():
        raise FileNotFoundError(f"Candidates file not found: {args.candidates}")
    count = record(args.candidates, args.report, args.state_file.expanduser())
    print(f"Recorded {count} paper(s) in {args.state_file.expanduser()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
