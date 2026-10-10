# ============================================================================
#  ВКЛАДКА "МОЗГ" (управление нейросетями) — pages/brain_page.py
#  --------------------------------------------------------------------------
#  Шаг 3 (+ расширение списка моделей): страница разделена на две зоны:
#    СЛЕВА — бесплатный локальный ИИ: 7 моделей в трёх категориях, подсказка
#            о требованиях к памяти, скачивание через Ollama с прогресс-баром.
#    СПРАВА — облачный ИИ: поля для API-ключей Claude / OpenAI, сохранение
#             в config.json и кнопка "Проверить связь".
# ============================================================================

# --- ПОДКЛЮЧЕНИЕ БИБЛИОТЕК -----------------------------------------------------

import threading                       # потоки — скачивание не должно тормозить окно

import customtkinter as ctk            # библиотека современного красивого интерфейса
import tkinter.messagebox as messagebox  # простые понятные окошки сообщений

import theme                           # наш файл с цветами и шрифтами приложения
from services import netcheck          # проверка: запущена ли Ollama
from services import config_manager    # сохранение и чтение API-ключей
from services import cloud_api         # проверка облачных ключей Claude / OpenAI
from services import ollama_client     # скачивание моделей через Ollama

# Список моделей для выпадающего меню, разбитый на три категории:
# "понятная надпись" -> "техническое имя для Ollama"
MODEL_CHOICES = {
    # --- Сверхлегкие (для старых ноутбуков и слабых ПК) ---
    "Сверхлегкая (быстрая, мало памяти) — Llama 3.2 1B": "llama3.2:1b",
    "Универсальная легкая (от Microsoft) — Phi-3.5 3.8B": "phi3.5",
    # --- Оптимальные (золотой стандарт, нужен средний ПК с видеокартой) ---
    "Стандартная умная (от Meta) — Llama 3 8B": "llama3:8b",
    "Новая сбалансированная (рекомендуется) — Llama 3.1 8B": "llama3.1",
    "Мощная и быстрая (от Alibaba) — Qwen 2.5 7B": "qwen2.5:7b",
    # --- Тяжелые (для мощных игровых ПК с хорошей видеокартой) ---
    "Продвинутая тяжелая (очень умная) — Qwen 2.5 14B": "qwen2.5:14b",
    "Максимальная (требуется много VRAM) — Mistral Large 22B": "mistral-large",
}

# Подсказка для каждой модели: сколько памяти ей нужно (показывается под списком)
MODEL_HINTS = {
    "Сверхлегкая (быстрая, мало памяти) — Llama 3.2 1B":
        "💡 Достаточно 4 ГБ оперативной памяти — подойдет даже старому ноутбуку.",
    "Универсальная легкая (от Microsoft) — Phi-3.5 3.8B":
        "💡 Рекомендуется 8 ГБ оперативной памяти. Умная, но при этом легкая.",
    "Стандартная умная (от Meta) — Llama 3 8B":
        "💡 Рекомендуется минимум 8 ГБ оперативной памяти, лучше с видеокартой.",
    "Новая сбалансированная (рекомендуется) — Llama 3.1 8B":
        "💡 Рекомендуется минимум 8 ГБ оперативной памяти. Лучший выбор для начала!",
    "Мощная и быстрая (от Alibaba) — Qwen 2.5 7B":
        "💡 Рекомендуется 8 ГБ оперативной памяти и любая видеокарта.",
    "Продвинутая тяжелая (очень умная) — Qwen 2.5 14B":
        "💡 Нужно 16 ГБ оперативной памяти или видеокарта с 12 ГБ видеопамяти.",
    "Максимальная (требуется много VRAM) — Mistral Large 22B":
        "⚠️ Требуется мощная видеокарта и очень много памяти. Только для игровых ПК!",
}


class BrainPage(ctk.CTkFrame):
    """Страница "Мозг": выбор мозга для робота — локального или облачного."""

    def __init__(self, parent):
        # Создаём страницу как прозрачную рамку (фон будет от окна)
        super().__init__(parent, fg_color="transparent")

        # Страница растягивается на всю доступную область окна
        self.grid_rowconfigure(0, weight=1)      # строка растягивается по высоте
        self.grid_columnconfigure(0, weight=1)   # столбец растягивается по ширине

        self.is_downloading = False              # флаг: модель прямо сейчас скачивается?
        self.is_checking_key = False             # флаг: ключ прямо сейчас проверяется?
        self.last_percent_shown = None           # последний показанный процент (чтобы не спамить)

        self.create_widgets()                    # рисуем содержимое страницы
        self.load_saved_keys()                   # подставляем сохранённые ключи в поля
        self.start_ollama_check()                # сразу проверяем, запущена ли Ollama

    # ------------------------------------------------------------------ ИНТЕРФЕЙС

    def create_widgets(self):
        """Рисует все элементы, которые видит пользователь на этой странице."""

        # Внутренний контейнер — прижат к верху страницы
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="new")     # прижимаем к верху и растягиваем
        content.grid_columnconfigure(0, weight=1)       # левая колонка растягивается
        content.grid_columnconfigure(1, weight=1)       # правая колонка растягивается

        # --- Заголовок страницы ---------------------------------------------------
        title = ctk.CTkLabel(
            content,
            text="🧠  Управление нейросетями",               # заголовок вкладки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=22, weight="bold"),
            text_color=theme.COLOR_TEXT,                    # почти белый цвет
        )
        title.grid(row=0, column=0, columnspan=2, padx=36, pady=(28, 2), sticky="w")

        # Подзаголовок с объяснением простыми словами
        subtitle = ctk.CTkLabel(
            content,
            text="Выберите, откуда робот будет брать ум: бесплатно с вашего ПК или из облака",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_MUTED,                   # приглушённый серый
        )
        subtitle.grid(row=1, column=0, columnspan=2, padx=36, pady=(0, 20), sticky="w")

        # =====================================================================
        #  ЗОНА 1 (ЛЕВАЯ КАРТОЧКА): локальный ИИ
        # =====================================================================
        local_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,                      # тёмно-серый фон карточки
            corner_radius=16,                               # скруглённые углы, как в Win11
        )
        local_card.grid(row=2, column=0, padx=(36, 8), pady=(0, 36), sticky="nsew")
        local_card.grid_columnconfigure(0, weight=1)        # карточка тянется по ширине

        # Маленькая надпись-заголовок зоны
        local_title = ctk.CTkLabel(
            local_card,
            text="БЕСПЛАТНЫЙ ИИ НА ВАШЕМ ПК (ЛОКАЛЬНЫЙ)",   # название зоны
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11, weight="bold"),
            text_color=theme.COLOR_MUTED,
        )
        local_title.grid(row=0, column=0, padx=20, pady=(16, 6), sticky="w")

        # Объяснение для новичка, что это такое и что нужно
        local_hint = ctk.CTkLabel(
            local_card,
            text="Такая нейросеть работает прямо на компьютере, без интернета и бесплатно.\n"
                 "Нужна маленькая программа-помощник Ollama (ollama.com).",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            text_color=theme.COLOR_MUTED,                   # серый цвет подсказки
            justify="left",                                 # выравнивание по левому краю
            wraplength=360,                                 # переносить длинные строки
        )
        local_hint.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        # Строка статуса: запущена ли программа Ollama
        self.ollama_status_label = ctk.CTkLabel(
            local_card,
            text="Программа Ollama: проверяем...",          # стартовый текст статуса
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
            text_color=theme.COLOR_WAIT,                    # жёлтый, пока проверяем
        )
        self.ollama_status_label.grid(row=2, column=0, padx=20, pady=(0, 10), sticky="w")

        # Подпись над выпадающим списком
        model_caption = ctk.CTkLabel(
            local_card,
            text="Выберите модель:",                        # простая подсказка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_TEXT,
        )
        model_caption.grid(row=3, column=0, padx=20, pady=(0, 6), sticky="w")

        # Выпадающий список моделей (CTkOptionMenu)
        self.model_menu = ctk.CTkOptionMenu(
            local_card,
            values=list(MODEL_CHOICES.keys()),              # семь понятных вариантов
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            fg_color=theme.COLOR_LINE,                      # тёмный фон меню
            button_color=theme.COLOR_ACCENT,                # синяя стрелочка справа
            button_hover_color=theme.COLOR_HOVER,           # подсветка при наведении
            height=36,                                      # повыше — удобнее нажимать
            command=self.on_model_changed,                  # вызов при выборе модели
        )
        self.model_menu.grid(row=4, column=0, padx=20, pady=(0, 6), sticky="ew")

        # По умолчанию предлагаем рекомендованную (золотую середину)
        self.model_menu.set("Новая сбалансированная (рекомендуется) — Llama 3.1 8B")

        # Подсказка о требованиях выбранной модели (обновляется при выборе)
        self.model_hint_label = ctk.CTkLabel(
            local_card,
            text="",                                        # текст подставит функция ниже
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            text_color=theme.COLOR_MUTED,                   # серый цвет по умолчанию
            justify="left",
            wraplength=360,                                 # переносить длинные подсказки
        )
        self.model_hint_label.grid(row=5, column=0, padx=20, pady=(0, 14), sticky="w")
        self.apply_model_hint(self.model_menu.get())        # сразу показываем подсказку

        # Главная кнопка зоны: скачать и установить выбранную модель
        self.download_button = ctk.CTkButton(
            local_card,
            text="⬇  Скачать и установить",                 # надпись на кнопке
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14, weight="bold"),
            height=42,                                      # высокая кнопка — главная здесь
            corner_radius=10,                               # скруглённые углы
            fg_color=theme.COLOR_ACCENT,                    # синий фон
            hover_color=theme.COLOR_HOVER,                  # подсветка при наведении
            command=self.on_download_clicked,               # что делать при нажатии
        )
        self.download_button.grid(row=6, column=0, padx=20, pady=(0, 14), sticky="ew")

        # Полоса прогресса скачивания (по умолчанию пустая)
        self.model_progress = ctk.CTkProgressBar(
            local_card,
            height=10,                                      # тонкая изящная полоса
            corner_radius=5,                                # скруглённые концы
            fg_color=theme.COLOR_LINE,                      # серый фон "пустой" части
            progress_color=theme.COLOR_ACCENT,              # синяя "заполненная" часть
        )
        self.model_progress.set(0)                          # начинаем с нуля
        self.model_progress.grid(row=7, column=0, padx=20, pady=(0, 6), sticky="ew")

        # Текстовый статус скачивания: "Скачивание... 24%", ошибки и т.д.
        self.model_status_label = ctk.CTkLabel(
            local_card,
            text="Выберите модель и нажмите кнопку",        # стартовая подсказка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            text_color=theme.COLOR_MUTED,
            justify="left",
            wraplength=360,                                 # переносить длинные сообщения
        )
        self.model_status_label.grid(row=8, column=0, padx=20, pady=(0, 8), sticky="w")

        # Маленькая кнопка "проверить Ollama ещё раз" (на случай, если её запустили позже)
        self.recheck_button = ctk.CTkButton(
            local_card,
            text="↻  Проверить Ollama ещё раз",             # надпись маленькой кнопки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            height=30,                                      # пониже основной кнопки
            corner_radius=8,
            fg_color="transparent",                         # прозрачная — второстепенная
            hover_color=theme.COLOR_HOVER,                  # подсветка при наведении
            text_color=theme.COLOR_MUTED,                   # серый текст
            command=self.start_ollama_check,                # при нажатии — перепроверить
        )
        self.recheck_button.grid(row=9, column=0, padx=20, pady=(0, 16), sticky="w")

        # =====================================================================
        #  ЗОНА 2 (ПРАВАЯ КАРТОЧКА): облачный ИИ
        # =====================================================================
        cloud_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,                      # тёмно-серый фон карточки
            corner_radius=16,                               # скруглённые углы, как в Win11
        )
        cloud_card.grid(row=2, column=1, padx=(8, 36), pady=(0, 36), sticky="nsew")
        cloud_card.grid_columnconfigure(0, weight=1)        # карточка тянется по ширине

        # Маленькая надпись-заголовок зоны
        cloud_title = ctk.CTkLabel(
            cloud_card,
            text="МОЩНЫЙ ОБЛАЧНЫЙ ИИ (ЧЕРЕЗ ИНТЕРНЕТ)",     # название зоны
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11, weight="bold"),
            text_color=theme.COLOR_MUTED,
        )
        cloud_title.grid(row=0, column=0, padx=20, pady=(16, 6), sticky="w")

        # Объяснение для новичка про облачные нейросети и безопасность ключей
        cloud_hint = ctk.CTkLabel(
            cloud_card,
            text="Claude и ChatGPT умеют больше, но работают через интернет по платному ключу.\n"
                 "Ключи хранятся только у вас на компьютере, в файле config.json.",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            text_color=theme.COLOR_MUTED,
            justify="left",
            wraplength=360,                                 # переносить длинные строки
        )
        cloud_hint.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="w")

        # Подпись поля ключа Anthropic (Claude)
        anthropic_caption = ctk.CTkLabel(
            cloud_card,
            text="API-ключ Anthropic (Claude):",            # название первого поля
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_TEXT,
        )
        anthropic_caption.grid(row=2, column=0, padx=20, pady=(0, 4), sticky="w")

        # Поле ввода ключа Claude: символы прячутся за звёздочками (show="*")
        self.anthropic_entry = ctk.CTkEntry(
            cloud_card,
            show="*",                                       # вместо букв — звёздочки
            placeholder_text="вставьте сюда ключ sk-ant-...",  # подсказка в пустом поле
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            height=38,                                      # повыше — удобнее вставлять
            fg_color=theme.COLOR_LINE,                      # тёмный фон поля
            border_width=0,                                 # без лишней рамки
        )
        self.anthropic_entry.grid(row=3, column=0, padx=20, pady=(0, 12), sticky="ew")

        # Подпись поля ключа OpenAI (ChatGPT)
        openai_caption = ctk.CTkLabel(
            cloud_card,
            text="API-ключ OpenAI (ChatGPT):",              # название второго поля
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_TEXT,
        )
        openai_caption.grid(row=4, column=0, padx=20, pady=(0, 4), sticky="w")

        # Поле ввода ключа OpenAI, тоже со звёздочками
        self.openai_entry = ctk.CTkEntry(
            cloud_card,
            show="*",                                       # вместо букв — звёздочки
            placeholder_text="вставьте сюда ключ sk-...",   # подсказка в пустом поле
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            height=38,
            fg_color=theme.COLOR_LINE,
            border_width=0,
        )
        self.openai_entry.grid(row=5, column=0, padx=20, pady=(0, 14), sticky="ew")

        # Ряд с двумя кнопками: сохранить и проверить
        buttons_row = ctk.CTkFrame(cloud_card, fg_color="transparent")
        buttons_row.grid(row=6, column=0, padx=20, pady=(0, 12), sticky="ew")
        buttons_row.grid_columnconfigure(0, weight=1)       # обе кнопки делят ширину поровну
        buttons_row.grid_columnconfigure(1, weight=1)

        # Кнопка сохранения ключей в файл config.json
        self.save_button = ctk.CTkButton(
            buttons_row,
            text="💾  Сохранить ключи",                     # надпись кнопки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
            height=38,
            corner_radius=10,
            fg_color=theme.COLOR_ACCENT,
            hover_color=theme.COLOR_HOVER,
            command=self.on_save_clicked,                   # при нажатии — сохранить
        )
        self.save_button.grid(row=0, column=0, padx=(0, 6), sticky="ew")

        # Кнопка проверки связи с выбранным облаком
        self.check_button = ctk.CTkButton(
            buttons_row,
            text="📡  Проверить связь",                     # надпись кнопки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
            height=38,
            corner_radius=10,
            fg_color=theme.COLOR_LINE,                      # нейтральный тёмный фон
            hover_color=theme.COLOR_HOVER,
            command=self.on_check_clicked,                  # при нажатии — проверить
        )
        self.check_button.grid(row=0, column=1, padx=(6, 0), sticky="ew")

        # Переключатель: чей ключ проверять — Claude или OpenAI
        self.provider_switch = ctk.CTkSegmentedButton(
            cloud_card,
            values=["Claude", "OpenAI"],                    # два варианта проверки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            selected_color=theme.COLOR_ACCENT,              # синий выбранный сегмент
            selected_hover_color=theme.COLOR_HOVER,
            unselected_color=theme.COLOR_LINE,              # тёмный невыбранный
            unselected_hover_color=theme.COLOR_HOVER,
            height=34,
        )
        self.provider_switch.set("Claude")                  # по умолчанию проверяем Claude
        self.provider_switch.grid(row=7, column=0, padx=20, pady=(0, 12), sticky="ew")

        # Строка результата проверки связи (зелёная или красная надпись)
        self.check_result_label = ctk.CTkLabel(
            cloud_card,
            text="",                                        # пока пусто — ничего не проверяли
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12, weight="bold"),
            justify="left",
            wraplength=360,                                 # переносить длинные сообщения
            anchor="w",                                     # текст прижат к левому краю
        )
        self.check_result_label.grid(row=8, column=0, padx=20, pady=(0, 16), sticky="ew")

    # ------------------------------------------------------- ПОДСКАЗКА О МОДЕЛИ

    def on_model_changed(self, choice):
        """Вызывается, когда пользователь выбрал другую модель в списке."""
        self.apply_model_hint(choice)               # показываем подсказку новой модели

    def apply_model_hint(self, choice):
        """Показывает под списком требования выбранной модели к памяти."""
        hint_text = MODEL_HINTS.get(choice, "")     # достаём подсказку из словаря
        if not hint_text:                           # на всякий случай: подсказки нет
            hint_text = "💡 Выберите модель — подскажем, сколько нужно памяти."
        hint_color = theme.COLOR_MUTED              # обычный серый цвет подсказки
        if hint_text.startswith("⚠️"):              # тяжёлая модель — предупреждение
            hint_color = theme.COLOR_WAIT           # покажем её жёлтым цветом
        self.model_hint_label.configure(            # обновляем надпись и цвет
            text=hint_text,
            text_color=hint_color,
        )

    # ------------------------------------------------------- КЛЮЧИ: ЗАГРУЗКА/СОХРАНЕНИЕ

    def load_saved_keys(self):
        """Подставляет сохранённые ключи из config.json в поля (они же в звёздочках)."""
        saved_anthropic = config_manager.get_api_key("anthropic")  # читаем ключ Claude
        saved_openai = config_manager.get_api_key("openai")        # читаем ключ OpenAI
        if saved_anthropic:                             # если ключ Claude сохранён...
            self.anthropic_entry.delete(0, "end")       # очищаем поле
            self.anthropic_entry.insert(0, saved_anthropic)  # вставляем ключ
        if saved_openai:                                # если ключ OpenAI сохранён...
            self.openai_entry.delete(0, "end")          # очищаем поле
            self.openai_entry.insert(0, saved_openai)   # вставляем ключ

    def on_save_clicked(self):
        """Кнопка "Сохранить ключи": записывает оба ключа в config.json."""
        anthropic_key = self.anthropic_entry.get().strip()   # текст из поля Claude
        openai_key = self.openai_entry.get().strip()         # текст из поля OpenAI
        saved_ok = True                                 # оптимистично считаем, что всё выйдет

        if anthropic_key:                               # ключ Claude не пустой — сохраняем
            saved_ok = config_manager.save_api_key("anthropic", anthropic_key) and saved_ok
        if openai_key:                                  # ключ OpenAI не пустой — сохраняем
            saved_ok = config_manager.save_api_key("openai", openai_key) and saved_ok

        if saved_ok:                                    # файл записался успешно
            messagebox.showinfo(
                "Ключи сохранены",
                "Программа запомнила ключи и подставит их сама\n"
                "при следующем запуске. Файл: config.json",
            )
        else:                                           # записать файл не вышло
            messagebox.showerror(
                "Не получилось сохранить",
                "Не удалось записать файл config.json.\n"
                "Проверьте, не защищена ли папка программы от записи.",
            )

    # ------------------------------------------------------------------ ПРОВЕРКА КЛЮЧА

    def on_check_clicked(self):
        """Кнопка "Проверить связь": быстрый тестовый запрос к Claude или OpenAI."""
        if self.is_checking_key:                        # предыдущая проверка ещё идёт?
            return                                      # да — игнорируем повторный клик

        provider = "anthropic"                          # по умолчанию проверяем Claude
        if self.provider_switch.get() == "OpenAI":      # если выбран сегмент OpenAI...
            provider = "openai"                         # ...проверяем OpenAI

        # Берём ключ из поля; если поле пустое — пробуем сохранённый в файле
        key = self.anthropic_entry.get().strip() if provider == "anthropic" \
            else self.openai_entry.get().strip()
        if not key:                                     # в поле пусто...
            key = config_manager.get_api_key(provider)  # ...пробуем файл настроек
        if not key:                                     # ключа нет нигде
            self.check_result_label.configure(          # мягко объясняем, что делать
                text="Сначала вставьте ключ в поле и нажмите «Сохранить ключи»",
                text_color=theme.COLOR_WAIT,            # жёлтый цвет предупреждения
            )
            return                                      # проверять нечего — выходим

        # Блокируем кнопку и показываем, что пошла проверка
        self.is_checking_key = True                     # ставим флаг "проверка идёт"
        self.check_button.configure(state="disabled")   # отключаем кнопку
        self.check_result_label.configure(              # жёлтая надпись ожидания
            text="Проверяю связь, подождите пару секунд...",
            text_color=theme.COLOR_WAIT,
        )

        # Запускаем проверку в отдельном потоке, чтобы окно не замерзало
        worker = threading.Thread(                      # создаём поток
            target=self.key_check_worker,               # что он должен сделать
            args=(provider, key),                       # передаём провайдера и ключ
            daemon=True,                                # поток закроется вместе с окном
        )
        worker.start()                                  # поехали

    def key_check_worker(self, provider, key):
        """Сам запрос к облаку — работает в фоне, результат отправляет в окно."""
        if provider == "anthropic":                     # проверяем ключ Claude
            success, reason = cloud_api.test_anthropic_key(key)
        else:                                           # проверяем ключ OpenAI
            success, reason = cloud_api.test_openai_key(key)
        self.is_checking_key = False                    # проверка закончена
        try:
            # Показываем результат через after — безопасный путь из потока в окно
            self.after(0, self.show_check_result, success, reason)
        except Exception:
            pass                                        # окно уже закрыли — выходим тихо

    def show_check_result(self, success, reason):
        """Рисует результат проверки связи и возвращает кнопку в рабочее состояние."""
        self.check_button.configure(state="normal")     # включаем кнопку обратно
        if success:                                     # сервер принял ключ
            self.check_result_label.configure(
                text="Связь успешна! Ключ работает ✓",  # хорошая новость
                text_color=theme.COLOR_OK,              # зелёный цвет
            )
        else:                                           # ключ не принят или нет сети
            self.check_result_label.configure(
                text="Ошибка: неверный ключ или нет интернета ✗\n(" + reason + ")",
                text_color=theme.COLOR_BAD,             # красный цвет
            )

    # ------------------------------------------------------------ OLLAMA: СТАТУС И СКАЧКА

    def start_ollama_check(self):
        """Проверяет в фоне, запущена ли программа Ollama на компьютере."""
        self.ollama_status_label.configure(             # на время проверки — жёлтый текст
            text="Программа Ollama: проверяем...",
            text_color=theme.COLOR_WAIT,
        )
        worker = threading.Thread(                      # проверка сети — в отдельном потоке
            target=self.ollama_check_worker,
            daemon=True,
        )
        worker.start()                                  # запускаем поток

    def ollama_check_worker(self):
        """Фоновая проверка Ollama (до 2 секунд), результат — обратно в окно."""
        ollama_ok = netcheck.is_ollama_available()      # спрашиваем сервис проверки
        try:
            self.after(0, self.apply_ollama_status, ollama_ok)  # показываем результат
        except Exception:
            pass                                        # окно уже закрыли — выходим тихо

    def apply_ollama_status(self, ollama_ok):
        """Показывает статус Ollama и блокирует кнопку скачивания, если её нет."""
        if ollama_ok:                                   # Ollama запущена
            self.ollama_status_label.configure(
                text="Программа Ollama: найдена ✓",     # хорошая новость
                text_color=theme.COLOR_OK,              # зелёный цвет
            )
            self.download_button.configure(state="normal")      # кнопка доступна
        else:                                           # Ollama не запущена
            self.ollama_status_label.configure(
                text="Программа Ollama: не запущена ✗", # плохая новость
                text_color=theme.COLOR_BAD,             # красный цвет
            )
            self.download_button.configure(state="disabled")    # блокируем скачивание

    def on_download_clicked(self):
        """Кнопка "Скачать и установить": запускает скачивание модели в фоне."""
        if self.is_downloading:                         # скачивание уже идёт?
            return                                      # повторные клики игнорируем
        self.is_downloading = True                      # помечаем: скачивание началось

        # Блокируем элементы зоны, чтобы пользователь ничего не сломал во время скачки
        self.download_button.configure(state="disabled")     # кнопку гасим
        self.model_menu.configure(state="disabled")          # список тоже
        self.recheck_button.configure(state="disabled")      # и маленькую кнопку
        self.model_progress.set(0)                           # полоса — на ноль
        self.last_percent_shown = None                       # сбрасываем процент
        self.model_status_label.configure(                   # статус "готовимся"
            text="Связываюсь с Ollama...",
            text_color=theme.COLOR_MUTED,
        )

        worker = threading.Thread(                      # скачивание — строго в фоне
            target=self.download_worker,
            daemon=True,                                # поток умрёт вместе с окном
        )
        worker.start()                                  # поехали качать

    def download_worker(self):
        """Фоновая работа: проверка Ollama и само скачивание модели."""
        # Сначала ещё раз проверяем Ollama: могла быть закрыта после загрузки страницы
        if not netcheck.is_ollama_available():
            self.is_downloading = False                 # скачивание не началось
            try:
                self.after(0, self.show_ollama_missing) # просим окно показать подсказку
            except Exception:
                pass                                    # окно закрыто — выходим тихо
            return                                      # и больше ничего не делаем

        # Достаём техническое имя выбранной модели из выпадающего списка
        friendly_name = self.model_menu.get()           # понятная надпись из меню
        model_name = MODEL_CHOICES.get(friendly_name, "llama3.2:1b")  # имя для Ollama

        try:
            # Само скачивание: ollama_client дёргает on_pull_progress с прогрессом
            ollama_client.pull_model(model_name, self.on_pull_progress)
        except Exception as error:                      # что-то пошло не так
            self.is_downloading = False                 # скачивание закончилось неудачей
            try:
                self.after(0, self.show_download_error, str(error))  # показываем ошибку
            except Exception:
                pass                                    # окно закрыто — выходим тихо
            return                                      # дальше не идём

        self.is_downloading = False                     # всё скачалось — флаг сброшен
        try:
            self.after(0, self.show_download_success)   # сообщаем окну об успехе
        except Exception:
            pass                                        # окно закрыто — выходим тихо

    def show_ollama_missing(self):
        """Понятное сообщение: Ollama не запущена, скачка невозможна."""
        # Возвращаем элементы зоны в рабочее состояние (кроме кнопки — её решает проверка)
        self.model_menu.configure(state="normal")       # список снова активен
        self.recheck_button.configure(state="normal")   # кнопка проверки снова активна
        self.model_status_label.configure(              # статус с объяснением
            text="Сначала нужна программа Ollama. Скачайте её с сайта ollama.com и запустите.",
            text_color=theme.COLOR_BAD,                 # красный цвет ошибки
        )
        # Само всплывающее окно с фразой, которую просил пользователь
        messagebox.showwarning(
            "Ollama не запущена",
            "Пожалуйста, сначала запустите приложение Ollama на компьютере",
        )

    def on_pull_progress(self, percent, status_text):
        """Промежуточный отчёт от ollama_client — передаём его в окно."""
        # Чтобы не заваливать окно тысячами обновлений, показываем только изменения
        if percent == self.last_percent_shown and percent is not None:
            return                                      # процент не изменился — пропускаем
        self.last_percent_shown = percent               # запоминаем новый процент
        try:
            self.after(0, self.apply_pull_progress, percent, status_text)  # в окно
        except Exception:
            pass                                        # окно закрыто — выходим тихо

    def apply_pull_progress(self, percent, status_text):
        """Двигает полосу прогресса и меняет текст статуса (работает уже в окне)."""
        if percent is not None:                         # проценты известны...
            self.model_progress.set(percent / 100)      # ...двигаем полосу (от 0.0 до 1.0)
        self.model_status_label.configure(              # обновляем текст статуса
            text=status_text,                           # например "Скачивание... 24%"
            text_color=theme.COLOR_TEXT,                # обычный белый текст
        )

    def show_download_error(self, error_text):
        """Показывает понятное сообщение об ошибке скачивания."""
        self.model_menu.configure(state="normal")       # возвращаем список
        self.recheck_button.configure(state="normal")   # возвращаем маленькую кнопку
        self.download_button.configure(state="normal")  # разрешаем попробовать снова
        self.model_progress.set(0)                      # полосу — на ноль
        self.model_status_label.configure(              # статус с ошибкой
            text="Ошибка скачивания: " + error_text,    # показываем, что сказала Ollama
            text_color=theme.COLOR_BAD,                 # красный цвет
        )

    def show_download_success(self):
        """Радуемся: модель скачана и установлена."""
        self.download_button.configure(state="normal")  # кнопка снова доступна (для другой модели)
        self.model_menu.configure(state="normal")       # возвращаем список
        self.recheck_button.configure(state="normal")   # возвращаем маленькую кнопку
        self.model_progress.set(1)                      # полоса заполнена на 100%
        self.model_status_label.configure(              # хорошая новость
            text="Готово! Модель установлена ✓",        # текст успеха
            text_color=theme.COLOR_OK,                  # зелёный цвет
        )
