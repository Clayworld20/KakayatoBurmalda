"""
Точка входа Авто-Компилятора.

Запуск: двойной щелчок по этому файлу или команда «python main.py».

Что делает этот файл:
    1. Проверяет версию Python.
    2. Если библиотеки интерфейса customtkinter нет — сам тихо устанавливает её через pip.
    3. Запускает главное окно, защищая запуск от любых сбоев.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# importlib — чтобы «увидеть» библиотеку, установленную прямо во время работы.
import importlib
# subprocess — для запуска pip.
import subprocess
# sys — версия Python, путь к интерпретатору, пути поиска модулей.
import sys
# traceback — текст ошибки для аварийного окна.
import traceback
# Path — работа с путями.
from pathlib import Path

# Минимальная поддерживаемая версия Python.
MIN_PYTHON = (3, 9)
# Папка, где лежит этот файл (корень проекта).
PROJECT_ROOT = Path(__file__).resolve().parent

# Добавляем корень проекта в пути поиска модулей, чтобы «import autocompiler» работал
# независимо от того, из какой папки запущен скрипт.
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def show_fatal_error(title: str, message: str) -> None:
    """Показать аварийное сообщение, даже если customtkinter недоступен."""
    # Пробуем стандартное окно tkinter (есть в любом Python для Windows).
    try:
        # Импорт внутри функции: tkinter может отсутствовать в урезанных сборках Python.
        import tkinter
        # Модуль стандартных диалогов.
        from tkinter import messagebox
        # Создаём скрытое корневое окно (без него диалог не покажется).
        root = tkinter.Tk()
        # Прячем пустое корневое окно.
        root.withdraw()
        # Показываем красный значок ошибки с текстом.
        messagebox.showerror(title, message, parent=root)
        # Удаляем корневое окно.
        root.destroy()
    # Если даже tkinter недоступен — печатаем в консоль.
    except Exception:  # noqa: BLE001
        # Вывод в стандартный поток ошибок.
        print(f"{title}\n\n{message}", file=sys.stderr)


def ensure_customtkinter() -> bool:
    """Убедиться, что customtkinter установлен; при необходимости установить. True — всё готово."""
    # Пробуем импортировать библиотеку.
    try:
        # Импорт ради проверки наличия.
        import customtkinter  # noqa: F401
        # Библиотека есть — всё хорошо.
        return True
    # Библиотеки нет — пробуем установить.
    except ImportError:
        pass

    # В собранном .exe ничего доустановить нельзя — библиотека должна быть внутри.
    if getattr(sys, "frozen", False):
        return False

    # Сообщаем в консоль (если она есть), что происходит.
    print("Устанавливаю библиотеку интерфейса customtkinter, подождите…")
    # Параметры, скрывающие чёрное окно pip в Windows.
    extra: dict = {}
    # Только для Windows.
    if sys.platform.startswith("win"):
        # CREATE_NO_WINDOW — не показывать консоль.
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    # Запуск pip может не удаться (нет интернета, нет pip и т.п.).
    try:
        # Устанавливаем библиотеку для текущего пользователя через тот же Python, что запустил программу.
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet", "customtkinter>=5.2.2"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=600,
            **extra,
        )
    # Любая ошибка установки — сообщаем «нет».
    except Exception:  # noqa: BLE001
        return False

    # Сбрасываем кэш импорта, чтобы Python увидел новую библиотеку.
    importlib.invalidate_caches()
    # Пробуем импортировать ещё раз.
    try:
        # Повторный импорт.
        import customtkinter  # noqa: F401,F811
        # Успех.
        return True
    # Всё ещё не получается.
    except ImportError:
        return False


def set_windows_app_id() -> None:
    """Попросить Windows показывать на панели задач нашу иконку, а не иконку Python."""
    # Только для Windows.
    if not sys.platform.startswith("win"):
        return
    # Вызов WinAPI может не сработать на старых системах — это не критично.
    try:
        # ctypes — вызов функций Windows напрямую.
        import ctypes
        # Уникальный идентификатор приложения для панели задач.
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("AutoCompiler.App")  # type: ignore[attr-defined]
    # Ошибку игнорируем.
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    """Главная функция. Возвращает код завершения (0 — всё хорошо)."""
    # Проверка версии Python.
    if sys.version_info < MIN_PYTHON:
        # Понятное сообщение о слишком старом Python.
        show_fatal_error(
            "Слишком старая версия Python",
            f"Нужен Python {MIN_PYTHON[0]}.{MIN_PYTHON[1]} или новее.\nУ вас: {sys.version.split()[0]}.",
        )
        # Код ошибки.
        return 1

    # Проверка/установка библиотеки интерфейса.
    if not ensure_customtkinter():
        # Понятное сообщение, если установить не удалось.
        show_fatal_error(
            "Не удалось подготовить программу",
            "Не получилось установить библиотеку интерфейса customtkinter.\n\n"
            "Проверьте подключение к интернету и запустите программу ещё раз.",
        )
        # Код ошибки.
        return 1

    # Настраиваем иконку на панели задач Windows.
    set_windows_app_id()

    # Запуск окна защищён от любых сбоев.
    try:
        # Импортируем окно только сейчас — когда customtkinter точно установлен.
        from autocompiler.gui.main_window import MainWindow
        # Создаём главное окно.
        app = MainWindow()
        # Запускаем бесконечный цикл обработки событий окна.
        app.mainloop()
    # Пользователь прервал программу через Ctrl+C в консоли — выходим тихо.
    except KeyboardInterrupt:
        return 0
    # Любая ошибка при запуске — аварийное окно с подробностями.
    except Exception:  # noqa: BLE001
        # Показываем ошибку и технические подробности.
        show_fatal_error("Программа не смогла запуститься", traceback.format_exc())
        # Код ошибки.
        return 1
    # Нормальное завершение.
    return 0


# Этот блок выполняется только при прямом запуске файла (а не при импорте).
if __name__ == "__main__":
    # Передаём код завершения операционной системе.
    sys.exit(main())
