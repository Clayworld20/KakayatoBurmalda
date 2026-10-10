# ============================================================================
#  AI AGENT MANAGER — Шаг 2 из 4: автоустановка библиотек + живой дашборд
#  --------------------------------------------------------------------------
#  Этот файл — "точка входа" программы. Больше НЕ нужно вводить "pip install":
#  программа сама проверит и установит все библиотеки при первом запуске,
#  а затем откроет главное окно с вкладками "Главная", "Мозг" и "Робот".
#
#  Как запустить программу (одна команда):
#      python main.py
# ============================================================================

# --- АВТОУСТАНОВЩИК БИБЛИОТЕК (работает до открытия окна) ---------------------

import sys          # даёт путь к Python, чтобы правильно запустить установщик pip
import subprocess   # умеет запускать другие программы — нам он нужен для запуска pip

# Список библиотек, которые нужны программе.
# Записано парой: "название для установки" -> "название при подключении в коде".
REQUIRED_LIBRARIES = {
    "customtkinter": "customtkinter",  # красивый тёмный интерфейс программы
    "psutil":        "psutil",         # измерение нагрузки процессора и памяти
    "pyautogui":     "pyautogui",      # управление мышкой и клавиатурой (для робота)
    "requests":      "requests",       # общение с нейросетями через интернет
    "pillow":        "PIL",            # работа со скриншотами (подключается как PIL)
}


def show_error_window(error_text):
    """Показывает простое понятное окно с ошибкой (работает без красивых библиотек)."""
    try:
        # tkinter — встроенная в Python библиотека простых окошек
        import tkinter.messagebox as messagebox
        messagebox.showerror("AI Agent Manager", error_text)  # само окошко с ошибкой
    except Exception:
        # Если даже окошки недоступны — хотя бы напечатаем текст в консоль
        print(error_text)


def find_missing_libraries():
    """Возвращает список библиотек, которые не получилось подключить."""
    missing = []                               # сюда сложим названия недостающих
    for pip_name, import_name in REQUIRED_LIBRARIES.items():
        try:
            __import__(import_name)            # пробуем подключить библиотеку
        except ImportError:
            # Библиотеки нет — запоминаем её установочное имя
            missing.append(pip_name)
    return missing


def install_missing_libraries():
    """Проверяет библиотеки и САМ устанавливает недостающие через pip."""
    missing = find_missing_libraries()         # ищем, чего не хватает
    if not missing:                            # если всё на месте...
        return                                 # ...просто продолжаем запуск

    # Понятное сообщение для пользователя в консоли
    print("Устанавливаю необходимые компоненты для первого запуска, подождите...")
    for name in missing:                       # перечисляем, что именно ставим
        print(f"   → устанавливаю: {name}")

    try:
        # Запускаем установку командой: python -m pip install <названия>
        subprocess.check_call(
            [sys.executable, "-m", "pip", "install", "--disable-pip-version-check"] + missing
        )
    except Exception:
        # Сюда попадаем, если установки не вышло (чаще всего — нет интернета)
        show_error_window(
            "Не удалось автоматически установить компоненты.\n\n"
            "Пожалуйста, проверьте интернет и запустите программу ещё раз.\n\n"
            "Если не поможет — откройте командную строку и введите вручную:\n"
            "pip install " + " ".join(missing)
        )
        raise SystemExit                       # вежливо закрываем программу

    # После установки проверяем ещё раз: всё ли теперь на месте
    still_missing = find_missing_libraries()
    if still_missing:
        show_error_window(
            "Компоненты установились не полностью.\n\n"
            "Пожалуйста, проверьте интернет и запустите программу ещё раз."
        )
        raise SystemExit


# --- ПРОВЕРКА ОКОННОЙ БИБЛИОТЕКИ PYTHON ----------------------------------------

# tkinter должна быть встроена в Python. Если её нет — окна вообще не открыть.
try:
    import tkinter.messagebox as messagebox    # простые окошки сообщений
except ImportError:
    print("Похоже, Python установлен без оконной библиотеки tkinter.")
    print("Переустановите Python с сайта python.org и отметьте галочку 'tcl/tk'.")
    raise SystemExit                           # вежливо завершаем программу

# Запускаем автоустановщик — дальше все библиотеки гарантированно на месте
install_missing_libraries()

# --- ПОДКЛЮЧЕНИЕ ОСТАЛЬНЫХ БИБЛИОТЕК -------------------------------------------

# Теперь красивую библиотеку можно подключать смело (её только что установили)
try:
    import customtkinter as ctk
except ImportError:
    messagebox.showerror(
        "Не хватает одного модуля",
        "Программе нужна библиотека customtkinter.\n\n"
        "Откройте командную строку и введите:\n\n"
        "pip install customtkinter\n\n"
        "После этого запустите программу ещё раз.",
    )
    raise SystemExit

# Подключаем наши собственные модули (лежат рядом с этим файлом)
import theme                            # цвета и шрифты приложения
from pages.home_page import HomePage    # вкладка "Главная"
from pages.brain_page import BrainPage  # вкладка "Мозг"
from pages.robot_page import RobotPage  # вкладка "Робот"


class App(ctk.CTk):
    """Главное окно программы: боковое меню + область для вкладок."""

    def __init__(self):
        # Запускаем конструктор родительского класса (само окно)
        super().__init__(fg_color=theme.COLOR_WINDOW)

        # --- Внешний вид окна -------------------------------------------------
        ctk.set_appearance_mode("dark")            # включаем тёмную тему
        ctk.set_default_color_theme("blue")        # стандартная синяя палитра кнопок

        self.title("AI Agent Manager")             # надпись на верхней полоске окна
        self.geometry("1100x680")                  # размер окна: ширина x высота
        self.minsize(900, 600)                     # меньше этого размера окно не сожмётся
        self.center_window(1100, 680)              # ставим окно по центру экрана

        # --- Список вкладок: (служебное имя, надпись в меню, класс страницы) ---
        self.pages_config = [
            ("home",  "🏠   Главная", HomePage),   # первая кнопка меню
            ("brain", "🧠   Мозг",    BrainPage),  # вторая кнопка меню
            ("robot", "🤖   Робот",   RobotPage),  # третья кнопка меню
        ]

        # --- Собираем окно из двух частей --------------------------------------
        self.create_sidebar()                      # слева — панель с меню
        self.create_content_area()                 # справа — область со страницами

        # Показываем первую вкладку ("Главная") сразу после запуска
        self.show_page("home")

    def center_window(self, width, height):
        """Ставит окно ровно по центру экрана (по красоте)."""
        self.update_idletasks()                    # просим tkinter посчитать размеры
        screen_w = self.winfo_screenwidth()        # узнаём ширину экрана
        screen_h = self.winfo_screenheight()       # узнаём высоту экрана
        x = (screen_w - width) // 2                # отступ слева, чтобы centered
        y = (screen_h - height) // 3               # отступ сверху (чуть выше центра)
        self.geometry(f"{width}x{height}+{x}+{y}") # применяем позицию окна

    def create_sidebar(self):
        """Рисуем левую тёмную панель с логотипом и кнопками меню."""

        # Сама панель: тёмная, прижата к левому краю, без скруглений
        self.sidebar = ctk.CTkFrame(
            self,
            width=240,                             # ширина панели в пикселях
            corner_radius=0,                       # углы не скругляем — панель во всю высоту
            fg_color=theme.COLOR_SIDEBAR,          # очень тёмный цвет панели
        )
        self.sidebar.grid(row=0, column=0, sticky="ns")  # растягиваем по высоте окна
        self.sidebar.grid_propagate(False)         # запрещаем панели сжиматься под содержимое

        # Внутренняя сетка панели: строка-распорка (№10) тянется и толкает
        # версию программы в самый низ
        self.sidebar.grid_rowconfigure(10, weight=1)

        # --- Логотип приложения -------------------------------------------------
        logo = ctk.CTkLabel(
            self.sidebar,
            text="🤖 AI Agent\nManager",           # название программы в две строки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=20, weight="bold"),
            text_color=theme.COLOR_TEXT,           # почти белый цвет текста
            justify="left",                        # выравнивание строк по левому краю
        )
        logo.grid(row=0, column=0, padx=24, pady=(28, 2), sticky="w")

        # Маленькая подпись под логотипом
        slogan = ctk.CTkLabel(
            self.sidebar,
            text="центр управления ИИ",            # пояснение под названием
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            text_color=theme.COLOR_MUTED,          # приглушённый серый
        )
        slogan.grid(row=1, column=0, padx=24, pady=(0, 18), sticky="w")

        # Тонкая разделительная линия под шапкой панели
        line = ctk.CTkFrame(self.sidebar, fg_color=theme.COLOR_LINE, height=1)
        line.grid(row=2, column=0, padx=20, pady=(0, 16), sticky="ew")

        # --- Кнопки меню (создаём в цикле из списка вкладок) ---------------------
        self.nav_buttons = {}                      # словарь: имя вкладки -> её кнопка

        for index, (page_id, label, _) in enumerate(self.pages_config):
            button = ctk.CTkButton(
                self.sidebar,
                text=label,                        # надпись кнопки с эмодзи
                font=ctk.CTkFont(family=theme.FONT_FAMILY, size=15),
                anchor="w",                        # текст прижат влево, как в Win11
                height=44,                         # повыше обычной — удобно нажимать
                corner_radius=10,                  # скруглённые углы кнопки
                fg_color="transparent",            # обычная кнопка сливается с панелью
                hover_color=theme.COLOR_HOVER,     # подсветка при наведении мышки
                text_color=theme.COLOR_TEXT,       # цвет надписи кнопки
                # При клике — открываем вкладку с именем page_id
                command=lambda pid=page_id: self.show_page(pid),
            )
            # Раскладываем кнопки одна под другой, растягивая по ширине панели
            button.grid(row=3 + index, column=0, padx=14, pady=5, sticky="ew")
            self.nav_buttons[page_id] = button     # запоминаем кнопку по имени вкладки

        # --- Подпись версии в самом низу панели ----------------------------------
        version = ctk.CTkLabel(
            self.sidebar,
            text="Версия 0.4 · Шаг 4",             # текущий этап разработки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11),
            text_color=theme.COLOR_MUTED,          # почти незаметный серый
        )
        version.grid(row=11, column=0, padx=24, pady=16, sticky="w")

    def create_content_area(self):
        """Готовим правую область, где будут появляться страницы-вкладки."""

        # Контейнер на всю оставшуюся ширину окна
        self.container = ctk.CTkFrame(self, fg_color="transparent")
        self.container.grid(row=0, column=1, sticky="nsew")  # занимает всё место

        # Все страницы лежат в одной ячейке сетки, поверх друг друга
        self.container.grid_rowconfigure(0, weight=1)
        self.container.grid_columnconfigure(0, weight=1)

        # Создаём три страницы и складываем их в стопку
        self.pages = {}                            # словарь: имя вкладки -> страница

        for page_id, _, page_class in self.pages_config:
            page = page_class(self.container)      # создаём страницу
            page.grid(row=0, column=0, sticky="nsew")  # кладём в общую ячейку
            self.pages[page_id] = page             # запоминаем страницу по имени

    def show_page(self, page_id):
        """Показывает нужную вкладку и подсвечивает её кнопку в меню."""

        # Поднимаем наверх в стопке именно ту страницу, которую попросили
        self.pages[page_id].tkraise()

        # Перекрашиваем кнопки меню: активная — синяя, остальные — прозрачные
        for button_id, button in self.nav_buttons.items():
            if button_id == page_id:               # это кнопка открытой вкладки
                button.configure(
                    fg_color=theme.COLOR_ACCENT,           # синий фон
                    hover_color=theme.COLOR_ACCENT,        # при наведении не меняется
                )
            else:                                  # это кнопки остальных вкладок
                button.configure(
                    fg_color="transparent",                # сливаются с панелью
                    hover_color=theme.COLOR_HOVER,         # обычная подсветка
                )


# --- ЗАПУСК ПРОГРАММЫ ---------------------------------------------------------

# Этот блок срабатывает только если файл запустили напрямую: python main.py
if __name__ == "__main__":
    try:
        app = App()            # создаём главное окно со всеми вкладками
        app.mainloop()         # запускаем окно (программа работает, пока его не закрыли)
    except Exception as error: # если что-то пошло не так при запуске...
        # ...показываем понятное окно с ошибкой вместо аварийного закрытия
        messagebox.showerror(
            "Ошибка запуска",
            "Программа не смогла запуститься.\n\n"
            f"Техническая информация (можно отправить разработчику):\n{error}",
        )
