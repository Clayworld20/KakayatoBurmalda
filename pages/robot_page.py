# ============================================================================
#  ВКЛАДКА "РОБОТ" (агент-помощник) — pages/robot_page.py
#  --------------------------------------------------------------------------
#  Шаг 1: пока здесь заглушка с описанием будущего раздела.
#  Шаг 4: добавим большую кнопку "Включить робота", выбор режима работы
#         и живое окно трансляции: что робот делает прямо сейчас.
# ============================================================================

import customtkinter as ctk   # библиотека современного красивого интерфейса

import theme                   # наш файл с цветами и шрифтами приложения


class RobotPage(ctk.CTkFrame):
    """Страница "Робот": включение агента-помощника и наблюдение за ним."""

    def __init__(self, parent):
        # Создаём страницу как прозрачную рамку (фон будет от окна)
        super().__init__(parent, fg_color="transparent")

        # Говорим tkinter: страница может растягиваться на всё окно
        self.grid_rowconfigure(0, weight=1)      # строка растягивается по высоте
        self.grid_columnconfigure(0, weight=1)   # столбец растягивается по ширине

        self.create_widgets()                    # рисуем содержимое страницы

    def create_widgets(self):
        """Создаём все элементы, которые видит пользователь на этой странице."""

        # Большая карточка по центру страницы
        card = ctk.CTkFrame(
            self,                                # карточка живёт внутри страницы
            fg_color=theme.COLOR_CARD,           # тёмно-серый фон карточки
            corner_radius=16,                    # скруглённые углы, как в Windows 11
        )
        card.grid(row=0, column=0, padx=40, pady=40)  # размещаем по центру

        # Большой эмодзи-значок раздела
        icon = ctk.CTkLabel(
            card,
            text="🤖",                            # робот — символ агента-помощника
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=44),
        )
        icon.grid(row=0, column=0, padx=40, pady=(36, 8))  # сверху карточки

        # Крупный заголовок раздела
        title = ctk.CTkLabel(
            card,
            text="Робот-помощник",                         # текст заголовка
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=24, weight="bold"),
            text_color=theme.COLOR_TEXT,                   # почти белый цвет
        )
        title.grid(row=1, column=0, padx=40, pady=(0, 6))  # под значком

        # Подзаголовок с объяснением, зачем нужен этот раздел
        subtitle = ctk.CTkLabel(
            card,
            text="Умный помощник, который умеет работать за вас:\nписать отчёты, наводить порядок и управлять экраном",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=14),
            text_color=theme.COLOR_MUTED,                  # приглушённый серый
            justify="center",                              # текст по центру
        )
        subtitle.grid(row=2, column=0, padx=40, pady=(0, 20))

        # Тонкая разделительная линия внутри карточки
        line = ctk.CTkFrame(card, fg_color=theme.COLOR_LINE, corner_radius=0, height=1)
        line.grid(row=3, column=0, padx=40, pady=(0, 16), sticky="ew")

        # Подпись о том, что появится здесь в следующем шаге разработки
        hint = ctk.CTkLabel(
            card,
            text="🚧 Шаг 4: кнопка «Включить робота», выбор режима\nи живая трансляция его действий",
            font=ctk.CTkFont(family=theme.FONT_FAMILY, size=13),
            text_color=theme.COLOR_MUTED,                  # серый цвет подсказки
            justify="center",
        )
        hint.grid(row=4, column=0, padx=40, pady=(0, 36))  # внизу карточки
