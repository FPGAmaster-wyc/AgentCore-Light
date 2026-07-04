#!/usr/bin/env sh
# Local Cursor hook (Mac).
# Reads stdin JSON, tags it with source=local, writes to local queue.
QUEUE_DIR="${HOME}/.cursor/hooks/queue"
mkdir -p "$QUEUE_DIR"
payload=$(cat)
if [ -n "$payload" ]; then
  # Inject source: "local" if not present.
  case "$payload" in
    *'"source"'*) : ;;  # already tagged
    *) payload=$(printf '%s' "$payload" | sed 's/^{/{\"source\":\"local\",/' 2>/dev/null || printf '%s' "$payload") ;;
  esac
  file="$QUEUE_DIR/$(date +%s%N)-$$.json"
  printf '%s' "$payload" > "$file"
fi
exit 0
