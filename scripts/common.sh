#!/usr/bin/env bash
# Shared helpers: keep notification state (state.json) on a dedicated `state` branch so that
# the long-running monitor and one-off manual checks share the same dedup state.
set -u
export GIT_AUTHOR_NAME="thsr-bot" GIT_AUTHOR_EMAIL="thsr-bot@users.noreply.github.com"
export GIT_COMMITTER_NAME="$GIT_AUTHOR_NAME" GIT_COMMITTER_EMAIL="$GIT_AUTHOR_EMAIL"

sync_config() {  # pick up settings changed from the web console
  git fetch -q --depth 1 origin main && git reset -q --hard origin/main || echo "[warn] config sync failed"
}

pull_state() {
  if git fetch -q origin state 2>/dev/null; then
    git show origin/state:state.json > state.json 2>/dev/null || true
  fi
}

push_state() {
  [ -f state.json ] || return 0
  local blob old tree parent commit
  blob=$(git hash-object -w state.json)
  old=$(git rev-parse -q --verify origin/state:state.json 2>/dev/null || true)
  [ "$blob" = "$old" ] && return 0
  tree=$(printf '100644 blob %s\tstate.json\n' "$blob" | git mktree)
  parent=$(git rev-parse -q --verify origin/state 2>/dev/null || true)
  commit=$(git commit-tree "$tree" ${parent:+-p "$parent"} -m "Update notification state")
  git push -q origin "$commit:refs/heads/state" || git push -q -f origin "$commit:refs/heads/state" || echo "[warn] state push failed"
  git fetch -q origin state 2>/dev/null || true
}

check_once() {
  sync_config
  pull_state
  python -m thsr_alert run || echo "[warn] check failed"
  push_state
}
