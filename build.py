# ============================================================================
#  СБОРЩИК ПРОГРАММЫ В ОДИН ФАЙЛ EXE (build.py)
#  --------------------------------------------------------------------------
#  Запустите:  python build.py
#  Скрипт сам проверит и установит сборщик PyInstaller (если его нет),
#  соберёт готовый AI-Agent-Manager.exe в папку dist/ и подскажет, что дальше.
#  Этот exe можно передать любому человеку — ему не нужны ни Python,
#  ни командная строка: двойной клик — и программа работает.
# ============================================================================

# --- ПОДКЛЮЧЕНИЕ БИБЛИОТЕК -----------------------------------------------------

import importlib.util  # проверка: установлен ли PyInstaller (без его запуска)
import os              # пути к папкам и разделитель для флага --add-data
import subprocess      # запуск установщика и самого сборщика
import sys             # путь к текущему Python (чтобы pip ставил в нужное место)

# --- НАСТРОЙКИ СБОРКИ -----------------------------------------------------------

APP_NAME = "AI-Agent-Manager"          # имя будущего exe-файла
ENTRY_POINT = "main.py"                # файл, с которого начинается программа
DATA_FOLDERS = ["pages", "services"]   # папки с вкладками и сервисами — кладём внутрь exe


def is_pyinstaller_installed():
    """Возвращает True, если PyInstaller уже установлен на этом компьютере."""
    return importlib.util.find_spec("PyInstaller") is not None


def install_pyinstaller():
    """Устанавливает PyInstaller через pip — точно так же, как наш автоустановщик."""
    print("Устанавливаю сборщик PyInstaller, подождите минуту...")
    subprocess.check_call([
        sys.executable, "-m", "pip", "install",       # запускаем pip тем же Python'ом
        "--disable-pip-version-check", "pyinstaller", # что именно установить
    ])


def build_command():
    """Собирает команду PyInstaller в виде списка. Возвращает список для запуска."""
    # Разделитель внутри --add-data: на Windows это ";", на Mac/Linux — ":"
    separator = ";" if os.name == "nt" else ":"

    add_data_flags = []                    # сюда сложим флаги для папок
    for folder in DATA_FOLDERS:
        # --add-data "pages;pages" означает: взять папку pages и положить
        # её внутрь exe под тем же именем, чтобы вкладки не потерялись
        add_data_flags += ["--add-data", f"{folder}{separator}{folder}"]

    return [
        sys.executable, "-m", "PyInstaller",   # запускаем сборщик через Python
        "--noconfirm",                         # перезаписывать старую сборку без вопросов
        "--onefile",                           # упаковать всё в ОДИН exe-файл
        "--noconsole",                         # без чёрного окна консоли — только программа
        "--name", APP_NAME,                    # имя exe-файла на выходе
        # Темы и оформление customtkinter — это файлы данных внутри библиотеки.
        # Без этого флага готовый exe запустится, но потеряет вкладки и цвета!
        "--collect-data", "customtkinter",
    ] + add_data_flags + [ENTRY_POINT]         # в конец — какой файл собирать


def main():
    """Главная функция: проверка -> сборка -> радостное сообщение."""
    print("=" * 60)
    print("   Сборка AI Agent Manager в один файл .exe")
    print("=" * 60)

    # Шаг 0: убеждаемся, что нас запустили из папки программы
    if not os.path.exists(ENTRY_POINT):
        print(f"Не нашёл файл {ENTRY_POINT}.")
        print("Запустите build.py из папки программы (где лежит main.py).")
        sys.exit(1)

    # Шаг 1: проверяем сборщик и при необходимости устанавливаем
    if not is_pyinstaller_installed():
        try:
            install_pyinstaller()
        except Exception:
            print("Не смог установить PyInstaller.")
            print("Пожалуйста, проверьте интернет и запустите build.py ещё раз.")
            sys.exit(1)

    # Шаг 2: собираем программу
    print("Собираю программу, это займёт 1-3 минуты, подождите...")
    result = subprocess.call(build_command())   # запускаем PyInstaller и ждём

    # Шаг 3: проверяем результат
    exe_path = os.path.join("dist", APP_NAME + ".exe")   # где должен появиться файл
    if result == 0 and os.path.exists(exe_path):
        size_mb = os.path.getsize(exe_path) / (1024 * 1024)  # размер файла в мегабайтах
        print()
        print(f"✅ Готово! Файл: {os.path.abspath(exe_path)} ({size_mb:.0f} МБ)")
        print()
        print("Что дальше:")
        print("  1. Скопируйте exe на любой компьютер с Windows.")
        print("  2. Дважды щёлкните по нему — программа запустится сама.")
        print("  3. Первый запуск может занять 10-20 секунд, а антивирус")
        print("     спросит разрешение — это обычное поведение для exe,")
        print("     собранных PyInstaller. Нажмите «Подробнее» -> «Выполнить».")
    else:
        print()
        print("❌ Сборка не удалась. Прокрутите сообщения выше:")
        print("   PyInstaller обычно пишет, что именно ему не понравилось.")
        sys.exit(1)


# Этот блок срабатывает только при запуске напрямую: python build.py
if __name__ == "__main__":
    main()
