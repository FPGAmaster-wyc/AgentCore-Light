#!/usr/bin/env sh
# Remote (SSH side) Cursor hook (Linux).
# Reads stdin JSON, tags it with source=ssh, writes to local queue.
# A queue worker forwards it to the Mac status light via SSH reverse tunnel.
QUEUE_DIR="${HOME}/.cursor/hooks/queue"
mkdir -p "$QUEUE_DIR"
payload=$(cat)
if [ -n "$payload" ]; then
  # Inject source: "ssh" if not present.
  case "$payload" in
    *'"source"'*) : ;;
    *) payload=$(printf '%s' "$payload" | sed 's/^{/{\"source\":\"ssh\",/' 2>/dev/null || printf '%s' "$payload") ;;
  esac
  file="$QUEUE_DIR/$(date +%s%N)-$$.json"
  printf '%s' "$payload" > "$file"
fi
exit 0
