#!/usr/bin/env bash
# Самопроверка wireless-adb-nowifi.sh на фейковом adb (tests/mock/adb).
# Реальное устройство не нужно: поднимаем локальные слушатели портов и
# подменяем adb через PATH.
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
SCRIPT="$ROOT/wireless-adb-nowifi.sh"
MOCKDIR="$HERE/mock"
WORK="${MOCK_WORK:-/tmp/wadb-selftest}"
rm -rf "$WORK"; mkdir -p "$WORK"

PASS=0; FAIL=0
GREEN=$'\033[32m'; RED=$'\033[31m'; BOLD=$'\033[1m'; RST=$'\033[0m'

# IP этой машины — его «видит» фейковое устройство
SANDBOX_IP="$(python3 -c "import socket;s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(('8.8.8.8',1));print(s.getsockname()[0])" 2>/dev/null || echo 127.0.0.1)"
export MOCK_IP="$SANDBOX_IP"

# фальшивые слушатели 5555 и 46161, чтобы проверка порта (tcp_open) проходила
probe_port() { ( exec 3<>"/dev/tcp/$SANDBOX_IP/$1" ) >/dev/null 2>&1; }

if probe_port 5555 && probe_port 46161; then
  printf '  порты 5555/46161 уже слушаются — использую существующий слушатель\n'
  LISTENER_PID=""
else
  python3 -c "
import socket, threading, time

def serve(s):
    while True:
        try:
            c, _ = s.accept(); c.close()
        except OSError:
            return

socks = []
for p in (5555, 46161):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    except (AttributeError, OSError):
        pass
    s.bind(('0.0.0.0', p)); s.listen(16); socks.append(s)
    threading.Thread(target=serve, args=(s,), daemon=True).start()
time.sleep(900)" &
  LISTENER_PID=$!
  trap 'kill $LISTENER_PID 2>/dev/null || true' EXIT
  for i in $(seq 1 20); do
    probe_port 5555 && probe_port 46161 && break
    sleep 0.5
  done
  if ! (probe_port 5555 && probe_port 46161); then
    printf '  %sFAIL%s не удалось поднять тестовые слушатели 5555/46161\n' "$RED" "$RST"
    exit 1
  fi
fi

run_case() {   # run_case <имя> <ожидаемый rc> <режим> <аргументы...> -- <ожидаемые подстроки>
  local name="$1" want_rc="$2" mode="$3"; shift 3
  local -a args=() expects=()
  local side=args a
  for a in "$@"; do
    if [ "$a" = "--" ]; then side=expects; continue; fi
    if [ "$side" = args ]; then args+=("$a"); else expects+=("$a"); fi
  done

  local statedir="$WORK/state-$name"
  rm -rf "$statedir"; mkdir -p "$statedir"
  local log="$WORK/$name.log"

  ( export PATH="${CASE_PATH:-$MOCKDIR}:$PATH"
    export MOCK_MODE="$mode" MOCK_STATE="$statedir"
    export MOCK_NO_DEVICES="${CASE_NO_DEVICES:-0}"
    export ANDROID_ROOT="${CASE_ANDROID_ROOT:-}"
    export NO_COLOR=1
    timeout 150 "$SCRIPT" "${args[@]}" ) </dev/null >"$log" 2>&1
  local rc=$?

  local ok=1 msg=""
  [ "$rc" = "$want_rc" ] || { ok=0; msg="$msg rc=$rc(ожидался $want_rc)"; }
  for e in "${expects[@]}"; do
    grep -qF -- "$e" "$log" || { ok=0; msg="$msg нет подстроки: '$e'"; }
  done

  if [ $ok = 1 ]; then
    PASS=$((PASS+1)); printf '  %sPASS%s %s\n' "$GREEN" "$RST" "$name"
  else
    FAIL=$((FAIL+1)); printf '  %sFAIL%s %s%s\n' "$RED" "$RST" "$name" "$msg"
    printf '%s\n' "        лог: $log"
    sed 's/^/        | /' "$log" | tail -n 25
  fi
}

printf '%sСамопроверка wireless-adb-nowifi.sh%s (IP мока: %s)\n\n' "$BOLD" "$RST" "$SANDBOX_IP"

run_case "usb-tcpip-success" 0 usb-ok \
  --strategy usb-tcpip \
  -- "restarting in TCP mode port: 5555" "service.adb.tcp.port = 5555" "5555 слушает" "Готово" "usb-tcpip"

run_case "auto-usb" 0 usb-ok \
  -- "Готово" "Отключить:"

run_case "no-permissions" 1 denied \
  --iface-wait 3 \
  -- "Ни root, ни права на запись Settings.Global" "WRITE_SECURE_SETTINGS" "pm grant"

run_case "root-tcpip" 0 root-ok \
  --strategy root-tcpip \
  -- "service.adb.tcp.port = 5555" "5555 слушает" "Готово" "root-tcpip"

run_case "hotspot-race" 0 hotspot-race \
  --strategy hotspot-race --no-input --race-timeout 20 --iface-wait 5 \
  -- "демон запущен и держится" "TLS-сервер adbd на порту 46161" "Готово" "hotspot-race"

run_case "tls-force" 0 root-ok \
  --strategy tls-force \
  -- "persist.adb.tls_server.enable = 1" "TLS-сервер adbd на порту 46161" "Готово" "tls-force"

run_case "status" 0 root-ok \
  --status \
  -- "adb_wifi_enabled" "tls_server.enable" "Android SDK"

run_case "off" 0 root-ok \
  --off \
  -- "Выключаю всё" "adb_wifi_enabled = 0"

run_case "dry-run" 0 usb-ok \
  --dry-run --strategy usb-tcpip \
  -- "[dry-run]"

run_case "help" 0 usb-ok \
  --help \
  -- "Использование" "--strategy"

run_case "bad-strategy" 2 usb-ok \
  --strategy none \
  -- "неизвестная стратегия"

# --- запуск прямо на устройстве (имитация Termux: adb-устройств нет, есть /system) ---
CASE_PATH="$HERE/mock-device:$MOCKDIR" CASE_NO_DEVICES=1 CASE_ANDROID_ROOT=/system \
run_case "device-termux-race" 0 hotspot-race \
  --strategy hotspot-race --no-input --race-timeout 20 --iface-wait 5 \
  -- "Контекст: device" "демон запущен и держится" "Готово" "hotspot-race"

CASE_PATH="$HERE/mock-device:$MOCKDIR" CASE_NO_DEVICES=1 CASE_ANDROID_ROOT=/system \
run_case "device-termux-root" 0 root-ok \
  --strategy root-tcpip \
  -- "Контекст: device" "root: да" "5555 слушает" "Готово" "root-tcpip"

printf '\n%sИтого:%s %sPASS=%s%s  %sFAIL=%s%s\n' "$BOLD" "$RST" "$GREEN" "$PASS" "$RST" "$RED" "$FAIL" "$RST"
[ "$FAIL" = 0 ]
