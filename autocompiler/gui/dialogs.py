"""
Красивое красное окно ошибки.

Показывает: крупный заголовок, понятное описание, совет «что делать»
и скрытый по умолчанию блок технических подробностей (для разработчика).
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# Библиотека современного интерфейса.
import customtkinter as ctk

# Настройки внешнего вида.
from autocompiler.config import Colors, Fonts, Layout


class ErrorDialog(ctk.CTkToplevel):
    """Модальное (блокирующее главное окно) окно с описанием ошибки."""

    def __init__(self, master, title: str, message: str, hint: str = "", details: str = "") -> None:
        # Создаём отдельное окно поверх главного.
        super().__init__(master)
        # Сохраняем технические подробности для копирования.
        self._details = details
        # Флаг: показаны ли сейчас подробности.
        self._details_visible = False

        # --- Параметры окна ---
        self.title("Ошибка")
        # Стартовый размер окна.
        self.geometry("560x340")
        # Минимальный размер, чтобы текст не обрезался.
        self.minsize(480, 300)
        # Тёмно-красный фон окна.
        self.configure(fg_color=Colors.DANGER_BACKGROUND)
        # Окно «привязано» к главному (не появляется отдельно на панели задач).
        self.transient(master)
        # Единственная колонка растягивается.
        self.grid_columnconfigure(0, weight=1)
        # Строка с подробностями растягивается при раскрытии.
        self.grid_rowconfigure(3, weight=1)

        # Шрифты окна ошибки.
        title_font = ctk.CTkFont(family=Fonts.UI_FAMILY, size=20, weight="bold")
        # Шрифт основного текста.
        body_font = ctk.CTkFont(family=Fonts.UI_FAMILY, size=14)
        # Шрифт кнопок.
        button_font = ctk.CTkFont(family=Fonts.UI_FAMILY, size=13, weight="bold")
        # Моноширинный шрифт для подробностей.
        mono_font = ctk.CTkFont(family=Fonts.MONO_FAMILY, size=12)

        # --- Красная шапка с крестиком и заголовком ---
        header = ctk.CTkFrame(self, fg_color=Colors.DANGER_DARK, corner_radius=0)
        # Шапка во всю ширину окна.
        header.grid(row=0, column=0, sticky="ew")
        # Колонка заголовка растягивается.
        header.grid_columnconfigure(1, weight=1)
        # Большой значок ошибки.
        ctk.CTkLabel(header, text="✖", font=ctk.CTkFont(size=28, weight="bold"), text_color="#ffffff").grid(
            row=0, column=0, padx=(20, 12), pady=16
        )
        # Заголовок ошибки.
        ctk.CTkLabel(header, text=title, font=title_font, text_color="#ffffff", anchor="w", justify="left", wraplength=440).grid(
            row=0, column=1, sticky="ew", padx=(0, 20), pady=16
        )

        # --- Описание ошибки ---
        self._message_label = ctk.CTkLabel(
            self, text=message, font=body_font, text_color=Colors.TEXT, anchor="w", justify="left", wraplength=500
        )
        # Размещаем описание под шапкой.
        self._message_label.grid(row=1, column=0, sticky="ew", padx=24, pady=(18, 6))

        # --- Совет «что делать» (если есть) ---
        if hint:
            # Жёлтоватый текст с подсказкой.
            self._hint_label = ctk.CTkLabel(
                self,
                text=f"Что делать: {hint}",
                font=body_font,
                text_color=Colors.WARNING,
                anchor="w",
                justify="left",
                wraplength=500,
            )
            # Размещаем подсказку под описанием.
            self._hint_label.grid(row=2, column=0, sticky="ew", padx=24, pady=(4, 8))

        # --- Блок технических подробностей (скрыт по умолчанию) ---
        self._details_box = ctk.CTkTextbox(
            self, font=mono_font, fg_color=Colors.LOG_BACKGROUND, text_color=Colors.TEXT_MUTED, wrap="none", height=160
        )
        # Вставляем текст подробностей.
        self._details_box.insert("1.0", details or "Технические подробности отсутствуют.")
        # Запрещаем редактирование.
        self._details_box.configure(state="disabled")

        # --- Нижняя панель с кнопками ---
        buttons = ctk.CTkFrame(self, fg_color="transparent")
        # Панель прижата к низу окна.
        buttons.grid(row=4, column=0, sticky="ew", padx=24, pady=(8, 20))
        # Пустая колонка слева «выталкивает» кнопку «Понятно» вправо.
        buttons.grid_columnconfigure(2, weight=1)
        # Общие параметры второстепенных кнопок.
        secondary = dict(
            height=Layout.BUTTON_HEIGHT,
            corner_radius=8,
            font=button_font,
            fg_color="transparent",
            border_width=1,
            border_color=Colors.DANGER_DARK,
            hover_color=Colors.DANGER_DARK,
            text_color=Colors.TEXT,
        )
        # Кнопка показа/скрытия подробностей.
        self._toggle_button = ctk.CTkButton(buttons, text="Подробности ▼", command=self._toggle_details, **secondary)
        # Размещаем слева.
        self._toggle_button.grid(row=0, column=0, padx=(0, 8))
        # Кнопка копирования подробностей в буфер обмена.
        self._copy_button = ctk.CTkButton(buttons, text="Скопировать", command=self._copy_details, **secondary)
        # Размещаем рядом.
        self._copy_button.grid(row=0, column=1)
        # Главная кнопка закрытия окна.
        ctk.CTkButton(
            buttons,
            text="Понятно",
            command=self._close,
            height=Layout.BUTTON_HEIGHT,
            width=130,
            corner_radius=8,
            font=button_font,
            fg_color=Colors.DANGER_DARK,
            hover_color=Colors.DANGER_HOVER,
            text_color="#ffffff",
        ).grid(row=0, column=3, sticky="e")

        # Клавиши Enter и Escape закрывают окно.
        self.bind("<Return>", lambda _event: self._close())
        # Escape — тоже закрыть.
        self.bind("<Escape>", lambda _event: self._close())
        # Крестик в заголовке окна — тоже закрыть корректно.
        self.protocol("WM_DELETE_WINDOW", self._close)

        # Ставим окно по центру главного окна.
        self._center_over(master)
        # CTkToplevel в Windows иногда появляется ПОД главным окном — поднимаем его чуть позже.
        self.after(150, self._bring_to_front)

    # ------------------------------------------------------------------ #

    def _bring_to_front(self) -> None:
        """Поднять окно наверх, дать фокус и сделать модальным."""
        # Окно могли уже закрыть — тогда ничего не делаем.
        try:
            # Поднимаем окно над остальными.
            self.lift()
            # Передаём ему фокус клавиатуры.
            self.focus_force()
            # grab_set блокирует клики по главному окну, пока ошибка не закрыта.
            self.grab_set()
        # Окно уже уничтожено — просто игнорируем.
        except Exception:  # noqa: BLE001
            pass

    def _center_over(self, master) -> None:
        """Разместить окно по центру над главным окном."""
        # Если расчёт координат не удастся — окно просто появится где решит Windows.
        try:
            # Обновляем геометрию, чтобы получить актуальные размеры.
            self.update_idletasks()
            # Координаты и размеры главного окна.
            mx, my, mw, mh = master.winfo_rootx(), master.winfo_rooty(), master.winfo_width(), master.winfo_height()
            # Размеры окна ошибки.
            w, h = 560, 340
            # Центр по горизонтали и вертикали.
            x, y = mx + (mw - w) // 2, my + (mh - h) // 3
            # Применяем позицию (не даём уйти за левый/верхний край экрана).
            self.geometry(f"{w}x{h}+{max(x, 0)}+{max(y, 0)}")
        # Ошибка позиционирования некритична.
        except Exception:  # noqa: BLE001
            pass

    def _toggle_details(self) -> None:
        """Показать или спрятать технические подробности."""
        # Переключаем флаг.
        self._details_visible = not self._details_visible
        # Подробности нужно показать.
        if self._details_visible:
            # Размещаем блок подробностей.
            self._details_box.grid(row=3, column=0, sticky="nsew", padx=24, pady=(4, 4))
            # Меняем текст кнопки.
            self._toggle_button.configure(text="Скрыть ▲")
            # Увеличиваем окно, чтобы подробности поместились.
            self.geometry(f"{max(self.winfo_width(), 640)}x{max(self.winfo_height(), 540)}")
        # Подробности нужно спрятать.
        else:
            # Убираем блок с экрана (не уничтожая).
            self._details_box.grid_remove()
            # Возвращаем текст кнопки.
            self._toggle_button.configure(text="Подробности ▼")

    def _copy_details(self) -> None:
        """Скопировать технические подробности в буфер обмена."""
        # Очищаем буфер обмена.
        self.clipboard_clear()
        # Кладём текст подробностей.
        self.clipboard_append(self._details or "")
        # Короткая обратная связь прямо на кнопке.
        self._copy_button.configure(text="Скопировано ✔")
        # Через 1.5 секунды возвращаем исходный текст (если окно ещё открыто).
        self.after(1500, lambda: self._copy_button.winfo_exists() and self._copy_button.configure(text="Скопировать"))

    def _close(self) -> None:
        """Корректно закрыть окно (снять блокировку главного окна)."""
        # Снимаем модальность; ошибки игнорируем — окно может быть уже наполовину закрыто.
        try:
            # Возвращаем управление главному окну.
            self.grab_release()
        # Игнорируем — главное закрыть окно.
        except Exception:  # noqa: BLE001
            pass
        # Уничтожаем окно.
        self.destroy()
