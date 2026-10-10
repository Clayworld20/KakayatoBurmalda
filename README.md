# ⚙ Auto-Compiler — Python → .exe в один клик

[![Сборка Auto-Compiler.exe](https://github.com/Clayworld20/KakayatoBurmalda/actions/workflows/compiler_release.yml/badge.svg)](https://github.com/Clayworld20/KakayatoBurmalda/actions/workflows/compiler_release.yml)

Программа с простым тёмным интерфейсом, которая превращает любой Python-скрипт в готовый `.exe`.
Рассчитана на людей без опыта программирования: никакой командной строки, только кнопки.
На компьютере пользователя **не нужен установленный Python** — компилятор сам скачивает
официальный встроенный Python с python.org и всё необходимое для сборки.

**Статус: версия 1.0.0 — проект завершён.** ✅

## ⬇ Скачать готовый Auto-Compiler.exe

* **Releases** (постоянные ссылки, вход в GitHub не нужен):
  <https://github.com/Clayworld20/KakayatoBurmalda/releases/latest> → блок **Assets** → `Auto-Compiler.exe`.
* **Свежая сборка из любой ветки** (нужен вход в GitHub, хранится 30 дней):
  вкладка **Actions** → «Сборка Auto-Compiler.exe» → нужный запуск → блок **Artifacts** → `Auto-Compiler.exe`.

Первый запуск: Windows SmartScreen может показать «Система Windows защитила ваш компьютер» — файл
не подписан цифровой подписью. Нажмите **«Подробнее» → «Выполнить в любом случае»**.
Рядом с `.exe` в релизе лежит `Auto-Compiler.exe.sha256` — контрольная сумма для проверки файла.

При первой сборке компилятор скачает встроенный Python (~15–45 МБ) в
`%LOCALAPPDATA%\AutoCompiler\runtime` — дальше всё работает быстро.

## Как это работает

1. **Анализ кода** — файл проверяется на синтаксические ошибки, модуль `ast` находит все `import`
   и `from … import` во всех файлах проекта, а также файлы ресурсов (картинки, звуки, `config.json`,
   папки `assets/`, `images/` …).
2. **Подготовка встроенного Python** — при первом запуске в папку `runtime/` скачивается
   официальный Windows embeddable Python 3.12 (`python-3.12.x-embed-*.zip`, проверка SHA-256),
   в `python312._pth` раскомментируется `import site`, затем скачивается и запускается `get-pip.py`.
   Сразу после pip один раз ставятся сборочные утилиты `setuptools` и `wheel` (get-pip.py для
   Python 3.12+ их не ставит), а в корень runtime кладётся мост `sitecustomize.py`: embeddable-Python
   игнорирует `PYTHONPATH`, через который pip подключает свой изолированный сборщик, поэтому без моста
   библиотеки, выложенные только исходным кодом (например, PyAutoGUI), падали с ошибкой
   `BackendUnavailable: Cannot import 'setuptools.build_meta'`.
   В embeddable-версии нет tkinter — если программа пользователя рисует окна (tkinter/customtkinter),
   tkinter автоматически докачивается из официального полного архива python.org.
3. **Загрузка библиотек** — имена импортов переводятся в имена pip-пакетов по встроенной карте
   (`PIL → pillow`, `cv2 → opencv-python`, `sklearn → scikit-learn`, `win32api → pywin32` …),
   сравниваются с уже установленными, недостающие ставятся скрытым
   `runtime\python.exe -m pip install` со статусом
   «Скачиваю необходимые компоненты для компиляции: [Имя]…».
4. **Упаковка в .exe** — в runtime ставится PyInstaller (≥ 6), сборка учитывает `--onefile`,
   `--noconsole`, `--icon=`, добавляет `--add-data` для ресурсов и `--collect-data` для библиотек
   со своими данными (для `customtkinter` — **всегда**). По окончании загорается зелёная кнопка
   «Открыть папку с готовым файлом» (`explorer /select,`).

Любая ошибка (нет интернета, антивирус, библиотека не найдена, упаковщик упал) показывается
в красном окне с объяснением и советом — программа при этом не закрывается.

## Запуск (для разработчика)

```bash
python main.py
```

Если библиотеки `customtkinter` нет, `main.py` сам тихо установит её через pip.
Нужен Python 3.9 или новее (на Windows tkinter входит в стандартную установку).

Для отладки на любой ОС можно подменить встроенный Python внешним:
`AUTOCOMPILER_RUNTIME_PYTHON=/путь/к/python python main.py` (в логе появится предупреждение
«Режим разработчика»).

## Автоматическая сборка (GitHub Actions)

Файл `.github/workflows/compiler_release.yml` при каждом push (и вручную кнопкой **Run workflow**)
на настоящей виртуальной машине Windows:

1. ставит Python 3.12, зависимости из `requirements.txt` и PyInstaller;
2. собирает компилятор:
   `pyinstaller --onefile --noconsole --collect-data customtkinter main.py --name Auto-Compiler`;
3. **проверяет готовый файл в деле** — `Auto-Compiler.exe --selftest` с нуля (скачивая встроенный
   Python с python.org) собирает тестовую программу `tests/selftest/hello_app.py`
   (customtkinter + Pillow + Tcl/Tk + папка `assets` + иконка), затем собранная программа запускается
   и подтверждает, что всё внутри работает;
4. выкладывает `Auto-Compiler.exe` в **Artifacts** запуска (сам `.exe`, без zip-архива);
5. при публикации релиза на вкладке **Releases** — прикрепляет `Auto-Compiler.exe` и
   `Auto-Compiler.exe.sha256` к этому релизу.

**Как выпустить новую версию:** поднимите `APP_VERSION` в `autocompiler/__init__.py`, затем на GitHub:
**Releases → Draft a new release → Choose a tag** (например, `v1.1.0`, «Create new tag») → **Publish release**.
Через пару минут файл появится в блоке **Assets** этого релиза.

## Структура проекта

```
KakayatoBurmalda/
├── .github/workflows/
│   └── compiler_release.yml    # Автосборка Auto-Compiler.exe на Windows, самопроверка, публикация
├── main.py                     # Точка входа: проверка Python, автоустановка customtkinter, запуск окна
│                               # (+ служебный режим --selftest для проверки в GitHub Actions)
├── requirements.txt            # Зависимости самого компилятора
├── autocompiler/
│   ├── __init__.py             # Название и версия приложения
│   ├── config.py               # Цвета, шрифты, размеры, все тексты интерфейса
│   ├── gui/
│   │   ├── main_window.py      # Главное окно: выбор файла, настройки, кнопка сборки, лог
│   │   ├── widgets.py          # SectionCard, PathField, LogConsole (цветной лог)
│   │   └── dialogs.py          # Красное окно ошибки с «Подробностями»
│   ├── core/
│   │   └── pipeline.py         # AST-сканер, карта «импорт → pip-пакет», установка библиотек,
│   │                           # флаги и запуск PyInstaller, перевод его лога в шаги
│   └── utils/
│       ├── event_bus.py        # Потокобезопасная очередь событий «фон → окно»
│       ├── errors.py           # Типы ошибок и перевод любых ошибок на понятный язык
│       └── system.py           # Встроенный Python (скачивание, ._pth, get-pip, tkinter),
│                               # загрузки с повторами, скрытый запуск процессов, проводник
├── tests/selftest/             # Тестовая программа для самопроверки готового Auto-Compiler.exe
└── runtime/                    # Встроенный Python при запуске из исходников (в .gitignore)
```

При запуске из исходников `runtime/` создаётся рядом с `main.py` (если туда нельзя писать —
в `%LOCALAPPDATA%\AutoCompiler\`). Собранный `Auto-Compiler.exe` всегда хранит её в
`%LOCALAPPDATA%\AutoCompiler\runtime`, чтобы не захламлять «Загрузки» и не терять среду при переносе файла
(портативный режим: если рядом с `.exe` уже лежит готовая папка `runtime`, используется она).
Готовый `.exe` появляется в папке `Готовая программа` рядом со скриптом пользователя.

## Принципы

* **Окно никогда не зависает** — сборка идёт в фоновом потоке, окно получает события через `EventBus`.
* **Окно никогда не падает** — каждый этап обёрнут в `try-except`, ошибки Tk-обработчиков и потоков
  перехватываются и показываются в красном окне с советом, что делать.
* **Без лишних рисков** — импорты из веток только для macOS/Linux (`if sys.platform == "darwin":`)
  не устанавливаются; модули, загружаемые динамически (`importlib.import_module`), только передаются
  PyInstaller как `--hidden-import`, но не скачиваются; необязательные импорты
  (`try: import x / except ImportError`) при неудачной установке дают лишь предупреждение.
* **Закрытие окна во время сборки** останавливает pip/PyInstaller вместе с дочерними процессами.
* **Собранный компилятор не «заражает» дочерние процессы** — внутри `Auto-Compiler.exe` сбрасывается
  `SetDllDirectory` и из окружения убираются переменные PyInstaller и Tcl/Tk (как советует документация
  PyInstaller), чтобы встроенный Python и упаковщик использовали только свои библиотеки.
* **Все цвета и тексты — в `config.py`.**

## Дорожная карта

- [x] **Шаг 1.** Структура проекта, главное окно, лог сборки, окно ошибок, этап «Анализ кода».
- [x] **Шаг 2.** Сканер импортов и автоматическая подготовка изолированной среды (embeddable Python + pip).
- [x] **Шаг 3.** Умная сборка PyInstaller (`--onefile`, `--noconsole`, `--icon`, `--add-data`, `--collect-data`).
- [x] **Шаг 4.** Упаковка самого компилятора в `Auto-Compiler.exe` через GitHub Actions с самопроверкой на Windows.

🎉 **Все шаги выполнены — проект завершён (версия 1.0.0).**
