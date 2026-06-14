#!/usr/bin/env bash
set -u
ROOT="${TTSMODACHI_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
LOG_DIR="$ROOT/logs"
mkdir -p "$LOG_DIR"
RUN_ID="${1:-$(date -u +%Y%m%dT%H%M%SZ)}"
LOG="$LOG_DIR/ttsmodachi-watch-$RUN_ID.log"
INTERVAL_SECONDS="${WATCH_INTERVAL_SECONDS:-60}"
DURATION_SECONDS="${WATCH_DURATION_SECONDS:-0}"
PROBE_EVERY="${WATCH_PROBE_EVERY_LOOPS:-5}"
RESTART_COOLDOWN_SECONDS="${WATCH_RESTART_COOLDOWN_SECONDS:-300}"
LOCK="$LOG_DIR/ttsmodachi-watch.lock"

cd "$ROOT" || exit 1
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "$(date -u +%FT%TZ) another watcher is already running" | tee -a "$LOG"
  exit 2
fi

summary_json_to_line() {
  python3 -c 'import json,sys
try:
    s=json.load(sys.stdin)
    a=s.get("analytics",{})
    r=s.get("renderer",{})
    ws=(r.get("pool") or {}).get("workers") or []
    print("servers=%s linked=%s renders=%s inflight=%s readyWorkers=%s workerErrors=%s activeJobs=%s" % (a.get("serverCount"), a.get("linkedAccountCount"), a.get("renderRequestCount"), r.get("inflightRenders"), sum(1 for w in ws if w.get("ready")), sum(1 for w in ws if w.get("last_error")), sum(int(w.get("active_job_count") or 0) for w in ws)))
except Exception as e:
    print("summary_error=" + type(e).__name__)
'
}

render_probe() {
  python3 -c 'import json,time,urllib.request
payload=json.dumps({"text":"watch probe %s"%int(time.time()),"voice":{},"mode":"text"}).encode()
req=urllib.request.Request("http://127.0.0.1:18080/render",data=payload,headers={"Content-Type":"application/json"},method="POST")
start=time.time()
try:
    r=urllib.request.urlopen(req,timeout=45)
    r.read(16)
    print("ok status=%s cache=%s ms=%s elapsed=%.2f"%(r.status,r.headers.get("X-Cache"),r.headers.get("X-Render-Time-Ms"),time.time()-start))
    r.close()
except Exception as e:
    print("fail %s %s elapsed=%.2f"%(type(e).__name__,str(e)[:160],time.time()-start))
'
}

now_epoch() { date +%s; }
last_tts_worker_restart=0
last_bot_recover=0
loop=0
baseline_restarts=""
start_at=$(now_epoch)
end_at=0
if [ "$DURATION_SECONDS" -gt 0 ]; then
  end_at=$(( start_at + DURATION_SECONDS ))
fi

echo "$(date -u +%FT%TZ) watch_start mode=$([ "$DURATION_SECONDS" -gt 0 ] && echo duration || echo indefinite) duration=${DURATION_SECONDS}s interval=${INTERVAL_SECONDS}s probe_every=${PROBE_EVERY} cooldown=${RESTART_COOLDOWN_SECONDS}s log=$LOG" >> "$LOG"

while true; do
  if [ "$end_at" -gt 0 ] && [ "$(now_epoch)" -ge "$end_at" ]; then
    break
  fi

  loop=$((loop + 1))
  ts="$(date -u +%FT%TZ)"
  alerts=()
  actions=()
  current_epoch=$(now_epoch)

  ps_line="$(docker compose ps --services --filter status=running 2>/dev/null | tr '\n' ',' | sed 's/,$//')"
  inspect="$(docker compose ps -q bot bot2 tts-worker 2>/dev/null | xargs -r docker inspect -f '{{.Name}} restart={{.RestartCount}} oom={{.State.OOMKilled}} status={{.State.Status}} health={{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}' 2>/dev/null | tr '\n' ';')"
  restarts="$(printf '%s' "$inspect" | sed -E 's#[^;]*restart=([0-9]+)[^;]*#\1 #g')"
  if [ -z "$baseline_restarts" ]; then baseline_restarts="$restarts"; fi

  container_problem=0
  if printf '%s' "$inspect" | grep -q 'oom=true'; then alerts+=("oom"); container_problem=1; fi
  if printf '%s' "$inspect" | grep -q 'status=exited\|status=dead'; then alerts+=("container_down"); container_problem=1; fi
  if ! printf '%s' "$ps_line" | grep -q 'bot' || ! printf '%s' "$ps_line" | grep -q 'bot2' || ! printf '%s' "$ps_line" | grep -q 'tts-worker'; then alerts+=("missing_running_service"); container_problem=1; fi
  if [ -n "$restarts" ] && [ "$restarts" != "$baseline_restarts" ]; then alerts+=("restart_count_changed:${baseline_restarts}->${restarts}"); baseline_restarts="$restarts"; fi

  summary="$(curl -fsS http://127.0.0.1:18080/api/bot/summary 2>/dev/null | summary_json_to_line || echo 'summary_error=curl')"
  ready_workers="$(printf '%s' "$summary" | sed -nE 's/.*readyWorkers=([0-9]+).*/\1/p')"
  worker_errors="$(printf '%s' "$summary" | sed -nE 's/.*workerErrors=([0-9]+).*/\1/p')"
  inflight="$(printf '%s' "$summary" | sed -nE 's/.*inflight=([0-9]+).*/\1/p')"

  renderer_problem=0
  if printf '%s' "$summary" | grep -q 'summary_error'; then alerts+=("summary_failed"); renderer_problem=1; fi
  if [ -n "$ready_workers" ] && [ "$ready_workers" -lt 1 ]; then alerts+=("no_ready_workers"); renderer_problem=1; fi
  if [ -n "$worker_errors" ] && [ "$worker_errors" -gt 0 ]; then alerts+=("worker_errors=$worker_errors"); renderer_problem=1; fi
  if [ -n "$inflight" ] && [ "$inflight" -gt 80 ]; then alerts+=("high_inflight=$inflight"); fi

  recent_logs="$(timeout 20s docker compose logs --since=75s --tail=600 --no-color bot bot2 tts-worker 2>/dev/null || true)"
  appfails="$(printf '%s\n' "$recent_logs" | grep -Eic 'TTS playback job failed|Renderer failed with HTTP 500|Renderer queue is full|Traceback \(most recent call last\)|Timed out waiting for Citra renderer|CRITICAL|ConnectionRefused|OOM|Killed' || true)"
  renderer_fails="$(printf '%s\n' "$recent_logs" | grep -Eic 'Renderer failed with HTTP 500|Renderer queue is full|Timed out waiting for Citra renderer|Renderer worker .*failed startup|All renderer workers failed' || true)"
  if [ "$appfails" -gt 0 ]; then alerts+=("appfails=$appfails"); fi
  if [ "$renderer_fails" -gt 0 ]; then alerts+=("renderer_fails=$renderer_fails"); renderer_problem=1; fi

  stats="$(timeout 10s sh -c 'docker compose ps -q bot bot2 tts-worker 2>/dev/null | xargs -r docker stats --no-stream --format "{{.Name}} cpu={{.CPUPerc}} mem={{.MemUsage}}"' 2>/dev/null | tr '\n' ';' || true)"

  probe="skip"
  if [ $((loop % PROBE_EVERY)) -eq 0 ]; then
    probe="$(render_probe 2>/dev/null || echo 'fail probe_script')"
    if printf '%s' "$probe" | grep -q '^fail'; then alerts+=("probe_failed"); renderer_problem=1; fi
  fi

  if [ "$container_problem" -eq 1 ]; then
    if [ $((current_epoch - last_bot_recover)) -ge "$RESTART_COOLDOWN_SECONDS" ]; then
      actions+=("compose_up")
      echo "$ts action=compose_up reason=container_problem" >> "$LOG"
      docker compose up -d bot bot2 tts-worker >> "$LOG" 2>&1 || actions+=("compose_up_failed")
      last_bot_recover="$current_epoch"
    else
      actions+=("compose_up_suppressed_cooldown")
    fi
  fi

  if [ "$renderer_problem" -eq 1 ]; then
    if [ $((current_epoch - last_tts_worker_restart)) -ge "$RESTART_COOLDOWN_SECONDS" ]; then
      actions+=("restart_tts_worker")
      echo "$ts action=restart_tts_worker reason=renderer_problem" >> "$LOG"
      docker compose restart tts-worker >> "$LOG" 2>&1 || actions+=("restart_tts_worker_failed")
      last_tts_worker_restart="$current_epoch"
    else
      actions+=("restart_tts_worker_suppressed_cooldown")
    fi
  fi

  alert_text="none"
  if [ "${#alerts[@]}" -gt 0 ]; then alert_text="${alerts[*]}"; fi
  action_text="none"
  if [ "${#actions[@]}" -gt 0 ]; then action_text="${actions[*]}"; fi
  echo "$ts loop=$loop alerts=$alert_text actions=$action_text ps=[$ps_line] inspect=[$inspect] $summary appfails=$appfails rendererFails=$renderer_fails probe=[$probe] stats=[$stats]" >> "$LOG"
  sleep "$INTERVAL_SECONDS"
done

echo "$(date -u +%FT%TZ) watch_done log=$LOG" >> "$LOG"
