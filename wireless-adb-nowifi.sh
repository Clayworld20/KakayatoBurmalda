#!/usr/bin/env bash
# =============================================================================
#  wireless-adb-nowifi.sh  v1.1.0
#  Включает ADB (в т.ч. «Беспроводную отладку» / Wireless Debugging) когда
#  Android refuses it with "Нет подключения к Wi-Fi" / "No Wi-Fi connection".
#
#  Работает в двух контекстах:
#    * с ПК через adb (устройство по USB или уже по сети);
#    * прямо на устройстве (Termux / любой shell с WRITE_SECURE_SETTINGS или root).
#
#  Стратегии (выбор --strategy auto|usb-tcpip|root-tcpip|tls-force|hotspot-race):
#    1) usb-tcpip   — «классика»: adb tcpip <port>. Wi-Fi не нужен вообще,
#                     нужен только уже авторизованный adb (USB или сеть).
#    2) root-tcpip  — root: setprop service.adb.tcp.port + рестарт adbd,
#                     фиксированный порт 5555, слушает все интерфейсы.
#    3) tls-force   — root: setprop persist.adb.tls_server.enable=1 — это то же
#                     свойство, которое выставляет тумблер «Беспроводная отладка».
#                     Прямой обход Wi-Fi-валидации на уровне демона adbd.
#    4) hotspot-race— без root: циклическая запись global adb_wifi_enabled=1
#                     (AdbSettingsObserver стартует демон, watchdog его гасит —
#                     ловим момент) + любая живая сеть (точка доступа/USB-тетеринг/
#                     Ethernet), иначе демону не на чём слушать.
#
#  Все записи настроек проверяются чтением; при нехватке прав скрипт печатает
#  понятное сообщение, что именно нужно выдать.
#
#  Лицензия: MIT. Пользуйтесь на свой страх и риск: открытый ADB = полный
#  доступ к устройству. Отключайте флагом --off, когда закончили.
# =============================================================================

set -uo pipefail

PROG="${0##*/}"
VERSION="1.1.0"

# ---------------------------------------------------------------- настройки --
PORT=5555
STRATEGY="auto"
ACTION="enable"          # enable | off | status
TARGET_IP=""
TARGET_PORT=""
RACE_TIMEOUT=30          # секунд на «race»-стратегию
IFACE_WAIT=90            # секунд ожидания, пока появится IP (точка доступа и т.п.)
DO_PAIR=0
DRY_RUN=0
VERBOSE=0
SERIAL=""
ADB_BIN="${ADB:-adb}"
NO_INPUT=0

# Предпочтительные сетевые интерфейсы устройства (порядок важен)
IFACE_PREF="wlan0 wlan1 wlan2 eth0 eth1 usb0 rndis0 rndis1 swlan0 ap0 softap0 wlan0.1 rmnet_data0 rmnet0 ccmni0"

# ------------------------------------------------------------------- вывод ---
if [ -t 1 ] && [ -z "${NO_COLOR:-}" ]; then
  C_B=$'\033[1m'; C_G=$'\033[32m'; C_Y=$'\033[33m'; C_R=$'\033[31m'; C_C=$'\033[36m'; C_0=$'\033[0m'
else
  C_B=""; C_G=""; C_Y=""; C_R=""; C_C=""; C_0=""
fi

info()  { printf '%s\n' "$*"; }
dim()   { printf '%s%s%s\n' "$C_C" "$*" "$C_0"; }
ok()    { printf '  %s[ok]%s %s\n'   "$C_G" "$C_0" "$*"; }
warn()  { printf '  %s[!]%s %s\n'    "$C_Y" "$C_0" "$*" >&2; }
err()   { printf '  %s[×]%s %s\n'    "$C_R" "$C_0" "$*" >&2; }
step()  { printf '\n%s==>%s %s%s%s\n' "$C_C" "$C_0" "$C_B" "$*" "$C_0"; }
rule()  { printf '%s\n' "────────────────────────────────────────────────────────────────"; }

usage() {
  cat <<EOF
${C_B}${PROG}${C_0} v${VERSION} — включить ADB без подключения к Wi-Fi

Использование:
  ${PROG} [опции]

Опции:
  --port N              порт для стратегий tcpip (по умолчанию ${PORT})
  --strategy NAME       auto | usb-tcpip | root-tcpip | tls-force | hotspot-race
  --ip A.B.C.D          не искать IP, а использовать этот
  --pair                после включения выполнить интерактивный adb pair
  --serial SERIAL       конкретное устройство (adb -s)
  --adb PATH            путь к бинарнику adb (по умолчанию \$ADB или adb)
  --race-timeout N      секунд на стратегию hotspot-race (по умолчанию ${RACE_TIMEOUT})
  --no-input            не задавать вопросы, только ждать появления сети
  --dry-run             печатать команды, ничего не менять
  --verbose             печатать все выполняемые команды и их вывод
  -o, --off             всё выключить (убрать порты, флаги, отключиться)
  -s, --status          показать текущее состояние и выйти
  -h, --help            эта справка

Примеры:
  ${PROG}                              # всё автоматически
  ${PROG} --strategy usb-tcpip         # устройство на USB, включить порт 5555
  ${PROG} --strategy tls-force --pair  # root, «настоящая» беспроводная отладка + пейринг
  ${PROG} --strategy hotspot-race      # без root: точка доступа + race
  ${PROG} --off                        # убрать всё и закрыть порт
EOF
}

# --------------------------------------------------------------- утилиты ----
sanitize() { printf '%s' "${1:-}" | tr -d '\r' | sed -e 's/^[[:space:]]*//' -e 's/[[:space:]]*$//' | tail -n 1; }

sq() { printf "'%s'" "$(printf '%s' "$1" | sed "s/'/'\\\\''/g")"; }   # экранирование для одиночных кавычек

is_denied() {
  printf '%s' "${1:-}" | grep -qiE 'Permission denial|SecurityException|not permitted|requires:android\.permission|Permission Denial|java\.lang\.SecurityException'
}

PERM_HINT_SHOWN=0
explain_permissions() {
  [ "$PERM_HINT_SHOWN" = 1 ] && return 0
  PERM_HINT_SHOWN=1
  rule
  printf '%sНет прав на запись системных настроек (Settings.Global).%s\n' "$C_B" "$C_0"
  info "Android разрешает писать Settings.Global только:"
  info "  1) из adb (shell uid 2000) — запустите скрипт с ПК, включив «Отладку по USB»;"
  info "  2) приложению с правом WRITE_SECURE_SETTINGS:"
  info "       adb shell pm grant <пакет> android.permission.WRITE_SECURE_SETTINGS"
  info "     (в Termux: pm grant com.termux ... — только если Termux может это выдать;"
  info "      иначе используйте Shizuku и запуск через 'rish'/'shizuku');"
  info "  3) от root (su) — тогда скрипт сам всё применит."
  info ""
  info "Быстрая проверка прав:"
  info "  adb shell settings put global adb_wifi_enabled 1 && adb shell settings get global adb_wifi_enabled"
  info "  → должно вернуть 1. Если 0/Permission denial — прав нет."
  rule
}

log_cmd() { [ "$VERBOSE" = 1 ] && dim "    \$ $*"; return 0; }

# ------------------------------------------------ состояние подключения -----
CONTEXT="unknown"     # pc | device
HAVE_ROOT=0
USE_SU=0
HAVE_WSS=0            # можно ли писать Settings.Global
LAST_OUT=""
LAST_RC=0

android_shell_dirs="/system/bin:/system/xbin:/vendor/bin:/sbin:/su/bin:/debug_ramdisk"

is_android_device() {
  [ -f /system/build.prop ] || [ -n "${ANDROID_ROOT:-}${ANDROID_DATA:-}" ] || command -v getprop >/dev/null 2>&1
}

adb_devices_list() {
  "$ADB_BIN" devices 2>/dev/null | awk 'NR>1 && $2=="device" {print $1}'
}

detect_context() {
  local devs=""
  if command -v "$ADB_BIN" >/dev/null 2>&1; then
    devs="$(adb_devices_list)"
  fi

  if [ -n "$devs" ]; then
    CONTEXT="pc"
    if [ -z "$SERIAL" ]; then
      SERIAL="$(printf '%s\n' "$devs" | head -n 1)"
    fi
    return 0
  fi

  if is_android_device; then
    CONTEXT="device"
    # в Termux системные бинари (settings/getprop/su) не всегда в PATH
    export PATH="$PATH:$android_shell_dirs"
    return 0
  fi

  if command -v "$ADB_BIN" >/dev/null 2>&1; then
    CONTEXT="pc"   # adb есть, но устройство ещё не подключено — скажем об этом позже
    return 0
  fi

  return 1
}

# выполнить команду в шелле устройства (через adb или локально)
dcmd() {
  local cmd="$1" write="${2:-0}" out rc
  if [ "$DRY_RUN" = 1 ] && [ "$write" = 1 ]; then
    dim "    [dry-run] $cmd"
    LAST_OUT=""; LAST_RC=0; return 0
  fi
  log_cmd "$cmd"
  if [ "$CONTEXT" = "device" ]; then
    out="$(eval "$cmd" 2>&1)"; rc=$?
  elif [ -n "$SERIAL" ]; then
    out="$("$ADB_BIN" -s "$SERIAL" shell "$cmd" 2>&1)"; rc=$?
  else
    out="$("$ADB_BIN" shell "$cmd" 2>&1)"; rc=$?
  fi
  LAST_OUT="$out"; LAST_RC=$rc
  [ "$VERBOSE" = 1 ] && [ -n "$out" ] && printf '%s\n' "$out" >&2
  return $rc
}

# то же, но от root
droot() {
  local cmd="$1" write="${2:-1}"
  if [ "$HAVE_ROOT" = 1 ] && [ "$USE_SU" = 0 ]; then
    dcmd "$cmd" "$write"
  else
    dcmd "su -c $(sq "$cmd")" "$write"
  fi
}

# выполнить команду самим adb (tcpip/connect/devices/pair)
host_adb() {
  local sfx=""; [ -n "$SERIAL" ] && sfx="-s ${SERIAL}"
  if [ "$DRY_RUN" = 1 ]; then
    dim "    [dry-run] adb ${sfx} $*"
    LAST_OUT=""; LAST_RC=0; return 0
  fi
  log_cmd "adb ${sfx} $*"
  if [ -n "$SERIAL" ]; then
    LAST_OUT="$("$ADB_BIN" -s "$SERIAL" "$@" 2>&1)"; LAST_RC=$?
  else
    LAST_OUT="$("$ADB_BIN" "$@" 2>&1)"; LAST_RC=$?
  fi
  [ "$VERBOSE" = 1 ] && [ -n "$LAST_OUT" ] && printf '%s\n' "$LAST_OUT" >&2
  return $LAST_RC
}

can_talk() {
  dcmd 'echo PING_OK' 0 >/dev/null 2>&1
  printf '%s' "$LAST_OUT" | grep -q 'PING_OK'
}

# --------------------------------------------------------------- разведка ---
probe_root() {
  dcmd 'id -u' 0
  local uid; uid="$(sanitize "$LAST_OUT")"
  if [ "$uid" = "0" ]; then
    HAVE_ROOT=1; USE_SU=0; return 0
  fi
  dcmd 'su -c id -u' 0
  local suid; suid="$(sanitize "$LAST_OUT")"
  if [ "$suid" = "0" ]; then
    HAVE_ROOT=1; USE_SU=1; return 0
  fi
  HAVE_ROOT=0; return 1
}

# Проверяем возможность писать Settings.Global (WRITE_SECURE_SETTINGS/root/adb).
# Попутно это и есть включение флага «Беспроводная отладка».
probe_wss() {
  if [ "$DRY_RUN" = 1 ]; then
    HAVE_WSS=1
    info "запись Settings.Global: dry-run (проверка пропущена)"
    return 0
  fi
  local put_out got
  dcmd "settings put global adb_wifi_enabled 1" 1
  put_out="$LAST_OUT"
  dcmd "settings get global adb_wifi_enabled" 0
  got="$(sanitize "$LAST_OUT")"
  if [ "$got" = "1" ]; then
    HAVE_WSS=1
    return 0
  fi
  HAVE_WSS=0
  if is_denied "$put_out"; then
    explain_permissions
  fi
  return 1
}

gset() {   # gset <key> <value> [quiet]
  local k="$1" v="$2" q="${3:-0}" put_out got
  if [ "$DRY_RUN" = 1 ]; then dim "    [dry-run] settings put global $k $v"; return 0; fi
  dcmd "settings put global $k $v" 1
  put_out="$LAST_OUT"
  dcmd "settings get global $k" 0
  got="$(sanitize "$LAST_OUT")"
  if [ "$got" = "$v" ]; then
    [ "$q" = 0 ] && ok "global $k = $v"
    return 0
  fi
  if is_denied "$put_out"; then
    [ "$q" = 0 ] && warn "нет прав на запись global $k (нужен WRITE_SECURE_SETTINGS или root)"
    explain_permissions
  else
    [ "$q" = 0 ] && warn "global $k не применился (прочитано «${got}», ожидалось «${v}»)"
  fi
  return 1
}

gget() { dcmd "settings get global $1" 0; sanitize "$LAST_OUT"; }

sdk_version() { dcmd 'getprop ro.build.version.sdk' 0; sanitize "$LAST_OUT"; }

# ----------------------------------------------------------- сеть устройства -
dump_addrs() {
  dcmd 'ip -f inet addr show 2>/dev/null || ifconfig -a 2>/dev/null || netcfg 2>/dev/null' 0
  printf '%s\n' "$LAST_OUT" | awk '
    /^[0-9]+: [A-Za-z0-9_.@:-]+:/ { iface=$2; sub(/:.*/,"",iface); next }
    /^[A-Za-z0-9_.@:-]+[ \t]+Link encap:/ { iface=$1; next }
    /[ \t]inet[ \t]/ {
      ip=$0; sub(/^.*[ \t]inet[ \t]+/,"",ip); sub(/[ \t\/].*$/,"",ip); sub(/addr:/,"",ip)
      if (iface != "" && iface != "lo" && ip != "127.0.0.1" && ip ~ /^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$/) print iface" "ip
    }'
}

pick_ip() {   # печатает лучший IP (сначала --ip, затем по IFACE_PREF, затем любой)
  if [ -n "$TARGET_IP" ]; then printf '%s' "$TARGET_IP"; return 0; fi
  local addrs iface ip
  addrs="$(dump_addrs)"
  [ -z "$addrs" ] && return 1
  for iface in $IFACE_PREF; do
    ip="$(printf '%s\n' "$addrs" | awk -v i="$iface" '$1==i {print $2; exit}')"
    if [ -n "$ip" ]; then printf '%s' "$ip"; return 0; fi
  done
  printf '%s\n' "$addrs" | awk 'NR==1 {print $2}'
}

list_addrs() { dump_addrs | awk '{printf "    %-12s %s\n", $1, $2}'; }

tcp_open() {   # tcp_open <ip> <port> — доступен ли порт (bash /dev/tcp)
  local ip="$1" p="$2"
  [ "$DRY_RUN" = 1 ] && return 0
  ( exec 3<>"/dev/tcp/${ip}/${p}" ) >/dev/null 2>&1
}

discover_tls_port() {  # порт TLS-сервера adbd из logcat, затем из ss (root)
  local deadline=$(( SECONDS + ${1:-15} )) port=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    dcmd 'logcat -d -s adbd:* 2>/dev/null | grep -Ei "adb ?wifi (started|running) on port|adbwifi started on port" | tail -n 1' 0
    port="$(printf '%s' "$LAST_OUT" | grep -oE '[0-9]{4,5}' | tail -n 1)"
    if [ -z "$port" ]; then
      dcmd 'logcat -d 2>/dev/null | grep -Ei "adb ?wifi (started|running) on port|adbwifi started on port" | tail -n 1' 0
      port="$(printf '%s' "$LAST_OUT" | grep -oE '[0-9]{4,5}' | tail -n 1)"
    fi
    if [ -z "$port" ] && [ "$HAVE_ROOT" = 1 ]; then
      dcmd 'ss -tlnp 2>/dev/null | grep -i adbd | head -n 1' 0
      port="$(printf '%s' "$LAST_OUT" | grep -oE '[: ][0-9]{4,5}[ ]' | grep -oE '[0-9]{4,5}' | tail -n 1)"
    fi
    if [ -n "$port" ]; then printf '%s' "$port"; return 0; fi
    sleep 1
  done
  return 1
}

# Ждём появления любого глобального IPv4 (пользователь включает точку доступа
# или подключает USB-Ethernet). Возвращает 0, если IP появился.
ensure_network_iface() {
  local deadline ip
  ip="$(pick_ip 2>/dev/null)"
  if [ -n "$ip" ]; then
    ok "сетевой интерфейс уже есть: ${ip}"
    LAST_IP="$ip"; return 0
  fi

  info "У устройства нет ни одного IPv4-адреса — демону adbd не на чём слушать порт."

  if [ "$HAVE_ROOT" = 1 ]; then
    info "Пробую включить точку доступа программно (best-effort)..."
    droot 'cmd wifi start-softap' 1 >/dev/null 2>&1
    droot 'svc wifi start-softap' 1 >/dev/null 2>&1
    sleep 3
    ip="$(pick_ip 2>/dev/null)"
    [ -n "$ip" ] && { ok "точка доступа поднята: ${ip}"; LAST_IP="$ip"; return 0; }
  fi

  if [ "$NO_INPUT" = 0 ] && [ -t 0 ]; then
    printf '\n%s  Включите на устройстве «Точку доступа» (Hotspot / Мобильная точка доступа)%s\n' "$C_B" "$C_0"
    printf '  или USB-тетеринг/Ethernet, затем нажмите Enter (ждать до %s с)...%s' "$IFACE_WAIT" "$C_0"
    read -r _ </dev/tty 2>/dev/null || true
    printf '\n'
  else
    info "Жду появления сети до ${IFACE_WAIT} с (включите точку доступа/USB-тетеринг/Ethernet)..."
  fi

  deadline=$(( SECONDS + IFACE_WAIT ))
  while [ "$SECONDS" -lt "$deadline" ]; do
    ip="$(pick_ip 2>/dev/null)"
    if [ -n "$ip" ]; then ok "сеть появилась: ${ip}"; LAST_IP="$ip"; return 0; fi
    sleep 2
  done

  warn "IP так и не появился. Продолжаю: для локального подключения (Termux/Shizuku) это может сработать и без сети."
  LAST_IP=""
  return 1
}

# ------------------------------------------------------------- подключение ---
adb_transport_state() {   # состояние конкретного транспорта ip:port
  local t="$1"
  host_adb devices >/dev/null 2>&1
  printf '%s' "$LAST_OUT" | awk -v t="$t" '$1==t {print $2}' | head -n 1
}

connect_and_verify() {
  local ip="$1" port="$2" out state
  rule
  if [ "$DRY_RUN" = 1 ]; then
    dim "    [dry-run] adb connect ${ip}:${port} + проверка 'adb -s ${ip}:${port} shell id'"
    STRATEGY_USED="${STRATEGY_USED:-dry-run}"; CONNECTED_AT="${ip}:${port}"
    return 0
  fi
  info "Подключаюсь: ${C_B}adb connect ${ip}:${port}${C_0}"
  host_adb connect "${ip}:${port}"
  out="$LAST_OUT"
  printf '%s\n' "$out" | sed 's/^/    /'
  if ! printf '%s' "$out" | grep -qiE 'connected to|already connected'; then
    err "adb connect не удался."
    return 1
  fi
  sleep 1

  state="$(adb_transport_state "${ip}:${port}")"
  case "$state" in
    device)
      ok "транспорт ${ip}:${port} в состоянии device"
      ;;
    unauthorized)
      err "устройство unauthorized — ключ хоста не принят."
      info "  • На устройстве подтвердите диалог «Разрешить отладку?» (и поставьте «Всегда»);"
      info "  • либо (root) добавьте свой ключ вручную:"
      info "      adb push ~/.android/adbkey.pub /sdcard/ && adb shell su -c 'cat /sdcard/adbkey.pub >> /data/misc/adb/adb_keys && chmod 600 /data/misc/adb/adb_keys'"
      info "  • затем: adb connect ${ip}:${port}"
      return 1
      ;;
    offline)
      warn "транспорт offline — обычно лечится: adb disconnect ${ip}:${port} && adb connect ${ip}:${port}"
      ;;
    *)
      warn "не удалось определить состояние транспорта (adb devices не показывает ${ip}:${port})"
      ;;
  esac

  # финальная проверка — реально выполняем команду на устройстве
  LAST_OUT="$("$ADB_BIN" -s "${ip}:${port}" shell 'echo ADB_TRANSPORT_OK; id' 2>&1)"
  if printf '%s' "$LAST_OUT" | grep -q 'ADB_TRANSPORT_OK'; then
    ok "проверка связи пройдена:"
    printf '%s\n' "$LAST_OUT" | grep -v 'ADB_TRANSPORT_OK' | sed 's/^/      /'
    return 0
  fi
  err "транспорт поднят, но команда на устройстве не выполняется:"
  printf '%s\n' "$LAST_OUT" | sed 's/^/      /'
  return 1
}

maybe_pair() {
  local ip="$1" port="$2" pport="" code="" out=""
  [ "$DO_PAIR" = 1 ] || return 0
  rule
  info "Пейринг (делается один раз на клиента)"
  info "  На устройстве: Настройки → Для разработчиков → Беспроводная отладка →"
  info "  «Связать устройство по коду» — там будет PORT и 6-значный код."
  dcmd 'am start -a android.settings.APPLICATION_DEVELOPMENT_SETTINGS >/dev/null 2>&1' 1 >/dev/null 2>&1
  if [ "$NO_INPUT" = 1 ] || [ ! -t 0 ]; then
    warn "--pair требует ввода с терминала, пропускаю"
    return 1
  fi
  printf '  Порт для пейринга: '; read -r pport </dev/tty 2>/dev/null || pport=""
  printf '  Код (6 цифр):      '; read -r code  </dev/tty 2>/dev/null || code=""
  if [ -z "$pport" ] || [ -z "$code" ]; then warn "пейринг отменён"; return 1; fi
  if [ "$DRY_RUN" = 1 ]; then dim "    [dry-run] adb pair ${ip}:${pport} <<< <код>"; return 0; fi
  out="$(printf '%s\n' "$code" | "$ADB_BIN" pair "${ip}:${pport}" 2>&1)"
  printf '%s\n' "$out" | sed 's/^/    /'
  if printf '%s' "$out" | grep -qi 'successfully paired'; then
    ok "пейринг выполнен"
    return 0
  fi
  warn "пейринг не прошёл — проверьте порт и код (порт пейринга ≠ порту подключения)"
  return 1
}

# ------------------------------------------------------------- стратегии ----

# Общие флаги: включаем отладку, держим тумблер, убираем авто-отзыв авторизации
# и (на старых версиях) валидацию сети/captive portal.
apply_common_flags() {
  local sdk; sdk="$(sdk_version)"
  info "Версия Android (SDK): ${sdk:-неизвестно}"

  gset adb_enabled 1                       # отладка должна быть включена
  gset adb_wifi_enabled 1                  # сам флаг «Беспроводная отладка»
  gset adb_allowed_connection_time 0       # 0 = отключить авто-отзыв авторизации (7 дней)

  if [ -n "$sdk" ] && [ "$sdk" -le 33 ] 2>/dev/null; then
    gset captive_portal_detection_enabled 0 1   # Android ≤13: не ждём валидацию сети
    gset captive_portal_mode 0 1                # 0 = не показывать/не блокировать сеть
  else
    dim "    captive_portal_* пропущен: на Android 14+ эти ключи не влияют на валидацию сети"
  fi
  return 0
}

s_usb_tcpip() {
  step "Стратегия usb-tcpip: adb tcpip ${PORT} (Wi-Fi не нужен совсем)"
  if [ "$CONTEXT" != "pc" ]; then
    warn "стратегия требует adb на ПК (запустите скрипт не с устройства)"
    return 1
  fi

  host_adb tcpip "$PORT"
  printf '%s\n' "$LAST_OUT" | sed 's/^/    /'
  if ! printf '%s' "$LAST_OUT" | grep -qiE 'restarting in TCP mode|restarting'; then
    warn "adbd не подтвердил переход в TCP-режим — на этой прошивке tcpip может быть закрыт"
  fi
  sleep 2

  dcmd 'getprop service.adb.tcp.port' 0
  local prop; prop="$(sanitize "$LAST_OUT")"
  if [ "$prop" = "$PORT" ]; then
    ok "service.adb.tcp.port = ${prop}"
  else
    warn "service.adb.tcp.port = «${prop}» (ожидалось ${PORT}) — проверяю порт напрямую"
  fi

  local ip; ip="$(pick_ip)" || ip=""
  [ -z "$ip" ] && { ensure_network_iface >/dev/null 2>&1; ip="$LAST_IP"; }
  [ -z "$ip" ] && { err "не нашёл IP устройства, укажите вручную: --ip 192.168.x.x"; return 1; }

  local i
  for i in 1 2 3 4 5; do
    tcp_open "$ip" "$PORT" && break
    sleep 1
  done
  tcp_open "$ip" "$PORT" || { err "порт ${ip}:${PORT} закрыт — tcpip на этой прошивке не работает, нужна другая стратегия"; return 1; }
  ok "порт ${ip}:${PORT} слушает"

  connect_and_verify "$ip" "$PORT" || return 1
  STRATEGY_USED="usb-tcpip"; CONNECTED_AT="${ip}:${PORT}"
  return 0
}

restart_adbd() {
  info "Перезапускаю adbd..."
  if [ "$HAVE_ROOT" = 1 ]; then
    droot 'setprop ctl.restart adbd' 1 >/dev/null 2>&1   # init сам поднимет сервис
  else
    dcmd 'setprop ctl.restart adbd' 1 >/dev/null 2>&1
  fi
  sleep 3
  if ! can_talk; then
    info "  не отвечает, пробую stop/start..."
    droot 'stop adbd' 1 >/dev/null 2>&1
    sleep 1
    droot 'start adbd' 1 >/dev/null 2>&1
    sleep 3
  fi
  can_talk
}

s_root_tcpip() {
  step "Стратегия root-tcpip: фиксированный порт ${PORT} через service.adb.tcp.port"
  if [ "$HAVE_ROOT" != 1 ]; then warn "нет root"; return 1; fi

  droot "setprop service.adb.tcp.port ${PORT}" 1
  droot "setprop persist.adb.tcp.port ${PORT}" 1
  restart_adbd

  dcmd 'getprop service.adb.tcp.port' 0
  local prop; prop="$(sanitize "$LAST_OUT")"
  [ "$prop" = "$PORT" ] && ok "service.adb.tcp.port = ${prop}" || warn "service.adb.tcp.port = «${prop}»"

  local ip; ip="$(pick_ip)" || ip=""
  [ -z "$ip" ] && { ensure_network_iface >/dev/null 2>&1; ip="$LAST_IP"; }
  [ -z "$ip" ] && { err "не нашёл IP устройства, укажите вручную: --ip 192.168.x.x"; return 1; }

  local i
  for i in 1 2 3 4 5; do tcp_open "$ip" "$PORT" && break; sleep 1; done
  if ! tcp_open "$ip" "$PORT"; then
    err "порт ${ip}:${PORT} не открылся (бывает, когда прошивка игнорирует service.adb.tcp.port)"
    warn "попробуйте: --strategy tls-force или --strategy hotspot-race"
    return 1
  fi
  ok "порт ${ip}:${PORT} слушает"

  connect_and_verify "$ip" "$PORT" || return 1
  STRATEGY_USED="root-tcpip"; CONNECTED_AT="${ip}:${PORT}"
  return 0
}

s_tls_force() {
  step "Стратегия tls-force: root → persist.adb.tls_server.enable=1 (обход Wi-Fi-проверки)"
  if [ "$HAVE_ROOT" != 1 ]; then warn "нет root"; return 1; fi

  droot 'setprop persist.adb.tls_server.enable 1' 1
  sleep 2

  # Держим флаг UI выставленным, чтобы система «видела» включённую беспроводную отладку
  gset adb_wifi_enabled 1

  dcmd 'getprop persist.adb.tls_server.enable' 0
  local prop; prop="$(sanitize "$LAST_OUT")"
  if [ "$prop" != "1" ]; then
    err "свойство persist.adb.tls_server.enable = «${prop}» — прошивка запрещает запись даже от root"
    warn "fallback: --strategy root-tcpip"
    return 1
  fi
  ok "persist.adb.tls_server.enable = 1 (это то же свойство, что выставляет тумблер)"

  local port; port="$(discover_tls_port 15)" || port=""
  [ -z "$port" ] && { err "не нашёл порт TLS-сервера в logcat (нужен доступ к logcat)"; return 1; }
  ok "TLS-сервер adbd на порту ${port}"

  local ip; ip="$(pick_ip)" || ip=""
  [ -z "$ip" ] && { ensure_network_iface >/dev/null 2>&1; ip="$LAST_IP"; }
  [ -z "$ip" ] && { err "не нашёл IP устройства, укажите вручную: --ip 192.168.x.x"; return 1; }

  maybe_pair "$ip" "$port"
  connect_and_verify "$ip" "$port" || return 1
  STRATEGY_USED="tls-force"; CONNECTED_AT="${ip}:${port}"
  return 0
}

s_hotspot_race() {
  step "Стратегия hotspot-race: без root, через AdbSettingsObserver"
  ensure_network_iface || true
  local ip="${LAST_IP:-}"
  [ -z "$ip" ] && ip="$(pick_ip 2>/dev/null)" || true
  [ -n "$ip" ] && info "Целевой адрес устройства: ${ip}"

  info "Циклически пишу global adb_wifi_enabled=1 (ловим окно, пока watchdog не погасил демон)..."
  local deadline=$(( SECONDS + RACE_TIMEOUT )) tries=0 prop="" flag=""
  while [ "$SECONDS" -lt "$deadline" ]; do
    dcmd 'settings put global adb_wifi_enabled 1' 1 >/dev/null 2>&1
    tries=$((tries+1))
    dcmd 'getprop persist.adb.tls_server.enable' 0
    prop="$(sanitize "$LAST_OUT")"
    dcmd 'settings get global adb_wifi_enabled' 0
    flag="$(sanitize "$LAST_OUT")"
    if [ "$prop" = "1" ] && [ "$flag" = "1" ]; then
      # убеждаемся, что состояние удержалось, а не мигнуло
      sleep 2
      dcmd 'getprop persist.adb.tls_server.enable' 0; prop="$(sanitize "$LAST_OUT")"
      dcmd 'settings get global adb_wifi_enabled' 0;  flag="$(sanitize "$LAST_OUT")"
      if [ "$prop" = "1" ] && [ "$flag" = "1" ]; then
        ok "демон запущен и держится (попыток: ${tries})"
        break
      fi
    fi
    sleep 0.2 >/dev/null 2>&1 || true
  done

  dcmd 'settings get global adb_wifi_enabled' 0; flag="$(sanitize "$LAST_OUT")"
  dcmd 'getprop persist.adb.tls_server.enable' 0; prop="$(sanitize "$LAST_OUT")"
  if [ "$flag" != "1" ] || [ "$prop" != "1" ]; then
    err "за ${RACE_TIMEOUT} с демон не запустился (adb_wifi_enabled=${flag}, tls_server.enable=${prop})"
    info "  • убедитесь, что включена точка доступа / USB-тетеринг / Ethernet;"
    info "  • попробуйте увеличить окно: --race-timeout 60;"
    info "  • на Android 17+ (ADB Wi-Fi 2.0) этот обход может быть закрыт."
    return 1
  fi

  local port; port="$(discover_tls_port 15)" || port=""
  if [ -z "$port" ]; then
    err "демон запущен, но порт не определён (нет доступа к logcat?)"
    info "  Узнайте порт вручную: Настройки → Для разработчиков → Беспроводная отладка"
    return 1
  fi
  ok "TLS-сервер adbd на порту ${port}"

  if [ -z "$ip" ] && [ "$CONTEXT" = "device" ]; then ip="127.0.0.1"; fi
  [ -z "$ip" ] && { err "не нашёл IP, укажите --ip"; return 1; }

  maybe_pair "$ip" "$port"
  connect_and_verify "$ip" "$port" || return 1
  STRATEGY_USED="hotspot-race"; CONNECTED_AT="${ip}:${port}"
  return 0
}

# ------------------------------------------------------------- выключение ----
do_off() {
  step "Выключаю всё, что включили"
  local ip="$TARGET_IP" port="$TARGET_PORT"

  if [ -n "$ip" ] && [ -n "$port" ]; then
    host_adb disconnect "${ip}:${port}" >/dev/null 2>&1
    ok "adb disconnect ${ip}:${port}"
  fi

  gset adb_wifi_enabled 0 1
  ok "global adb_wifi_enabled = $(gget adb_wifi_enabled)"
  gset adb_allowed_connection_time 604800000 1   # вернуть дефолт (7 дней)

  if [ "$HAVE_ROOT" = 1 ]; then
    droot 'setprop persist.adb.tls_server.enable 0' 1 >/dev/null 2>&1
    droot "setprop service.adb.tcp.port -1" 1 >/dev/null 2>&1
    droot "setprop persist.adb.tcp.port \"\"" 1 >/dev/null 2>&1
    restart_adbd >/dev/null 2>&1
    ok "порты adbd закрыты (service.adb.tcp.port=-1, tls_server.enable=0)"
  else
    # без root legacy-порт гасим через сам adb
    if [ "$CONTEXT" = "pc" ] && [ -n "$SERIAL" ]; then
      host_adb usb >/dev/null 2>&1
      ok "adb usb (возврат в USB-режим)"
    else
      warn "без root legacy-порт закрыть нечем: выключите «Беспроводную отладку» в настройках"
      warn "или перезагрузите устройство"
    fi
  fi
  rule
  info "Готово. Проверьте: ${PROG} --status"
  return 0
}

# --------------------------------------------------------------- статус ------
do_status() {
  step "Состояние устройства"
  info "Контекст: ${CONTEXT} ${SERIAL:+(serial: ${SERIAL})}"
  if [ "$CONTEXT" != "unknown" ] && can_talk; then
    ok "связь с устройством есть"
    probe_root >/dev/null 2>&1
    local sdk; sdk="$(sdk_version)"
    info "Android SDK:        ${sdk:-?}"
    info "root:               $([ "$HAVE_ROOT" = 1 ] && echo 'да' || echo 'нет')"
    info "adb_enabled:        $(gget adb_enabled)"
    info "adb_wifi_enabled:   $(gget adb_wifi_enabled)"
    info "adb_allowed_conn:   $(gget adb_allowed_connection_time)"
    dcmd 'getprop persist.adb.tls_server.enable' 0
    info "tls_server.enable:  $(sanitize "$LAST_OUT")"
    dcmd 'getprop service.adb.tcp.port' 0
    info "service.adb.tcp:    $(sanitize "$LAST_OUT")"
    info "IP устройства:"
    list_addrs | sed 's/^/  /'
    info "Слушающие порты (root):"
    dcmd 'ss -tln 2>/dev/null | head -n 12' 0
    printf '%s\n' "$LAST_OUT" | sed 's/^/  /'
  else
    err "устройство не отвечает (adb devices)"
  fi
  info "Транспорты adb на ПК:"
  command -v "$ADB_BIN" >/dev/null 2>&1 && "$ADB_BIN" devices -l 2>/dev/null | sed 's/^/  /'
  return 0
}

# ------------------------------------------------------------------ main -----
STRATEGY_USED=""
CONNECTED_AT=""
LAST_IP=""

main() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --port)           PORT="${2:?}"; shift 2 ;;
      --strategy)       STRATEGY="${2:?}"; shift 2 ;;
      --ip)             TARGET_IP="${2:?}"; shift 2 ;;
      --pair)           DO_PAIR=1; shift ;;
      --serial|-S)      SERIAL="${2:?}"; shift 2 ;;
      --adb)            ADB_BIN="${2:?}"; shift 2 ;;
      --race-timeout)   RACE_TIMEOUT="${2:?}"; shift 2 ;;
      --iface-wait)     IFACE_WAIT="${2:?}"; shift 2 ;;
      --no-input)       NO_INPUT=1; shift ;;
      --dry-run)        DRY_RUN=1; shift ;;
      --verbose|-v)     VERBOSE=1; shift ;;
      -o|--off)         ACTION="off"; shift ;;
      -s|--status)      ACTION="status"; shift ;;
      -h|--help)        usage; exit 0 ;;
      *)                err "неизвестный аргумент: $1"; usage; exit 2 ;;
    esac
  done

  rule
  printf '%s wireless-adb-nowifi %s %s\n' "$C_B" "v${VERSION}" "$C_0"
  printf ' Включение ADB без подключения к Wi-Fi (обход «Нет подключения к Wi-Fi»)\n'
  rule

  if ! detect_context; then
    err "Не удалось определить окружение: нет ни adb, ни признаков Android-устройства."
    info "Установите platform-tools (adb) на ПК либо запустите скрипт в Termux на устройстве."
    exit 1
  fi
  info "Контекст: ${CONTEXT}$([ -n "$SERIAL" ] && printf ' (%s)' "$SERIAL")"

  if [ "$ACTION" = "status" ]; then do_status; exit 0; fi

  if [ "$CONTEXT" = "pc" ] && [ -z "$SERIAL" ]; then
    err "adb не видит ни одного устройства в состоянии device."
    info "  1) включите «Отладку по USB» и подтвердите RSA-ключ на устройстве;"
    info "  2) adb devices должно показать '<serial>\\tdevice';"
    info "  3) если устройство уже в сети — укажите адрес: $PROG --ip 192.168.x.x --strategy hotspot-race"
    exit 1
  fi

  if ! can_talk; then
    err "Устройство не отвечает на команды."
    exit 1
  fi

  probe_root
  info "root: $([ "$HAVE_ROOT" = 1 ] && echo 'да' || echo 'нет')"

  if [ "$ACTION" = "off" ]; then do_off; exit 0; fi

  step "Базовые флаги (проверяю применение каждой записи)"
  apply_common_flags
  probe_wss
  info "запись Settings.Global: $([ "$HAVE_WSS" = 1 ] && echo 'разрешена' || echo 'ЗАПРЕЩЕНА')"

  if [ "$HAVE_WSS" != 1 ] && [ "$HAVE_ROOT" != 1 ]; then
    rule
    err "Ни root, ни права на запись Settings.Global — обход невозможен."
    explain_permissions
    exit 1
  fi

  local rc=0
  case "$STRATEGY" in
    auto)
      # Порядок: самый надёжный → самый «хитрый»
      if [ "$CONTEXT" = "pc" ]; then
        s_usb_tcpip || rc=1
      fi
      if [ "$rc" != 0 ]; then
        rc=0
        if [ "$CONTEXT" = "pc" ]; then
          warn "usb-tcpip не сработал — пробую остальные стратегии"
        fi
        if [ "$HAVE_ROOT" = 1 ]; then
          if ! s_root_tcpip; then
            if ! s_tls_force; then
              s_hotspot_race || rc=1
            fi
          fi
        else
          s_hotspot_race || rc=1
        fi
      fi
      ;;
    usb-tcpip)     s_usb_tcpip    || rc=1 ;;
    root-tcpip)    s_root_tcpip   || rc=1 ;;
    tls-force)     s_tls_force    || rc=1 ;;
    hotspot-race)  s_hotspot_race || rc=1 ;;
    *)             err "неизвестная стратегия: $STRATEGY"; exit 2 ;;
  esac

  rule
  if [ "$rc" = 0 ]; then
    printf '%sГотово.%s ADB работает без Wi-Fi.\n' "$C_G" "$C_0"
    info "  стратегия:  ${STRATEGY_USED}"
    info "  адрес:      ${CONNECTED_AT}"
    info ""
    info "  Проверка:   adb -s ${CONNECTED_AT} shell id"
    info "  scrcpy:     scrcpy -s ${CONNECTED_AT}"
    info "  Отключить:  ${PROG} --off${TARGET_IP:+ --ip $TARGET_IP}${TARGET_PORT:+ --port $TARGET_PORT}"
    info ""
    if [ "$STRATEGY_USED" = "hotspot-race" ] || [ "$STRATEGY_USED" = "tls-force" ]; then
      info "  Замечание: флаг adb_wifi_enabled удержан, тайм-аут авторизации отключён"
      info "  (adb_allowed_connection_time=0), но watchdog системы может погасить демон —"
      info "  если соединение отвалилось, просто перезапустите скрипт."
    fi
    if [ "$STRATEGY_USED" = "root-tcpip" ] || [ "$STRATEGY_USED" = "usb-tcpip" ]; then
      warn "порт ${CONNECTED_AT} открыт для всей сети без шифрования — не оставляйте его включённым"
      warn "в чужой/публичной сети. Завершили работу → ${PROG} --off"
    fi
  else
    printf '%sНе удалось поднять ADB.%s\n' "$C_R" "$C_0"
    info "Что попробовать дальше:"
    info "  1) ${PROG} --verbose            — увидеть все команды и ответы;"
    info "  2) ${PROG} --strategy usb-tcpip — если есть USB-кабель (самый надёжный путь);"
    info "  3) ${PROG} --strategy root-tcpip / tls-force — если есть root;"
    info "  4) ${PROG} --strategy hotspot-race --race-timeout 60 — без root (нужна точка доступа);"
    info "  5) ${PROG} --status             — посмотреть текущие флаги и IP."
    exit 1
  fi
}

main "$@"
