"""
Перевод «программистских» ошибок на понятный человеку язык.

Любая ошибка внутри компилятора превращается в CompilerError с четырьмя частями:
    title   — короткий заголовок («Нет подключения к интернету»);
    message — что случилось простыми словами;
    hint    — что пользователю сделать, чтобы исправить;
    details — технический текст (traceback или вывод pip/PyInstaller) для опытных пользователей.

Дополнительно здесь живут специальные исключения:
    BuildCancelled     — пользователь отменил сборку (это НЕ ошибка, красное окно не нужно);
    ProcessFailedError — внешняя программа (pip, PyInstaller) завершилась с ошибкой;
    DownloadError      — файл скачался повреждённым или не полностью.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# http.client — чтобы распознать обрыв соединения во время скачивания (IncompleteRead).
import http.client
# socket — для распознавания сетевых тайм-аутов в старых версиях Python.
import socket
# ssl — для распознавания проблем с защищённым соединением (сертификаты).
import ssl
# subprocess — чтобы распознавать ошибки внешних команд и тайм-ауты процессов.
import subprocess
# traceback — превращает исключение в подробный технический текст.
import traceback
# urllib.error — ошибки HTTP-запросов (404, нет сети и т.п.).
import urllib.error
# zipfile — чтобы распознать повреждённые zip-архивы.
import zipfile
# Типы для подсказок.
from typing import Optional, Sequence


# ====================================================================== #
#   ИСКЛЮЧЕНИЯ ПРОЕКТА                                                    #
# ====================================================================== #

class CompilerError(Exception):
    """Ошибка, уже переведённая на понятный язык и готовая к показу пользователю."""

    def __init__(self, title: str, message: str, hint: str = "", details: str = "") -> None:
        # Передаём сообщение в базовый класс Exception (для str(exc) и логов).
        super().__init__(message)
        # Короткий заголовок окна ошибки.
        self.title = title
        # Основной понятный текст ошибки.
        self.message = message
        # Совет, как исправить проблему.
        self.hint = hint
        # Технические подробности (traceback или вывод внешней программы).
        self.details = details


class BuildCancelled(Exception):
    """Пользователь отменил сборку (например, закрыл окно). Красное окно НЕ показываем."""


class ProcessFailedError(Exception):
    """Внешняя программа (pip, PyInstaller, get-pip) завершилась с ненулевым кодом."""

    def __init__(
        self,
        description: str,
        command: Sequence[str],
        returncode: int,
        output_tail: Sequence[str],
        kind: str = "",
        package: str = "",
    ) -> None:
        # Короткое описание того, что запускали («Установка библиотеки requests»).
        self.description = description
        # Сама команда (список аргументов) — для технических подробностей.
        self.command = list(command)
        # Код завершения процесса.
        self.returncode = returncode
        # Последние строки вывода процесса — в них почти всегда написана причина.
        self.output_tail = list(output_tail)
        # Вид процесса: "pip", "pyinstaller", "get-pip", "python" — влияет на текст ошибки.
        self.kind = kind
        # Имя библиотеки, которую устанавливали (если это pip).
        self.package = package
        # Сообщение для базового Exception.
        super().__init__(f"{description}: код завершения {returncode}")

    @property
    def output_text(self) -> str:
        """Хвост вывода одной строкой."""
        # Склеиваем строки через перевод строки.
        return "\n".join(self.output_tail)


class DownloadError(Exception):
    """Файл скачался не полностью или с неверной контрольной суммой."""

    def __init__(self, url: str, reason: str) -> None:
        # Адрес файла, который не удалось скачать.
        self.url = url
        # Причина простыми словами.
        self.reason = reason
        # Сообщение для базового Exception.
        super().__init__(f"{reason} ({url})")


# ====================================================================== #
#   ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ                                               #
# ====================================================================== #

def format_traceback(exc: BaseException) -> str:
    """Превратить исключение в полный технический текст (для блока «Подробности»)."""
    # format_exception возвращает список строк — склеиваем их в одну.
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


# Фразы в выводе pip/PyInstaller/Windows, по которым узнаём проблемы с сетью.
_NETWORK_MARKERS = (
    # Не удалось узнать IP-адрес сайта (нет интернета или DNS).
    "getaddrinfo failed",
    # То же самое в Linux/macOS.
    "name or service not known",
    # Временная ошибка DNS.
    "temporary failure in name resolution",
    # Не удалось установить соединение.
    "newconnectionerror",
    # Не удалось установить соединение (другая формулировка).
    "failed to establish a new connection",
    # pip исчерпал попытки переподключения.
    "max retries exceeded",
    # Тайм-аут подключения.
    "connecttimeout",
    # Тайм-аут чтения данных.
    "readtimeout",
    # Соединение оборвалось.
    "connection aborted",
    # Соединение сброшено сервером или сетью.
    "connection reset",
    # Ошибка прокси-сервера.
    "proxyerror",
    # Сеть недоступна.
    "network is unreachable",
    # Нет маршрута до сервера.
    "no route to host",
    # Русская формулировка Windows: «Этот хост неизвестен».
    "хост неизвестен",
)

# Фразы, по которым узнаём проблемы с сертификатами (антивирус/прокси, неверная дата на ПК).
_SSL_MARKERS = ("certificate verify failed", "sslerror", "ssl: ", "certificate_verify_failed")

# Фразы, означающие «такой библиотеки нет в каталоге PyPI».
_NOT_FOUND_MARKERS = ("no matching distribution found", "could not find a version that satisfies")

# Фразы, означающие «библиотеку нужно компилировать из исходников, а компилятора нет».
_NEEDS_COMPILER_MARKERS = (
    # Классическое сообщение об отсутствии Visual C++.
    "microsoft visual c++",
    # pip не смог собрать колесо (wheel).
    "failed building wheel",
    # Не удалось собрать пакет.
    "failed to build",
    # Ошибка на этапе подготовки метаданных при сборке из исходников.
    "metadata-generation-failed",
    # Нужен CMake (сборка из исходников).
    "cmake",
    # Не найден Python.h — в embeddable-Python нет заголовков для компиляции.
    "python.h",
)

# Фразы о нехватке места на диске.
_DISK_FULL_MARKERS = ("no space left", "winerror 112", "not enough space", "недостаточно места")

# Фразы, означающие, что антивирус заблокировал файл.
_VIRUS_MARKERS = ("winerror 225", "contains a virus", "potentially unwanted software", "содержит вирус")

# Фразы о запрете доступа / занятом файле.
_ACCESS_MARKERS = (
    # «Отказано в доступе» по-английски.
    "access is denied",
    # Код этой ошибки в Windows.
    "winerror 5]",
    # Файл занят другим процессом.
    "winerror 32",
    # Общая ошибка прав доступа Python.
    "permissionerror",
    # Русская формулировка Windows.
    "отказано в доступе",
    # Русская формулировка «файл занят».
    "процесс не может получить доступ к файлу",
)

# Фразы о слишком длинном пути к файлу.
_LONG_PATH_MARKERS = ("winerror 206", "filename or extension is too long", "path too long", "имя файла или его расширение имеет слишком большую длину")


def _contains_any(text: str, markers: Sequence[str]) -> bool:
    """True, если в тексте встречается хотя бы одна из фраз (без учёта регистра)."""
    # Текст уже переведён в нижний регистр вызывающей стороной — просто ищем вхождения.
    return any(marker in text for marker in markers)


def _extract_missing_icon_hint(text: str) -> Optional[str]:
    """Распознать проблемы с иконкой в выводе PyInstaller."""
    # PyInstaller пишет про иконку в нескольких формулировках.
    if "icon" in text and ("not found" in text or "unable to" in text or "failed" in text or "invalid" in text):
        # Возвращаем понятное описание.
        return "PyInstaller не смог встроить выбранную иконку."
    # Иконка не при чём.
    return None


def describe_process_failure(exc: ProcessFailedError) -> CompilerError:
    """Проанализировать вывод упавшей внешней программы и подобрать понятное объяснение."""
    # Весь хвост вывода в нижнем регистре — для поиска ключевых фраз.
    text = exc.output_text.lower()
    # Технические подробности: команда + код + вывод.
    details = (
        f"{exc.description}\n"
        f"Команда: {' '.join(exc.command)}\n"
        f"Код завершения: {exc.returncode}\n\n"
        f"Последние строки вывода:\n{exc.output_text}"
    )
    # Название библиотеки для текстов с ведущим пробелом (или пустая строка, если неизвестно).
    package = f" «{exc.package}»" if exc.package else ""

    # 1. Нет интернета.
    if _contains_any(text, _NETWORK_MARKERS):
        return CompilerError(
            title="Нет подключения к интернету",
            message=f"Не удалось скачать необходимые компоненты{package}.",
            hint="Проверьте подключение к интернету (или настройки прокси/VPN) и нажмите «Собрать .exe» ещё раз.",
            details=details,
        )

    # 2. Проблемы с сертификатами (часто — антивирус или неверная дата на компьютере).
    if _contains_any(text, _SSL_MARKERS):
        return CompilerError(
            title="Не удалось установить защищённое соединение",
            message="Сервер библиотек не прошёл проверку безопасности (ошибка SSL-сертификата).",
            hint="Проверьте, что на компьютере правильные дата и время. Если включена «проверка HTTPS» в антивирусе — временно отключите её.",
            details=details,
        )

    # 3. Библиотеки нет в каталоге PyPI.
    if _contains_any(text, _NOT_FOUND_MARKERS):
        return CompilerError(
            title="Библиотека не найдена",
            message=f"Библиотека{package} не найдена в интернет-каталоге Python (PyPI) или не поддерживает Python 3.12.",
            hint=(
                "Если это ваш собственный модуль — положите его .py-файл в ту же папку, что и главный файл. "
                "Если это опечатка в import — исправьте её в коде."
            ),
            details=details,
        )

    # 4. Библиотеку нужно компилировать.
    if _contains_any(text, _NEEDS_COMPILER_MARKERS):
        return CompilerError(
            title="Библиотеку невозможно установить автоматически",
            message=f"Для библиотеки{package} нет готовой версии под Windows и Python 3.12 — её нужно компилировать из исходного кода.",
            hint="Попробуйте заменить эту библиотеку на популярный аналог или поищите её готовую сборку (файл .whl) для Python 3.12.",
            details=details,
        )

    # 5. Закончилось место на диске.
    if _contains_any(text, _DISK_FULL_MARKERS):
        return CompilerError(
            title="Закончилось место на диске",
            message="На диске не хватает свободного места для сборки.",
            hint="Освободите хотя бы 2 ГБ (очистите «Загрузки» и корзину) и попробуйте снова.",
            details=details,
        )

    # 6. Антивирус удалил или заблокировал файл.
    if _contains_any(text, _VIRUS_MARKERS):
        return CompilerError(
            title="Антивирус заблокировал файл",
            message="Антивирус принял файл сборки за угрозу и заблокировал его. Это частая ложная тревога для программ, собранных PyInstaller.",
            hint="Добавьте папку с проектом и папку компилятора в исключения антивируса (Защитник Windows → Исключения) и соберите снова.",
            details=details,
        )

    # 7. Нет доступа / файл занят.
    if _contains_any(text, _ACCESS_MARKERS):
        return CompilerError(
            title="Нет доступа к файлу",
            message="Один из файлов занят другой программой или защищён от записи.",
            hint="Закройте ранее собранную программу (если она запущена), подождите минуту, пока антивирус закончит проверку, и попробуйте снова.",
            details=details,
        )

    # 8. Слишком длинный путь.
    if _contains_any(text, _LONG_PATH_MARKERS):
        return CompilerError(
            title="Слишком длинный путь к файлам",
            message="Windows не может работать со слишком длинными путями к файлам.",
            hint="Переместите проект в папку с коротким путём, например C:\\Projects\\MyApp.",
            details=details,
        )

    # 9. Специфические ошибки PyInstaller.
    if exc.kind == "pyinstaller":
        # Проблемы с иконкой.
        icon_problem = _extract_missing_icon_hint(text)
        # Если это иконка — говорим об этом.
        if icon_problem:
            return CompilerError(
                title="Проблема с иконкой",
                message=icon_problem,
                hint="Выберите другой .ico-файл или уберите иконку крестиком и соберите снова.",
                details=details,
            )
        # Слишком глубокая рекурсия при анализе импортов.
        if "recursionerror" in text or "maximum recursion depth" in text:
            return CompilerError(
                title="Слишком сложная структура программы",
                message="Упаковщик запутался в зависимостях программы (слишком глубокая цепочка импортов).",
                hint="Попробуйте собрать в режиме папки (выключите «Собрать в один-единственный файл»). Если не поможет — отправьте подробности разработчику.",
                details=details,
            )
        # Устаревшие пакеты-«заглушки», несовместимые с PyInstaller.
        if "obsolete backport" in text:
            return CompilerError(
                title="Мешает устаревшая библиотека",
                message="В среде установлен устаревший пакет (например, pathlib или typing), несовместимый с упаковщиком.",
                hint="Уберите этот импорт из кода — в современных версиях Python он уже встроен.",
                details=details,
            )
        # Не найден файл ресурса.
        if "unable to find" in text and "data" in text:
            return CompilerError(
                title="Не найден файл ресурса",
                message="Один из файлов картинок/звуков/данных, используемых программой, не найден при упаковке.",
                hint="Проверьте, что все папки с ресурсами лежат рядом с главным файлом программы.",
                details=details,
            )
        # Синтаксическая ошибка в одном из модулей проекта.
        if "syntaxerror" in text:
            return CompilerError(
                title="Ошибка в коде одного из модулей",
                message="В одном из файлов вашего проекта есть синтаксическая ошибка.",
                hint="Откройте «Подробности» — там указан файл и строка с ошибкой. Исправьте её и соберите снова.",
                details=details,
            )
        # Общая ошибка PyInstaller.
        return CompilerError(
            title="Сборка .exe не удалась",
            message="Упаковщик PyInstaller завершился с ошибкой.",
            hint="Посмотрите последние красные строки в логе. Попробуйте режим папки (выключите «один файл») — он устойчивее.",
            details=details,
        )

    # 10. Общая ошибка установки библиотеки.
    if exc.kind == "pip":
        return CompilerError(
            title="Не удалось установить библиотеку",
            message=f"Установка библиотеки{package} завершилась с ошибкой.",
            hint="Проверьте подключение к интернету и попробуйте снова. Подробная причина — в «Подробностях».",
            details=details,
        )

    # 11. Ошибка установки pip во встроенный Python.
    if exc.kind == "get-pip":
        return CompilerError(
            title="Не удалось подготовить установщик библиотек",
            message="Не получилось установить pip во встроенный Python.",
            hint="Проверьте подключение к интернету. Если ошибка повторяется — удалите папку runtime рядом с программой и попробуйте снова.",
            details=details,
        )

    # 12. Всё остальное.
    return CompilerError(
        title="Внешняя программа завершилась с ошибкой",
        message=f"{exc.description} завершилась с кодом {exc.returncode}.",
        hint="Посмотрите последние строки в логе — там обычно указана причина.",
        details=details,
    )


# ====================================================================== #
#   ГЛАВНЫЙ ПЕРЕВОДЧИК                                                    #
# ====================================================================== #

def describe_exception(exc: BaseException, stage: str = "") -> CompilerError:
    """Подобрать понятное описание для любой ошибки Python."""
    # Если ошибка уже «понятная» — возвращаем как есть.
    if isinstance(exc, CompilerError):
        return exc

    # Технические подробности нужны в любом случае.
    details = format_traceback(exc)
    # Приставка с названием этапа, на котором всё сломалось.
    where = f" на этапе «{stage}»" if stage else ""

    # Отмена — не ошибка, но на всякий случай даём понятный текст.
    if isinstance(exc, BuildCancelled):
        return CompilerError(title="Сборка отменена", message="Сборка была остановлена пользователем.", details=details)

    # Упала внешняя программа — анализируем её вывод.
    if isinstance(exc, ProcessFailedError):
        return describe_process_failure(exc)

    # Файл скачался повреждённым.
    if isinstance(exc, DownloadError):
        return CompilerError(
            title="Файл скачался с ошибкой",
            message=f"Не удалось корректно скачать файл{where}:\n{exc.reason}",
            hint="Скорее всего, оборвалось соединение. Проверьте интернет и попробуйте снова.",
            details=details,
        )

    # HTTP-ошибка (сервер ответил, но с кодом ошибки). Проверяем ДО URLError — это его подкласс.
    if isinstance(exc, urllib.error.HTTPError):
        # 404/410 — файла больше нет на сервере.
        if exc.code in (404, 410):
            return CompilerError(
                title="Файл не найден на сервере",
                message=f"Сервер сообщил, что нужного файла больше нет (код {exc.code}):\n{exc.url}",
                hint="Возможно, вышла новая версия компилятора — обновите программу.",
                details=details,
            )
        # Прочие коды — проблемы на стороне сервера.
        return CompilerError(
            title="Сервер временно недоступен",
            message=f"Сервер ответил ошибкой {exc.code}{where}.",
            hint="Подождите несколько минут и попробуйте снова.",
            details=details,
        )

    # Проблема с сертификатом. Проверяем ДО URLError: URLError часто «оборачивает» SSLError.
    ssl_reason = getattr(exc, "reason", None)
    # SSLError может прийти как сам по себе, так и внутри URLError.reason.
    if isinstance(exc, ssl.SSLError) or isinstance(ssl_reason, ssl.SSLError):
        return CompilerError(
            title="Не удалось установить защищённое соединение",
            message=f"Ошибка проверки SSL-сертификата{where}.",
            hint="Проверьте, что на компьютере правильные дата и время, и отключите «проверку HTTPS» в антивирусе.",
            details=details,
        )

    # Нет сети: URLError, тайм-аут, разрыв соединения, неполное чтение.
    if isinstance(exc, (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, http.client.IncompleteRead)):
        return CompilerError(
            title="Нет подключения к интернету",
            message=f"Не удалось скачать необходимые компоненты{where}.",
            hint="Проверьте подключение к интернету (или настройки прокси/VPN) и нажмите «Собрать .exe» ещё раз.",
            details=details,
        )

    # Повреждённый zip-архив.
    if isinstance(exc, zipfile.BadZipFile):
        return CompilerError(
            title="Архив повреждён",
            message=f"Скачанный архив оказался повреждённым{where}.",
            hint="Попробуйте ещё раз — файл будет скачан заново.",
            details=details,
        )

    # Внешняя программа работала слишком долго.
    if isinstance(exc, subprocess.TimeoutExpired):
        return CompilerError(
            title="Операция заняла слишком много времени",
            message=f"Внешняя программа не ответила за отведённое время{where}.",
            hint="Проверьте скорость интернета и попробуйте снова. Большие библиотеки (например, torch) могут скачиваться очень долго.",
            details=details,
        )

    # Файл или папка не найдены.
    if isinstance(exc, FileNotFoundError):
        return CompilerError(
            title="Файл не найден",
            message=f"Не удалось найти файл или папку{where}:\n{exc.filename or exc}",
            hint="Проверьте, что файл не был удалён, переименован или перемещён (иногда файлы удаляет антивирус).",
            details=details,
        )

    # Нет прав доступа (файл занят, папка защищена).
    if isinstance(exc, PermissionError):
        return CompilerError(
            title="Нет доступа к файлу",
            message=f"Windows запретила доступ к файлу{where}:\n{exc.filename or exc}",
            hint=(
                "Закройте программы, которые могут использовать этот файл "
                "(в том числе ранее собранный .exe), или выберите другую папку."
            ),
            details=details,
        )

    # Файл в непонятной кодировке.
    if isinstance(exc, UnicodeDecodeError):
        return CompilerError(
            title="Не удалось прочитать текст файла",
            message=f"Файл сохранён в неизвестной кодировке{where}.",
            hint="Откройте файл в редакторе и сохраните его в кодировке UTF-8.",
            details=details,
        )

    # Синтаксическая ошибка в коде пользователя.
    if isinstance(exc, SyntaxError):
        # Номер строки может отсутствовать — подставляем «?».
        line = exc.lineno if exc.lineno is not None else "?"
        # Имя файла, в котором ошибка (может быть не главный файл, а модуль проекта).
        filename = f" «{exc.filename}»" if exc.filename else ""
        return CompilerError(
            title="Ошибка в коде программы",
            message=f"В файле{filename} есть ошибка в строке {line}:\n{exc.msg}",
            hint="Исправьте ошибку в коде (обычно это опечатка, лишняя скобка или отступ) и попробуйте снова.",
            details=details,
        )

    # Внешняя команда (через subprocess.run(check=True)) завершилась с ошибкой.
    if isinstance(exc, subprocess.CalledProcessError):
        return CompilerError(
            title="Внешний инструмент завершился с ошибкой",
            message=f"Команда завершилась с кодом {exc.returncode}{where}.",
            hint="Посмотрите последние красные строки в логе — там обычно указана причина.",
            details=details,
        )

    # Не хватает оперативной памяти.
    if isinstance(exc, MemoryError):
        return CompilerError(
            title="Не хватает памяти",
            message=f"Компьютеру не хватило оперативной памяти{where}.",
            hint="Закройте лишние программы и попробуйте снова.",
            details=details,
        )

    # Прочие ошибки ОС — уточняем по коду ошибки Windows.
    if isinstance(exc, OSError):
        # Код ошибки Windows (есть только в Windows, иначе None).
        winerror = getattr(exc, "winerror", None)
        # 112 — диск заполнен.
        if winerror == 112:
            return CompilerError(
                title="Закончилось место на диске",
                message=f"На диске не хватает места{where}.",
                hint="Освободите хотя бы 2 ГБ и попробуйте снова.",
                details=details,
            )
        # 225 — антивирус заблокировал файл.
        if winerror == 225:
            return CompilerError(
                title="Антивирус заблокировал файл",
                message=f"Антивирус заблокировал файл{where}. Это частая ложная тревога.",
                hint="Добавьте папку проекта и папку компилятора в исключения антивируса.",
                details=details,
            )
        # 206 — слишком длинный путь.
        if winerror == 206:
            return CompilerError(
                title="Слишком длинный путь к файлам",
                message=f"Путь к файлам слишком длинный для Windows{where}.",
                hint="Переместите проект в папку с коротким путём, например C:\\Projects\\MyApp.",
                details=details,
            )
        # Остальные ошибки ОС.
        return CompilerError(
            title="Ошибка операционной системы",
            message=f"Windows сообщила об ошибке{where}:\n{exc}",
            hint="Проверьте свободное место на диске и попробуйте переместить проект в папку с коротким путём (например, C:\\Projects).",
            details=details,
        )

    # Всё остальное — непредвиденная ошибка.
    return CompilerError(
        title="Непредвиденная ошибка",
        message=f"Что-то пошло не так{where}:\n{type(exc).__name__}: {exc}",
        hint="Попробуйте ещё раз. Если ошибка повторяется — скопируйте подробности и отправьте разработчику.",
        details=details,
    )
