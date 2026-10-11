# ============================================================================
#  ВКЛАДКА "РОБОТ" (агент-помощник) — pages/robot_page.py
#  --------------------------------------------------------------------------
#  Шаг 4: здесь пользователь включает робота и в живом окне трансляции видит,
#  что тот делает: "[Мысль]: ...", "[Действие]: Делаю скриншот экрана...".
#  Вся "умная" работа живёт в services/agent_runtime.py — эта страница только
#  кнопки, списки и лог.
# ============================================================================

# --- ПОДКЛЮЧЕНИЕ БИБЛИОТЕК -----------------------------------------------------

import customtkinter as ctk            # библиотека современного красивого интерфейса

import theme                           # наш файл с цветами и шрифтами приложения
from services.agent_runtime import (   # двигатель робота и имена режимов
    AgentRuntime,
    MODE_REPORT,
    MODE_CLEANUP,
    MODE_CONTROL,
)

# Список режимов для выпадающего меню:
# "понятная надпись" -> "техническое имя режима"
MODE_CHOICES = {
    "Напиши отчет": MODE_REPORT,
    "Чистка рабочего стола": MODE_CLEANUP,
    "Полное управление экраном через Computer Use": MODE_CONTROL,
}

# Оформление строк лога: тип сообщения -> (значок, цвет)
LOG_STYLES = {
    "thought": ("[Мысль]:   ", theme.COLOR_WAIT),    # жёлтый — что робот подумал
    "action":  ("[Действие]: ", theme.COLOR_TEXT),   # белый — что робот делает
    "success": ("[Готово]:   ", theme.COLOR_OK),     # зелёный — получилось
    "error":   ("[Ошибка]:   ", theme.COLOR_BAD),    # красный — проблема
    "info":    ("[Инфо]:     ", theme.COLOR_MUTED),  # серый — подсказки
}


class RobotPage(ctk.CTkFrame):
    """Страница "Робот": включение агента и живая трансляция его действий."""

    def __init__(self, parent):
        # Создаём страницу как прозрачную рамку (фон будет от окна)
        super().__init__(parent, fg_color="transparent")

        # Страница растягивается на всю доступную область окна
        self.grid_rowconfigure(0, weight=1)      # строка растягивается по высоте
        self.grid_columnconfigure(0, weight=1)   # столбец растягивается по ширине

        self.agent = None                        # здесь будет двигатель робота

        self.create_widgets()                    # рисуем содержимое страницы

    # ------------------------------------------------------------------ ИНТЕРФЕЙС

    def create_widgets(self):
        """Рисует все элементы, которые видит пользователь на этой странице."""

        # Внутренний контейнер — прижат к верху страницы
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.grid(row=0, column=0, sticky="new")     # прижимаем к верху
        content.grid_columnconfigure(0, weight=1)       # тянется по ширине окна

        # --- Заголовок страницы ---------------------------------------------------
        title = ctk.CTkLabel(
            content,
            text="🤖  Робот-помощник",                       # заголовок вкладки
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=22, weight="bold"),
            text_color=theme.COLOR_TEXT,
        )
        title.grid(row=0, column=0, padx=36, pady=(28, 2), sticky="w")

        # Подзаголовок с объяснением простыми словами
        subtitle = ctk.CTkLabel(
            content,
            text="Робот видит экран, двигает мышку и печатает за вас — а вы просто читаете лог",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_MUTED,
        )
        subtitle.grid(row=1, column=0, padx=36, pady=(0, 20), sticky="w")

        # --- КАРТОЧКА: панель управления роботом ------------------------------------
        control_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,                      # тёмно-серый фон карточки
            corner_radius=16,
        )
        control_card.grid(row=2, column=0, padx=36, pady=(0, 16), sticky="ew")
        control_card.grid_columnconfigure(0, weight=1)      # карточка тянется по ширине

        # Подпись поля задания
        task_caption = ctk.CTkLabel(
            control_card,
            text="Задание для робота (своими словами):",    # простая подсказка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_TEXT,
        )
        task_caption.grid(row=0, column=0, padx=20, pady=(16, 4), sticky="w")

        # Поле задания: сюда пишут тему отчёта или что сделать на экране
        self.task_entry = ctk.CTkEntry(
            control_card,
            placeholder_text="например: отчет о продажах за месяц / открой блокнот и напиши «привет»",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            height=38,
            fg_color=theme.COLOR_LINE,
            border_width=0,
        )
        self.task_entry.grid(row=1, column=0, padx=20, pady=(0, 12), sticky="ew")

        # Подпись поля выбора режима
        mode_caption = ctk.CTkLabel(
            control_card,
            text="Режим работы:",                           # простая подсказка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_TEXT,
        )
        mode_caption.grid(row=2, column=0, padx=20, pady=(0, 4), sticky="w")

        # Выпадающий список режимов
        self.mode_menu = ctk.CTkOptionMenu(
            control_card,
            values=list(MODE_CHOICES.keys()),               # три режима работы
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=12),
            fg_color=theme.COLOR_LINE,
            button_color=theme.COLOR_ACCENT,
            button_hover_color=theme.COLOR_HOVER,
            height=36,
        )
        self.mode_menu.set("Напиши отчет")                  # безопасный режим по умолчанию
        self.mode_menu.grid(row=3, column=0, padx=20, pady=(0, 16), sticky="ew")

        # ГЛАВНАЯ кнопка: включить/остановить робота
        self.power_button = ctk.CTkButton(
            control_card,
            text="🚀  ВКЛЮЧИТЬ РОБОТА",                     # стартовая надпись
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=16, weight="bold"),
            height=52,                                      # очень большая кнопка
            corner_radius=12,
            fg_color=theme.COLOR_ACCENT,                    # синяя, когда робот выключен
            hover_color=theme.COLOR_HOVER,
            command=self.on_power_clicked,                  # включение и остановка
        )
        self.power_button.grid(row=4, column=0, padx=20, pady=(0, 8), sticky="ew")

        # Строка статуса робота (выключен / работает / закончил)
        self.status_label = ctk.CTkLabel(
            control_card,
            text="⚪ Робот выключен",                       # стартовый статус
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13, weight="bold"),
            text_color=theme.COLOR_MUTED,
        )
        self.status_label.grid(row=5, column=0, padx=20, pady=(0, 16), sticky="w")

        # --- КАРТОЧКА: окно трансляции (лог действий) --------------------------------
        log_card = ctk.CTkFrame(
            content,
            fg_color=theme.COLOR_CARD,
            corner_radius=16,
        )
        log_card.grid(row=3, column=0, padx=36, pady=(0, 36), sticky="ew")
        log_card.grid_columnconfigure(0, weight=1)

        # Подпись над логом
        log_caption = ctk.CTkLabel(
            log_card,
            text="ТРАНСЛЯЦИЯ: ЧТО ДЕЛАЕТ РОБОТ ПРЯМО СЕЙЧАС",   # название окошка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=11, weight="bold"),
            text_color=theme.COLOR_MUTED,
        )
        log_caption.grid(row=0, column=0, padx=20, pady=(16, 8), sticky="w")

        # Большое текстовое поле лога (со встроенной прокруткой)
        self.log_box = ctk.CTkTextbox(
            log_card,
            height=260,                                     # высота окошка трансляции
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            fg_color=theme.COLOR_WINDOW,                    # фон темнее карточки
            text_color=theme.COLOR_TEXT,
            wrap="word",                                    # переносить длинные строки
            border_width=0,
        )
        self.log_box.grid(row=1, column=0, padx=20, pady=(0, 20), sticky="ew")
        self.log_box.configure(state="disabled")            # пользователь не может печатать тут

        # Приветственная строка в пустом логе
        self.write_log_line("info", "Привет! Нажми «ВКЛЮЧИТЬ РОБОТА» — и здесь я расскажу, что делаю.")

    # ------------------------------------------------------------------ ЛОГ

    def write_log_line(self, kind, text):
        """Добавляет одну строку в окно трансляции и прокручивает вниз."""
        prefix, color = LOG_STYLES.get(kind, LOG_STYLES["info"])   # значок и цвет строки
        self.log_box.configure(state="normal")              # открываем поле для записи
        self.log_box.insert("end", f"{prefix}{text}\n")     # дописываем строку в конец
        self.log_box.see("end")                             # авто-прокрутка к новой строке
        self.log_box.configure(state="disabled")            # снова закрываем от печати

    def on_agent_log(self, kind, text):
        """Робот (из своего потока) просит показать строку лога."""
        try:
            # after — безопасный способ трогать окно из чужого потока
            self.after(0, self.write_log_line, kind, text)
        except Exception:
            pass                                            # окно уже закрыто — тихо

    # ------------------------------------------------------------------ ВКЛЮЧЕНИЕ

    def on_power_clicked(self):
        """Большая кнопка: включает робота или просит его остановиться."""
        if self.agent is not None and self.agent.is_running():
            # Робот работает -> эта кнопка теперь "Остановить"
            self.agent.stop()                               # мягко просим остановиться
            self.write_log_line("info", "Останавливаю робота...")
            self.status_label.configure(
                text="⚪ Останавливаюсь...", text_color=theme.COLOR_MUTED)
            return

        # --- Робот выключен -> проверяем и включаем -------------------------------
        mode_key = MODE_CHOICES.get(self.mode_menu.get(), MODE_REPORT)  # выбранный режим
        task_text = self.task_entry.get().strip()           # задание пользователя

        # Для отчёта и управления экраном задание обязательно
        if mode_key in (MODE_REPORT, MODE_CONTROL) and not task_text:
            self.status_label.configure(                    # мягкая жёлтая подсказка
                text="⚠️ Сначала напишите задание в поле выше",
                text_color=theme.COLOR_WAIT,
            )
            return

        # Создаём свежий двигатель робота с нашими функциями лога и завершения
        self.agent = AgentRuntime(self.on_agent_log, self.on_agent_finished)
        self.agent.start(mode_key, task_text)               # поехали (в отдельном потоке)

        # Переключаем интерфейс в режим "робот работает"
        self.power_button.configure(                        # кнопка становится красной
            text="⏹  ОСТАНОВИТЬ РОБОТА",
            fg_color=theme.COLOR_BAD,
            hover_color=theme.COLOR_BAD,
        )
        self.mode_menu.configure(state="disabled")          # режим менять нельзя
        self.task_entry.configure(state="disabled")         # задание менять нельзя
        self.status_label.configure(                        # зелёный статус
            text="🟢 Робот работает — читайте трансляцию ниже",
            text_color=theme.COLOR_OK,
        )
        self.write_log_line("info", f"Робот включён. Режим: «{self.mode_menu.get()}».")

    def on_agent_finished(self):
        """Робот закончил (из своего потока): возвращаем кнопки в обычное состояние."""
        try:
            self.after(0, self.reset_running_ui)            # безопасно для потока
        except Exception:
            pass                                            # окно уже закрыто

    def reset_running_ui(self):
        """Возвращает кнопку, список и статус в состояние "робот выключен"."""
        self.power_button.configure(                        # снова большая синяя кнопка
            text="🚀  ВКЛЮЧИТЬ РОБОТА",
            fg_color=theme.COLOR_ACCENT,
            hover_color=theme.COLOR_HOVER,
        )
        self.mode_menu.configure(state="normal")            # список снова активен
        self.task_entry.configure(state="normal")           # задание снова можно менять
        self.status_label.configure(                        # спокойный серый статус
            text="⚪ Робот закончил работу",
            text_color=theme.COLOR_MUTED,
        )
