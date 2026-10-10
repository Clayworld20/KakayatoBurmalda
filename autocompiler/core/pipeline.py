"""
Конвейер сборки — выполняет этапы по очереди в ФОНОВОМ потоке.

Этапы:
    1. Анализ кода           — проверка файла и иконки, синтаксис, AST-сканер импортов и ресурсов;
    2. Подготовка среды      — портативный Python в runtime/ (скачивается один раз);
    3. Загрузка библиотек    — сверка импортов с runtime/ и тихая установка недостающих через pip;
    4. Упаковка в .exe       — установка PyInstaller (если нужно) и сборка с умными флагами.

Каждый этап обёрнут в собственный try-except (метод _run_stage), поэтому любая ошибка —
обрыв интернета, сбой pip, падение PyInstaller — превращается в понятное красное окно,
а программа продолжает работать.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# ast — разбор Python-кода в дерево без его запуска (основа сканера импортов).
import ast
# hashlib — короткий уникальный «отпечаток» пути проекта для имени временной папки.
import hashlib
# os — разделитель путей для --add-data.
import os
# re — очистка имени программы и разбор строк лога PyInstaller.
import re
# shutil — удаление старых результатов сборки.
import shutil
# sys — список модулей стандартной библиотеки текущего Python.
import sys
# sysconfig — путь к стандартной библиотеке (запасной способ для старых Python).
import sysconfig
# time — замер длительности сборки.
import time
# tokenize.open правильно определяет кодировку .py-файла (BOM, «# coding: …»).
import tokenize
# dataclass — короткая запись классов-контейнеров.
from dataclasses import dataclass, field
# Path — работа с путями.
from pathlib import Path
# Типы для подсказок.
from typing import Callable, Iterable, Optional, TypeVar

# Шина событий для общения с окном.
from autocompiler.utils.event_bus import EventBus, LogLevel
# Понятные ошибки и переводчик исключений.
from autocompiler.utils.errors import (
    BuildCancelled,
    CompilerError,
    ProcessFailedError,
    describe_exception,
    format_traceback,
)
# Работа с ОС и встроенным Python.
from autocompiler.utils.system import (
    IS_WINDOWS,
    CancelToken,
    PythonRuntime,
    format_size,
    is_dir_writable,
    user_data_dir,
)

# Обобщённый тип результата этапа.
T = TypeVar("T")

# ====================================================================== #
#   КОНСТАНТЫ                                                             #
# ====================================================================== #

# Допустимые расширения главного файла программы.
SCRIPT_EXTENSIONS = {".py", ".pyw"}
# «Магические» первые 4 байта настоящего .ico-файла.
ICO_MAGIC = b"\x00\x00\x01\x00"
# Имя папки с результатом рядом с главным файлом.
OUTPUT_DIR_NAME = "Готовая программа"
# Какую версию PyInstaller ставить (6.0+ нужна для --contents-directory).
PYINSTALLER_REQUIREMENT = "pyinstaller>=6.0"
# Максимум файлов проекта, которые сканируем (защита от сканирования «всего диска»).
MAX_SCANNED_FILES = 400

# Карта «имя в import → имя пакета в pip» для библиотек, у которых они НЕ совпадают.
# Если библиотеки нет в карте — ставим пакет с тем же именем, что и в import.
IMPORT_TO_PIP: dict[str, str] = {
    # --- Графика и изображения ---
    "PIL": "pillow",
    "cv2": "opencv-python",
    "skimage": "scikit-image",
    "fitz": "PyMuPDF",
    "pyzbar": "pyzbar",
    "qrcode": "qrcode[pil]",
    "barcode": "python-barcode",
    "cairosvg": "CairoSVG",
    "imageio": "imageio",
    "OpenGL": "PyOpenGL",
    "Box2D": "box2d-py",
    # --- Интерфейсы ---
    "customtkinter": "customtkinter",
    "CTkMessagebox": "CTkMessagebox",
    "CTkToolTip": "CTkToolTip",
    "CTkListbox": "CTkListbox",
    "CTkColorPicker": "CTkColorPicker",
    "CTkSpinbox": "CTkSpinbox",
    "CTkTable": "CTkTable",
    "CTkMenuBar": "CTkMenuBar",
    "sv_ttk": "sv-ttk",
    "wx": "wxPython",
    "webview": "pywebview",
    "eel": "Eel",
    "kivy": "Kivy",
    "kivymd": "kivymd",
    "qtpy": "QtPy",
    "PySimpleGUI": "PySimpleGUI",
    "FreeSimpleGUI": "FreeSimpleGUI",
    "tkinterdnd2": "tkinterdnd2",
    "tkcalendar": "tkcalendar",
    "tkintermapview": "tkintermapview",
    # --- Автоматизация Windows, ввод, экран ---
    "win32api": "pywin32",
    "win32con": "pywin32",
    "win32gui": "pywin32",
    "win32ui": "pywin32",
    "win32com": "pywin32",
    "win32process": "pywin32",
    "win32clipboard": "pywin32",
    "win32print": "pywin32",
    "win32service": "pywin32",
    "win32event": "pywin32",
    "win32file": "pywin32",
    "win32pipe": "pywin32",
    "win32crypt": "pywin32",
    "win32security": "pywin32",
    "win32timezone": "pywin32",
    "winerror": "pywin32",
    "pythoncom": "pywin32",
    "pywintypes": "pywin32",
    "wmi": "WMI",
    "pyautogui": "PyAutoGUI",
    "pymsgbox": "PyMsgBox",
    "pygetwindow": "PyGetWindow",
    "pydirectinput": "PyDirectInput",
    "pyscreeze": "PyScreeze",
    "Xlib": "python-xlib",
    "ahk": "ahk",
    "winotify": "winotify",
    "win10toast": "win10toast",
    "pystray": "pystray",
    # --- Звук, видео, речь ---
    "speech_recognition": "SpeechRecognition",
    "pyaudio": "PyAudio",
    "soundfile": "soundfile",
    "vlc": "python-vlc",
    "gtts": "gTTS",
    "moviepy": "moviepy",
    "pydub": "pydub",
    # --- Сеть, боты, API ---
    "bs4": "beautifulsoup4",
    "telebot": "pyTelegramBotAPI",
    "telegram": "python-telegram-bot",
    "telethon": "Telethon",
    "discord": "discord.py",
    "vk_api": "vk-api",
    "websocket": "websocket-client",
    "socketio": "python-socketio",
    "engineio": "python-engineio",
    "jwt": "PyJWT",
    "OpenSSL": "pyOpenSSL",
    "Crypto": "pycryptodome",
    "Cryptodome": "pycryptodomex",
    "nacl": "PyNaCl",
    "dns": "dnspython",
    "nmap": "python-nmap",
    "googleapiclient": "google-api-python-client",
    "webdriver_manager": "webdriver-manager",
    "undetected_chromedriver": "undetected-chromedriver",
    "deep_translator": "deep-translator",
    "serial": "pyserial",
    "usb": "pyusb",
    "zmq": "pyzmq",
    "grpc": "grpcio",
    "kafka": "kafka-python",
    "flask": "Flask",
    "jinja2": "Jinja2",
    "markupsafe": "MarkupSafe",
    # --- Данные, документы, таблицы ---
    "yaml": "PyYAML",
    "dotenv": "python-dotenv",
    "dateutil": "python-dateutil",
    "docx": "python-docx",
    "pptx": "python-pptx",
    "PyPDF2": "PyPDF2",
    "xlsxwriter": "XlsxWriter",
    "sklearn": "scikit-learn",
    "attr": "attrs",
    "magic": "python-magic-bin",
    "Levenshtein": "Levenshtein",
    "sqlalchemy": "SQLAlchemy",
    "psycopg2": "psycopg2-binary",
    "MySQLdb": "mysqlclient",
    "pymysql": "PyMySQL",
    "apscheduler": "APScheduler",
    "faker": "Faker",
    "babel": "Babel",
    "markdown": "Markdown",
    "charset_normalizer": "charset-normalizer",
    "pkg_resources": "setuptools",
    "distutils": "setuptools",
    "mpl_toolkits": "matplotlib",
    "pythonosc": "python-osc",
}

# Карта для «составных» импортов, где решает не первое слово, а путь целиком.
DOTTED_TO_PIP: dict[str, str] = {
    "google.protobuf": "protobuf",
    "google.generativeai": "google-generativeai",
    "google.genai": "google-genai",
    "google.cloud.storage": "google-cloud-storage",
    "google.oauth2": "google-auth",
    "google.auth": "google-auth",
    "google_auth_oauthlib": "google-auth-oauthlib",
    "mysql.connector": "mysql-connector-python",
    "infi.systray": "infi.systray",
    "azure.storage.blob": "azure-storage-blob",
}

# Импорты, которые никогда не нужно ставить через pip.
SKIP_INSTALL = {
    # tkinter и его «родственники» ставятся отдельно (из официального дистрибутива Python).
    "tkinter", "_tkinter", "turtle", "turtledemo", "idlelib",
    # Служебные пакеты, которые уже есть во встроенном Python или не нужны в .exe.
    "pip", "PyInstaller", "__main__", "__future__",
}

# Библиотеки, которым нужен tkinter внутри встроенного Python.
TK_DEPENDENT = {
    "tkinter", "_tkinter", "turtle", "customtkinter", "ttkbootstrap", "tkinterdnd2",
    "CTkMessagebox", "CTkToolTip", "CTkListbox", "CTkColorPicker", "CTkSpinbox", "CTkTable",
    "CTkMenuBar", "tkcalendar", "tksheet", "ttkthemes", "ttkwidgets", "sv_ttk", "pygubu",
    "PySimpleGUI", "FreeSimpleGUI", "pymsgbox", "pyautogui", "mouseinfo", "matplotlib",
    "tkintermapview", "tkinterweb",
}

# Особые флаги PyInstaller для «сложных» библиотек (данные тем, плагины, скрытые модули).
COLLECT_RULES: dict[str, list[str]] = {
    # ВАЖНО: темы и шрифты customtkinter лежат файлами — без них интерфейс ломается после сборки.
    "customtkinter": ["--collect-data", "customtkinter"],
    "CTkMessagebox": ["--collect-data", "CTkMessagebox"],
    "CTkColorPicker": ["--collect-data", "CTkColorPicker"],
    "tkinterdnd2": ["--collect-all", "tkinterdnd2"],
    "ttkbootstrap": ["--collect-data", "ttkbootstrap"],
    "ttkthemes": ["--collect-data", "ttkthemes"],
    "sv_ttk": ["--collect-data", "sv_ttk"],
    "tkintermapview": ["--collect-data", "tkintermapview"],
    "tkcalendar": ["--hidden-import", "babel.numbers"],
    "pyfiglet": ["--collect-data", "pyfiglet"],
    "plyer": ["--collect-submodules", "plyer"],
    "pyttsx3": ["--collect-submodules", "pyttsx3"],
    "pystray": ["--collect-submodules", "pystray"],
    "win10toast": ["--collect-data", "win10toast"],
    "langdetect": ["--collect-data", "langdetect"],
    "pygame_menu": ["--collect-data", "pygame_menu"],
    "pygame_gui": ["--collect-data", "pygame_gui"],
    "mediapipe": ["--collect-data", "mediapipe"],
    "ultralytics": ["--collect-data", "ultralytics"],
    "whisper": ["--collect-data", "whisper"],
    "escpos": ["--collect-data", "escpos"],
    "eel": ["--collect-data", "eel", "--hidden-import", "bottle_websocket"],
    "tiktoken": ["--hidden-import", "tiktoken_ext.openai_public", "--hidden-import", "tiktoken_ext"],
}

# Типичные имена папок с ресурсами — добавляем их в .exe автоматически, если они есть рядом.
DATA_DIR_NAMES = {
    "assets", "asset", "images", "image", "img", "imgs", "icons", "icon", "sounds", "sound",
    "sfx", "audio", "music", "fonts", "font", "data", "resources", "resource", "res", "media",
    "static", "templates", "sprites", "textures", "video", "videos", "locales", "lang",
    "translations", "maps", "levels", "themes",
}

# Папки, которые никогда не сканируем и не добавляем в .exe.
IGNORED_DIR_NAMES = {
    "__pycache__", ".git", ".hg", ".svn", ".venv", "venv", "env", ".env", ".idea", ".vscode",
    "build", "dist", "node_modules", "runtime", ".mypy_cache", ".pytest_cache", ".tox",
    OUTPUT_DIR_NAME.lower(),
}

# Расширения файлов с кодом — их PyInstaller собирает сам, как данные не добавляем.
CODE_SUFFIXES = {".py", ".pyw", ".pyc", ".pyo", ".spec"}

# Runtime-хук PyInstaller: при запуске .exe делает текущей папкой папку с ресурсами,
# чтобы в коде работали относительные пути вида open("assets/logo.png").
RUNTIME_HOOK_CODE = '''\
# Создано Auto-Compiler: делает относительные пути к ресурсам рабочими внутри .exe.
# os — смена текущей папки.
import os
# sys — признаки запуска из .exe.
import sys

# Программа запущена из собранного .exe (PyInstaller задаёт sys.frozen и sys._MEIPASS).
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    # Ошибка смены папки не должна мешать запуску программы.
    try:
        # Переходим в папку, куда PyInstaller распаковал ресурсы.
        os.chdir(sys._MEIPASS)
    # Не получилось — работаем из текущей папки.
    except OSError:
        pass
'''


# ====================================================================== #
#   ДАННЫЕ                                                                #
# ====================================================================== #

@dataclass(frozen=True)
class BuildSettings:
    """Все настройки, выбранные пользователем в окне, — одним объектом."""

    # Путь к главному .py-файлу программы.
    script_path: Path
    # Путь к иконке .ico (или None — стандартная иконка).
    icon_path: Optional[Path] = None
    # Скрыть консоль (флаг PyInstaller --noconsole).
    hide_console: bool = False
    # Собрать в один файл (флаг PyInstaller --onefile).
    one_file: bool = True


@dataclass
class ImportInfo:
    """Сведения об одном импортированном модуле верхнего уровня."""

    # Имя верхнего уровня («PIL» для «from PIL import Image»).
    name: str
    # Полные пути импорта («PIL.Image», «google.protobuf.message»).
    dotted: set[str] = field(default_factory=set)
    # True, если хотя бы один импорт обязательный (не в try/except ImportError и не в if).
    required: bool = False
    # True, если импорт динамический (importlib.import_module / __import__).
    dynamic: bool = False
    # True, если есть хотя бы один обычный (статический) import — только такие ставим через pip.
    static: bool = False
    # Файлы проекта, где встречается импорт.
    files: set[str] = field(default_factory=set)

    @property
    def optional(self) -> bool:
        """Необязательный импорт (только внутри try/except ImportError или условий)."""
        # Противоположность required.
        return not self.required

    @property
    def pip_name(self) -> str:
        """Имя пакета для pip install."""
        # Используем общую функцию сопоставления.
        return pip_name_for(self.name, self.dotted)


@dataclass(frozen=True)
class DataEntry:
    """Файл или папка с ресурсами для флага --add-data."""

    # Абсолютный путь к файлу/папке.
    source: Path
    # Путь назначения внутри .exe («assets», «.» и т.п.).
    dest: str
    # Почему добавлено (для понятного лога).
    reason: str

    @property
    def is_dir(self) -> bool:
        """Это папка?"""
        # Проверяем на диске.
        return self.source.is_dir()


@dataclass
class ScanResult:
    """Итог сканирования проекта."""

    # Все внешние импорты верхнего уровня (кроме модулей самого проекта).
    imports: dict[str, ImportInfo] = field(default_factory=dict)
    # Модули самого проекта (соседние .py-файлы и папки).
    local_modules: set[str] = field(default_factory=set)
    # Найденные ресурсы для --add-data.
    data_entries: list[DataEntry] = field(default_factory=list)
    # Просканированные файлы.
    scanned_files: list[Path] = field(default_factory=list)
    # Предупреждения (ошибки в второстепенных файлах и т.п.).
    warnings: list[str] = field(default_factory=list)
    # Абсолютные пути вне проекта, найденные в коде (на чужом ПК их не будет).
    external_paths: list[str] = field(default_factory=list)

    def third_party(self, stdlib: set[str]) -> list[ImportInfo]:
        """Сторонние библиотеки (не стандартная библиотека и не служебные модули)."""
        # Отбираем и сортируем по имени.
        return [
            info for name, info in sorted(self.imports.items(), key=lambda item: item[0].lower())
            if name not in stdlib and name not in SKIP_INSTALL
        ]

    @property
    def dynamic_imports(self) -> list[str]:
        """Полные пути динамических импортов (для --hidden-import)."""
        # Собираем все пути динамических импортов.
        names: set[str] = set()
        # Проходим по импортам.
        for info in self.imports.values():
            # Только динамические.
            if info.dynamic:
                names.update(info.dotted)
        # Стабильный порядок.
        return sorted(names)


@dataclass
class AnalysisResult:
    """Результат этапа анализа — нужен следующим этапам."""

    # Полный текст главного файла.
    source: str
    # Кодировка главного файла.
    encoding: str
    # Количество строк главного файла.
    line_count: int
    # Итог сканирования импортов и ресурсов.
    scan: ScanResult


# ====================================================================== #
#   ФУНКЦИИ СОПОСТАВЛЕНИЯ                                                 #
# ====================================================================== #

def pip_name_for(name: str, dotted: Iterable[str] = ()) -> str:
    """Подобрать имя pip-пакета по импорту (сначала составные пути, потом верхний уровень)."""
    # Проверяем составные пути: самое длинное совпадение побеждает.
    best = ""
    # Результат по составному пути.
    best_package = ""
    # Перебираем все полные пути импорта.
    for path in dotted:
        # Сравниваем с каждым ключом карты составных путей.
        for prefix, package in DOTTED_TO_PIP.items():
            # Путь совпадает с ключом или начинается с «ключ.».
            if (path == prefix or path.startswith(prefix + ".")) and len(prefix) > len(best):
                # Запоминаем лучшее совпадение.
                best, best_package = prefix, package
    # Нашли составное совпадение.
    if best_package:
        return best_package
    # Иначе — по имени верхнего уровня (или само имя, если его нет в карте).
    return IMPORT_TO_PIP.get(name, name)


def needs_tkinter(names: Iterable[str]) -> bool:
    """Нужен ли tkinter хотя бы одной из библиотек."""
    # Проверяем каждое имя.
    for name in names:
        # Явно известные библиотеки или префиксы CTk*/ttk*.
        if name in TK_DEPENDENT or name.startswith(("CTk", "ctk_", "ttk")):
            return True
    # Ни одной tkinter-библиотеки.
    return False


def compiler_stdlib_names() -> set[str]:
    """Модули стандартной библиотеки Python, в котором работает сам компилятор."""
    # В Python 3.10+ список есть готовый.
    names = set(getattr(sys, "stdlib_module_names", ()))
    # В Python 3.9 собираем список сами.
    if not names:
        # Встроенные в интерпретатор модули.
        names.update(sys.builtin_module_names)
        # Папки стандартной библиотеки.
        for key in ("stdlib", "platstdlib"):
            # Путь к папке.
            folder = Path(sysconfig.get_paths().get(key, ""))
            # Перебираем содержимое (и lib-dynload с C-модулями).
            for directory in (folder, folder / "lib-dynload"):
                # Папки может не быть.
                if not directory.is_dir():
                    continue
                # Каждый файл/папка — модуль.
                for entry in directory.iterdir():
                    # Имя модуля до первой точки (json, _ssl.cpython-39… → _ssl).
                    names.add(entry.name.split(".")[0])
    # Особые имена, которые всегда «встроенные».
    names.update({"__future__", "__main__"})
    # Готово.
    return names


# ====================================================================== #
#   AST-СКАНЕР ИМПОРТОВ                                                    #
# ====================================================================== #

def _catches_import_error(handler: ast.ExceptHandler) -> bool:
    """Ловит ли блок except ошибку импорта (тогда импорт в try считается необязательным)."""
    # «except:» без типа ловит всё.
    if handler.type is None:
        return True
    # Узлы, которые нужно проверить (один тип или кортеж типов).
    nodes = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    # Проверяем каждый тип.
    for node in nodes:
        # Имя типа: ImportError или builtins.ImportError.
        name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else ""
        # Эти исключения покрывают ошибку импорта.
        if name in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException"):
            return True
    # Ни один тип не подходит.
    return False


def _is_type_checking(test: ast.expr) -> bool:
    """Условие «if TYPE_CHECKING:» — импорты внутри нужны только редакторам кода."""
    # Простое имя или typing.TYPE_CHECKING.
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def _is_main_guard(test: ast.expr) -> bool:
    """Условие «if __name__ == '__main__':» — код внутри выполняется всегда при запуске."""
    # Ожидаем сравнение.
    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False
    # Обе стороны сравнения.
    sides = [test.left, test.comparators[0]]
    # Одна сторона — имя __name__.
    has_name = any(isinstance(s, ast.Name) and s.id == "__name__" for s in sides)
    # Другая — строка "__main__".
    has_main = any(isinstance(s, ast.Constant) and s.value == "__main__" for s in sides)
    # Обе части на месте.
    return has_name and has_main


# Значения sys.platform / os.name / platform.system() других операционных систем.
_OTHER_PLATFORM_TOKENS = ("darwin", "linux", "posix", "java", "freebsd", "openbsd", "aix", "emscripten", "wasi", "ios", "android", "mac")


def _classify_platform(token: str) -> Optional[bool]:
    """True — строка означает Windows, False — другую ОС, None — не про платформу."""
    # Приводим к нижнему регистру.
    token = token.lower()
    # «win32», «windows», «nt» — Windows.
    if token.startswith("win") or token == "nt":
        return True
    # «darwin», «linux», «posix»… — другие ОС.
    if token.startswith(_OTHER_PLATFORM_TOKENS):
        return False
    # Строка не про платформу.
    return None


def _platform_branch(test: ast.expr) -> Optional[bool]:
    """
    Понять, проверяет ли условие операционную систему.
    True — ветка if только для Windows, False — только для других ОС, None — не про ОС.
    """
    # «not условие» — инвертируем ответ.
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        # Ответ для вложенного условия.
        inner = _platform_branch(test.operand)
        # Инвертируем, если ответ известен.
        return None if inner is None else not inner
    # sys.platform.startswith("linux").
    if isinstance(test, ast.Call) and isinstance(test.func, ast.Attribute) and test.func.attr == "startswith":
        # Первый аргумент — строка.
        if test.args and isinstance(test.args[0], ast.Constant) and isinstance(test.args[0].value, str):
            return _classify_platform(test.args[0].value)
        # Не можем понять.
        return None
    # Ожидаем простое сравнение: sys.platform == "darwin".
    if not isinstance(test, ast.Compare) or len(test.ops) != 1:
        return None
    # Строковые константы в сравнении.
    tokens = [n.value for n in (test.left, *test.comparators) if isinstance(n, ast.Constant) and isinstance(n.value, str)]
    # Нет строк — не про платформу.
    if not tokens:
        return None
    # Классифицируем строку.
    verdict = _classify_platform(tokens[0])
    # Не про платформу.
    if verdict is None:
        return None
    # Оператор сравнения.
    op = test.ops[0]
    # «==», «is», «in» — ответ как есть.
    if isinstance(op, (ast.Eq, ast.Is, ast.In)):
        return verdict
    # «!=», «is not», «not in» — наоборот.
    if isinstance(op, (ast.NotEq, ast.IsNot, ast.NotIn)):
        return not verdict
    # Прочие операторы — не знаем.
    return None


class _ImportVisitor(ast.NodeVisitor):
    """Обходит дерево кода и собирает импорты и строковые константы."""

    def __init__(self) -> None:
        # Найденные импорты: (полный путь, необязательный?, динамический?).
        self.found: list[tuple[str, bool, bool]] = []
        # Строки из кода (кандидаты в пути к ресурсам).
        self.strings: list[str] = []
        # Глубина «необязательного» контекста (try/except ImportError, if).
        self._optional_depth = 0

    def _add(self, dotted: str, dynamic: bool = False) -> None:
        """Запомнить импорт с текущим признаком необязательности."""
        # Добавляем кортеж в список.
        self.found.append((dotted, self._optional_depth > 0, dynamic))

    def visit_Import(self, node: ast.Import) -> None:
        """import a, b.c as d"""
        # Каждое имя в строке импорта.
        for alias in node.names:
            self._add(alias.name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """from a.b import c"""
        # Относительные импорты («from . import x») — это модули самого проекта.
        if node.level == 0 and node.module:
            self._add(node.module)

    def visit_Try(self, node: ast.Try) -> None:
        """try/except: импорты внутри try с except ImportError — необязательные."""
        # Ловит ли этот try ошибки импорта.
        optional = any(_catches_import_error(handler) for handler in node.handlers)
        # Входим в «необязательный» контекст.
        if optional:
            self._optional_depth += 1
        # Тело try.
        for statement in node.body:
            self.visit(statement)
        # Блоки except (там часто «запасной» импорт — он тоже необязательный).
        for handler in node.handlers:
            self.visit(handler)
        # Выходим из «необязательного» контекста.
        if optional:
            self._optional_depth -= 1
        # Блоки else и finally выполняются как обычно.
        for statement in node.orelse + node.finalbody:
            self.visit(statement)

    # Python 3.11+: try/except* обрабатываем так же.
    visit_TryStar = visit_Try

    def visit_If(self, node: ast.If) -> None:
        """if: импорты внутри условий считаем необязательными (кроме if __name__ == '__main__')."""
        # Импорты для проверки типов пропускаем полностью.
        if _is_type_checking(node.test):
            # Ветку else всё же обходим.
            for statement in node.orelse:
                self.visit(statement)
            # Готово.
            return
        # Главный блок программы — обычный (обязательный) код.
        if _is_main_guard(node.test):
            self.generic_visit(node)
            # Готово.
            return
        # Проверка операционной системы: ветки для macOS/Linux в Windows-сборке не нужны.
        branch = _platform_branch(node.test)
        # Ветка if — только для Windows, else — для других ОС.
        if branch is True:
            # Нужные ветки: только тело if.
            statements = list(node.body)
        # Ветка if — для других ОС, else — для Windows.
        elif branch is False:
            # Нужные ветки: только else.
            statements = list(node.orelse)
        # Условие не про ОС — обе ветки.
        else:
            # Само условие может содержать строки и вызовы.
            self.visit(node.test)
            # Обе ветки.
            statements = node.body + node.orelse
        # Входим в «необязательный» контекст.
        self._optional_depth += 1
        # Обходим выбранные ветки.
        for statement in statements:
            self.visit(statement)
        # Выходим из контекста.
        self._optional_depth -= 1

    def visit_Call(self, node: ast.Call) -> None:
        """importlib.import_module("x") и __import__("x") — динамические импорты."""
        # Имя вызываемой функции.
        func = node.func
        # Получаем имя: import_module / __import__.
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else ""
        # Первый аргумент — строковая константа.
        if name in ("import_module", "__import__") and node.args:
            # Аргумент.
            first = node.args[0]
            # Строка, не относительный путь.
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value and not first.value.startswith("."):
                # Динамические импорты считаем необязательными, но запоминаем для --hidden-import.
                self.found.append((first.value, True, True))
        # Обходим вложенные узлы (аргументы и т.п.).
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        """Строковые константы — кандидаты в пути к файлам ресурсов."""
        # Короткие однострочные строки.
        if isinstance(node.value, str) and 0 < len(node.value) <= 260 and "\n" not in node.value:
            self.strings.append(node.value)


class ImportScanner:
    """
    Сканер проекта: находит все импорты (рекурсивно по модулям проекта) и ресурсы.

    Ничего не запускает — только читает код через ast, поэтому полностью безопасен.
    """

    def __init__(self, script_path: Path, max_files: int = MAX_SCANNED_FILES) -> None:
        # Главный файл (абсолютный путь).
        self.script_path = script_path.resolve()
        # Папка проекта — папка главного файла.
        self.project_dir = self.script_path.parent
        # Ограничение на число файлов.
        self.max_files = max_files

    def scan(self) -> ScanResult:
        """Просканировать главный файл и все модули проекта, которые он использует."""
        # Итоговый результат.
        result = ScanResult()
        # Очередь файлов на сканирование.
        queue: list[Path] = [self.script_path]
        # Уже просмотренные файлы.
        seen: set[Path] = set()
        # Все найденные строки (для поиска ресурсов).
        strings: list[str] = []
        # Пока есть файлы и не превышен лимит.
        while queue and len(seen) < self.max_files:
            # Берём следующий файл.
            path = queue.pop(0)
            # Уже сканировали — пропускаем.
            if path in seen:
                continue
            # Отмечаем как просмотренный.
            seen.add(path)
            # Сканируем файл (ошибки второстепенных файлов — только предупреждения).
            visitor = self._scan_file(path, result, is_main=(path == self.script_path))
            # Файл не удалось разобрать.
            if visitor is None:
                continue
            # Запоминаем файл.
            result.scanned_files.append(path)
            # Копим строки.
            strings.extend(visitor.strings)
            # Короткое имя файла для отчёта.
            short = self._relative(path)
            # Разбираем каждый найденный импорт.
            for dotted, optional, dynamic in visitor.found:
                # Имя верхнего уровня.
                top = dotted.split(".")[0]
                # Пустые имена пропускаем.
                if not top:
                    continue
                # Модуль проекта?
                local_files = self._local_targets(top)
                # Да — добавляем его файлы в очередь и идём дальше.
                if local_files is not None:
                    # Запоминаем имя модуля проекта.
                    result.local_modules.add(top)
                    # Динамический импорт своего модуля тоже нужен PyInstaller как hidden-import.
                    if dynamic:
                        info = result.imports.setdefault(top, ImportInfo(name=top))
                        info.dotted.add(dotted)
                        info.dynamic = True
                    # Добавляем файлы модуля в очередь.
                    queue.extend(f for f in local_files if f not in seen)
                    # К следующему импорту.
                    continue
                # Внешний модуль — обновляем сведения о нём.
                info = result.imports.setdefault(top, ImportInfo(name=top))
                # Полный путь импорта.
                info.dotted.add(dotted)
                # Обязательный, если хоть раз импортирован обязательно.
                info.required = info.required or not optional
                # Динамический, если хоть раз импортирован динамически.
                info.dynamic = info.dynamic or dynamic
                # Статический, если хоть раз импортирован обычным import.
                info.static = info.static or not dynamic
                # Файл, где встречается импорт.
                info.files.add(short)
        # Предупреждаем, если упёрлись в лимит.
        if queue:
            result.warnings.append(f"Проект очень большой: просканированы первые {self.max_files} файлов.")
        # Ищем ресурсы.
        result.data_entries = self._detect_data(strings, result)
        # Готово.
        return result

    # ------------------------------------------------------------------ #

    def _relative(self, path: Path) -> str:
        """Путь относительно папки проекта (для красивого лога)."""
        # Пробуем сделать относительный путь.
        try:
            return path.relative_to(self.project_dir).as_posix()
        # Файл вне проекта — показываем как есть.
        except ValueError:
            return str(path)

    def _scan_file(self, path: Path, result: ScanResult, is_main: bool) -> Optional[_ImportVisitor]:
        """Разобрать один файл. Для главного файла ошибки фатальны, для остальных — предупреждения."""
        # Чтение и разбор могут упасть.
        try:
            # Читаем исходник с правильной кодировкой.
            source, _encoding = read_source(path)
            # Строим дерево кода.
            tree = ast.parse(source, filename=str(path))
        # Ошибка в главном файле — пробрасываем (её обработает этап анализа).
        except (SyntaxError, UnicodeDecodeError, CompilerError, OSError) as exc:
            # Главный файл обязан читаться.
            if is_main:
                raise
            # Для модулей проекта — только предупреждение.
            line = getattr(exc, "lineno", None)
            # Номер строки, если известен.
            where = f" (строка {line})" if line else ""
            # Запоминаем предупреждение.
            result.warnings.append(f"Не удалось разобрать файл {self._relative(path)}{where}: {exc}")
            # Сигнал «файл пропущен».
            return None
        # Обходим дерево.
        visitor = _ImportVisitor()
        # Запускаем обход.
        visitor.visit(tree)
        # Возвращаем собранное.
        return visitor

    def _local_targets(self, name: str) -> Optional[list[Path]]:
        """
        Является ли имя модулем проекта. Возвращает список файлов модуля (возможно, пустой)
        или None, если это внешний модуль.
        """
        # Папка проекта.
        base = self.project_dir
        # Отдельный файл name.py / name.pyw рядом с главным.
        for suffix in (".py", ".pyw"):
            # Кандидат.
            candidate = base / f"{name}{suffix}"
            # Нашли файл.
            if candidate.is_file():
                return [candidate.resolve()]
        # Папка-пакет name/ рядом с главным.
        package = base / name
        # Папка существует и не служебная.
        if package.is_dir() and name.lower() not in IGNORED_DIR_NAMES:
            # Все .py-файлы внутри (кроме служебных папок).
            files = [
                f.resolve() for f in package.rglob("*.py")
                if not any(part.lower() in IGNORED_DIR_NAMES for part in f.relative_to(base).parts[:-1])
            ]
            # Есть хоть один .py — это пакет проекта.
            if files:
                return files[: self.max_files]
        # Скомпилированный модуль name.pyd / name.cp312-win_amd64.pyd рядом.
        if any(base.glob(f"{name}.*pyd")) or (base / f"{name}.pyd").is_file():
            return []
        # Это внешний модуль.
        return None

    def _detect_data(self, strings: list[str], result: ScanResult) -> list[DataEntry]:
        """Найти файлы и папки с ресурсами: по строкам в коде и по типичным именам папок."""
        # Папка проекта (абсолютный путь).
        base = self.project_dir
        # Кандидаты: путь → причина.
        found: dict[Path, str] = {}
        # 1. Пути, упомянутые в коде.
        for text in strings:
            # Пытаемся превратить строку в путь внутри проекта.
            path = self._string_to_path(text, result)
            # Подходит — запоминаем.
            if path is not None and path not in found:
                found[path] = f"упоминается в коде: «{text}»"
        # 2. Типичные папки с ресурсами.
        try:
            # Перебираем содержимое папки проекта.
            for child in base.iterdir():
                # Папка с «говорящим» именем, не пакет Python.
                if child.is_dir() and child.name.lower() in DATA_DIR_NAMES and not (child / "__init__.py").exists():
                    # Добавляем, если ещё нет.
                    found.setdefault(child.resolve(), "типичная папка с ресурсами")
        # Нет доступа к папке — пропускаем этот шаг.
        except OSError:
            pass
        # Сначала короткие пути (папки верхнего уровня), чтобы не дублировать вложенные файлы.
        ordered = sorted(found.items(), key=lambda item: (len(item[0].parts), str(item[0]).lower()))
        # Итоговый список.
        entries: list[DataEntry] = []
        # Уже добавленные папки.
        added_dirs: list[Path] = []
        # Перебираем кандидатов.
        for path, reason in ordered:
            # Внутри уже добавленной папки — пропускаем.
            if any(_is_relative_to(path, folder) for folder in added_dirs):
                continue
            # Путь относительно проекта.
            relative = path.relative_to(base)
            # Папка — копируем в папку с тем же относительным путём.
            if path.is_dir():
                # Добавляем запись.
                entries.append(DataEntry(source=path, dest=relative.as_posix(), reason=reason))
                # Запоминаем папку.
                added_dirs.append(path)
            # Файл — копируем в его родительскую папку («.» для корня).
            else:
                # Родительская папка.
                parent = relative.parent.as_posix()
                # Добавляем запись.
                entries.append(DataEntry(source=path, dest=parent if parent not in ("", ".") else ".", reason=reason))
        # Готово.
        return entries

    def _string_to_path(self, text: str, result: ScanResult) -> Optional[Path]:
        """Превратить строку из кода в путь к ресурсу внутри проекта (или None)."""
        # Убираем пробелы по краям.
        value = text.strip()
        # Пустые строки, адреса сайтов, флаги командной строки и шаблоны — не пути.
        if not value or "://" in value or value.startswith(("-", "%", "{", "<")):
            return None
        # Символы, недопустимые в путях Windows.
        if any(ch in value for ch in '<>"|?*\x00'):
            return None
        # Строка «.» или «./» — это папка проекта целиком, её не добавляем.
        if value.strip("./\\") == "":
            return None
        # Превращаем в путь.
        raw = Path(value)
        # Абсолютные пути проверяем отдельно.
        candidate = raw if raw.is_absolute() else self.project_dir / raw
        # Проверка существования может упасть на «странных» строках.
        try:
            # Нормализуем путь.
            resolved = candidate.resolve()
            # Не существует — не ресурс.
            if not resolved.exists():
                return None
        # Некорректный путь.
        except (OSError, ValueError, RuntimeError):
            return None
        # Путь вне проекта.
        if not _is_relative_to(resolved, self.project_dir):
            # Абсолютный путь на файл — предупредим: на другом компьютере его не будет.
            if raw.is_absolute() and value not in result.external_paths:
                result.external_paths.append(value)
            # Не добавляем.
            return None
        # Сама папка проекта или главный файл — не ресурс.
        if resolved == self.project_dir or resolved == self.script_path:
            return None
        # Файлы с кодом PyInstaller соберёт сам.
        if resolved.is_file() and resolved.suffix.lower() in CODE_SUFFIXES:
            return None
        # Части пути относительно проекта.
        parts = resolved.relative_to(self.project_dir).parts
        # Внутри служебных папок — пропускаем.
        if any(part.lower() in IGNORED_DIR_NAMES for part in parts):
            return None
        # Папка-пакет Python — это код, а не ресурс.
        if resolved.is_dir() and (resolved / "__init__.py").exists():
            return None
        # Это ресурс.
        return resolved


# ====================================================================== #
#   ПЕРЕВОДЧИК ЛОГА PYINSTALLER                                            #
# ====================================================================== #

# Фазы сборки: (фраза в логе, понятный статус, доля прогресса этапа).
_PYINSTALLER_PHASES: list[tuple[str, str, float]] = [
    ("PyInstaller:", "Запускаю упаковщик PyInstaller…", 0.02),
    ("Initializing module dependency graph", "Анализирую код и зависимости…", 0.05),
    ("Analyzing ", "Анализирую код и зависимости…", 0.10),
    ("module hook", "Подключаю специальные правила для библиотек…", 0.35),
    ("Looking for ctypes DLLs", "Ищу системные библиотеки (DLL)…", 0.50),
    ("Looking for dynamic libraries", "Ищу системные библиотеки (DLL)…", 0.55),
    ("Building PYZ", "Упаковываю модули Python…", 0.70),
    ("Building PKG", "Собираю пакет с данными…", 0.80),
    ("Building EXE", "Создаю .exe-файл…", 0.88),
    ("Copying icon", "Встраиваю иконку…", 0.90),
    ("Building COLLECT", "Собираю папку с программой…", 0.95),
    ("Build complete", "Сборка завершена!", 1.00),
]

# Шаблон начала строки лога PyInstaller: «12345 INFO: », «678 WARNING: ».
_PYI_PREFIX_RE = re.compile(r"^\d+\s+(INFO|WARNING|ERROR|DEBUG|CRITICAL):\s*")
# Повторяющиеся префиксы без времени: PyInstaller сам печатает «ERROR: ERROR: …» для фатальных ошибок.
_PYI_BARE_PREFIX_RE = re.compile(r"^(?:(ERROR|CRITICAL|WARNING):\s*)+")


class _PyInstallerLogTranslator:
    """Превращает лог PyInstaller в понятные шаги, статус и движение полосы прогресса."""

    def __init__(self, bus: EventBus, report: Callable[[float], None]) -> None:
        # Шина событий.
        self.bus = bus
        # Колбэк прогресса (доля этапа упаковки).
        self.report = report
        # Уже объявленные фазы (чтобы не повторять одно и то же).
        self._announced: set[str] = set()
        # Максимальная достигнутая доля (полоса не должна ехать назад).
        self._progress = 0.0

    def __call__(self, line: str) -> None:
        """Обработать одну строку лога."""
        # Уровень строки по префиксу PyInstaller.
        match = _PYI_PREFIX_RE.match(line)
        # Уровень («INFO», «ERROR» …) или пусто.
        level = match.group(1) if match else ""
        # Текст без технического префикса.
        text = line[match.end():] if match else line
        # Убираем повторяющиеся «ERROR: ERROR:» в начале текста.
        bare = _PYI_BARE_PREFIX_RE.match(text)
        # Префикс найден — запоминаем уровень (если его ещё нет) и отрезаем префикс.
        if bare:
            # Уровень из префикса без времени.
            level = level or bare.group(1)
            # Чистый текст ошибки.
            text = text[bare.end():] or text
        # Ищем фазу сборки.
        for marker, status, fraction in _PYINSTALLER_PHASES:
            # Фраза есть в строке.
            if marker in text:
                # Новая фаза — объявляем её один раз.
                if status not in self._announced:
                    # Запоминаем.
                    self._announced.add(status)
                    # Статус в окне.
                    self.bus.status(status)
                    # Понятная строка в лог.
                    self.bus.info(status)
                # Полоса только вперёд.
                if fraction > self._progress:
                    # Запоминаем новое значение.
                    self._progress = fraction
                    # Двигаем полосу.
                    self.report(fraction)
                # Одной фазы достаточно.
                break
        # Ошибки — красным.
        if level in ("ERROR", "CRITICAL") or text.startswith(("Traceback", "Error", "ERROR")):
            self.bus.log(text, LogLevel.ERROR)
        # Всё остальное (включая многочисленные WARNING) — серым, чтобы не пугать.
        else:
            self.bus.debug(text)


# ====================================================================== #
#   КОНВЕЙЕР СБОРКИ                                                       #
# ====================================================================== #

class BuildPipeline:
    """Последовательно выполняет этапы сборки и сообщает о ходе работы в EventBus."""

    # Этапы: номер → (название, доля общей полосы прогресса).
    STAGES: dict[int, tuple[str, float]] = {
        1: ("Анализ кода", 0.05),
        2: ("Подготовка встроенного Python", 0.30),
        3: ("Загрузка библиотек", 0.25),
        4: ("Упаковка в .exe", 0.40),
    }

    def __init__(self, settings: BuildSettings, bus: EventBus, runtime: Optional[PythonRuntime] = None) -> None:
        # Сохраняем настройки сборки.
        self.settings = settings
        # Сохраняем шину событий.
        self.bus = bus
        # Встроенный Python (можно подменить в тестах).
        self.runtime = runtime or PythonRuntime()
        # Флажок отмены.
        self._cancel = CancelToken()
        # Начало текущего этапа на общей полосе прогресса.
        self._stage_start = 0.0
        # Ширина текущего этапа на полосе.
        self._stage_span = 0.0

    def cancel(self) -> None:
        """Отменить сборку (вызывается из окна, например при закрытии программы)."""
        # Поднимаем флаг и убиваем запущенные процессы.
        self._cancel.cancel()

    # ------------------------------------------------------------------ #
    #   Точка входа фонового потока                                       #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Запустить все этапы. Этот метод НИКОГДА не выбрасывает исключения наружу."""
        # Запоминаем время старта.
        started = time.perf_counter()
        # Внешний try-except — последняя линия обороны от любых сбоев.
        try:
            # Сбрасываем прогресс-бар в ноль.
            self.bus.progress(0.0)
            # Этап 1: анализ кода и сканирование импортов.
            analysis = self._run_stage(1, self._stage_analyze)
            # Этап 2: портативный Python.
            self._run_stage(2, self._stage_prepare_runtime)
            # Этап 3: библиотеки.
            self._run_stage(3, lambda: self._stage_install_libraries(analysis))
            # Этап 4: упаковка.
            exe_path = self._run_stage(4, lambda: self._stage_build(analysis))
            # Длительность сборки.
            elapsed = time.perf_counter() - started
            # Зелёная итоговая строка.
            self.bus.success(f"Готово! Сборка заняла {_format_duration(elapsed)}. Файл: {exe_path}")
            # Сигнал окну: показать кнопку «Открыть папку».
            self.bus.finished(True, str(exe_path), "Программа успешно собрана!")
        # Пользователь отменил сборку — это не ошибка.
        except BuildCancelled:
            # Жёлтая строка.
            self.bus.warning("Сборка отменена.")
            # Сигнал окну.
            self.bus.finished(False, None, "Сборка отменена.")
        # Понятная ошибка одного из этапов — показываем её пользователю.
        except CompilerError as exc:
            # Красная строка в лог.
            self.bus.log(f"Ошибка: {exc.title}. {exc.message}", LogLevel.ERROR)
            # Красное окно с описанием.
            self.bus.error(exc.title, exc.message, exc.hint, exc.details)
            # Сообщаем окну, что сборка завершилась неудачно.
            self.bus.finished(False, None, "Сборка остановлена из-за ошибки.")
        # Совсем непредвиденная ситуация.
        except BaseException as exc:  # noqa: BLE001 — ловим вообще всё, чтобы поток не «умер» молча
            # Переводим ошибку на понятный язык.
            err = describe_exception(exc, "Сборка")
            # Красное окно.
            self.bus.error(err.title, err.message, err.hint, err.details or format_traceback(exc))
            # Сообщаем о завершении.
            self.bus.finished(False, None, "Сборка остановлена из-за ошибки.")

    # ------------------------------------------------------------------ #
    #   Защитная обёртка для каждого этапа                                #
    # ------------------------------------------------------------------ #

    def _run_stage(self, number: int, func: Callable[[], T]) -> T:
        """Выполнить один этап с отдельной защитой от сбоев и обновлением прогресса."""
        # Название и вес этапа.
        title, weight = self.STAGES[number]
        # Начало этапа на полосе = сумма весов предыдущих этапов.
        self._stage_start = sum(w for n, (_t, w) in self.STAGES.items() if n < number)
        # Ширина этапа на полосе.
        self._stage_span = weight
        # Перед началом этапа проверяем отмену.
        self._cancel.raise_if_cancelled()
        # Пишем в лог «Шаг N: …» и обновляем статус.
        self.bus.step(number, title)
        # Ставим полосу в начало этапа.
        self.bus.progress(self._stage_start)
        # Индивидуальный try-except для этапа.
        try:
            # Выполняем сам этап.
            result = func()
        # Понятные ошибки и отмену пробрасываем без изменений.
        except (CompilerError, BuildCancelled):
            raise
        # Любая другая ошибка — переводим на понятный язык с указанием этапа.
        except Exception as exc:  # noqa: BLE001
            raise describe_exception(exc, title) from exc
        # Этап прошёл — полоса в конец этапа.
        self.bus.progress(self._stage_start + self._stage_span)
        # Возвращаем результат этапа.
        return result

    def _sub(self, fraction: float) -> None:
        """Сообщить прогресс внутри текущего этапа (0..1)."""
        # Зажимаем долю в диапазон 0..1.
        fraction = max(0.0, min(1.0, fraction))
        # Переводим в общую полосу.
        self.bus.progress(self._stage_start + self._stage_span * fraction)

    # ------------------------------------------------------------------ #
    #   Этап 1 — анализ кода                                              #
    # ------------------------------------------------------------------ #

    def _stage_analyze(self) -> AnalysisResult:
        """Проверить главный файл и иконку, проверить синтаксис, найти импорты и ресурсы."""
        # Короткое имя для удобства.
        script = self.settings.script_path
        # Сообщаем, какой файл анализируем.
        self.bus.info(f"Проверяю файл: {script.name}")
        # Файл должен существовать.
        if not script.is_file():
            raise CompilerError(
                title="Файл не найден",
                message=f"Главный файл программы не найден:\n{script}",
                hint="Выберите файл заново кнопкой «Выбрать главный файл программы».",
            )
        # Расширение должно быть .py или .pyw.
        if script.suffix.lower() not in SCRIPT_EXTENSIONS:
            raise CompilerError(
                title="Неподходящий тип файла",
                message=f"Файл «{script.name}» не похож на Python-скрипт.",
                hint="Выберите файл с расширением .py или .pyw.",
            )
        # Читаем исходный код с автоматическим определением кодировки.
        source, encoding = read_source(script)
        # Считаем количество строк.
        line_count = len(source.splitlines())
        # Сообщаем о результатах чтения.
        self.bus.info(f"Файл прочитан. Строк кода: {line_count}, кодировка: {encoding}.")
        # Пустой файл — предупреждаем, но не останавливаемся.
        if not source.strip():
            self.bus.warning("Файл пустой — готовая программа ничего не будет делать.")
        # Проверяем синтаксис: compile() найдёт опечатки, не запуская код.
        self.bus.info("Проверяю код на ошибки…")
        # SyntaxError отсюда будет переведён в понятное сообщение в _run_stage.
        compile(source, str(script), "exec", dont_inherit=True)
        # Синтаксис в порядке.
        self.bus.success("Ошибок в коде не найдено.")
        # Прогресс внутри этапа.
        self._sub(0.3)

        # Сканируем импорты и ресурсы.
        self.bus.info("Ищу используемые библиотеки и файлы ресурсов…")
        # Запускаем сканер.
        scan = ImportScanner(script).scan()
        # Выводим отчёт.
        _log_scan_report(self.bus, scan, compiler_stdlib_names())
        # Прогресс внутри этапа.
        self._sub(0.8)

        # Проверка иконки.
        if self.settings.icon_path is not None:
            # Проверяем формат.
            validate_icon(self.settings.icon_path)
            # Иконка подходит.
            self.bus.success(f"Иконка подходит: {self.settings.icon_path.name}")
        # Иконка не выбрана.
        else:
            self.bus.info("Иконка не выбрана — будет использована стандартная.")
        # Режимы сборки простым языком.
        console_text = "без чёрного окна консоли" if self.settings.hide_console else "с окном консоли"
        # Один файл или папка.
        mode_text = "один .exe-файл" if self.settings.one_file else "папка с программой"
        # Итог настроек.
        self.bus.info(f"Режим сборки: {mode_text}, {console_text}.")
        # Возвращаем результат.
        return AnalysisResult(source=source, encoding=encoding, line_count=line_count, scan=scan)

    # ------------------------------------------------------------------ #
    #   Этап 2 — портативный Python                                       #
    # ------------------------------------------------------------------ #

    def _stage_prepare_runtime(self) -> None:
        """Скачать и настроить встроенный Python (только при первом запуске)."""
        # Вся логика — в PythonRuntime; передаём шину, отмену и прогресс этапа.
        self.runtime.ensure(self.bus, self._cancel, self._sub)

    # ------------------------------------------------------------------ #
    #   Этап 3 — библиотеки                                               #
    # ------------------------------------------------------------------ #

    def _stage_install_libraries(self, analysis: AnalysisResult) -> None:
        """Сверить импорты с runtime/ и установить недостающие библиотеки."""
        # Итог сканирования.
        scan = analysis.scan
        # Все внешние имена верхнего уровня.
        names = set(scan.imports)
        # Спрашиваем встроенный Python: что уже установлено и что входит в его stdlib.
        self.bus.info("Проверяю, какие библиотеки уже установлены…")
        # Запрос к встроенному Python.
        query = self.runtime.query_modules(names, self._cancel)
        # Stdlib встроенного Python (точнее, чем у компилятора); запасной вариант — свой список.
        stdlib = query.stdlib or compiler_stdlib_names()
        # Прогресс.
        self._sub(0.05)

        # Нужен ли tkinter.
        if needs_tkinter(names):
            # Объясняем.
            self.bus.info("Программа использует окна на tkinter — проверяю графические компоненты…")
            # Доставляем tkinter (0% → 30% этапа).
            self.runtime.ensure_tkinter(self.bus, self._cancel, lambda f: self._sub(0.05 + 0.25 * f))
        # Прогресс.
        self._sub(0.30)

        # Сторонние библиотеки.
        third_party = scan.third_party(stdlib)
        # Имена только из importlib.import_module("…") не ставим автоматически: это часто плагины
        # или опечатки, а установка неизвестного пакета из интернета небезопасна.
        for info in [i for i in third_party if not i.static]:
            self.bus.debug(f"Динамический импорт «{info.name}» не устанавливаю автоматически (будет передан как --hidden-import).")
        # Оставляем только обычные импорты.
        third_party = [info for info in third_party if info.static]
        # Уже установленные.
        installed = [info for info in third_party if info.name in query.found]
        # Недостающие.
        missing = [info for info in third_party if info.name not in query.found]
        # Сообщаем об уже установленных.
        if installed:
            self.bus.success("Уже установлены: " + ", ".join(info.name for info in installed))
        # Всё есть — этап завершён.
        if not missing:
            # Зелёная строка.
            self.bus.success("Все нужные библиотеки на месте.")
            # Готово.
            return

        # Группируем по pip-пакету (win32api и win32con → один pywin32).
        groups: dict[str, list[ImportInfo]] = {}
        # Заполняем группы.
        for info in missing:
            groups.setdefault(info.pip_name, []).append(info)
        # Сообщаем план.
        self.bus.info("Нужно скачать: " + ", ".join(groups))
        # Количество пакетов.
        total = len(groups)
        # Устанавливаем по одному — так пользователь видит имя каждой библиотеки.
        for index, (requirement, infos) in enumerate(groups.items()):
            # Начало и ширина отрезка полосы для этого пакета.
            start = 0.30 + 0.65 * index / total
            # Ширина отрезка.
            span = 0.65 / total
            # Установка может упасть.
            try:
                # Тихая установка с живым статусом.
                self.runtime.pip_install(
                    requirement,
                    bus=self.bus,
                    cancel=self._cancel,
                    display_name=requirement,
                    on_fraction=lambda f, s=start, w=span: self._sub(s + w * f),
                )
            # pip завершился с ошибкой.
            except ProcessFailedError:
                # Все импорты этого пакета необязательные — пропускаем с предупреждением.
                if all(info.optional for info in infos):
                    self.bus.warning(f"Необязательная библиотека «{requirement}» не установилась — продолжаю без неё.")
                    # К следующему пакету.
                    continue
                # Обязательная — ошибка (errors.py разберёт вывод pip).
                raise

        # Повторная проверка: всё ли теперь импортируется.
        recheck = self.runtime.query_modules([info.name for info in missing], self._cancel)
        # Перебираем недостающие.
        for info in missing:
            # Установилось — отлично.
            if info.name in recheck.found:
                continue
            # Необязательные — только предупреждение.
            if info.optional:
                self.bus.warning(f"Модуль «{info.name}» недоступен (импорт необязательный) — программа должна работать и без него.")
                # Дальше.
                continue
            # Обязательный модуль так и не появился.
            raise CompilerError(
                title="Библиотека не подключается",
                message=f"Пакет «{info.pip_name}» установлен, но модуль «{info.name}» в нём не найден.",
                hint=(
                    "Скорее всего, имя пакета в pip отличается от имени в import. "
                    "Если «{0}» — ваш собственный модуль, положите файл {0}.py рядом с главным файлом.".format(info.name)
                ),
            )
        # Итог этапа.
        self.bus.success("Все библиотеки установлены.")

    # ------------------------------------------------------------------ #
    #   Этап 4 — упаковка в .exe                                          #
    # ------------------------------------------------------------------ #

    def _stage_build(self, analysis: AnalysisResult) -> Path:
        """Установить PyInstaller (если нужно) и собрать .exe. Вернуть путь к готовому файлу."""
        # Настройки для краткости.
        settings = self.settings
        # Папка проекта.
        project_dir = settings.script_path.resolve().parent

        # --- 1. PyInstaller во встроенном Python ---
        if "PyInstaller" in self.runtime.query_modules(["PyInstaller"], self._cancel).found:
            # Уже есть.
            self.bus.success("Упаковщик PyInstaller уже установлен.")
        # Нет — ставим.
        else:
            # Сообщаем.
            self.bus.info("Устанавливаю упаковщик PyInstaller во встроенный Python…")
            # Тихая установка (0% → 25% этапа).
            self.runtime.pip_install(
                PYINSTALLER_REQUIREMENT,
                bus=self.bus,
                cancel=self._cancel,
                display_name="PyInstaller",
                on_fraction=lambda f: self._sub(0.25 * f),
            )
        # Прогресс.
        self._sub(0.25)

        # --- 2. Пути ---
        app_name = safe_app_name(settings.script_path.stem)
        # Папка результата.
        output_dir = resolve_output_dir(project_dir)
        # Временная папка сборки (уникальная для проекта).
        fingerprint = hashlib.sha1(str(settings.script_path.resolve()).lower().encode("utf-8")).hexdigest()[:8]
        # Путь временной папки.
        work_dir = user_data_dir() / "build" / f"{app_name}-{fingerprint}"
        # Начинаем с чистой временной папки.
        _recreate_dir(work_dir)
        # Имя готового файла.
        exe_name = app_name + (".exe" if IS_WINDOWS else "")
        # Ожидаемый путь к .exe.
        expected = output_dir / exe_name if settings.one_file else output_dir / app_name / exe_name
        # Удаляем результат прошлой сборки (и проверяем, что старая версия не запущена).
        _remove_previous_build(output_dir, app_name, exe_name, settings.one_file)

        # --- 3. Команда PyInstaller ---
        args = self._pyinstaller_args(analysis.scan, app_name, output_dir, work_dir)
        # Показываем команду серым (для опытных пользователей).
        self.bus.debug("Команда: python -m PyInstaller " + " ".join(_quote(a) for a in args))

        # --- 4. Сборка ---
        self.bus.status("Упаковываю программу в .exe — это может занять несколько минут…")
        # Запуск PyInstaller с переводчиком лога (25% → 98% этапа).
        self.runtime.run_python(
            ["-m", "PyInstaller", *args],
            description="Упаковка в .exe (PyInstaller)",
            kind="pyinstaller",
            on_line=_PyInstallerLogTranslator(self.bus, lambda f: self._sub(0.25 + 0.73 * f)),
            cancel=self._cancel,
            timeout=3600,
            cwd=project_dir,
        )

        # --- 5. Проверка результата ---
        if not expected.is_file():
            raise CompilerError(
                title="Готовый файл не найден",
                message=f"PyInstaller завершился без ошибок, но файл не появился:\n{expected}",
                hint="Скорее всего, его сразу удалил антивирус. Добавьте папку «{}» в исключения и соберите снова.".format(OUTPUT_DIR_NAME),
            )
        # Размер готового файла.
        self.bus.success(f"Создан файл {expected.name} ({format_size(expected.stat().st_size)}).")
        # Убираем временные файлы (ошибки не важны).
        shutil.rmtree(work_dir, ignore_errors=True)
        # Возвращаем путь.
        return expected

    def _pyinstaller_args(self, scan: ScanResult, app_name: str, output_dir: Path, work_dir: Path) -> list[str]:
        """Сформировать аргументы PyInstaller с учётом галочек и найденных зависимостей."""
        # Настройки для краткости.
        settings = self.settings
        # Папка проекта.
        project_dir = settings.script_path.resolve().parent
        # Базовые аргументы: без вопросов, имя, папки результата и временных файлов.
        args = [
            "--noconfirm",
            "--log-level", "INFO",
            "--name", app_name,
            "--distpath", str(output_dir),
            "--workpath", str(work_dir / "build"),
            "--specpath", str(work_dir),
            "--paths", str(project_dir),
        ]
        # Галочка «один файл».
        if settings.one_file:
            # Один .exe.
            args.append("--onefile")
            # Сообщаем.
            self.bus.info("Флаг --onefile: всё будет упаковано в один .exe-файл.")
        # Режим папки.
        else:
            # Файлы рядом с .exe (без подпапки _internal) — проще для относительных путей.
            args += ["--onedir", "--contents-directory", "."]
            # Сообщаем.
            self.bus.info("Режим папки: .exe и его файлы будут лежать в одной папке.")
        # Галочка «скрыть консоль».
        if settings.hide_console:
            # Без чёрного окна.
            args.append("--noconsole")
            # Сообщаем.
            self.bus.info("Флаг --noconsole: чёрное окно консоли будет скрыто.")
        # Иконка.
        if settings.icon_path is not None:
            # Абсолютный путь к иконке.
            args.append(f"--icon={settings.icon_path.resolve()}")
            # Сообщаем.
            self.bus.info(f"Флаг --icon: {settings.icon_path.name}")
        # Ресурсы.
        for entry in scan.data_entries:
            # «источник;назначение» (в Windows разделитель — точка с запятой).
            args += ["--add-data", f"{entry.source}{os.pathsep}{entry.dest}"]
            # Сообщаем.
            self.bus.info(f"Флаг --add-data: {entry.source.name}{'/' if entry.is_dir else ''} → {entry.dest}")
        # Особые правила для сложных библиотек.
        for name in sorted(scan.imports):
            # Правило для библиотеки.
            rule = COLLECT_RULES.get(name)
            # Есть правило — добавляем.
            if rule:
                args += rule
                # Сообщаем.
                self.bus.info(f"Библиотека {name}: добавляю {' '.join(rule)}")
        # Динамические импорты PyInstaller сам не видит — подсказываем.
        for dotted in scan.dynamic_imports:
            # Скрытый импорт.
            args += ["--hidden-import", dotted]
            # Сообщаем.
            self.bus.info(f"Флаг --hidden-import: {dotted} (динамический импорт)")
        # Если есть ресурсы — runtime-хук, делающий относительные пути рабочими.
        if scan.data_entries:
            # Файл хука во временной папке.
            hook = work_dir / "autocompiler_rthook.py"
            # Записываем код хука.
            hook.write_text(RUNTIME_HOOK_CODE, encoding="utf-8")
            # Подключаем хук.
            args += ["--runtime-hook", str(hook)]
        # Главный файл — последним аргументом.
        args.append(str(settings.script_path.resolve()))
        # Готово.
        return args


# ====================================================================== #
#   ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ МОДУЛЯ                                        #
# ====================================================================== #

def read_source(path: Path) -> tuple[str, str]:
    """Прочитать .py-файл, правильно определив кодировку. Вернуть (текст, кодировка)."""
    # Сначала пробуем стандартный способ Python (учитывает BOM и «# -*- coding -*-»).
    try:
        # tokenize.open возвращает текстовый файл с уже определённой кодировкой.
        with tokenize.open(str(path)) as handle:
            # Читаем весь текст и запоминаем кодировку.
            return handle.read(), handle.encoding
    # Кодировка не UTF-8 и не указана в файле — пробуем популярные в России cp1251 и cp866.
    except (SyntaxError, UnicodeDecodeError) as exc:
        # Запоминаем исходную ошибку.
        original_error = exc
        # Читаем «сырые» байты файла.
        raw = path.read_bytes()
        # Перебираем запасные кодировки.
        for encoding in ("cp1251", "cp866"):
            # Пробуем декодировать.
            try:
                # Успех — возвращаем текст (заменяя \r\n на \n, как это делает Python).
                return raw.decode(encoding).replace("\r\n", "\n"), encoding
            # Не подошла — следующая.
            except UnicodeDecodeError:
                continue
        # Ни одна кодировка не подошла.
        raise CompilerError(
            title="Не удалось прочитать текст файла",
            message=f"Файл «{path.name}» сохранён в неизвестной кодировке.",
            hint="Откройте файл в редакторе (например, Блокноте) и сохраните его в кодировке UTF-8.",
        ) from original_error


def validate_icon(icon: Path) -> None:
    """Убедиться, что иконка существует и является настоящим .ico-файлом."""
    # Файл должен существовать.
    if not icon.is_file():
        raise CompilerError(
            title="Иконка не найдена",
            message=f"Файл иконки не найден:\n{icon}",
            hint="Выберите иконку заново или уберите её, чтобы использовать стандартную.",
        )
    # Первые 4 байта файла.
    with icon.open("rb") as handle:
        header = handle.read(4)
    # Не .ico (например, переименованный .png).
    if header != ICO_MAGIC:
        raise CompilerError(
            title="Неподходящий файл иконки",
            message=f"Файл «{icon.name}» не является настоящей иконкой .ico.",
            hint="Похоже, это картинка с переименованным расширением. Сконвертируйте её в .ico любым онлайн-конвертером.",
        )


def safe_app_name(stem: str) -> str:
    """Безопасное имя программы для Windows (без запрещённых символов и зарезервированных имён)."""
    # Заменяем запрещённые символы на подчёркивание.
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .")
    # Пустое имя — подставляем стандартное.
    if not name:
        name = "Program"
    # Зарезервированные имена устройств Windows (CON, NUL, COM1…) — добавляем суффикс.
    if re.fullmatch(r"(?i)(con|prn|aux|nul|com\d|lpt\d)", name):
        name += "_app"
    # Готово.
    return name


def resolve_output_dir(project_dir: Path) -> Path:
    """Папка для готовой программы: рядом с главным файлом, а если там нельзя писать — в профиле."""
    # Предпочтительная папка.
    preferred = project_dir / OUTPUT_DIR_NAME
    # Можно писать — используем.
    if is_dir_writable(preferred):
        return preferred
    # Запасная папка в профиле пользователя.
    fallback = Path.home() / "AutoCompiler" / OUTPUT_DIR_NAME / project_dir.name
    # Можно писать — используем.
    if is_dir_writable(fallback):
        return fallback
    # Писать некуда.
    raise CompilerError(
        title="Некуда сохранить программу",
        message=f"Нет прав на запись ни в папку проекта, ни в папку пользователя:\n{preferred}",
        hint="Скопируйте проект в обычную папку (например, «Документы») и соберите снова.",
    )


def _remove_previous_build(output_dir: Path, app_name: str, exe_name: str, one_file: bool) -> None:
    """Удалить результат прошлой сборки; если он занят (программа запущена) — понятная ошибка."""
    # Что удаляем: один файл или папку программы.
    target = output_dir / exe_name if one_file else output_dir / app_name
    # Нечего удалять.
    if not target.exists():
        return
    # Удаление может не получиться.
    try:
        # Папка — удаляем целиком.
        if target.is_dir():
            shutil.rmtree(target)
        # Файл — удаляем.
        else:
            target.unlink()
    # Файл занят — скорее всего, старая версия программы запущена.
    except PermissionError as exc:
        raise CompilerError(
            title="Старая версия программы ещё запущена",
            message=f"Не удаётся заменить прошлый результат сборки:\n{target}",
            hint=f"Закройте программу {exe_name} (проверьте и область уведомлений возле часов) и нажмите «Собрать .exe» снова.",
            details=format_traceback(exc),
        ) from exc


def _recreate_dir(path: Path) -> None:
    """Удалить папку (если есть) и создать заново пустой."""
    # Удаляем старое содержимое (ошибки игнорируем — PyInstaller перезапишет файлы).
    shutil.rmtree(path, ignore_errors=True)
    # Создаём папку.
    path.mkdir(parents=True, exist_ok=True)


def _log_scan_report(bus: EventBus, scan: ScanResult, stdlib: set[str]) -> None:
    """Вывести понятный отчёт о найденных импортах и ресурсах."""
    # Сторонние библиотеки.
    third_party = scan.third_party(stdlib)
    # Встроенные модули Python.
    builtin = sorted(name for name in scan.imports if name in stdlib)
    # Количество файлов.
    bus.info(f"Просканировано файлов проекта: {len(scan.scanned_files)}.")
    # Библиотеки найдены.
    if third_party:
        # Список «имя (pip: пакет)» — пакет показываем, только если он отличается.
        parts = [
            info.name + (f" (pip: {info.pip_name})" if info.pip_name.lower() != info.name.lower() else "")
            + ("" if info.required else " — необязательная")
            for info in third_party
        ]
        # Строка в лог.
        bus.success("Найдены библиотеки: " + ", ".join(parts))
    # Библиотек нет.
    else:
        bus.info("Сторонние библиотеки не используются.")
    # Встроенные модули — серым.
    if builtin:
        bus.debug("Встроенные модули Python: " + ", ".join(builtin))
    # Модули самого проекта.
    if scan.local_modules:
        bus.info("Модули вашего проекта: " + ", ".join(sorted(scan.local_modules)))
    # Ресурсы.
    for entry in scan.data_entries:
        # Папка или файл.
        kind = "папка" if entry.is_dir else "файл"
        # Строка в лог.
        bus.info(f"Ресурс ({kind}): {entry.dest if entry.is_dir else entry.source.name} — {entry.reason}")
    # Абсолютные пути вне проекта.
    for path in scan.external_paths:
        bus.warning(f"Код использует файл по абсолютному пути «{path}» — на другом компьютере его не будет.")
    # Предупреждения сканера.
    for warning in scan.warnings:
        bus.warning(warning)


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Path.is_relative_to для Python 3.8–3.9."""
    # relative_to выбрасывает ValueError, если путь снаружи.
    try:
        path.relative_to(parent)
        # Путь внутри.
        return True
    # Путь снаружи.
    except ValueError:
        return False


def _quote(arg: str) -> str:
    """Взять аргумент в кавычки, если в нём есть пробелы (для красивого показа команды)."""
    # Пробел внутри — кавычки нужны.
    return f'"{arg}"' if " " in arg else arg


def _format_duration(seconds: float) -> str:
    """Красиво записать длительность: 75 → «1 мин 15 сек»."""
    # Минуты и секунды.
    minutes, secs = divmod(int(round(seconds)), 60)
    # Есть минуты.
    if minutes:
        return f"{minutes} мин {secs} сек"
    # Только секунды.
    return f"{seconds:.1f} сек"
