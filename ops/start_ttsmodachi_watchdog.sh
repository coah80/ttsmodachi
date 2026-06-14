#!/usr/bin/env bash
set -euo pipefail
ROOT="${TTSMODACHI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
cd "$ROOT"
mkdir -p logs
if [ -f logs/ttsmodachi-watch.pid ]; then
  old_pid="$(cat logs/ttsmodachi-watch.pid 2>/dev/null || true)"
  if [ -n "$old_pid" ] && kill -0 "$old_pid" 2>/dev/null; then
    kill "$old_pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      kill -0 "$old_pid" 2>/dev/null || break
      sleep 0.5
    done
  fi
fi
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)"
LOG="$ROOT/logs/ttsmodachi-watch-$RUN_ID.log"
OUT="/tmp/ttsmodachi-watch-$RUN_ID.out"
nohup env WATCH_DURATION_SECONDS=0 WATCH_INTERVAL_SECONDS=60 WATCH_PROBE_EVERY_LOOPS=5 WATCH_RESTART_COOLDOWN_SECONDS=300 "$ROOT/ops/watch_ttsmodachi_health.sh" "$RUN_ID" >"$OUT" 2>&1 &
pid="$!"
echo "$pid" > "$ROOT/logs/ttsmodachi-watch.pid"
echo "$LOG" > "$ROOT/logs/ttsmodachi-watch.current"
echo "pid=$pid"
echo "log=$LOG"
echo "out=$OUT"
