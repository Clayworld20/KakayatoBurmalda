"""
Перевод «программистских» ошибок на понятный человеку язык.

Любая ошибка внутри компилятора превращается в CompilerError с тремя частями:
    title   — короткий заголовок («Не удалось прочитать файл»);
    message — что случилось простыми словами;
    hint    — что пользователю сделать, чтобы исправить;
    details — технический текст (traceback) для опытных пользователей.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# subprocess — нужен, чтобы распознавать ошибки внешних команд (pip, PyInstaller).
import subprocess
# traceback — превращает исключение в подробный технический текст.
import traceback


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
        # Технические подробности (traceback).
        self.details = details


def format_traceback(exc: BaseException) -> str:
    """Превратить исключение в полный технический текст (для блока «Подробности»)."""
    # format_exception возвращает список строк — склеиваем их в одну.
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))


def describe_exception(exc: BaseException, stage: str = "") -> CompilerError:
    """Подобрать понятное описание для любой ошибки Python."""
    # Если ошибка уже «понятная» — возвращаем как есть.
    if isinstance(exc, CompilerError):
        return exc

    # Технические подробности нужны в любом случае.
    details = format_traceback(exc)
    # Приставка с названием этапа, на котором всё сломалось.
    where = f" на этапе «{stage}»" if stage else ""

    # Файл или папка не найдены.
    if isinstance(exc, FileNotFoundError):
        return CompilerError(
            title="Файл не найден",
            message=f"Не удалось найти файл или папку{where}:\n{exc.filename or exc}",
            hint="Проверьте, что файл не был удалён, переименован или перемещён.",
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
        return CompilerError(
            title="Ошибка в коде программы",
            message=f"В файле есть ошибка в строке {line}:\n{exc.msg}",
            hint="Исправьте ошибку в коде (обычно это опечатка, лишняя скобка или отступ) и попробуйте снова.",
            details=details,
        )

    # Внешняя команда (pip, PyInstaller) завершилась с ошибкой.
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

    # Прочие ошибки операционной системы (диск переполнен, путь слишком длинный и т.п.).
    if isinstance(exc, OSError):
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
