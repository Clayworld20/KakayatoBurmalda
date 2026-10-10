"""
Тестовая программа для автоматической самопроверки Auto-Compiler в GitHub Actions.

Её собирает уже готовый Auto-Compiler.exe, затем собранный файл запускается и проверяет, что внутри есть всё нужное:
    * customtkinter со своими темами (проверка флага --collect-data customtkinter);
    * Pillow, импортируемый как PIL (проверка карты «импорт → pip-пакет»);
    * графический движок Tcl/Tk (проверка автодокачки tkinter во встроенный Python);
    * файл из папки assets по относительному пути (проверка --add-data и runtime-хука).
Результат записывается в файл, путь к которому передан первым аргументом.
"""

# sys — аргументы командной строки.
import sys
# tkinter — стандартная графика; Tcl() создаёт интерпретатор без окна (на сервере окна не нужны).
import tkinter
# Path — работа с путями.
from pathlib import Path

# customtkinter при импорте читает файлы тем — без --collect-data импорт упадёт.
import customtkinter
# Pillow: имя импорта PIL отличается от имени пакета pillow.
from PIL import Image


def main() -> int:
    """Проверить содержимое собранной программы и записать отчёт."""
    # Файл отчёта (абсолютный путь — текущая папка внутри .exe меняется runtime-хуком).
    report = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.home() / "autocompiler-hello.txt"
    # Ресурс из папки assets по относительному пути.
    greeting = Path("assets/greeting.txt").read_text(encoding="utf-8").strip()
    # Версия Tcl — значит, библиотеки Tcl/Tk найдены и работают.
    tcl_version = tkinter.Tcl().eval("info patchlevel")
    # Маленькая картинка — Pillow действительно работает, а не просто импортировался.
    size = Image.new("RGB", (4, 2), "navy").size
    # Записываем отчёт.
    report.write_text(
        f"OK | {greeting} | customtkinter {customtkinter.__version__} | Tcl {tcl_version} | Pillow {size}",
        encoding="utf-8",
    )
    # Успех.
    return 0


# Запуск при старте программы.
if __name__ == "__main__":
    # Передаём код завершения системе.
    sys.exit(main())
