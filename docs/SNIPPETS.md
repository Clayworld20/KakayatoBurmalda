# Копипаст-рецепты (если не хотите ставить скрипт)

Каждый блок — самодостаточный. `<IP>` — адрес устройства, `<PORT>` — порт,
`<PAIRPORT>` — порт пейринга (всегда **другой**, показывается на экране).

Узнать IP (интерфейс не важен: Ethernet/USB-тетеринг/точка доступа/Wi-Fi):

```bash
adb shell ip -f inet addr show | grep 'inet '
```

---

## A. Есть USB-кабель — самый стабильный путь

```bash
adb tcpip 5555
adb connect <IP>:5555
adb devices            # должно быть: <IP>:5555  device
```

Wi-Fi не нужен вообще: `adb tcpip` переводит демон в TCP-режим на всех интерфейсах.

## B. Root: фиксированный порт 5555 (переживает перезагрузку)

```bash
adb shell su -c 'setprop service.adb.tcp.port 5555; setprop persist.adb.tcp.port 5555; setprop ctl.restart adbd'
sleep 3
adb connect <IP>:5555
```

`persist.adb.tcp.port` выживает ребут; `ctl.restart` безопаснее `stop/start`
(иначе можно потерять собственный шелл).

## C. Root: «настоящая» беспроводная отладка без Wi-Fi (обход проверки)

```bash
adb shell su -c 'setprop persist.adb.tls_server.enable 1'
adb shell su -c 'settings put global adb_wifi_enabled 1'
adb shell su -c 'settings put global adb_allowed_connection_time 0'
adb shell logcat -d | grep -Ei 'adb ?wifi (started|running) on port'   # узнать PORT
adb connect <IP>:<PORT>
# первый раз: adb pair <IP>:<PAIRPORT>  →  ввести код с экрана
```

`persist.adb.tls_server.enable` — это ровно то свойство, которое выставляет
тумблер «Беспроводная отладка», то есть проверка Wi-Fi обходится полностью.

## D. Без root, только WRITE_SECURE_SETTINGS (race + точка доступа)

1. Включите на устройстве **точку доступа** (или USB-тетеринг/Ethernet) — демону
   нужен интерфейс с IP.
2. Спам флагом (он поднимает демон, а watchdog фреймворка его гасит — ловим окно):

```bash
# Linux / macOS / Termux
for i in $(seq 1 300); do adb shell settings put global adb_wifi_enabled 1; done
```

```bat
:: Windows (cmd.exe)
for /l %i in (1,1,300) do adb shell settings put global adb_wifi_enabled 1
```

3. Проверка, что демон закрепился (обе команды должны вернуть `1`):

```bash
adb shell settings get global adb_wifi_enabled
adb shell getprop persist.adb.tls_server.enable
```

4. Узнать порт и подключиться:

```bash
adb shell logcat -d | grep -Ei 'adb ?wifi (started|running) on port'
adb connect <IP>:<PORT>
```

Если не закрепилось за 30 с — повторите цикл или увеличьте число итераций.

## E. Termux / Shizuku: локально, без ПК

```bash
pkg install android-tools -y                      # в Termux
# выдать право на запись настроек (один раз, из adb с ПК или через Shizuku):
adb shell pm grant com.termux android.permission.WRITE_SECURE_SETTINGS
# дальше — блок D, но подключаться к себе:
adb connect 127.0.0.1:<PORT>
```

## F. Проверить, есть ли право на запись настроек

```bash
adb shell settings put global adb_wifi_enabled 1 && adb shell settings get global adb_wifi_enabled
```

Вернуло `1` — право есть. Вернуло `0` или `Permission denial … WRITE_SECURE_SETTINGS` —
нужен adb с ПК, `pm grant` или root.

## G. Откат (закрыть всё)

```bash
adb disconnect <IP>:<PORT>
adb shell settings put global adb_wifi_enabled 0
adb shell su -c 'setprop persist.adb.tls_server.enable 0; setprop service.adb.tcp.port -1; setprop persist.adb.tcp.port ""; setprop ctl.restart adbd'
```

Без root legacy-порт гасится командой `adb usb` (нужен USB) либо перезагрузкой.
