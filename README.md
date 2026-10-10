# wireless-adb-nowifi — включаем ADB без Wi-Fi

Скрипт убирает/обходит ошибку **«Нет подключения к Wi-Fi»** («No Wi-Fi connection»),
из-за которой Android не даёт включить **Беспроводную отладку** (Wireless Debugging)
и не поднимает ADB по сети.

Один bash-скрипт, работает и с ПК (через `adb`), и прямо на устройстве
(Termux / Shizuku / root). Все запись настроек **проверяется чтением**, а при
нехватке прав скрипт печатает понятное сообщение, что именно нужно выдать.

```
wireless-adb-nowifi.sh [опции]
```

---

## 1. Почему Android вообще требует Wi-Fi

| Уровень | Что проверяет | Где в AOSP |
|---|---|---|
| Приложение «Настройки» | тумблер «Беспроводная отладка» неактивен/гаснет без Wi-Fi | `WirelessDebuggingPreferenceController` пишет `Settings.Global.adb_wifi_enabled` [1](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/) |
| `system_server` | `AdbDebuggingManager` при включении делает `getCurrentWifiApInfo()`; если устройства нет — **сразу пишет `adb_wifi_enabled=0`** [1](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/) |
| `system_server` (watchdog) | при выключении Wi-Fi, потере сети или смене BSSID — сбрасывает `adb_wifi_enabled` в `0` [8](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/master/services/core/java/com/android/server/adb/AdbDebuggingManager.java) |
| `adbd` | слушает порт только если выставлено свойство `persist.adb.tls_server.enable=1` (TLS) или `service.adb.tcp.port` (legacy) [8](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md) |

То есть «виноваты» два места: **проверка Wi-Fi в фреймворке** и **свойство, которым
фреймворк включает демон**. Скрипт бьёт по второму: заставляет `adbd` слушать порт
на любом доступном интерфейсе — без участия Wi-Fi. Подробности: [`docs/HOW-IT-WORKS.md`](docs/HOW-IT-WORKS.md).

> Важно: на устройстве **без root** и без LSPosed/Xposed снять саму проверку
> в приложении «Настройки» нельзя — она живёт в фреймворке. Но **демон поднять
> можно**, и тогда ADB работает, даже если тумблер в UI выглядит выключенным.

---

## 2. Быстрый старт

### Вариант A. Есть USB-кабель (самый надёжный, root не нужен)

```bash
# 1. На устройстве: Настройки → О телефоне → 7 раз по «Номеру сборки»
# 2. Настройки → Для разработчиков → включить «Отладка по USB»
# 3. Подключить кабель, подтвердить RSA-ключ на экране
adb devices                      # должно быть: <serial>  device
./wireless-adb-nowifi.sh         # всё остальное скрипт сделает сам
```

Скрипт выполнит `adb tcpip 5555`, найдёт IP на любом интерфейсе (Ethernet по USB-C,
USB-тетеринг, Ethernet, Wi-Fi — неважно) и подключится. **Wi-Fi не нужен вообще.**

### Вариант B. Есть root (Termux или adb)

```bash
./wireless-adb-nowifi.sh --strategy root-tcpip     # фиксированный порт 5555
./wireless-adb-nowifi.sh --strategy tls-force      # «настоящая» беспроводная отладка (TLS)
```

`tls-force` выставляет то же свойство, что и тумблер в настройках
(`persist.adb.tls_server.enable=1`), то есть **полностью обходит Wi-Fi-валидацию**.
Порт будет случайным — скрипт достанет его из `logcat`; для первого клиента
понадобится `--pair`.

### Вариант C. Без root и без ПК (Termux + WRITE_SECURE_SETTINGS / Shizuku)

```bash
# один раз, с ПК или через Shizuku — выдать право на запись системных настроек:
adb shell pm grant com.termux android.permission.WRITE_SECURE_SETTINGS
# в Termux:
pkg install android-tools
./wireless-adb-nowifi.sh --strategy hotspot-race
```

Скрипт попросит **включить точку доступа** (или USB-тетеринг/Ethernet) — демону
нужен хотя бы один живой интерфейс. Дальше он циклически пишет
`adb_wifi_enabled=1`, ловя окно, пока фреймворк не погасил демон, находит порт
и подключается (из Termux — по `127.0.0.1`).

### Вариант D. Только Shizuku (без Termux)

Запустите в Shizuku/`rish` те же команды, что печатает `./wireless-adb-nowifi.sh --dry-run`,
либо сам скрипт из Termux с правами, выданными через Shizuku.

---

## 3. Стратегии

| `--strategy` | Требования | Что делает | Когда выбирать |
|---|---|---|---|
| `auto` (по умолчанию) | — | перебирает: `usb-tcpip` → `root-tcpip`/`tls-force` → `hotspot-race` | всегда начинайте отсюда |
| `usb-tcpip` | ПК + рабочий `adb` (USB или уже сеть) | `adb tcpip <port>`, слушает все интерфейсы | есть кабель — самый стабильный путь [9](https://stackoverflow.com/questions/2604727/how-can-i-connect-to-android-with-adb-over-tcp) |
| `root-tcpip` | root | `setprop service.adb.tcp.port 5555` + рестарт `adbd` | нужен фиксированный порт и простой скриптинг [5](https://xdaforums.com/t/adding-service-adb-tcp-port-5555-to-system-build-prop-by-desoldering-flash-on-unlockable-bootloader-possible.4669304/) |
| `tls-force` | root | `setprop persist.adb.tls_server.enable 1` — то же свойство, что выставляет тумблер [8](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md) | нужна штатная «Беспроводная отладка» с шифрованием |
| `hotspot-race` | WRITE_SECURE_SETTINGS, без root | спам `adb_wifi_enabled=1` + живой интерфейс (точка доступа) | Android 13–16 без root [1](https://www.reddit.com/r/Android/comments/1rki743/i_enabled_wireless_adb_pairing_on_device_without/) |

Дополнительно (во всех стратегиях) скрипт выставляет «полезные» флаги:

| Ключ | Значение | Смысл |
|---|---|---|
| `global adb_enabled` | `1` | отладка включена |
| `global adb_wifi_enabled` | `1` | сам флаг тумблера «Беспроводная отладка» (UI показывает «включено») |
| `global adb_allowed_connection_time` | `0` | отключить авто-отзыв авторизации через 7 дней [1](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/) |
| `global captive_portal_detection_enabled` | `0` | Android ≤13: не ждать валидацию сети (на 14+ ключ игнорируется) |
| `global captive_portal_mode` | `0` | то же, «не блокировать сеть без интернета» |

---

## 4. Какие нужны разрешения

| Что делаем | Кто может | Как получить |
|---|---|---|
| `settings put global …` | shell (2000) из adb, приложение с `WRITE_SECURE_SETTINGS`, root | `adb shell pm grant <пакет> android.permission.WRITE_SECURE_SETTINGS`; право «signature\|privileged\|development», третьим приложениям его выдаёт только пользователь через adb/Shizuku [10](https://github.com/Jocala/wifiadb) |
| `setprop persist.adb.tls_server.enable` | root / init / system_server | Magisk/KernelSU: `su -c setprop …` |
| `setprop service.adb.tcp.port` + `stop/start adbd` | root (или сам `adbd` по команде `adb tcpip`) | root, либо `adb tcpip` с ПК [9](https://stackoverflow.com/questions/2604727/how-can-i-connect-to-android-with-adb-over-tcp) |
| чтение `logcat` (чтобы узнать порт) | adb shell, root, приложение с `READ_LOGS` | обычно доступно из `adb shell` |

Скрипт **не требует** установки приложений, не требует Magisk-модулей и не
перезаписывает `/system` — только системные настройки и свойства.

---

## 5. Установка и запуск, по шагам

### Linux / macOS

```bash
git clone <ваш-форк> && cd KakayatoBurmalda
chmod +x wireless-adb-nowifi.sh
./wireless-adb-nowifi.sh --help
./wireless-adb-nowifi.sh --status        # посмотреть флаги/сеть/порты
./wireless-adb-nowifi.sh                 # включить
```

`adb` должен быть в `PATH` ([platform-tools](https://developer.android.com/tools/releases/platform-tools)),
либо укажите путь: `./wireless-adb-nowifi.sh --adb ~/Android/Sdk/platform-tools/adb`.

### Windows

Запускайте в **Git Bash** / **WSL** (чистый `cmd.exe` не нужен):

```bash
./wireless-adb-nowifi.sh --adb "$LOCALAPPDATA/Android/Sdk/platform-tools/adb.exe"
```

### Termux (на самом устройстве)

```bash
pkg install android-tools git -y
git clone <ваш-форк> && cd KakayatoBurmalda
chmod +x wireless-adb-nowifi.sh
# выдать право на запись настроек (один раз, из adb с ПК либо через Shizuku):
adb shell pm grant com.termux android.permission.WRITE_SECURE_SETTINGS
./wireless-adb-nowifi.sh --strategy hotspot-race     # без root
su -c ./wireless-adb-nowifi.sh --strategy root-tcpip # с root
```

### Что увидеть в конце

```
Готово. ADB работает без Wi-Fi.
  стратегия:  usb-tcpip
  адрес:      192.168.42.129:5555
  Проверка:   adb -s 192.168.42.129:5555 shell id
  scrcpy:     scrcpy -s 192.168.42.129:5555
  Отключить:  wireless-adb-nowifi.sh --off
```

---

## 6. Все опции

| Опция | Смысл |
|---|---|
| `--port N` | порт для tcpip-стратегий (по умолчанию 5555) |
| `--strategy NAME` | `auto` \| `usb-tcpip` \| `root-tcpip` \| `tls-force` \| `hotspot-race` |
| `--ip A.B.C.D` | не искать IP, использовать этот |
| `--pair` | интерактивный `adb pair` (спросит порт и 6-значный код) |
| `--serial SERIAL` | конкретное устройство (`adb -s`) |
| `--adb PATH` | путь к бинарнику adb |
| `--race-timeout N` | окно для `hotspot-race` (по умолчанию 30 с) |
| `--iface-wait N` | сколько ждать появления IP (по умолчанию 90 с) |
| `--no-input` | не задавать вопросы, только ждать сеть |
| `--dry-run` | показать команды, ничего не менять |
| `--verbose` | печатать все команды и ответы |
| `--off` / `-o` | выключить всё: флаги, порты, отсоединиться |
| `--status` / `-s` | текущее состояние: флаги, свойства, IP, порты |
| `--help` / `-h` | справка |

---

## 7. Обработка ошибок: симптом → причина → решение

Скрипт проверяет каждую запись чтением, но на всякий случай — шпаргалка:

| Симптом | Причина | Что делать |
|---|---|---|
| `Ни root, ни права на запись Settings.Global` / `Permission denial: writing to settings requires:android.permission.WRITE_SECURE_SETTINGS` | shell/приложение без права | `adb shell pm grant <пакет> android.permission.WRITE_SECURE_SETTINGS`, либо root/Shizuku, либо запуск с ПК через adb |
| `adb не видит ни одного устройства` | нет USB-отладки или ключ не подтверждён | включить «Отладку по USB», подтвердить диалог RSA, `adb devices` → `device` |
| `устройство unauthorized` | ключ хоста не принят | подтвердить диалог на устройстве; для root — дописать `~/.android/adbkey.pub` в `/data/misc/adb/adb_keys` |
| `порт …:5555 закрыт` | прошивка игнорирует `service.adb.tcp.port`/`adb tcpip` | `--strategy tls-force` или `--strategy hotspot-race` |
| `демон не запустился` в `hotspot-race` | нет ни одного живого интерфейса | включить точку доступа/USB-тетеринг, увеличить `--race-timeout 60` |
| `не нашёл порт TLS-сервера в logcat` | нет доступа к logcat | `--verbose`; посмотреть порт глазами в «Беспроводной отладке» и передать `--ip` + подключиться вручную |
| ADB подключился и тут же отвалился | watchdog фреймворка погасил демон | перезапустить скрипт; для root — `tls-force` держится стабильнее |
| `adb tcpip` требует root | на user-сборке `adbd` не даёт сменить режим | root-стратегии, либо `hotspot-race` [4](https://stackoverflow.com/questions/11074868/android-adb-tcpip-error) |
| Всё включилось, но Wi-Fi так и нет | так и задумано | транспорт — Ethernet/USB-тетеринг/точка доступа; Wi-Fi не требуется |

Диагностика: `./wireless-adb-nowifi.sh --verbose` (показывает каждую команду и ответ)
и `./wireless-adb-nowifi.sh --status`.

---

## 8. Безопасность

* Открытый ADB — это **полный доступ к устройству** (установка APK, чтение данных,
  `shell`). Держите порт открытым только пока нужно.
* Legacy-режим (`usb-tcpip`, `root-tcpip`) слушает **без шифрования** на всех
  интерфейсах и не умеет пейринг; в обсуждении Shizuku отдельно отмечали, что
  такой режим — худший по безопасности, чем современная «Беспроводная отладка»
  ([thedjchi/Shizuku#165](https://github.com/thedjchi/Shizuku/issues/165#issuecomment-4009369029)).
  В публичных сетях предпочитайте `tls-force` / `hotspot-race` (TLS + пейринг).
* После работы:

```bash
./wireless-adb-nowifi.sh --off
```

---

## 9. Ограничения и FAQ

**Почему тумблер в настройках всё равно показывает «выключено»?**
Потому что фреймворк проверяет Wi-Fi в UI и в watchdog. Скрипт поднимает **демон**,
а не «убеждает» UI. Если нужен «честный» включённый тумблер — root + `--strategy tls-force`
(система синхронизирует `adb_wifi_enabled` со свойством [10](https://github.com/Jocala/wifiadb)),
либо Xposed-модуль, снимающий проверку на Android 15/16 [2](https://modules.lsposed.org/module/io.drsr.hotspotadb/).

**Будет ли работать на Android 16/17?**
На 13–16 — да (кейс с Pixel 7/Android 16 подтверждён: точка доступа + спам флага [1](https://www.reddit.com/r/Android/comments/1rki743/i_enabled_wireless_adb_pairing_on_device_without/)).
Google анонсировала переработку «ADB Wi-Fi 2.0» в Android 17 — там поведение может
измениться; скрипт корректно сообщит, если демон не поднимется.

**Порт каждый раз новый?**
Да: у TLS-сервера порт случайный [8](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md),
на Android 14+ он вдобавок меняется после сна/перезагрузки [6](https://github.com/mouldybread/adb-auto-enable).
Скрипт достаёт актуальный порт из `logcat`. Фиксированный 5555 дают только
`usb-tcpip` и `root-tcpip`.

**Нужно ли каждый раз заново?**
После перезагрузки — да (кроме случая root + `persist.adb.tcp.port`, который
выживает reboot [9](https://stackoverflow.com/questions/2604727/how-can-i-connect-to-android-with-adb-over-tcp)). Повторный пейринг не нужен:
ключ клиента уже в `/data/misc/adb`.

**Можно ли совсем без сети (без точки доступа)?**
Демону нужен интерфейс с IP. Минимум — USB-тетеринг, Ethernet-переходник (USB-C→RJ45)
или локальная точка доступа. Для Termux хватает и `127.0.0.1` (Shizuku/LADB-сценарий).

---

## 10. Состав репозитория и самопроверка

```
wireless-adb-nowifi.sh     # сам скрипт (bash, без зависимостей, кроме adb)
docs/HOW-IT-WORKS.md       # как именно устроена проверка Wi-Fi в AOSP
tests/mock/adb             # фейковый adb + логика устройства (без реального девайса)
tests/mock-device/         # фейковые settings/getprop/setprop/ip/su — запуск «из Termux»
tests/run-self-test.sh     # 13 сценариев: ПК/устройство, успех, нет прав, root, race, --off, dry-run…
```

Прогнать проверки (устройство не нужно):

```bash
bash tests/run-self-test.sh
# Итого: PASS=13  FAIL=0
```

---

## Источники

1. Разбор Android R UsbDebug: `AdbDebuggingManager`, `WirelessDebuggingPreferenceController`, `ADB_ALLOWED_CONNECTION_TIME` — [lixiaogang03.github.io](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/)
2. `AdbDebuggingManager`: сброс `adb_wifi_enabled` при потере Wi-Fi/смене BSSID — [AOSP cs](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/master/services/core/java/com/android/server/adb/AdbDebuggingManager.java)
3. Документация AOSP по ADB Wi-Fi: `persist.adb.tls_server.enable`, случайный порт, mDNS-сервисы — [platform/packages/modules/adb](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md)
4. `adb tcpip` и `service.adb.tcp.port` (root) — [Stack Overflow](https://stackoverflow.com/questions/2604727/how-can-i-connect-to-android-with-adb-over-tcp)
5. Порядок чтения свойств в `adbd`: `service.adb.tcp.port` → `persist.adb.tcp.port` — [XDA](https://xdaforums.com/t/adding-service-adb-tcp-port-5555-to-system-build-prop-by-desoldering-flash-on-unlockable-bootloader-possible.4669304/)
6. `settings put global adb_wifi_enabled 1` без root — [XDA guide](https://xdaforums.com/t/guide-how-to-enable-adb-via-wifi.4651610/)
7. Связка свойства `persist.adb.tls_server.enable` и `Settings.Global.adb_wifi_enabled` — [github.com/Jocala/wifiadb](https://github.com/Jocala/wifiadb)
8. Android 11+ включает беспроводную отладку только в режиме Wi-Fi-клиента — [модуль Hotspot Wireless Debugging](https://modules.lsposed.org/module/io.drsr.hotspotadb/)
9. Кейс: беспроводная отладка без Wi-Fi на Pixel 7 / Android 16 — [Reddit](https://www.reddit.com/r/Android/comments/1rki743/i_enabled_wireless_adb_pairing_on_device_without/)
10. Разбор race condition, логи `adbd`, локальная точка доступа — [thedjchi/Shizuku#165](https://github.com/thedjchi/Shizuku/issues/165#issuecomment-4009369029)
11. Рандомизация порта на Android 14+ — [adb-auto-enable](https://github.com/mouldybread/adb-auto-enable)

---

<details>
<summary>Исходное содержимое README этого репозитория</summary>

```
Вот такой хаммам мам мам я банан нан нан чемодан дан дан ам ам ам ам ам
```

</details>
