# ============================================================================
#  ВКЛАДКА "ГЛАВНАЯ" (дашборд) — pages/home_page.py
#  --------------------------------------------------------------------------
#  Шаг 2: страница живёт своей жизнью:
#    • проверяет интернет и локальную нейросеть Ollama (каждые 5 секунд);
#    • показывает нагрузку процессора и памяти живыми полосами (каждую секунду);
#    • все тяжёлые проверки идут в фоне — окно не зависает и не лагает.
# ============================================================================

# --- ПОДКЛЮЧЕНИЕ БИБЛИОТЕК -----------------------------------------------------

import threading                       # потоки — чтобы проверки сети не тормозили окно

import customtkinter as ctk            # библиотека современного красивого интерфейса

try:
    import psutil                      # библиотека, которая измеряет нагрузку компьютера
except ImportError:
    psutil = None                      # если её вдруг нет — просто не показываем нагрузку

import theme                           # наш файл с цветами и шрифтами приложения
from services import netcheck          # наши функции проверки интернета и Ollama


def color_for_load(percent):
    """Подбирает цвет полосы по уровню нагрузки (как светофор)."""
    if percent < 60:                   # нагрузка маленькая
        return theme.COLOR_OK          # зелёный — всё спокойно
    if percent < 85:                   # нагрузка средняя
        return theme.COLOR_WAIT        # жёлтый — стоит присмотреться
    return theme.COLOR_BAD             # нагрузка высокая — красный цвет


class HomePage(ctk.CTkFrame):
    """Страница "Главная": статус системы и живые индикаторы нагрузки."""

    def __init__(self, parent):
        # Создаём страницу как прозрачную рамку (фон будет от окна)
        super().__init__(parent, fg_color="transparent")

        # Страница растягивается на всю доступную область окна
        self.grid_rowconfigure(0, weight=1)      # строка растягивается по высоте
        self.grid_columnconfigure(0, weight=1)   # столбец растягивается по ширине

        self.is_checking_network = False         # флаг: проверка сети прямо сейчас идёт?

        self.create_widgets()                    # рисуем содержимое страницы
        self.start_monitoring()                  # включаем фоновые обновления

    # ------------------------------------------------------------------ ИНТЕРФЕЙС

    def create_widgets(self):
        """Рисует все элементы, которые видит пользователь на этой странице."""

        # Внутренний контейнер — прижат к верху страницы
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="new")     # "new" = север (верх) + восток-запад
        content.grid_columnconfigure(0, weight=1)       # контейнер тянется по ширине

        # --- Заголовок страницы ---------------------------------------------------
        title = ctk.CTkLabel(
            content,
            text="👋  Привет! Это ваш центр управления",   # дружелюбное приветствие
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=22, weight="bold"),
            text_color=theme.COLOR_TEXT,                    # почти белый цвет
        )
        title.grid(row=0, column=0, padx=36, pady=(28, 2), sticky="w")

        # Подзаголовок с подсказкой, что здесь происходит
        subtitle = ctk.CTkLabel(
            content,
            text="Следим за компьютером и нейросетями в реальном времени",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_MUTED,                   # приглушённый серый
        )
        subtitle.grid(row=1, column=0, padx=36, pady=(0, 20), sticky="w")

        # --- КАРТОЧКА 1: состояние системы ----------------------------------------
        status_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,                      # тёмно-серый фон карточки
            corner_radius=16,                               # скруглённые углы, как в Win11
        )
        status_card.grid(row=2, column=0, padx=36, pady=(0, 16), sticky="ew")
        status_card.grid_columnconfigure(1, weight=1)       # колонка имён растягивается

        # Маленькая надпись-заголовок карточки
        status_title = ctk.CTkLabel(
            status_card,
            text="СОСТОЯНИЕ СИСТЕМЫ",                       # заголовок карточки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11, weight="bold"),
            text_color=theme.COLOR_MUTED,                   # серый цвет
        )
        status_title.grid(row=0, column=0, columnspan=3, padx=20, pady=(16, 10), sticky="w")

        # --- Строка "Интернет" ----------------------------------------------------
        self.internet_dot = self.make_dot(status_card)      # цветной кружок-индикатор
        self.internet_dot.grid(row=1, column=0, padx=(20, 10), pady=7)

        internet_name = ctk.CTkLabel(
            status_card,
            text="Интернет",                                # название показателя
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14),
            text_color=theme.COLOR_TEXT,
        )
        internet_name.grid(row=1, column=1, padx=0, pady=7, sticky="w")

        self.internet_value = ctk.CTkLabel(
            status_card,
            text="Проверяем...",                            # стартовый статус
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14, weight="bold"),
            text_color=theme.COLOR_WAIT,                    # жёлтый, пока проверяем
        )
        self.internet_value.grid(row=1, column=2, padx=(0, 20), pady=7, sticky="e")

        # --- Строка "Локальная Ollama" ---------------------------------------------
        self.ollama_dot = self.make_dot(status_card)        # второй кружок-индикатор
        self.ollama_dot.grid(row=2, column=0, padx=(20, 10), pady=(7, 18))

        ollama_name = ctk.CTkLabel(
            status_card,
            text="Локальная Ollama",                        # название показателя
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14),
            text_color=theme.COLOR_TEXT,
        )
        ollama_name.grid(row=2, column=1, padx=0, pady=(7, 18), sticky="w")

        self.ollama_value = ctk.CTkLabel(
            status_card,
            text="Проверяем...",                            # стартовый статус
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14, weight="bold"),
            text_color=theme.COLOR_WAIT,                    # жёлтый, пока проверяем
        )
        self.ollama_value.grid(row=2, column=2, padx=(0, 20), pady=(7, 18), sticky="e")

        # --- КАРТОЧКА 2: нагрузка компьютера ----------------------------------------
        load_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,                      # тёмно-серый фон карточки
            corner_radius=16,                               # скруглённые углы, как в Win11
        )
        load_card.grid(row=3, column=0, padx=36, pady=(0, 36), sticky="ew")
        load_card.grid_columnconfigure(0, weight=1)         # карточка тянется по ширине

        # Маленькая надпись-заголовок карточки
        load_title = ctk.CTkLabel(
            load_card,
            text="НАГРУЗКА КОМПЬЮТЕРА",                     # заголовок карточки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11, weight="bold"),
            text_color=theme.COLOR_MUTED,                   # серый цвет
        )
        load_title.grid(row=0, column=0, columnspan=2, padx=20, pady=(16, 10), sticky="w")

        # --- Процессор (CPU): подпись + проценты + полоса ----------------------------
        cpu_name = ctk.CTkLabel(
            load_card,
            text="Процессор (CPU)",                         # название показателя
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14),
            text_color=theme.COLOR_TEXT,
        )
        cpu_name.grid(row=1, column=0, padx=20, pady=(0, 4), sticky="w")

        self.cpu_percent_label = ctk.CTkLabel(
            load_card,
            text="0 %",                                     # здесь будет процент загрузки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14, weight="bold"),
            text_color=theme.COLOR_TEXT,
            width=64,                                       # фиксированная ширина, чтобы не прыгало
        )
        self.cpu_percent_label.grid(row=1, column=1, padx=(0, 20), pady=(0, 4), sticky="e")

        self.cpu_bar = ctk.CTkProgressBar(                  # сама полоса загрузки CPU
            load_card,
            height=10,                                      # тонкая изящная полоса
            corner_radius=5,                                # скруглённые концы
            fg_color=theme.COLOR_LINE,                      # серый фон "пустой" части
            progress_color=theme.COLOR_OK,                  # зелёная "заполненная" часть
        )
        self.cpu_bar.set(0)                                 # начинаем с нулевой загрузки
        self.cpu_bar.grid(row=2, column=0, columnspan=2, padx=20, pady=(0, 16), sticky="ew")

        # --- Оперативная память (RAM): подпись + проценты + полоса -------------------
        ram_name = ctk.CTkLabel(
            load_card,
            text="Оперативная память (RAM)",                # название показателя
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14),
            text_color=theme.COLOR_TEXT,
        )
        ram_name.grid(row=3, column=0, padx=20, pady=(0, 4), sticky="w")

        self.ram_percent_label = ctk.CTkLabel(
            load_card,
            text="0 %",                                     # здесь будет процент загрузки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14, weight="bold"),
            text_color=theme.COLOR_TEXT,
            width=64,                                       # фиксированная ширина, чтобы не прыгало
        )
        self.ram_percent_label.grid(row=3, column=1, padx=(0, 20), pady=(0, 4), sticky="e")

        self.ram_bar = ctk.CTkProgressBar(                  # сама полоса загрузки RAM
            load_card,
            height=10,                                      # тонкая изящная полоса
            corner_radius=5,                                # скруглённые концы
            fg_color=theme.COLOR_LINE,                      # серый фон "пустой" части
            progress_color=theme.COLOR_OK,                  # зелёная "заполненная" часть
        )
        self.ram_bar.set(0)                                 # начинаем с нулевой загрузки
        self.ram_bar.grid(row=4, column=0, columnspan=2, padx=20, pady=(0, 20), sticky="ew")

    def make_dot(self, parent):
        """Создаёт маленький круглый индикатор (цветной кружок)."""
        dot = ctk.CTkFrame(
            parent,
            width=14,                       # диаметр кружка по ширине
            height=14,                      # диаметр кружка по высоте
            corner_radius=7,                # половина размера = идеальный круг
            fg_color=theme.COLOR_WAIT,      # пока жёлтый — "ждём проверки"
        )
        dot.grid_propagate(False)           # запрещаем кружку сжиматься до нуля
        return dot                          # отдаём кружок тому, кто попросил

    # ------------------------------------------------------------------ МОНИТОРИНГ

    def start_monitoring(self):
        """Включает два фоновых "тикателя": нагрузка (1 сек) и сеть (5 сек)."""
        self.update_load()                            # сразу показываем текущую нагрузку
        self.schedule_network_check()                 # сразу запускаем первую проверку сети
        self.after(1000, self.tick_load)              # через 1 секунду — снова нагрузка
        self.after(5000, self.tick_network)           # через 5 секунд — снова сеть

    def tick_load(self):
        """Тикать каждую секунду: обновлять полосы нагрузки компьютера."""
        self.update_load()                            # обновляем полосы и проценты
        self.after(1000, self.tick_load)              # назначаем следующий тик через секунду

    def tick_network(self):
        """Тикать каждые 5 секунд: перепроверять интернет и Ollama."""
        self.schedule_network_check()                 # запускаем фоновую проверку сети
        self.after(5000, self.tick_network)           # назначаем следующий тик через 5 секунд

    def update_load(self):
        """Читает нагрузку компьютера и двигает полосы-индикаторы."""
        if psutil is None:                            # библиотеки psutil вдруг нет
            self.cpu_percent_label.configure(text="нет данных")   # показываем прочерки
            self.ram_percent_label.configure(text="нет данных")
            return                                    # и выходим, ничего не измеряя
        try:
            cpu_percent = psutil.cpu_percent(interval=None)       # загрузка ЦП в процентах
            ram_percent = psutil.virtual_memory().percent         # загрузка памяти в процентах

            # Полоса принимает значение от 0.0 до 1.0 — делим проценты на 100
            self.cpu_bar.set(cpu_percent / 100)
            self.ram_bar.set(ram_percent / 100)

            # Обновляем цифры и цвет полос по принципу светофора
            self.cpu_bar.configure(progress_color=color_for_load(cpu_percent))
            self.ram_bar.configure(progress_color=color_for_load(ram_percent))
            self.cpu_percent_label.configure(text=f"{int(cpu_percent)} %")
            self.ram_percent_label.configure(text=f"{int(ram_percent)} %")
        except Exception:
            pass  # даже если измерение не удалось — ни в коем случае не закрываем окно

    def schedule_network_check(self):
        """Запускает проверку сети в отдельном потоке (чтобы окно не замирало)."""
        if self.is_checking_network:                  # предыдущая проверка ещё идёт?
            return                                    # да — пропускаем этот тик
        self.is_checking_network = True               # помечаем: проверка запущена
        worker = threading.Thread(                    # создаём отдельный поток...
            target=self.network_check_worker,         # ...который выполнит эту функцию
            daemon=True,                              # поток закроется вместе с окном
        )
        worker.start()                                # поехали — поток работает параллельно

    def network_check_worker(self):
        """Тяжёлая работа с интернетом — выполняется в фоне, а не в окне."""
        internet_ok = netcheck.is_internet_available()    # проверяем интернет (до 10 сек)
        ollama_ok = netcheck.is_ollama_available()        # проверяем Ollama (до 2 сек)
        self.is_checking_network = False                  # проверка закончена

        def show_result():
            # Показываем результат через after — безопасный способ трогать окно из потока
            self.show_network_status(internet_ok, ollama_ok)

        try:
            self.after(0, show_result)                    # просим окно показать результат
        except Exception:
            pass  # окно уже закрыли — ничего страшного, просто выходим

    def show_network_status(self, internet_ok, ollama_ok):
        """Рисует результат проверки: зелёные или красные индикаторы."""
        if internet_ok:                                   # интернет работает
            self.internet_dot.configure(fg_color=theme.COLOR_OK)              # зелёный кружок
            self.internet_value.configure(text="Подключен ✓", text_color=theme.COLOR_OK)
        else:                                             # интернета нет
            self.internet_dot.configure(fg_color=theme.COLOR_BAD)             # красный кружок
            # Мягкая подсказка пользователю, что делать дальше
            self.internet_value.configure(text="Отключен — проверьте сеть ✗",
                                          text_color=theme.COLOR_BAD)

        if ollama_ok:                                     # локальная нейросеть запущена
            self.ollama_dot.configure(fg_color=theme.COLOR_OK)                # зелёный кружок
            self.ollama_value.configure(text="Найдена ✓", text_color=theme.COLOR_OK)
        else:                                             # Ollama не запущена
            self.ollama_dot.configure(fg_color=theme.COLOR_BAD)               # красный кружок
            self.ollama_value.configure(text="Не запущена ✗", text_color=theme.COLOR_BAD)
