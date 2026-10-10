# Как устроена проверка Wi-Fi и что именно обходит скрипт

## 1. Цепочка включения «Беспроводной отладки» в AOSP

```
Пользователь жмёт тумблер
        │
        ▼
WirelessDebuggingPreferenceController (приложение «Настройки»)
        │  IAdbManager.enableAdbWireless(...)
        ▼
AdbService / AdbDebuggingManager (system_server)
        │  проверка getCurrentWifiApInfo()  ←── ВОТ ТУТ «Нет подключения к Wi-Fi»
        │  Settings.Global.adb_wifi_enabled = 1
        ▼
свойство persist.adb.tls_server.enable = 1
        ▼
adbd поднимает TLSServer на случайном порту + mDNS _adb-tls-connect._tcp
```

Подтверждающие исходники:

* `AdbDebuggingManager.MSG_ADBDWIFI_ENABLE`: если `getCurrentWifiApInfo()` вернул `null`
  (нет Wi-Fi-сети с `networkId != -1`) — фреймворк **сразу пишет `adb_wifi_enabled = 0`**
  и ничего не включает [1](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/).
* Watchdog в том же классе: при `WIFI_STATE_DISABLED`, отключении сети или смене BSSID —
  `adb_wifi_enabled` снова `0` [2](https://android.googlesource.com/platform/frameworks/base/+/refs/heads/master/services/core/java/com/android/server/adb/AdbDebuggingManager.java).
* Документация AOSP: `persist.adb.tls_server.enable` — свойство, которым UI включает
  TLSServer в `adbd`; порт выбирается случайно; сервисы mDNS:
  `_adb._tcp` (legacy `adb tcpip`), `_adb-tls-pairing._tcp`, `_adb-tls-connect._tcp`
  [3](https://android.googlesource.com/platform/packages/modules/adb/+/HEAD/docs/dev/adb_wifi.md).
* `WirelessDebuggingPreferenceController` пишет `Settings.Global.ADB_WIFI_ENABLED`
  (`adb_wifi_enabled`) и `ADB_ALLOWED_CONNECTION_TIME` (0 = «Отключить тайм-аут
  авторизации adb») [1](https://lixiaogang03.github.io/2020/11/17/android-R-UsbDebug/).

## 2. Что на самом деле делает `settings put global adb_wifi_enabled 1`

Флаг — не просто «картинка» в UI: в system_server есть `AdbSettingsObserver`,
который на изменение `adb_wifi_enabled` дёргает запуск демона. В логах это выглядит так:

```
D AdbSettingsObserver: onChange content://settings/global/adb_wifi_enabled
I adbd    : persist.adb.tls_server.enable changed to 1
I adbd    : adbwifi started on port 46161
I adbd    : TlsServer running on port 46161
```

Но **тут же** срабатывает проверка «а есть ли Wi-Fi» (п. 1), и watchdog возвращает
флаг в `0`. Возникает состояние гонки: если писать флаг часто, на одной из итераций
демон успевает подняться и закрепиться. Это и есть стратегия `hotspot-race`:

* воспроизводится на Android 13–16 (в т.ч. Pixel 7 / Android 16) [9](https://www.reddit.com/r/Android/comments/1rki743/i_enabled_wireless_adb_pairing_on_device_without/);
* разбор и логи — в обсуждении Shizuku [10](https://github.com/thedjchi/Shizuku/issues/165#issuecomment-4009369029);
* демону всё равно нужен живой сетевой интерфейс: подходит точка доступа,
  локальная точка доступа (LocalOnlyHotspot), USB-тетеринг, Ethernet;
* после того как демон поднят, подключение к **новым** интерфейсам он уже не открывает —
  то есть attack surface не растёт.

## 3. Почему одного флага мало

`adb_wifi_enabled` — это «зеркало» состояния. Значение читается/перезаписывается
системой: например, `AdbService.systemReady()` копирует значение свойства
`persist.adb.tls_server.enable` в `Settings.Global.adb_wifi_enabled`
[7](https://github.com/Jocala/wifiadb). Поэтому:

* писать флаг «в один приём» бессмысленно — его тут же затрёт watchdog;
* на Android 14+ порт рандомизируется и меняется после сна/перезагрузки [11](https://github.com/mouldybread/adb-auto-enable),
  поэтому «запомнить» порт нельзя — скрипт достаёт его из `logcat`;
* на Android 17 Google обещает «ADB Wi-Fi 2.0» — поведение может измениться.

## 4. Legacy-путь: `service.adb.tcp.port`

Совсем другой, официально документированный механизм: `adbd` при старте читает
свойства и, если порт задан, слушает его на всех интерфейсах:

```
std::string prop_port = GetProperty("service.adb.tcp.port", "");
if (prop_port.empty()) prop_port = GetProperty("persist.adb.tcp.port", "");
```

[5](https://xdaforums.com/t/adding-service-adb-tcp-port-5555-to-system-build-prop-by-desoldering-flash-on-unlockable-bootloader-possible.4669304/)

* `adb tcpip 5555` с ПК — тот же механизм, свойство ставит сам `adbd`
  [4](https://stackoverflow.com/questions/2604727/how-can-i-connect-to-android-with-adb-over-tcp);
* проверки Wi-Fi в этом пути **нет вообще** — поэтому `usb-tcpip` самый надёжный;
* на части user-сборок `adbd` не даёт выставить свойство без root [4](https://stackoverflow.com/questions/11074868/android-adb-tcpip-error);
* трафик не шифруется, авторизация — по RSA-ключу из `/data/misc/adb/adb_keys`
  (ключи, ранее подтверждённые по USB, работают сразу).

## 5. Что делает скрипт, шаг за шагом

1. Определяет контекст: ПК с `adb` (`adb devices`) или shell на самом устройстве
   (Termux — по `/system/build.prop`, `getprop`).
2. Проверяет root (`id -u`, `su -c id -u`) и право писать `Settings.Global`
   (пробная запись + чтение).
3. Выставляет базовые флаги, **каждый раз проверяя запись чтением**:
   `adb_enabled=1`, `adb_wifi_enabled=1`, `adb_allowed_connection_time=0`,
   а на Android ≤13 — `captive_portal_detection_enabled=0`, `captive_portal_mode=0`.
4. Выбирает стратегию (`auto` = usb-tcpip → root-tcpip → tls-force → hotspot-race).
5. Убеждается, что есть интерфейс с IP (`ip -f inet addr show`, при необходимости
   просит включить точку доступа и ждёт до `--iface-wait` секунд).
6. Поднимает демона выбранным способом и проверяет факт: свойство, реальный
   TCP-коннект (`/dev/tcp`), для TLS — порт из `logcat`.
7. Подключается (`adb connect`), разбирает состояние транспорта
   (`device` / `unauthorized` / `offline`) и выполняет контрольную команду
   `adb -s host:port shell id`.
8. Печатает итог и напоминание про `--off`.

## 6. Почему нельзя просто «выключить проверку» в UI

* Проверка живёт в `system_server` и в приложении «Настройки» — это системный код;
  без root/LSPosed его не изменить [8](https://modules.lsposed.org/module/io.drsr.hotspotadb/).
* `WRITE_SECURE_SETTINGS` даёт только запись настроек — не более: даже с ним
  `system_adbd_prop` (`persist.adb.tls_server.enable`) пишет только system_server/init [7](https://github.com/Jocala/wifiadb).
* Поэтому скрипт действует «снизу»: заставляет `adbd` слушать порт на существующем
  интерфейсе. Для пользователя это и есть искомый результат — ADB работает,
  хотя Wi-Fi нет.
