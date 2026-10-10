"""
Работа с операционной системой: открытие проводника, скрытый запуск процессов.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# os — для os.startfile (открыть папку в Windows).
import os
# subprocess — для запуска проводника и других внешних программ.
import subprocess
# sys — чтобы определить текущую ОС.
import sys
# Path — удобная работа с путями к файлам.
from pathlib import Path
# Типы для подсказок.
from typing import Any

# True, если программа работает в Windows.
IS_WINDOWS = sys.platform.startswith("win")
# True, если программа работает в macOS.
IS_MAC = sys.platform == "darwin"


def hidden_subprocess_kwargs() -> dict[str, Any]:
    """
    Параметры для subprocess, которые прячут чёрное окно консоли в Windows.

    Используется на следующих этапах при запуске pip и PyInstaller,
    чтобы у пользователя не мелькали страшные чёрные окна.
    """
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


def reveal_in_explorer(path: str | Path) -> None:
    """
    Открыть проводник и выделить в нём указанный файл.
    Если передана папка — просто открыть её.
    """
    # Превращаем путь в абсолютный объект Path.
    target = Path(path).resolve()
    # Если ни файла, ни папки нет — сообщаем об этом понятной ошибкой.
    if not target.exists():
        # FileNotFoundError позже переведётся на понятный язык в errors.py.
        raise FileNotFoundError(2, "Путь не найден", str(target))

    # Ветка для Windows.
    if IS_WINDOWS:
        # Для файла — открываем папку и выделяем сам файл.
        if target.is_file():
            # Проводник требует именно такой формат: /select,"путь" (одной строкой).
            subprocess.Popen(f'explorer /select,"{target}"')
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
