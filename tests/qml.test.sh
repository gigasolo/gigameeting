#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fail() { echo "qml.test: $*" >&2; exit 1; }

widget="$root/Widget.qml"
grep -q 'ipcTarget: "gigasolo.gigameeting"' "$widget" || fail "card needs an IPC target"
block=$(awk '/IpcHandler \{/,/^  \}/' "$widget")
[[ -n $block ]] || fail "card needs an IpcHandler"
grep -q 'function open' <<<"$block" || fail "IPC must open the card"
grep -q 'function close' <<<"$block" || fail "IPC must close the card"
grep -q 'function toggle' <<<"$block" || fail "IPC must toggle the card"
if grep -Eq 'record|start|run-meeting' <<<"$block"; then
  fail "IPC must not start a recording"
fi

grep -q 'id: callersTimer' "$widget" || fail "callers poll must be a timer"
grep -q 'interval: 10000' "$widget" || fail "callers poll must be 10s"
grep -q 'root.helper, "callers"' "$widget" || fail "callers poll must use meeting-bar callers"
awk '/function applyCallers/,/function close/' "$widget" | grep -Eq 'run-meeting|launch_recorder|"start"' \
  && fail "the call hint must not start a recording"
grep -q 'running: root.panelOpen && !root.showingHistory' "$widget" \
  || fail "callers poll must stop when the card is closed or History is up"

echo "qml.test: ok"
