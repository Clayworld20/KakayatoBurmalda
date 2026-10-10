"""
Точка входа Авто-Компилятора.

Запуск: двойной щелчок по этому файлу или команда «python main.py».

Что делает этот файл:
    1. Проверяет версию Python.
    2. Если библиотеки интерфейса customtkinter нет — сам тихо устанавливает её через pip.
    3. Запускает главное окно, защищая запуск от любых сбоев.

Служебный режим (для автоматической проверки в GitHub Actions, пользователю не нужен):
    Auto-Compiler.exe --selftest путь\к\скрипту.py --log лог.txt [--icon файл.ico] [--onedir] [--console]
    Выполняет всю сборку БЕЗ окна, пишет подробный лог в файл и завершается с кодом 0 (успех) или 1.
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


def run_selftest(argv: list[str]) -> int:
    """Служебный режим: собрать скрипт без окна (для проверки готового Auto-Compiler.exe в GitHub Actions)."""
    # Импорты внутри функции: обычному запуску с окном они не нужны.
    import argparse
    # threading — сборка идёт в фоне, а главный поток пишет лог.
    import threading
    # time — пауза между чтениями событий.
    import time

    # Описание параметров командной строки.
    parser = argparse.ArgumentParser(prog="Auto-Compiler --selftest", description="Сборка без окна (самопроверка).")
    # Путь к собираемому скрипту.
    parser.add_argument("script", help="главный .py-файл программы")
    # Файл подробного лога.
    parser.add_argument("--log", default="autocompiler-selftest.log", help="куда записать лог сборки")
    # Файл, куда записать путь к готовому .exe.
    parser.add_argument("--result-file", default="", help="куда записать путь к готовому .exe")
    # Иконка (необязательно).
    parser.add_argument("--icon", default="", help="иконка .ico")
    # Режим «папка» вместо одного файла.
    parser.add_argument("--onedir", action="store_true", help="собрать папку вместо одного .exe")
    # Оставить окно консоли у собранной программы.
    parser.add_argument("--console", action="store_true", help="не скрывать консоль собранной программы")
    # Неверные параметры: argparse вызывает SystemExit — превращаем его в код ошибки 2.
    try:
        # Разбираем параметры.
        args = parser.parse_args(argv)
    # Ошибка в параметрах.
    except SystemExit:
        return 2

    # Файл лога (папку создаём, если её нет).
    log_path = Path(args.log).resolve()
    # Создаём папку для лога.
    log_path.parent.mkdir(parents=True, exist_ok=True)
    # Модули компилятора импортируем здесь: окно (customtkinter) этому режиму не нужно.
    from autocompiler.core.pipeline import BuildPipeline, BuildSettings
    # Шина событий и типы событий.
    from autocompiler.utils.event_bus import EventBus, EventKind

    # Настройки сборки — как если бы пользователь выбрал их в окне.
    settings = BuildSettings(
        script_path=Path(args.script).resolve(),
        icon_path=Path(args.icon).resolve() if args.icon else None,
        hide_console=not args.console,
        one_file=not args.onedir,
    )
    # Шина событий (вместо окна её читает этот цикл).
    bus = EventBus()
    # Конвейер сборки.
    pipeline = BuildPipeline(settings, bus)
    # Фоновый поток со сборкой.
    worker = threading.Thread(target=pipeline.run, name="SelftestBuild", daemon=True)
    # Итог: успех и путь к .exe.
    result: dict = {"success": False, "output_path": None}

    # Открываем лог в UTF-8 (русский текст).
    with log_path.open("w", encoding="utf-8") as log:
        # Запускаем сборку.
        worker.start()
        # Читаем события, пока поток жив (и ещё раз после его завершения).
        while True:
            # Жив ли поток — проверяем ДО чтения, чтобы не потерять последние события.
            alive = worker.is_alive()
            # Забираем накопившиеся события.
            for event in bus.drain(1000):
                # Данные события.
                data = event.payload
                # Время события.
                stamp = event.created_at.strftime("%H:%M:%S")
                # Строка лога.
                if event.kind == EventKind.LOG:
                    log.write(f"[{stamp}] {str(data['level'].value).upper():8} {data['text']}\n")
                # Красное окно ошибки — пишем все его части.
                elif event.kind == EventKind.ERROR:
                    log.write(f"[{stamp}] !!! ОШИБКА: {data['title']}\n    {data['message']}\n    Совет: {data['hint']}\n")
                    # Технические подробности (если есть).
                    if data.get("details"):
                        log.write("    Подробности:\n" + "\n".join("      " + line for line in str(data["details"]).splitlines()) + "\n")
                # Завершение сборки — запоминаем итог.
                elif event.kind == EventKind.FINISHED:
                    result.update(success=data["success"], output_path=data["output_path"])
                    # Итоговая строка.
                    log.write(f"[{stamp}] ИТОГ: {data['summary']}\n")
            # Сразу сбрасываем на диск, чтобы лог был виден даже при зависании.
            log.flush()
            # Поток завершился и все события прочитаны — выходим.
            if not alive:
                break
            # Небольшая пауза, чтобы не грузить процессор.
            time.sleep(0.2)
        # Итоговая машинно-читаемая строка.
        log.write(f"RESULT={'OK' if result['success'] else 'FAIL'} EXE={result['output_path'] or ''}\n")

    # Путь к готовому .exe — в отдельный файл (удобно читать из скрипта CI).
    if args.result_file and result["output_path"]:
        Path(args.result_file).write_text(str(result["output_path"]), encoding="utf-8")
    # Код завершения: 0 — успех, 1 — ошибка.
    return 0 if result["success"] else 1


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

    # Служебный режим самопроверки (без окна) — для GitHub Actions.
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        # Ошибки самопроверки не должны превращаться в «вечное» окно ошибки на сервере сборки.
        try:
            # Запускаем сборку без окна.
            return run_selftest(sys.argv[2:])
        # Любой непредвиденный сбой — код 1 и текст ошибки в файл рядом.
        except Exception:  # noqa: BLE001
            # Пишем трассировку в файл, т.к. консоли у собранного .exe нет.
            Path("autocompiler-selftest-crash.log").write_text(traceback.format_exc(), encoding="utf-8")
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
