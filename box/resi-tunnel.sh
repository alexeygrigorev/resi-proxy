#!/usr/bin/env bash
# Adapted from box-proxies cn-tunnel-18090.sh; no systemd/cron required.
set -uo pipefail
umask 077
S=${RESI_TUNNEL_STATE:-${XDG_STATE_HOME:-$HOME/.local/state}/resi-tunnel}
HOST=${RESI_TUNNEL_HOST:-hetzner}
SELF=$(readlink -f "$0")
mkdir -p "$S"
PIDF=$S/pid
LOG=$S/log
child=
sleeper=
valid_ports() {
  awk 'NF { if (NF != 1 || $1 !~ /^[0-9]+$/ || $1 < 1024 || $1 > 65535) exit 1; print $1 }' | sort -nu
}
discover() {
  local raw ports
  if [[ ${RESI_TUNNEL_PORTS+x} ]]; then
    raw=${RESI_TUNNEL_PORTS//,/$'\n'}
    ports=$(printf '%s\n' "$raw" | valid_ports) || return 1
  elif raw=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "$HOST" '"$HOME/.local/bin/proxy" list --ports' 2>>"$LOG") && ports=$(printf '%s\n' "$raw" | valid_ports); then
    printf '%s\n' "$ports" > "$S/ports.tmp"
    mv "$S/ports.tmp" "$S/ports"
  elif [[ -f $S/ports ]]; then
    echo "$(date -Is) discovery failed; using cached ports" >> "$LOG"
    ports=$(valid_ports < "$S/ports") || return 1
  else
    echo "$(date -Is) discovery failed; no cached ports" >> "$LOG"
    return 1
  fi
  printf '%s\n' "$ports"
}
command_for() {
  SSH_ARGS=(-N -o BatchMode=yes -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 -o ConnectTimeout=10)
  while read -r port; do
    [[ -n $port ]] && SSH_ARGS+=(-L "127.0.0.1:$port:127.0.0.1:$port")
  done <<< "$1"
  SSH_ARGS+=("$HOST")
}
running() {
  [[ -s $PIDF ]] || return 1
  local pid
  pid=$(cat "$PIDF")
  [[ $pid =~ ^[0-9]+$ ]] || return 1
  kill -0 "$pid" 2>/dev/null || return 1
  [[ -r /proc/$pid/cmdline ]] || return 1
  tr '\0' '\n' < "/proc/$pid/cmdline" | grep -Fxq "$SELF" || return 1
  ! flock -n "$S/lock" true
}
cleanup() {
  [[ -n $sleeper ]] && kill "$sleeper" 2>/dev/null
  if [[ -n $child ]]; then kill "$child" 2>/dev/null; wait "$child" 2>/dev/null; fi
  rm -f "$PIDF" "$S/active-ports"
}
case "${1:-ensure}" in
  dry-run)
    ports=$(discover) || exit 1
    if [[ -z $ports ]]; then echo 'no active ports'; exit 0; fi
    command_for "$ports"
    printf 'ssh'; printf ' %q' "${SSH_ARGS[@]}"; printf '\n'
    ;;
  ensure)
    if ! running; then
      setsid nohup "$SELF" run >/dev/null 2>&1 </dev/null 9>&- &
    fi
    ;;
  run)
    exec 9>"$S/lock"
    flock -n 9 || exit 0
    echo $$ > "$PIDF"
    trap 'exit 0' TERM INT
    trap cleanup EXIT
    current=
    while true; do
      ports=$(discover) || { sleep 5 9>&- & sleeper=$!; wait "$sleeper"; sleeper=; continue; }
      if [[ $ports != "$current" ]] || { [[ -n $ports ]] && { [[ -z $child ]] || ! kill -0 "$child" 2>/dev/null; }; }; then
        if [[ -n $child ]]; then kill "$child" 2>/dev/null; wait "$child" 2>/dev/null; child=; fi
        current=$ports
        printf '%s\n' "$ports" > "$S/active-ports"
        if [[ -n $ports ]]; then
          command_for "$ports"
          echo "$(date -Is) connecting ports=${ports//$'\n'/,}" >> "$LOG"
          ssh "${SSH_ARGS[@]}" >> "$LOG" 2>&1 9>&- & child=$!
        fi
      fi
      tail -n 200 "$LOG" > "$S/log.tmp" 2>/dev/null && mv "$S/log.tmp" "$LOG"
      sleep "${RESI_TUNNEL_INTERVAL:-30}" 9>&- & sleeper=$!; wait "$sleeper"; sleeper=
    done
    ;;
  status)
    if running; then
      echo "supervisor pid $(cat "$PIDF")"
      echo 'forwarded ports:'
      cat "$S/active-ports" 2>/dev/null
      ss -ltn | awk 'NR==1 || /127.0.0.1:/'
      tail -n 3 "$LOG" 2>/dev/null
    else echo 'not running'; exit 1; fi
    ;;
  stop)
    if running; then kill "$(cat "$PIDF")"; echo stopped; else echo 'not running'; fi
    ;;
  *) echo "usage: $0 ensure|status|stop|dry-run" >&2; exit 2 ;;
esac
