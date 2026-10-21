#!/usr/bin/env bash
set -euo pipefail

usage() {
  echo "Usage: $0 --report PATH --repo PATH [--remote NAME] [--branch NAME]" >&2
}

REPORT=""
REPO=""
REMOTE="origin"
BRANCH=""
while (($#)); do
  case "$1" in
    --report) REPORT="${2:?Missing report path}"; shift 2 ;;
    --repo) REPO="${2:?Missing repository path}"; shift 2 ;;
    --remote) REMOTE="${2:?Missing remote name}"; shift 2 ;;
    --branch) BRANCH="${2:?Missing branch name}"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) usage; exit 2 ;;
  esac
done

if [[ -z "$REPORT" || -z "$REPO" || ! -f "$REPORT" ]]; then
  usage
  exit 2
fi

REPO_ROOT=$(git -C "$REPO" rev-parse --show-toplevel)
REPORT_ABS=$(python3 -c 'import os,sys; print(os.path.realpath(sys.argv[1]))' "$REPORT")
REPORT_REL=$(python3 -c 'import os,sys; print(os.path.relpath(sys.argv[1],sys.argv[2]))' "$REPORT_ABS" "$REPO_ROOT")
if [[ "$REPORT_REL" == .. || "$REPORT_REL" == ../* || "$REPORT_REL" == /* ]]; then
  echo "Report must be inside the target Git repository: $REPORT_ABS" >&2
  exit 1
fi

CURRENT_BRANCH=$(git -C "$REPO_ROOT" symbolic-ref --quiet --short HEAD) || {
  echo "Cannot publish from a detached HEAD." >&2
  exit 1
}
if [[ -n "$BRANCH" && "$BRANCH" != "$CURRENT_BRANCH" ]]; then
  echo "Configured branch '$BRANCH' is not the checked-out branch '$CURRENT_BRANCH'." >&2
  exit 1
fi
BRANCH="$CURRENT_BRANCH"

TRACKING_REF="refs/remotes/$REMOTE/$BRANCH"
if ! git -C "$REPO_ROOT" show-ref --verify --quiet "$TRACKING_REF"; then
  echo "Missing remote-tracking ref '$REMOTE/$BRANCH'; fetch before publishing." >&2
  exit 1
fi
if ! git -C "$REPO_ROOT" merge-base --is-ancestor "$TRACKING_REF" HEAD; then
  echo "Local branch and '$REMOTE/$BRANCH' have diverged; sync before publishing." >&2
  exit 1
fi
UNPUBLISHED=$(git -C "$REPO_ROOT" rev-list --count "$TRACKING_REF..HEAD")
if [[ "$UNPUBLISHED" != "0" ]]; then
  echo "Local branch has $UNPUBLISHED unpublished commit(s); publish them separately first." >&2
  exit 1
fi

git -C "$REPO_ROOT" add -- "$REPORT_REL"
if git -C "$REPO_ROOT" diff --cached --quiet HEAD -- "$REPORT_REL"; then
  echo "Report has no changes; skipping commit and push: $REPORT_REL"
  exit 0
fi

git -C "$REPO_ROOT" commit --only \
  -m "Add EAlert journal briefing: $(basename "$REPORT_ABS")" \
  -- "$REPORT_REL"
git -C "$REPO_ROOT" push "$REMOTE" "$BRANCH"
echo "Published report: $REPORT_REL"
