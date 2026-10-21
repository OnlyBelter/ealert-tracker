#!/usr/bin/env python3
"""Migrate a legacy sent-papers JSON file into user-local state."""

import argparse
import json
from pathlib import Path

from state_store import convert_legacy_state, save_state


def migrate(legacy_path, state_path):
    legacy_file = Path(legacy_path).expanduser()
    target = Path(state_path).expanduser()
    if not legacy_file.is_file():
        raise FileNotFoundError(f"Legacy state file not found: {legacy_file}")
    if target.exists():
        raise FileExistsError(
            f"State file already exists and will not be overwritten: {target}"
        )
    try:
        legacy = json.loads(legacy_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"Invalid legacy state JSON: {legacy_file}") from error
    state = convert_legacy_state(legacy)
    save_state(target, state)
    return len(state["papers"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--legacy-state", required=True, type=Path)
    parser.add_argument("--state-file", required=True, type=Path)
    args = parser.parse_args()
    count = migrate(args.legacy_state, args.state_file)
    print(f"Migrated {count} paper record(s) to {args.state_file.expanduser()}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError) as error:
        print(f"Error: {error}")
        raise SystemExit(1)
