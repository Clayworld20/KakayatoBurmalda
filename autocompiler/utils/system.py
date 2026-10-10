"""
Работа с операционной системой и встроенной («изолированной») средой Python.

Что здесь есть:
    • пути программы (папка программы, папка данных пользователя);
    • скрытый запуск внешних программ без чёрных окон с живым построчным выводом;
    • отмена сборки (CancelToken) с остановкой всего дерева процессов;
    • надёжное скачивание файлов: повторы, проверка размера и SHA-256, прогресс;
    • PythonRuntime — портативный Python в папке runtime/:
        1) скачивает официальный Windows Embeddable Package с python.org;
        2) распаковывает и правит файл pythonXY._pth (включает «import site»);
        3) скачивает get-pip.py и устанавливает pip;
        4) по требованию доставляет tkinter (в embeddable-версии его нет!);
        5) проверяет установленные модули и ставит недостающие библиотеки через pip;
    • открытие проводника с выделенным готовым .exe.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# hashlib — подсчёт SHA-256 для проверки целостности скачанных файлов.
import hashlib
# json — чтение каталога версий python.org и обмен данными со встроенным Python.
import json
# os — переменные окружения, атомарная замена файлов, открытие папок.
import os
# platform — определение архитектуры процессора (64/32 бита, ARM).
import platform
# re — разбор строк вывода pip («Progress 123 of 456»).
import re
# shutil — удаление папок и копирование содержимого файлов.
import shutil
# signal — сигнал SIGKILL для остановки группы процессов в Linux/macOS.
import signal
# subprocess — запуск внешних программ.
import subprocess
# sys — информация о текущем интерпретаторе и ОС.
import sys
# tempfile — проверка, можно ли писать в папку.
import tempfile
# threading — отмена и тайм-ауты процессов из другого потока.
import threading
# time — паузы между повторными попытками скачивания.
import time
# urllib.error — ошибки HTTP (404, 500…) при скачивании.
import urllib.error
# urllib.request — скачивание файлов по HTTPS без сторонних библиотек.
import urllib.request
# zipfile — распаковка архивов Python.
import zipfile
# deque — хранение последних N строк вывода процесса.
from collections import deque
# dataclass — короткие классы-контейнеры данных.
from dataclasses import dataclass, field
# datetime — отметка времени создания среды.
from datetime import datetime
# Path — удобная работа с путями.
from pathlib import Path
# Типы для подсказок.
from typing import Any, Callable, Iterable, Optional, Sequence

# Ошибки проекта.
from autocompiler.utils.errors import BuildCancelled, CompilerError, DownloadError, ProcessFailedError
# Шина событий (для живого статуса в окне).
from autocompiler.utils.event_bus import EventBus, LogLevel

# ====================================================================== #
#   ОБЩИЕ КОНСТАНТЫ                                                       #
# ====================================================================== #

# True, если программа работает в Windows.
IS_WINDOWS = sys.platform.startswith("win")
# True, если программа работает в macOS.
IS_MAC = sys.platform == "darwin"
# Имя папки приложения в профиле пользователя.
APP_FOLDER_NAME = "AutoCompiler"
# Заголовок User-Agent для HTTP-запросов (некоторые серверы не любят пустой).
USER_AGENT = "AutoCompiler/1.0 (+https://github.com/Clayworld20/KakayatoBurmalda)"
# Переменная окружения для разработчиков: путь к «готовому» Python вместо встроенного.
RUNTIME_OVERRIDE_ENV = "AUTOCOMPILER_RUNTIME_PYTHON"

# Тип функции-обработчика строк вывода процесса.
LineHandler = Callable[[str], None]
# Тип функции, сообщающей долю выполнения (0..1).
ProgressHandler = Callable[[float], None]


# ====================================================================== #
#   ПУТИ ПРОГРАММЫ                                                        #
# ====================================================================== #

def is_frozen() -> bool:
    """True, если компилятор сам запущен из собранного PyInstaller-файла Auto-Compiler.exe."""
    # PyInstaller выставляет sys.frozen = True внутри собранного приложения.
    return bool(getattr(sys, "frozen", False))


def frozen_bundle_dir() -> Optional[Path]:
    """Временная папка, куда собранный Auto-Compiler.exe распаковал свои библиотеки (или None)."""
    # sys._MEIPASS есть только внутри собранного приложения.
    bundle = getattr(sys, "_MEIPASS", None)
    # Возвращаем путь, если он есть.
    return Path(bundle) if bundle else None


def sanitize_frozen_environment() -> None:
    """
    Вернуть Windows стандартный порядок поиска DLL (только внутри собранного Auto-Compiler.exe).

    Загрузчик PyInstaller вызывает SetDllDirectoryW(<папка распаковки>), и эту настройку
    наследуют ВСЕ запускаемые нами программы. Встроенный Python, pip и PyInstaller тогда
    могли бы подхватить чужие (наши) копии DLL другой версии. Документация PyInstaller
    советует сбросить настройку вызовом SetDllDirectoryW(NULL) — что мы и делаем.
    Модули Python (.pyd) от этого не страдают: они ищут зависимости в своей папке.
    """
    # Нужно только в Windows и только в собранном .exe.
    if not (IS_WINDOWS and is_frozen()):
        return
    # Вызов WinAPI не должен ронять программу ни при каких условиях.
    try:
        # ctypes — прямой вызов функций Windows.
        import ctypes
        # NULL (None) — восстановить стандартный порядок поиска DLL.
        ctypes.windll.kernel32.SetDllDirectoryW(None)  # type: ignore[attr-defined]
    # Не получилось — работаем как есть.
    except Exception:  # noqa: BLE001
        pass


def program_root() -> Path:
    """Папка, где лежит сама программа (рядом с main.py или с собранным .exe компилятора)."""
    # Если компилятор сам собран в .exe — берём папку этого .exe.
    if is_frozen():
        return Path(sys.executable).resolve().parent
    # Иначе: этот файл лежит в autocompiler/utils/ — поднимаемся на два уровня вверх.
    return Path(__file__).resolve().parents[2]


def user_data_dir() -> Path:
    """Папка для служебных файлов пользователя (кэш загрузок, временные файлы сборки)."""
    # В Windows — %LOCALAPPDATA%\\AutoCompiler.
    if IS_WINDOWS:
        # Если переменной вдруг нет — собираем путь вручную.
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        # Возвращаем путь к папке приложения.
        return Path(base) / APP_FOLDER_NAME
    # В Linux/macOS — ~/.local/share/AutoCompiler (или XDG_DATA_HOME).
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    # Возвращаем путь к папке приложения.
    return Path(base) / APP_FOLDER_NAME


def is_dir_writable(path: Path) -> bool:
    """Проверить, можно ли создавать файлы в папке (создаёт папку при необходимости)."""
    # Любая ошибка означает «писать нельзя».
    try:
        # Создаём папку, если её ещё нет.
        path.mkdir(parents=True, exist_ok=True)
        # Пробуем создать и сразу удалить временный файл.
        with tempfile.NamedTemporaryFile(dir=str(path), prefix=".write-test-", delete=True):
            pass
        # Получилось — папка доступна для записи.
        return True
    # Нет прав, диск только для чтения и т.п.
    except OSError:
        return False


def shorten_path(path: str | Path, max_length: int = 70) -> str:
    """Сократить длинный путь, заменив середину на «…» (для красивого отображения)."""
    # Превращаем путь в строку.
    text = str(path)
    # Если путь и так короткий — возвращаем без изменений.
    if len(text) <= max_length:
        return text
    # Сколько символов оставить с каждой стороны (минус 1 символ на «…»).
    keep = (max_length - 1) // 2
    # Склеиваем начало, многоточие и конец.
    return f"{text[:keep]}…{text[-keep:]}"


def format_size(num_bytes: float) -> str:
    """Красиво записать размер: 1536 → «1.5 КБ»."""
    # Перебираем единицы измерения от меньшей к большей.
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        # Если число меньше 1024 — нашли подходящую единицу.
        if abs(num_bytes) < 1024:
            # Байты без дробной части, остальное — с одним знаком.
            return f"{num_bytes:.0f} {unit}" if unit == "Б" else f"{num_bytes:.1f} {unit}"
        # Переходим к следующей единице.
        num_bytes /= 1024
    # Очень большие размеры — в терабайтах.
    return f"{num_bytes:.1f} ТБ"


# ====================================================================== #
#   СКРЫТЫЙ ЗАПУСК ПРОЦЕССОВ                                              #
# ====================================================================== #

def hidden_subprocess_kwargs() -> dict[str, Any]:
    """Параметры для subprocess, которые прячут чёрное окно консоли в Windows."""
    # На других ОС прятать нечего — возвращаем пустой словарь.
    if not IS_WINDOWS:
        return {}
    # STARTUPINFO описывает, как Windows должна показать окно нового процесса.
    startupinfo = subprocess.STARTUPINFO()  # type: ignore[attr-defined]
    # Флаг «использовать поле wShowWindow» из STARTUPINFO.
    startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW  # type: ignore[attr-defined]
    # SW_HIDE = 0 — окно процесса скрыто.
    startupinfo.wShowWindow = 0
    # CREATE_NO_WINDOW не создаёт консоль вовсе (двойная защита).
    return {
        "startupinfo": startupinfo,
        "creationflags": subprocess.CREATE_NO_WINDOW,  # type: ignore[attr-defined]
    }


def _is_inside(path: Path, folder: Path) -> bool:
    """Лежит ли path внутри folder (сравнение без учёта регистра в Windows)."""
    # Сравнение путей может упасть на «кривых» значениях из PATH.
    try:
        # Нормализуем оба пути (регистр, разделители).
        child = os.path.normcase(os.path.abspath(str(path)))
        # Папка-контейнер.
        parent = os.path.normcase(os.path.abspath(str(folder)))
        # Совпадает или начинается с «папка + разделитель».
        return child == parent or child.startswith(parent.rstrip(os.sep) + os.sep)
    # Ошибку считаем «не внутри».
    except (OSError, ValueError):
        return False


def child_process_env(extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """
    «Чистые» переменные окружения для встроенного Python.

    Убираем всё, что может «подмешать» чужую установку Python пользователя,
    и включаем UTF-8 + небуферизованный вывод, чтобы лог шёл в реальном времени.
    """
    # Копия текущего окружения (саму os.environ не меняем).
    env = dict(os.environ)
    # Удаляем переменные, которые ломают изолированность среды.
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONSTARTUP", "PYTHONEXECUTABLE", "VIRTUAL_ENV", "PIP_TARGET", "PIP_PREFIX", "CONDA_PREFIX"):
        # pop с значением по умолчанию не падает, если переменной нет.
        env.pop(name, None)
    # Переменные Tcl/Tk: внутри собранного Auto-Compiler.exe они указывают на НАШИ файлы Tcl/Tk,
    # и без очистки встроенный Python и PyInstaller взяли бы не свои графические компоненты.
    for name in ("TCL_LIBRARY", "TK_LIBRARY", "TKPATH", "TIX_LIBRARY"):
        # Удаляем, если есть.
        env.pop(name, None)
    # Служебные переменные загрузчика PyInstaller (_PYI_*, _MEIPASS2) не должны «протекать» в дочерние процессы.
    for name in [key for key in env if key.upper().startswith(("_PYI_", "_MEIPASS"))]:
        # Удаляем каждую найденную.
        env.pop(name, None)
    # Просим любые запущенные нами PyInstaller-программы стартовать «с чистого листа» (PyInstaller ≥ 6.9).
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    # Папка распаковки собранного Auto-Compiler.exe (если мы в нём).
    bundle = frozen_bundle_dir()
    # Убираем её из PATH, чтобы дочерние программы не находили там наши DLL.
    if bundle is not None and env.get("PATH"):
        # Разбиваем PATH на части и оставляем только «чужие» папки.
        parts = [part for part in env["PATH"].split(os.pathsep) if part and not _is_inside(Path(part), bundle)]
        # Собираем PATH обратно.
        env["PATH"] = os.pathsep.join(parts)
    # Принудительный UTF-8 во всех дочерних Python-процессах.
    env["PYTHONUTF8"] = "1"
    # Кодировка стандартных потоков ввода-вывода.
    env["PYTHONIOENCODING"] = "utf-8"
    # Без буферизации — строки лога приходят сразу, а не пачками.
    env["PYTHONUNBUFFERED"] = "1"
    # Не подключать пакеты из профиля пользователя (%APPDATA%\\Python).
    env["PYTHONNOUSERSITE"] = "1"
    # pip не должен спрашивать что-либо у пользователя.
    env["PIP_NO_INPUT"] = "1"
    # pip не должен проверять свои обновления (лишний сетевой запрос).
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    # Отключаем требование виртуального окружения из чужих настроек pip.
    env["PIP_REQUIRE_VIRTUALENV"] = "false"
    # Запрещаем установку «в профиль пользователя» из чужих настроек pip.
    env["PIP_USER"] = "false"
    # Добавляем дополнительные переменные, если переданы.
    if extra:
        env.update(extra)
    # Возвращаем готовое окружение.
    return env


def kill_process_tree(process: subprocess.Popen) -> None:
    """Принудительно завершить процесс вместе со всеми его дочерними процессами."""
    # Linux/macOS: процесс запущен в собственной группе — убиваем всю группу целиком
    # (даже если сам процесс уже завершился, а его «дети» ещё живы).
    if not IS_WINDOWS:
        # Ошибки (группы уже нет) игнорируем.
        try:
            # SIGKILL всей группе процессов (её номер совпадает с PID процесса).
            os.killpg(process.pid, signal.SIGKILL)  # type: ignore[attr-defined]
        # Группа уже завершилась или нет прав.
        except (OSError, AttributeError):
            pass
    # Процесс уже завершился — больше делать нечего.
    if process.poll() is not None:
        return
    # В Windows taskkill /T убивает всё дерево (pip и PyInstaller запускают дочерние процессы).
    if IS_WINDOWS:
        # Ошибки taskkill игнорируем — ниже есть запасной вариант.
        try:
            # /F — принудительно, /T — с дочерними процессами.
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(process.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=15,
                **hidden_subprocess_kwargs(),
            )
        # taskkill не сработал — не страшно.
        except Exception:  # noqa: BLE001
            pass
    # Запасной вариант: убить сам процесс.
    try:
        # kill() отправляет SIGKILL / TerminateProcess.
        process.kill()
    # Процесс уже завершился сам.
    except OSError:
        pass


class CancelToken:
    """
    «Флажок отмены», общий для окна и фонового потока.

    Окно вызывает cancel(), а фоновый код регулярно вызывает raise_if_cancelled().
    Запущенные внешние процессы регистрируются здесь и убиваются при отмене.
    """

    def __init__(self) -> None:
        # Потокобезопасный флаг «отменено».
        self._event = threading.Event()
        # Замок для безопасной работы со списком процессов из двух потоков.
        self._lock = threading.Lock()
        # Сейчас запущенные внешние процессы.
        self._processes: set[subprocess.Popen] = set()

    @property
    def cancelled(self) -> bool:
        """True, если отмена уже запрошена."""
        # Просто читаем флаг.
        return self._event.is_set()

    def cancel(self) -> None:
        """Запросить отмену и немедленно остановить все запущенные процессы."""
        # Поднимаем флаг.
        self._event.set()
        # Берём копию списка процессов под замком.
        with self._lock:
            processes = list(self._processes)
        # Убиваем каждый процесс вместе с детьми.
        for process in processes:
            kill_process_tree(process)

    def raise_if_cancelled(self) -> None:
        """Выбросить BuildCancelled, если пользователь отменил сборку."""
        # Флаг поднят — прерываем работу.
        if self._event.is_set():
            raise BuildCancelled()

    def wait(self, seconds: float) -> bool:
        """Подождать указанное время; вернуть True, если за это время пришла отмена."""
        # Event.wait возвращает True, как только флаг поднят.
        return self._event.wait(seconds)

    def register(self, process: subprocess.Popen) -> None:
        """Запомнить запущенный процесс (чтобы его можно было убить при отмене)."""
        # Добавляем под замком.
        with self._lock:
            self._processes.add(process)
        # Если отмена пришла ровно в момент запуска — убиваем сразу.
        if self._event.is_set():
            kill_process_tree(process)

    def unregister(self, process: subprocess.Popen) -> None:
        """Забыть завершившийся процесс."""
        # Удаляем под замком (discard не падает, если процесса уже нет).
        with self._lock:
            self._processes.discard(process)


@dataclass
class ProcessResult:
    """Результат работы внешнего процесса."""

    # Код завершения (0 — успех).
    returncode: int
    # Последние строки вывода.
    output_tail: list[str] = field(default_factory=list)


def _decode_line(raw: bytes) -> str:
    """Превратить байты строки вывода в текст (UTF-8, с запасным вариантом для консоли Windows)."""
    # Сначала пробуем UTF-8 — дочерний Python выводит именно его (PYTHONUTF8=1).
    try:
        return raw.decode("utf-8")
    # Системные утилиты Windows пишут в кодировке консоли (cp866 для русской Windows).
    except UnicodeDecodeError:
        return raw.decode("cp866" if IS_WINDOWS else "latin-1", errors="replace")


def run_process(
    command: Sequence[str],
    *,
    description: str,
    kind: str = "",
    package: str = "",
    on_line: Optional[LineHandler] = None,
    cwd: Optional[Path] = None,
    env: Optional[dict[str, str]] = None,
    cancel: Optional[CancelToken] = None,
    timeout: Optional[float] = None,
    check: bool = True,
    tail_size: int = 80,
) -> ProcessResult:
    """
    Запустить внешнюю программу БЕЗ чёрного окна и построчно передавать её вывод в on_line.

    При ошибке (check=True) выбрасывает ProcessFailedError с последними строками вывода,
    при отмене — BuildCancelled, при превышении времени — subprocess.TimeoutExpired.
    """
    # Если сборку уже отменили — даже не запускаем процесс.
    if cancel is not None:
        cancel.raise_if_cancelled()
    # Последние строки вывода (deque сам выбрасывает самые старые).
    tail: deque[str] = deque(maxlen=tail_size)
    # Внутри собранного Auto-Compiler.exe — стандартный поиск DLL для запускаемых программ.
    sanitize_frozen_environment()
    # Параметры запуска: скрытое окно в Windows.
    popen_kwargs = hidden_subprocess_kwargs()
    # В Linux/macOS — собственная группа процессов, чтобы при отмене убить и всех «детей».
    if not IS_WINDOWS:
        popen_kwargs["start_new_session"] = True
    # Запускаем процесс: stderr склеиваем со stdout, чтобы видеть ошибки в общем потоке.
    process = subprocess.Popen(
        list(command),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        cwd=str(cwd) if cwd else None,
        env=env,
        **popen_kwargs,
    )
    # Регистрируем процесс для возможной отмены.
    if cancel is not None:
        cancel.register(process)
    # Флаг «процесс убит по тайм-ауту» (список — чтобы менять из вложенной функции).
    timed_out = [False]

    def _on_timeout() -> None:
        """Сработал таймер — убиваем зависший процесс."""
        # Запоминаем причину.
        timed_out[0] = True
        # Останавливаем всё дерево процессов.
        kill_process_tree(process)

    def _reader() -> None:
        """Отдельный поток: читает вывод построчно и передаёт его обработчику."""
        # Канал может закрыться в любой момент — это нормально.
        try:
            # stdout точно есть, т.к. мы передали PIPE.
            assert process.stdout is not None
            # Читаем, пока процесс (и его «дети») не закроют канал.
            for raw in iter(process.stdout.readline, b""):
                # Декодируем и убираем перевод строки в конце.
                line = _decode_line(raw).rstrip("\r\n")
                # Пустые строки не интересны.
                if not line.strip():
                    continue
                # Запоминаем строку в хвосте.
                tail.append(line)
                # Передаём строку обработчику (его ошибка не должна ломать сборку).
                if on_line is not None:
                    try:
                        on_line(line)
                    except Exception:  # noqa: BLE001
                        pass
        # Канал закрыт во время чтения.
        except (OSError, ValueError):
            pass

    # Таймер тайм-аута (если задан).
    timer = threading.Timer(timeout, _on_timeout) if timeout else None
    # Таймер не должен мешать закрытию программы.
    if timer is not None:
        timer.daemon = True
        # Запускаем отсчёт.
        timer.start()
    # Поток чтения вывода (демон — не мешает закрыть программу).
    reader = threading.Thread(target=_reader, name="ProcessOutputReader", daemon=True)
    # Запускаем чтение.
    reader.start()
    # Блок finally гарантирует уборку при любой ошибке.
    try:
        # Ждём завершения САМОГО процесса (а не закрытия канала — его может держать «внук»).
        returncode = process.wait()
        # Даём потоку чтения дочитать остаток вывода (но не ждём вечно).
        reader.join(timeout=10)
    # Уборка выполняется всегда.
    finally:
        # Останавливаем таймер.
        if timer is not None:
            timer.cancel()
        # Убираем процесс из списка отмены.
        if cancel is not None:
            cancel.unregister(process)
        # Не оставляем «сирот»: добиваем процесс и его дочерние процессы.
        kill_process_tree(process)
        # Поток чтения закончил работу — закрываем канал (иначе остаётся открытый дескриптор).
        if not reader.is_alive() and process.stdout is not None:
            process.stdout.close()

    # Процесс убит из-за отмены — сообщаем об отмене, а не об ошибке.
    if cancel is not None and cancel.cancelled:
        raise BuildCancelled()
    # Процесс убит по тайм-ауту.
    if timed_out[0]:
        raise subprocess.TimeoutExpired(list(command), timeout or 0, output="\n".join(tail))
    # Ненулевой код завершения — ошибка.
    if check and returncode != 0:
        raise ProcessFailedError(description, command, returncode, list(tail), kind=kind, package=package)
    # Всё хорошо — возвращаем результат.
    return ProcessResult(returncode=returncode, output_tail=list(tail))


# ====================================================================== #
#   СКАЧИВАНИЕ ФАЙЛОВ                                                     #
# ====================================================================== #

def sha256_of(path: Path) -> str:
    """Посчитать SHA-256 файла (читаем кусками, чтобы не грузить файл целиком в память)."""
    # Создаём объект хэша.
    digest = hashlib.sha256()
    # Открываем файл в двоичном режиме.
    with path.open("rb") as handle:
        # Читаем по 1 МБ, пока файл не закончится.
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            # Добавляем кусок в хэш.
            digest.update(chunk)
    # Возвращаем хэш в виде шестнадцатеричной строки.
    return digest.hexdigest()


def fetch_json(url: str, timeout: float = 20) -> Any:
    """Скачать и разобрать небольшой JSON-файл."""
    # Запрос с понятным User-Agent.
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    # Открываем соединение (with гарантирует закрытие).
    with urllib.request.urlopen(request, timeout=timeout) as response:
        # Читаем и разбираем JSON.
        return json.loads(response.read().decode("utf-8"))


def download_file(
    url: str,
    destination: Path,
    *,
    on_progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[CancelToken] = None,
    expected_sha256: Optional[str] = None,
    timeout: float = 30,
    retries: int = 3,
) -> Path:
    """
    Надёжно скачать файл: до `retries` попыток, проверка размера и (если задан) SHA-256.

    Файл сначала пишется во временный «.part», и только после всех проверок
    переименовывается в destination — так недокачанный файл никогда не выдаётся за готовый.
    """
    # Создаём папку назначения.
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Временный файл рядом с итоговым.
    partial = destination.with_name(destination.name + ".part")
    # Последняя пойманная ошибка (чтобы выбросить её после всех попыток).
    last_error: Optional[BaseException] = None

    # Делаем несколько попыток.
    for attempt in range(1, retries + 1):
        # Проверяем отмену перед каждой попыткой.
        if cancel is not None:
            cancel.raise_if_cancelled()
        # Попытка скачивания.
        try:
            # Формируем запрос.
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            # Открываем соединение и временный файл.
            with urllib.request.urlopen(request, timeout=timeout) as response, partial.open("wb") as handle:
                # Ожидаемый размер файла (0, если сервер его не сообщил).
                total = int(response.headers.get("Content-Length") or 0)
                # Сколько уже скачано.
                done = 0
                # Хэш считаем «на лету».
                digest = hashlib.sha256()
                # Читаем кусками по 256 КБ.
                while True:
                    # Проверяем отмену во время скачивания.
                    if cancel is not None:
                        cancel.raise_if_cancelled()
                    # Очередной кусок данных.
                    chunk = response.read(256 * 1024)
                    # Пустой кусок — файл закончился.
                    if not chunk:
                        break
                    # Записываем кусок на диск.
                    handle.write(chunk)
                    # Обновляем хэш.
                    digest.update(chunk)
                    # Увеличиваем счётчик.
                    done += len(chunk)
                    # Сообщаем о прогрессе.
                    if on_progress is not None:
                        on_progress(done, total)
            # Сервер обещал больше, чем прислал, — соединение оборвалось.
            if total and done != total:
                raise DownloadError(url, f"Файл скачан не полностью: {format_size(done)} из {format_size(total)}")
            # Контрольная сумма не совпала — файл повреждён или подменён.
            if expected_sha256 and digest.hexdigest().lower() != expected_sha256.lower():
                raise DownloadError(url, "Контрольная сумма файла не совпала — файл повреждён")
            # Все проверки пройдены — атомарно переименовываем.
            os.replace(partial, destination)
            # Возвращаем путь к готовому файлу.
            return destination
        # Отмена — сразу наружу, без повторов.
        except BuildCancelled:
            raise
        # HTTP-ошибки 4xx повторять бессмысленно (файла нет), 5xx — можно повторить.
        except urllib.error.HTTPError as exc:
            # Запоминаем ошибку.
            last_error = exc
            # Ошибки клиента (404 и т.п.) — выходим сразу.
            if 400 <= exc.code < 500:
                break
        # Сетевые ошибки, обрывы, повреждения — пробуем ещё раз.
        except Exception as exc:  # noqa: BLE001
            # Запоминаем ошибку.
            last_error = exc
        # Уборка временного файла после неудачной попытки.
        finally:
            # Удаляем недокачанный файл (если он остался).
            if partial.exists():
                try:
                    partial.unlink()
                except OSError:
                    pass
        # Пауза перед следующей попыткой: 2, 4, 6 секунд (прерывается отменой).
        if attempt < retries and cancel is not None and cancel.wait(2 * attempt):
            raise BuildCancelled()
        # Без токена отмены — обычная пауза.
        if attempt < retries and cancel is None:
            time.sleep(2 * attempt)

    # Все попытки исчерпаны — выбрасываем последнюю ошибку (её переведёт errors.py).
    assert last_error is not None
    raise last_error


# ====================================================================== #
#   ОТКРЫТИЕ ПРОВОДНИКА                                                   #
# ====================================================================== #

def reveal_in_explorer(path: str | Path) -> None:
    """Открыть проводник и выделить в нём указанный файл (для папки — просто открыть её)."""
    # Превращаем путь в абсолютный объект Path.
    target = Path(path).resolve()
    # Если ни файла, ни папки нет — сообщаем об этом понятной ошибкой.
    if not target.exists():
        # FileNotFoundError позже переведётся на понятный язык в errors.py.
        raise FileNotFoundError(2, "Путь не найден", str(target))

    # Ветка для Windows.
    if IS_WINDOWS:
        # Проводник — внешняя программа: не передаём ему настройки DLL собранного .exe.
        sanitize_frozen_environment()
        # Для файла — открываем папку и выделяем сам файл.
        if target.is_file():
            # Проводник требует именно такой формат: explorer.exe /select,"путь" (одной строкой).
            subprocess.Popen(f'explorer.exe /select,"{target}"')
        # Для папки — просто открываем её стандартным способом Windows.
        else:
            # os.startfile открывает папку в проводнике.
            os.startfile(str(target))  # type: ignore[attr-defined]
        # Дальше идти не нужно.
        return

    # Ветка для macOS: «open -R» показывает файл в Finder.
    if IS_MAC:
        # Запускаем Finder без ожидания завершения.
        subprocess.Popen(["open", "-R", str(target)])
        # Выходим из функции.
        return

    # Ветка для Linux: открываем папку файловым менеджером по умолчанию.
    folder = target if target.is_dir() else target.parent
    # xdg-open — стандартный способ открыть папку в Linux.
    subprocess.Popen(["xdg-open", str(folder)])


# ====================================================================== #
#   ПЕРЕВОДЧИК ВЫВОДА PIP                                                  #
# ====================================================================== #

# Шаблон строки «сырого» прогресса pip: «Progress 262144 of 16918164».
_PIP_PROGRESS_RE = re.compile(r"^Progress (\d+) of (\d+)$")
# Шаблон строки скачивания: «Downloading numpy-2.4.6-...whl (16.9 MB)».
_PIP_DOWNLOADING_RE = re.compile(r"^\s*Downloading (\S+)(?: \(([^)]+)\))?")
# Шаблон строки поиска пакета: «Collecting requests» или «Collecting idna<4 (from requests)».
_PIP_COLLECTING_RE = re.compile(r"^\s*Collecting (\S+)")


class PipOutputTranslator:
    """Превращает «сырой» вывод pip в понятные строки лога и живой статус в окне."""

    def __init__(self, bus: EventBus, display_name: str, on_fraction: Optional[ProgressHandler] = None) -> None:
        # Шина событий.
        self.bus = bus
        # Понятное имя устанавливаемого компонента (для статуса).
        self.display_name = display_name
        # Колбэк для полосы прогресса (доля скачивания текущего файла).
        self.on_fraction = on_fraction
        # Имя файла, который сейчас скачивается.
        self._current_file = ""
        # Последний показанный процент (чтобы не дёргать окно на каждый килобайт).
        self._last_percent = -1

    def __call__(self, line: str) -> None:
        """Обработать одну строку вывода pip."""
        # Строка «сырого» прогресса скачивания.
        progress = _PIP_PROGRESS_RE.match(line.strip())
        # Это прогресс — обновляем статус и полосу, в лог не пишем.
        if progress:
            # Сколько скачано и сколько всего.
            done, total = int(progress.group(1)), int(progress.group(2))
            # Доля от 0 до 1 (защита от деления на ноль).
            fraction = done / total if total else 0.0
            # Процент целым числом.
            percent = int(fraction * 100)
            # Обновляем, только если процент изменился.
            if percent != self._last_percent:
                # Запоминаем процент.
                self._last_percent = percent
                # Живой статус для пользователя.
                self.bus.status(
                    f"Скачиваю необходимые компоненты для компиляции: {self.display_name}… "
                    f"{percent}% ({format_size(done)} из {format_size(total)})"
                )
                # Двигаем полосу прогресса.
                if self.on_fraction is not None:
                    self.on_fraction(fraction)
            # Дальше эту строку не обрабатываем.
            return

        # Начало поиска очередного пакета.
        collecting = _PIP_COLLECTING_RE.match(line)
        # Это «Collecting …».
        if collecting:
            # Статус в окне.
            self.bus.status(f"Скачиваю необходимые компоненты для компиляции: {self.display_name}…")
            # Серая строка с именем найденного пакета.
            self.bus.debug(f"Ищу пакет: {collecting.group(1)}")
            # Готово.
            return

        # Начало скачивания файла.
        downloading = _PIP_DOWNLOADING_RE.match(line)
        # Это «Downloading …» (метаданные .metadata пропускаем — они крошечные).
        if downloading and not downloading.group(1).endswith(".metadata"):
            # Запоминаем имя файла.
            self._current_file = downloading.group(1)
            # Сбрасываем процент для нового файла.
            self._last_percent = -1
            # Размер файла (если pip его сообщил).
            size = f" ({downloading.group(2)})" if downloading.group(2) else ""
            # Понятная строка в лог.
            self.bus.info(f"Загружаю файл {self._current_file}{size}")
            # Готово.
            return

        # Установка скачанных пакетов.
        if line.startswith("Installing collected packages:"):
            # Список пакетов после двоеточия.
            names = line.split(":", 1)[1].strip()
            # Статус и строка в лог.
            self.bus.status(f"Устанавливаю: {names}…")
            # Строка в лог.
            self.bus.info(f"Устанавливаю: {names}")
            # Готово.
            return

        # Успешное завершение.
        if line.startswith("Successfully installed"):
            # Перечисление установленных версий.
            names = line[len("Successfully installed"):].strip()
            # Зелёная строка.
            self.bus.success(f"Установлено: {names}")
            # Готово.
            return

        # Ошибки pip — красным.
        if line.startswith("ERROR:") or line.lstrip().startswith("error:"):
            # Красная строка.
            self.bus.log(line, LogLevel.ERROR)
            # Готово.
            return

        # Всё остальное — серым (технические подробности).
        self.bus.debug(line)


# ====================================================================== #
#   ВСТРОЕННЫЙ (ИЗОЛИРОВАННЫЙ) PYTHON                                     #
# ====================================================================== #

# Небольшая программа, которую мы запускаем ВНУТРИ встроенного Python, чтобы узнать:
#   • какие модули из списка уже можно импортировать;
#   • список модулей стандартной библиотеки этой версии Python;
#   • версию Python.
_QUERY_SNIPPET = r"""
import sys, json, importlib.util
names = json.loads(sys.argv[1])
found = []
for name in names:
    try:
        if importlib.util.find_spec(name) is not None:
            found.append(name)
    except Exception:
        pass
result = {
    "found": found,
    "stdlib": sorted(getattr(sys, "stdlib_module_names", ())),
    "version": list(sys.version_info[:3]),
}
print("__AC_JSON__" + json.dumps(result))
"""

# Программа проверки tkinter: создаёт интерпретатор Tcl без окна и спрашивает версию.
_TK_CHECK_SNIPPET = "import tkinter; print('Tk', tkinter.Tcl().eval('info patchlevel'))"


@dataclass
class ModuleQuery:
    """Ответ встроенного Python о модулях."""

    # Модули из запроса, которые уже можно импортировать.
    found: set[str]
    # Модули стандартной библиотеки этой версии Python.
    stdlib: set[str]
    # Версия Python (major, minor, micro).
    version: tuple[int, ...]


def patch_pth_file(pth_file: Path, extra_paths: Iterable[str] = ("Lib",)) -> bool:
    """
    Настроить pythonXY._pth встроенного Python:
        • раскомментировать «import site» (без него pip и site-packages не работают);
        • добавить дополнительные пути поиска модулей (папка Lib — для tkinter).
    Возвращает True, если файл был изменён.
    """
    # Исходный текст файла.
    original = pth_file.read_text(encoding="utf-8")
    # Новые строки файла.
    lines: list[str] = []
    # Уже присутствующие пути (в нижнем регистре — Windows не различает регистр).
    present: set[str] = set()
    # Нашли ли строку import site.
    site_index: Optional[int] = None
    # Проходим по строкам исходного файла.
    for line in original.splitlines():
        # Строка без пробелов по краям.
        stripped = line.strip()
        # Строка «#import site» или «import site» (с любым количеством решёток и пробелов).
        if stripped.lstrip("#").strip() == "import site":
            # Запоминаем позицию и записываем строку БЕЗ решётки.
            site_index = len(lines)
            # Раскомментированная строка.
            lines.append("import site")
            # К следующей строке.
            continue
        # Запоминаем существующие пути (не комментарии).
        if stripped and not stripped.startswith("#"):
            present.add(stripped.lower())
        # Остальные строки оставляем как есть.
        lines.append(line)
    # Если строки import site не было вовсе — добавляем её в конец.
    if site_index is None:
        # Позиция новой строки.
        site_index = len(lines)
        # Добавляем строку.
        lines.append("import site")
    # Добавляем недостающие пути ПЕРЕД import site (порядок важен для читаемости).
    for extra in extra_paths:
        # Путь ещё не указан.
        if extra.lower() not in present:
            # Вставляем перед import site.
            lines.insert(site_index, extra)
            # import site сдвинулся на одну строку вниз.
            site_index += 1
    # Итоговый текст с переводом строки в конце.
    updated = "\n".join(lines) + "\n"
    # Изменений нет — ничего не пишем.
    if updated == original:
        return False
    # Записываем новый текст.
    pth_file.write_text(updated, encoding="utf-8")
    # Файл изменён.
    return True


# Содержимое файла runtime/sitecustomize.py — «мост» для изолированной сборки библиотек pip.
#
# Зачем он нужен: многие библиотеки (например, PyAutoGUI и его зависимости) выложены только
# в виде исходного кода, и pip собирает их сам. Для этого pip скачивает сборщик (setuptools,
# hatchling, flit…) во временную папку и подключает её через переменную PYTHONPATH и свой
# файл sitecustomize.py. Но портативный Python из-за файла pythonXY._pth ИГНОРИРУЕТ PYTHONPATH,
# поэтому сборщик «не виден» и pip падает с ошибкой «BackendUnavailable: Cannot import
# 'setuptools.build_meta'». Этот мост находит sitecustomize.py, который pip положил в папку
# из PYTHONPATH, и выполняет его — изоляция pip начинает работать как в обычном Python.
# Во всех остальных случаях (PYTHONPATH пуст или в нём нет sitecustomize.py) мост ничего не делает.
SITECUSTOMIZE_BRIDGE_CODE = '''\
# Создано Auto-Compiler. Мост для изолированной сборки библиотек pip во встроенном Python.
# Встроенный Python игнорирует PYTHONPATH (из-за файла ._pth), а pip через него подключает
# временную папку со сборщиком пакетов. Этот файл выполняет подготовленный pip sitecustomize.py.

# os — переменные окружения и пути, sys — список путей поиска модулей.
import os
import sys


def _autocompiler_pip_bridge():
    """Найти sitecustomize.py от pip в папках из PYTHONPATH и выполнить его."""
    # Путь к этому файлу (чтобы не выполнить самого себя).
    here = os.path.normcase(os.path.abspath(__file__))
    # Перебираем папки из PYTHONPATH.
    for entry in os.environ.get("PYTHONPATH", "").split(os.pathsep):
        # Пустые элементы пропускаем.
        if not entry:
            continue
        # Файл, который pip кладёт в свою временную папку.
        candidate = os.path.join(entry, "sitecustomize.py")
        # Нет файла или это мы сами — дальше.
        if not os.path.isfile(candidate) or os.path.normcase(os.path.abspath(candidate)) == here:
            continue
        # Делаем папку видимой для импорта (как это сделал бы обычный Python).
        if entry not in sys.path:
            sys.path.insert(0, entry)
        # Читаем код pip.
        with open(candidate, encoding="utf-8") as handle:
            code = handle.read()
        # Выполняем его: pip сам уберёт системные пакеты и подключит папку со сборщиком.
        exec(compile(code, candidate, "exec"), {"__name__": "__pip_build_env__", "__file__": candidate})
        # Одного файла достаточно.
        return


# Мост никогда не должен мешать запуску Python.
try:
    # Запускаем поиск.
    _autocompiler_pip_bridge()
# Любая ошибка — просто работаем без моста.
except Exception:
    pass
'''


class PythonRuntime:
    """Портативный Python в папке runtime/ — «внутренняя изолированная среда» компилятора."""

    # Версия Python. 3.12.10 — последняя версия ветки 3.12 с официальными сборками для Windows;
    # под неё есть готовые колёса (wheels) практически у всех популярных библиотек.
    PYTHON_VERSION = "3.12.10"
    # Имя файла-маркера: появляется только после ПОЛНОСТЬЮ успешной настройки.
    MARKER_NAME = ".autocompiler-runtime.json"
    # Базовые сборочные утилиты: без них pip не может собрать библиотеки, выложенные только
    # исходным кодом (get-pip.py для Python 3.12+ их больше не ставит).
    BUILD_TOOLS: tuple[str, ...] = ("setuptools", "wheel")
    # Адрес официального установщика pip.
    GET_PIP_URL = "https://bootstrap.pypa.io/get-pip.py"
    # Базовый адрес загрузок python.org.
    PYTHON_FTP = "https://www.python.org/ftp/python"
    # Модули/файлы tkinter, которые нужно взять из полного дистрибутива.
    TK_EXTRA_DLLS = ("_tkinter.pyd", "zlib1.dll")

    def __init__(self, root: Optional[Path] = None, python_override: Optional[str] = None) -> None:
        # Режим разработчика: путь к готовому Python из аргумента или переменной окружения.
        override = python_override or os.environ.get(RUNTIME_OVERRIDE_ENV)
        # True — используем чужой Python и ничего не скачиваем.
        self.external = bool(override)
        # Ветка внешнего Python.
        if override:
            # Путь к интерпретатору.
            self.python_exe = Path(override)
            # Корень — папка интерпретатора.
            self.root = self.python_exe.parent
        # Ветка встроенного Python.
        else:
            # Папка runtime (рядом с программой или в профиле пользователя).
            self.root = root or self.default_root()
            # Интерпретатор внутри неё.
            self.python_exe = self.root / "python.exe"
        # Кэш: поддерживает ли pip «сырой» прогресс.
        self._pip_raw_progress: Optional[bool] = None

    # ------------------------------------------------------------------ #
    #   Пути и состояние                                                  #
    # ------------------------------------------------------------------ #

    @classmethod
    def default_root(cls) -> Path:
        """Где хранить runtime: рядом с программой (портативно) или в профиле пользователя."""
        # Вариант «рядом с программой».
        portable = program_root() / "runtime"
        # Вариант «в профиле пользователя» (если папка программы защищена от записи).
        fallback = user_data_dir() / "runtime"
        # Если среда уже настроена в одном из мест — используем её.
        for candidate in (portable, fallback):
            # Маркер готовности существует.
            if (candidate / cls.MARKER_NAME).is_file():
                return candidate
        # Собранный Auto-Compiler.exe обычно лежит в «Загрузках» или на рабочем столе:
        # не захламляем эту папку и не теряем среду при переносе .exe — храним её в профиле.
        # (Портативный режим остаётся: если рядом с .exe уже есть готовая папка runtime, берём её.)
        if is_frozen():
            return fallback
        # Иначе выбираем портативный вариант, если в папку программы можно писать.
        return portable if is_dir_writable(program_root()) else fallback

    @property
    def marker_file(self) -> Path:
        """Путь к файлу-маркеру готовности."""
        # Маркер лежит в корне runtime.
        return self.root / self.MARKER_NAME

    @property
    def downloads_dir(self) -> Path:
        """Папка для временных загрузок."""
        # Внутри папки данных пользователя.
        return user_data_dir() / "downloads"

    @staticmethod
    def architecture() -> str:
        """Архитектура Windows для имён файлов python.org: amd64, arm64 или win32."""
        # platform.machine() в Windows возвращает архитектуру ОС: «AMD64», «ARM64», «x86».
        machine = platform.machine().lower()
        # 64-битный ARM.
        if machine in ("arm64", "aarch64"):
            return "arm64"
        # Обычный 64-битный процессор Intel/AMD.
        if machine in ("amd64", "x86_64", "x64"):
            return "amd64"
        # Старые 32-битные системы.
        return "win32"

    def pth_file(self) -> Optional[Path]:
        """Найти файл pythonXY._pth (например, python312._pth)."""
        # Ищем по шаблону в корне runtime.
        matches = sorted(self.root.glob("python3*._pth"))
        # Первый найденный файл или None.
        return matches[0] if matches else None

    def read_marker(self) -> dict[str, Any]:
        """Прочитать маркер готовности (пустой словарь, если его нет или он повреждён)."""
        # Ошибки чтения означают «маркера нет».
        try:
            # Читаем и разбираем JSON.
            return json.loads(self.marker_file.read_text(encoding="utf-8"))
        # Нет файла или он испорчен.
        except (OSError, ValueError):
            return {}

    def write_marker(self, **updates: Any) -> None:
        """Обновить маркер готовности (сохраняя старые поля)."""
        # Текущее содержимое.
        data = self.read_marker()
        # Добавляем новые значения.
        data.update(updates)
        # Записываем JSON с отступами (удобно читать человеку).
        self.marker_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def is_ready(self) -> bool:
        """True, если встроенный Python полностью настроен и готов к работе."""
        # Внешний Python считаем готовым, если файл существует.
        if self.external:
            return self.python_exe.is_file()
        # Данные маркера.
        marker = self.read_marker()
        # Готов, если есть интерпретатор, маркер нужной версии и установлен pip.
        return (
            self.python_exe.is_file()
            and marker.get("python_version") == self.PYTHON_VERSION
            and bool(marker.get("pip"))
        )

    # ------------------------------------------------------------------ #
    #   Запуск встроенного Python                                         #
    # ------------------------------------------------------------------ #

    def run_python(
        self,
        args: Sequence[str],
        *,
        description: str,
        kind: str = "python",
        package: str = "",
        on_line: Optional[LineHandler] = None,
        cancel: Optional[CancelToken] = None,
        timeout: Optional[float] = 600,
        cwd: Optional[Path] = None,
        check: bool = True,
    ) -> ProcessResult:
        """Запустить встроенный Python с аргументами (скрыто, с «чистым» окружением)."""
        # Интерпретатор должен существовать.
        if not self.python_exe.is_file():
            raise FileNotFoundError(2, "Встроенный Python не найден", str(self.python_exe))
        # Запускаем через общий механизм.
        return run_process(
            [str(self.python_exe), *args],
            description=description,
            kind=kind,
            package=package,
            on_line=on_line,
            cwd=cwd or self.root,
            env=child_process_env(),
            cancel=cancel,
            timeout=timeout,
            check=check,
        )

    def query_modules(self, names: Iterable[str], cancel: Optional[CancelToken] = None) -> ModuleQuery:
        """Спросить у встроенного Python, какие модули уже установлены, и список его stdlib."""
        # Уникальные имена в стабильном порядке.
        unique = sorted(set(names))
        # Сюда попадёт строка с JSON-ответом.
        answer: list[str] = []

        def _collect(line: str) -> None:
            """Ловим строку с ответом среди возможного прочего вывода."""
            # Наша строка начинается с особого префикса.
            if line.startswith("__AC_JSON__"):
                answer.append(line[len("__AC_JSON__"):])

        # Запускаем проверочную программу.
        self.run_python(
            ["-c", _QUERY_SNIPPET, json.dumps(unique)],
            description="Проверка установленных библиотек",
            on_line=_collect,
            cancel=cancel,
            timeout=120,
        )
        # Ответа нет — что-то пошло совсем не так.
        if not answer:
            raise CompilerError(
                title="Встроенный Python не отвечает",
                message="Не удалось получить список установленных библиотек.",
                hint="Удалите папку runtime рядом с программой — при следующей сборке она будет создана заново.",
            )
        # Разбираем JSON.
        data = json.loads(answer[-1])
        # Возвращаем удобный объект.
        return ModuleQuery(
            found=set(data.get("found", [])),
            stdlib=set(data.get("stdlib", [])),
            version=tuple(data.get("version", [])),
        )

    def has_tkinter(self, cancel: Optional[CancelToken] = None) -> bool:
        """Работает ли tkinter во встроенном Python."""
        # Запускаем проверку без исключения при ошибке (check=False).
        result = self.run_python(
            ["-c", _TK_CHECK_SNIPPET],
            description="Проверка tkinter",
            cancel=cancel,
            timeout=60,
            check=False,
        )
        # Код 0 — tkinter работает.
        return result.returncode == 0

    def pip_supports_raw_progress(self, cancel: Optional[CancelToken] = None) -> bool:
        """Поддерживает ли pip режим «--progress-bar raw» (pip 24.1 и новее)."""
        # Ответ уже известен — возвращаем из кэша.
        if self._pip_raw_progress is not None:
            return self._pip_raw_progress
        # Узнаём версию pip.
        result = self.run_python(["-m", "pip", "--version"], description="Проверка pip", kind="pip", cancel=cancel, timeout=60, check=False)
        # Ищем «pip 26.2.1» в выводе.
        match = re.search(r"pip (\d+)\.(\d+)", "\n".join(result.output_tail))
        # Сравниваем версию с 24.1.
        self._pip_raw_progress = bool(match) and (int(match.group(1)), int(match.group(2))) >= (24, 1)  # type: ignore[union-attr]
        # Возвращаем ответ.
        return self._pip_raw_progress

    def pip_install(
        self,
        requirement: str | Sequence[str],
        *,
        bus: EventBus,
        cancel: Optional[CancelToken] = None,
        display_name: Optional[str] = None,
        on_fraction: Optional[ProgressHandler] = None,
        timeout: float = 1800,
    ) -> None:
        """Скрыто установить библиотеку во встроенный Python с живым статусом в окне."""
        # Одна библиотека или сразу несколько — приводим к списку.
        requirements = [requirement] if isinstance(requirement, str) else list(requirement)
        # Понятное имя для статуса.
        name = display_name or ", ".join(requirements)
        # Статус сразу — пользователь видит, что работа началась.
        bus.status(f"Скачиваю необходимые компоненты для компиляции: {name}…")
        # Базовая команда pip.
        args = [
            "-m", "pip", "install",
            # Предпочитать готовые колёса (wheels) сборке из исходников — компилятора у пользователя нет.
            "--prefer-binary",
            # Не предупреждать, что папка Scripts не в PATH (пользователю это не нужно).
            "--no-warn-script-location",
            # Не проверять обновления pip.
            "--disable-pip-version-check",
        ]
        # Если pip умеет — включаем машиночитаемый прогресс скачивания.
        if self.pip_supports_raw_progress(cancel):
            args += ["--progress-bar", "raw"]
        # Имена устанавливаемых пакетов.
        args.extend(requirements)
        # Запускаем pip с переводчиком вывода.
        self.run_python(
            args,
            description=f"Установка библиотеки {name}",
            kind="pip",
            package=name,
            on_line=PipOutputTranslator(bus, name, on_fraction),
            cancel=cancel,
            timeout=timeout,
        )

    # ------------------------------------------------------------------ #
    #   Создание среды с нуля                                             #
    # ------------------------------------------------------------------ #

    def ensure(self, bus: EventBus, cancel: CancelToken, progress: ProgressHandler) -> None:
        """Убедиться, что встроенный Python готов; при необходимости скачать и настроить его."""
        # Режим разработчика: используем внешний Python как есть.
        if self.external:
            # Проверяем, что файл существует.
            if not self.python_exe.is_file():
                raise CompilerError(
                    title="Указанный Python не найден",
                    message=f"Переменная {RUNTIME_OVERRIDE_ENV} указывает на несуществующий файл:\n{self.python_exe}",
                    hint=f"Исправьте путь в переменной {RUNTIME_OVERRIDE_ENV} или удалите её.",
                )
            # Сообщаем, что работаем в режиме разработчика.
            bus.warning(f"Режим разработчика: используется внешний Python {self.python_exe}")
            # Прогресс этапа — 100%.
            progress(1.0)
            # Больше ничего не нужно.
            return

        # Среда уже готова — ничего не скачиваем.
        if self.is_ready():
            # Зелёная строка.
            bus.success(f"Встроенный Python {self.PYTHON_VERSION} уже установлен: {self.root}")
            # Среда, созданная старой версией компилятора, могла остаться без сборочных утилит — доустанавливаем.
            self.ensure_build_tools(bus, cancel, progress)
            # Прогресс этапа — 100%.
            progress(1.0)
            # Готово.
            return

        # Embeddable-версия Python существует только для Windows.
        if not IS_WINDOWS:
            raise CompilerError(
                title="Сборка .exe возможна только в Windows",
                message="Файлы .exe собираются только в Windows, а встроенный Python скачивается в Windows-версии.",
                hint=f"Запустите компилятор в Windows. Разработчики могут указать готовый Python в переменной {RUNTIME_OVERRIDE_ENV}.",
            )

        # Объясняем пользователю, что происходит и почему это долго только в первый раз.
        bus.info("Первый запуск: скачиваю портативный Python (это нужно сделать только один раз, ~15 МБ).")
        # Удаляем остатки прошлой неудачной попытки (если были).
        self._wipe_incomplete_root()
        # Создаём папку runtime.
        self.root.mkdir(parents=True, exist_ok=True)

        # --- 1. Скачивание официального embeddable-архива (0% → 35%) ---
        arch = self.architecture()
        # Имя архива, например python-3.12.10-embed-amd64.zip.
        archive_name = f"python-{self.PYTHON_VERSION}-embed-{arch}.zip"
        # Полный адрес на python.org.
        url = f"{self.PYTHON_FTP}/{self.PYTHON_VERSION}/{archive_name}"
        # Сообщаем в лог.
        bus.info(f"Скачиваю {archive_name} с python.org…")
        # Скачиваем с прогрессом.
        archive = download_file(
            url,
            self.downloads_dir / archive_name,
            on_progress=self._download_reporter(bus, "портативный Python", progress, 0.0, 0.35),
            cancel=cancel,
        )

        # --- 2. Распаковка (35% → 45%) ---
        bus.status("Распаковываю портативный Python…")
        # Распаковываем с проверкой архива.
        self._extract_zip(archive, self.root)
        # Архив больше не нужен — экономим место.
        _remove_quietly(archive)
        # Двигаем прогресс.
        progress(0.45)
        # Проверяем, что интерпретатор на месте.
        if not self.python_exe.is_file():
            raise CompilerError(
                title="Архив Python повреждён",
                message="После распаковки не найден файл python.exe.",
                hint="Попробуйте ещё раз — архив будет скачан заново.",
            )
        # Сообщаем об успехе.
        bus.success("Портативный Python распакован.")

        # --- 3. Настройка файла pythonXY._pth ---
        pth = self.pth_file()
        # Без этого файла embeddable-Python не может работать с pip.
        if pth is None:
            raise CompilerError(
                title="Неожиданная структура Python",
                message="В портативном Python не найден файл настроек pythonXY._pth.",
                hint="Удалите папку runtime и попробуйте снова.",
            )
        # Раскомментируем import site и добавляем папку Lib.
        patch_pth_file(pth, extra_paths=("Lib",))
        # Создаём папку Lib (туда pip положит site-packages, а мы — tkinter).
        (self.root / "Lib").mkdir(exist_ok=True)
        # Сообщаем в лог.
        bus.info(f"Настроен файл {pth.name}: включён «import site».")
        # Проверяем, что Python вообще запускается.
        self.run_python(["-c", "import sys; print(sys.version)"], description="Проверка портативного Python", cancel=cancel, timeout=60)

        # --- 4. Скачивание get-pip.py (45% → 50%) ---
        bus.info("Скачиваю установщик библиотек pip…")
        # Скачиваем во временную папку загрузок.
        get_pip = download_file(
            self.GET_PIP_URL,
            self.downloads_dir / "get-pip.py",
            on_progress=self._download_reporter(bus, "установщик pip", progress, 0.45, 0.50),
            cancel=cancel,
        )

        # --- 5. Установка pip (50% → 85%) ---
        bus.status("Устанавливаю pip во встроенный Python…")
        # Запускаем get-pip.py (он сам скачает свежий pip).
        self.run_python(
            [str(get_pip), "--no-warn-script-location", "--progress-bar", "raw"],
            description="Установка pip",
            kind="get-pip",
            on_line=PipOutputTranslator(bus, "pip", lambda f: progress(0.50 + 0.35 * f)),
            cancel=cancel,
            timeout=900,
        )
        # Файл get-pip.py больше не нужен.
        _remove_quietly(get_pip)
        # Проверяем, что pip работает.
        self.run_python(["-m", "pip", "--version"], description="Проверка pip", kind="pip", cancel=cancel, timeout=120)
        # Сообщаем об успехе.
        bus.success("pip установлен и работает.")

        # --- 6. Маркер готовности Python + pip ---
        # Пишется ДО сборочных утилит: если их установка сорвётся (например, пропал интернет),
        # в следующий раз не придётся заново скачивать Python — доустановятся только утилиты.
        self.write_marker(
            python_version=self.PYTHON_VERSION,
            arch=arch,
            pip=True,
            build_tools=False,
            tkinter=False,
            created=datetime.now().isoformat(timespec="seconds"),
        )
        # Прогресс.
        progress(0.85)

        # --- 7. Сборочные утилиты setuptools и wheel (85% → 100%) ---
        self.ensure_build_tools(bus, cancel, lambda f: progress(0.85 + 0.15 * f))
        # Прогресс этапа — 100%.
        progress(1.0)
        # Итоговое сообщение.
        bus.success(f"Встроенный Python готов: {self.root}")

    def write_sitecustomize_bridge(self) -> None:
        """Положить в корень runtime мост sitecustomize.py (если его нет или он устарел)."""
        # Путь к файлу моста: корень runtime есть в pythonXY._pth (строка «.»).
        target = self.root / "sitecustomize.py"
        # Файл уже на месте и совпадает — ничего не делаем.
        if target.is_file() and target.read_text(encoding="utf-8", errors="replace") == SITECUSTOMIZE_BRIDGE_CODE:
            return
        # Записываем (перезаписываем) файл моста.
        target.write_text(SITECUSTOMIZE_BRIDGE_CODE, encoding="utf-8")

    def ensure_build_tools(self, bus: EventBus, cancel: CancelToken, progress: Optional[ProgressHandler] = None) -> None:
        """
        Один раз установить во встроенный Python сборочные утилиты setuptools и wheel
        и мост sitecustomize.py — без них pip не может собрать библиотеки из исходного кода
        (ошибка «BackendUnavailable: Cannot import 'setuptools.build_meta'», например у PyAutoGUI).
        """
        # Внешний Python (режим разработчика) не трогаем — это чужая установка.
        if self.external:
            return
        # Мост пишем всегда (это мгновенно): он мог устареть после обновления компилятора.
        self.write_sitecustomize_bridge()
        # Утилиты уже установлены раньше — повторно не ставим.
        if self.read_marker().get("build_tools"):
            return
        # Обработчик прогресса (может отсутствовать).
        report = progress or (lambda _fraction: None)
        # Объясняем пользователю, что происходит.
        bus.info("Устанавливаю сборочные утилиты setuptools и wheel (нужны для библиотек, которые pip собирает сам)…")
        # Тихая установка: скрытое окно, --no-warn-script-location, понятный статус в окне.
        self.pip_install(
            list(self.BUILD_TOOLS),
            bus=bus,
            cancel=cancel,
            display_name="setuptools, wheel",
            on_fraction=lambda f: report(0.9 * f),
            timeout=900,
        )
        # Проверяем, что сборщик действительно импортируется.
        self.run_python(
            ["-c", "import setuptools.build_meta, wheel"],
            description="Проверка сборочных утилит setuptools и wheel",
            kind="pip",
            package="setuptools",
            cancel=cancel,
            timeout=120,
        )
        # Запоминаем, что утилиты на месте (больше устанавливать не нужно).
        self.write_marker(build_tools=True)
        # Прогресс — 100%.
        report(1.0)
        # Зелёная строка.
        bus.success("Сборочные утилиты setuptools и wheel установлены.")

    def ensure_tkinter(self, bus: EventBus, cancel: CancelToken, progress: ProgressHandler) -> None:
        """
        Доставить tkinter во встроенный Python (в embeddable-версии его нет).

        Берём файлы из ОФИЦИАЛЬНОГО полного zip-дистрибутива той же версии с python.org,
        проверяя SHA-256 по официальному каталогу windows-<версия>.json.
        """
        # tkinter уже работает — ничего не делаем.
        if self.has_tkinter(cancel):
            # Отмечаем в маркере (для внешнего Python маркер не пишем).
            if not self.external:
                self.write_marker(tkinter=True)
            # Прогресс 100%.
            progress(1.0)
            # Готово.
            return
        # Во внешнем Python мы ничего не устанавливаем.
        if self.external:
            raise CompilerError(
                title="В Python нет tkinter",
                message=f"Программе нужен tkinter, но в Python {self.python_exe} он не установлен.",
                hint="Установите Python с компонентом «tcl/tk and IDLE» или уберите переменную режима разработчика.",
            )

        # Объясняем пользователю, зачем нужна загрузка.
        bus.info("Программе нужен tkinter (окна, кнопки). Скачиваю графические компоненты Python (~30 МБ, один раз)…")
        # Архитектура и суффикс в каталоге python.org.
        arch = self.architecture()
        # Суффикс идентификатора в windows-<версия>.json.
        suffix = {"amd64": "64", "win32": "32", "arm64": "arm64"}[arch]
        # Версия «3.12» для идентификатора.
        short = ".".join(self.PYTHON_VERSION.split(".")[:2])
        # Адрес по умолчанию (если каталог недоступен).
        url = f"{self.PYTHON_FTP}/{self.PYTHON_VERSION}/python-{self.PYTHON_VERSION}-{arch}.zip"
        # Ожидаемая контрольная сумма (если удастся получить).
        sha256: Optional[str] = None
        # Пробуем прочитать официальный каталог с адресом и SHA-256.
        try:
            # Скачиваем каталог версий.
            catalog = fetch_json(f"{self.PYTHON_FTP}/{self.PYTHON_VERSION}/windows-{self.PYTHON_VERSION}.json")
            # Ищем запись полного дистрибутива нужной архитектуры.
            for entry in catalog.get("versions", []):
                # Идентификатор вида pythoncore-3.12-64.
                if entry.get("id") == f"pythoncore-{short}-{suffix}":
                    # Берём адрес и хэш из каталога.
                    url = entry.get("url") or url
                    # Хэш SHA-256.
                    sha256 = (entry.get("hash") or {}).get("sha256")
                    # Нашли — выходим из цикла.
                    break
        # Каталог недоступен — продолжаем без проверки хэша (HTTPS всё равно защищает от подмены).
        except Exception as exc:  # noqa: BLE001
            bus.debug(f"Каталог версий python.org недоступен ({exc}); продолжаю без проверки контрольной суммы.")

        # Имя файла архива.
        archive_name = url.rsplit("/", 1)[-1]
        # Скачиваем (0% → 80%).
        archive = download_file(
            url,
            self.downloads_dir / archive_name,
            on_progress=self._download_reporter(bus, "графические компоненты (tkinter)", progress, 0.0, 0.8),
            cancel=cancel,
            expected_sha256=sha256,
        )
        # Сообщаем о проверке.
        if sha256:
            bus.success("Контрольная сумма архива совпала с официальной.")
        # Извлекаем только файлы tkinter (80% → 95%).
        bus.status("Устанавливаю tkinter во встроенный Python…")
        # Копирование файлов.
        copied = self._extract_tkinter(archive)
        # Архив больше не нужен.
        _remove_quietly(archive)
        # Убеждаемся, что папка Lib есть в путях поиска.
        pth = self.pth_file()
        # Добавляем Lib, если её нет.
        if pth is not None:
            patch_pth_file(pth, extra_paths=("Lib",))
        # Прогресс.
        progress(0.95)
        # Финальная проверка.
        if not self.has_tkinter(cancel):
            raise CompilerError(
                title="Не удалось установить tkinter",
                message="Файлы tkinter скопированы, но он не запускается во встроенном Python.",
                hint="Удалите папку runtime рядом с программой и попробуйте снова.",
            )
        # Отмечаем в маркере.
        self.write_marker(tkinter=True)
        # Прогресс 100%.
        progress(1.0)
        # Итоговое сообщение.
        bus.success(f"tkinter установлен ({copied} файлов).")

    # ------------------------------------------------------------------ #
    #   Внутренние помощники                                              #
    # ------------------------------------------------------------------ #

    def _wipe_incomplete_root(self) -> None:
        """Удалить недонастроенную папку runtime (после обрыва интернета и т.п.)."""
        # Папки нет — удалять нечего.
        if not self.root.exists():
            return
        # Признаки того, что папка — наша (а не чужая папка с таким же именем).
        ours = (
            (self.root / "python.exe").exists()
            or self.marker_file.exists()
            or self.pth_file() is not None
            or not any(self.root.iterdir())
        )
        # Чужие файлы не трогаем никогда.
        if not ours:
            raise CompilerError(
                title="Папка runtime занята",
                message=f"В папке {self.root} лежат посторонние файлы.",
                hint="Переименуйте или переместите эту папку — компилятор создаст свою.",
            )
        # Удаляем папку целиком (снимая атрибут «только чтение», если мешает).
        _rmtree(self.root)

    def _extract_zip(self, archive: Path, target: Path) -> None:
        """Распаковать zip с проверкой целостности и защитой от «вредных» путей."""
        # Открываем архив.
        with zipfile.ZipFile(archive) as bundle:
            # testzip проверяет контрольные суммы всех файлов (None — всё в порядке).
            broken = bundle.testzip()
            # Найден повреждённый файл.
            if broken is not None:
                raise zipfile.BadZipFile(f"Повреждён файл внутри архива: {broken}")
            # Проверяем каждый путь: он не должен выходить за пределы папки назначения.
            for member in bundle.namelist():
                # Итоговый путь файла.
                destination = (target / member).resolve()
                # Путь «убегает» наружу (атака zip-slip) — отказываемся.
                if not _is_within(destination, target.resolve()):
                    raise zipfile.BadZipFile(f"Подозрительный путь в архиве: {member}")
            # Распаковываем всё.
            bundle.extractall(target)

    def _extract_tkinter(self, archive: Path) -> int:
        """Скопировать из полного дистрибутива только файлы tkinter. Вернуть число файлов."""
        # Счётчик скопированных файлов.
        copied = 0
        # Абсолютный путь корня runtime.
        root = self.root.resolve()
        # Открываем архив.
        with zipfile.ZipFile(archive) as bundle:
            # Все имена файлов (с прямыми слэшами).
            names = [name.replace("\\", "/") for name in bundle.namelist()]
            # Ищем «опорный» файл, чтобы понять, в какой подпапке архива лежит Python.
            anchor = next((n for n in names if n.lower().endswith("dlls/_tkinter.pyd")), None)
            # Без _tkinter.pyd ничего не получится.
            if anchor is None:
                raise CompilerError(
                    title="В архиве нет tkinter",
                    message="В скачанном дистрибутиве Python не найден модуль _tkinter.",
                    hint="Сообщите разработчику — возможно, python.org изменил формат архивов.",
                )
            # Префикс подпапки (часто пустой).
            prefix = anchor[: len(anchor) - len("DLLs/_tkinter.pyd")]
            # Проходим по всем файлам архива.
            for original in bundle.namelist():
                # Имя с прямыми слэшами.
                name = original.replace("\\", "/")
                # Пропускаем папки и файлы вне префикса.
                if name.endswith("/") or not name.startswith(prefix):
                    continue
                # Путь относительно корня дистрибутива.
                relative = name[len(prefix):]
                # Тот же путь в нижнем регистре — для сравнения.
                lower = relative.lower()
                # Куда копировать (None — файл не нужен).
                destination: Optional[Path] = None
                # Библиотеки tkinter из DLLs/ кладём в корень runtime (рядом с python.exe).
                if lower.startswith("dlls/"):
                    # Имя файла без папки.
                    file_name = relative.split("/", 1)[1]
                    # Нижний регистр имени.
                    low_name = file_name.lower()
                    # _tkinter.pyd, zlib1.dll, tcl86t.dll, tk86t.dll и т.п.
                    if low_name in self.TK_EXTRA_DLLS or (low_name.endswith(".dll") and low_name.startswith(("tcl", "tk"))):
                        destination = root / file_name
                # Пакет tkinter и модуль turtle — в runtime/Lib.
                elif lower.startswith("lib/tkinter/") or lower == "lib/turtle.py":
                    destination = root / relative
                # Библиотека скриптов Tcl/Tk — в runtime/tcl (там её ищет _tkinter).
                elif lower.startswith("tcl/"):
                    destination = root / relative
                # Ненужный файл — пропускаем.
                if destination is None:
                    continue
                # Защита от «вредных» путей.
                if not _is_within(destination.resolve(), root):
                    continue
                # Создаём папку назначения.
                destination.parent.mkdir(parents=True, exist_ok=True)
                # Копируем содержимое файла из архива.
                with bundle.open(original) as source, destination.open("wb") as target:
                    shutil.copyfileobj(source, target)
                # Увеличиваем счётчик.
                copied += 1
        # Возвращаем количество файлов.
        return copied

    @staticmethod
    def _download_reporter(
        bus: EventBus, title: str, progress: ProgressHandler, start: float, end: float
    ) -> Callable[[int, int], None]:
        """Создать обработчик прогресса скачивания: статус + полоса прогресса в диапазоне [start, end]."""
        # Последний показанный процент (храним в списке, чтобы менять из вложенной функции).
        last = [-1]

        def _report(done: int, total: int) -> None:
            """Вызывается при каждом скачанном куске."""
            # Доля скачанного (если размер неизвестен — 0).
            fraction = done / total if total else 0.0
            # Целый процент.
            percent = int(fraction * 100)
            # Обновляем окно только при смене процента.
            if percent == last[0]:
                return
            # Запоминаем процент.
            last[0] = percent
            # Текст статуса (с размером, если он известен).
            sizes = f" ({format_size(done)} из {format_size(total)})" if total else f" ({format_size(done)})"
            # Живой статус.
            bus.status(f"Скачиваю необходимые компоненты для компиляции: {title}… {percent}%{sizes}")
            # Полоса прогресса.
            progress(start + (end - start) * fraction)

        # Возвращаем обработчик.
        return _report


# ====================================================================== #
#   МЕЛКИЕ ПОМОЩНИКИ МОДУЛЯ                                               #
# ====================================================================== #

def _is_within(path: Path, parent: Path) -> bool:
    """True, если path находится внутри parent (или совпадает с ним)."""
    # relative_to выбрасывает ValueError, если путь снаружи.
    try:
        path.relative_to(parent)
        # Путь внутри.
        return True
    # Путь снаружи.
    except ValueError:
        return False


def _remove_quietly(path: Path) -> None:
    """Удалить файл, игнорируя ошибки (например, если его держит антивирус)."""
    # Пробуем удалить.
    try:
        path.unlink()
    # Не получилось — не страшно, это временный файл.
    except OSError:
        pass


def _rmtree(path: Path) -> None:
    """Удалить папку целиком, учитывая разницу API shutil.rmtree в разных версиях Python."""
    # В Python 3.12+ параметр называется onexc (onerror устарел).
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)  # type: ignore[call-arg]
    # В старых версиях — onerror.
    else:
        shutil.rmtree(path, onerror=_force_remove)


def _force_remove(function: Callable[..., Any], path: str, _exc_info: Any) -> None:
    """Обработчик ошибок shutil.rmtree: снимаем «только чтение» и пробуем ещё раз."""
    # Делаем файл доступным для записи.
    try:
        os.chmod(path, 0o700)
        # Повторяем исходную операцию (удаление файла или папки).
        function(path)
    # Если и это не помогло — пусть ошибка всплывёт при следующей операции.
    except OSError:
        pass
