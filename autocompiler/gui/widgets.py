"""
Переиспользуемые «кирпичики» интерфейса:
    SectionCard — карточка-секция с заголовком;
    PathField   — поле, показывающее выбранный путь к файлу;
    LogConsole  — большое цветное поле лога сборки с кнопками «Копировать» и «Очистить».
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# datetime — для отметок времени в логе.
from datetime import datetime
# Типы для подсказок.
from typing import Optional

# Библиотека современного интерфейса.
import customtkinter as ctk

# Настройки внешнего вида.
from autocompiler.config import Behaviour, Colors, Layout
# Уровни важности строк лога.
from autocompiler.utils.event_bus import LogLevel
# Функция сокращения длинных путей.
from autocompiler.utils.system import shorten_path

# Соответствие «уровень лога → цвет текста».
LEVEL_COLORS = {
    # Заголовки шагов — голубые.
    LogLevel.STEP: Colors.STEP,
    # Обычные сообщения — светлые.
    LogLevel.INFO: Colors.TEXT,
    # Успех — зелёный.
    LogLevel.SUCCESS: Colors.SUCCESS,
    # Предупреждения — жёлтые.
    LogLevel.WARNING: Colors.WARNING,
    # Ошибки — красные.
    LogLevel.ERROR: Colors.DANGER,
    # Технические подробности — серые.
    LogLevel.DEBUG: Colors.TEXT_MUTED,
}

# Короткие значки перед строками лога (только символы из базового набора Unicode,
# чтобы они гарантированно отображались в любой версии Windows).
LEVEL_ICONS = {
    # Шаг — стрелка.
    LogLevel.STEP: "►",
    # Информация — точка.
    LogLevel.INFO: "•",
    # Успех — галочка.
    LogLevel.SUCCESS: "✔",
    # Предупреждение — треугольник.
    LogLevel.WARNING: "▲",
    # Ошибка — крестик.
    LogLevel.ERROR: "✖",
    # Подробности — тонкая черта.
    LogLevel.DEBUG: "·",
}


class SectionCard(ctk.CTkFrame):
    """Карточка с заголовком — визуально группирует связанные элементы."""

    def __init__(self, master, title: str, title_font: ctk.CTkFont, **kwargs) -> None:
        # Создаём рамку с цветом карточки, скруглением и тонкой границей.
        super().__init__(
            master,
            fg_color=Colors.SURFACE,
            corner_radius=Layout.RADIUS,
            border_width=1,
            border_color=Colors.BORDER,
            **kwargs,
        )
        # Единственная колонка карточки растягивается по ширине.
        self.grid_columnconfigure(0, weight=1)
        # Заголовок карточки.
        self.title_label = ctk.CTkLabel(self, text=title, font=title_font, text_color=Colors.TEXT, anchor="w")
        # Размещаем заголовок сверху с отступами.
        self.title_label.grid(row=0, column=0, sticky="ew", padx=Layout.PAD_INNER, pady=(Layout.PAD_INNER, 8))
        # Внутренний контейнер для содержимого карточки (без собственного фона).
        self.body = ctk.CTkFrame(self, fg_color="transparent")
        # Контейнер занимает всё оставшееся место.
        self.body.grid(row=1, column=0, sticky="nsew", padx=Layout.PAD_INNER, pady=(0, Layout.PAD_INNER))
        # Колонка внутри контейнера тоже растягивается.
        self.body.grid_columnconfigure(0, weight=1)


class PathField(ctk.CTkFrame):
    """Поле «только для чтения», показывающее выбранный путь или подсказку."""

    def __init__(self, master, placeholder: str, font: ctk.CTkFont, **kwargs) -> None:
        # Тёмная плашка со скруглёнными углами.
        super().__init__(master, fg_color=Colors.SURFACE_ALT, corner_radius=8, height=Layout.BUTTON_HEIGHT, **kwargs)
        # Запоминаем текст-подсказку для пустого состояния.
        self._placeholder = placeholder
        # Полный (несокращённый) путь — или None, если ничего не выбрано.
        self._full_path: Optional[str] = None
        # Колонка с текстом растягивается.
        self.grid_columnconfigure(0, weight=1)
        # Надпись с путём.
        self._label = ctk.CTkLabel(self, text=placeholder, font=font, text_color=Colors.TEXT_MUTED, anchor="w")
        # Размещаем надпись с отступами слева/справа.
        self._label.grid(row=0, column=0, sticky="ew", padx=12, pady=6)

    def set_path(self, path: Optional[str]) -> None:
        """Показать путь (или подсказку, если path=None)."""
        # Сохраняем полный путь.
        self._full_path = path
        # Путь выбран — показываем его светлым цветом (сокращённым, если длинный).
        if path:
            self._label.configure(text=shorten_path(path, 80), text_color=Colors.TEXT)
        # Путь сброшен — показываем серую подсказку.
        else:
            self._label.configure(text=self._placeholder, text_color=Colors.TEXT_MUTED)

    @property
    def path(self) -> Optional[str]:
        """Текущий полный путь (или None)."""
        # Возвращаем сохранённый путь.
        return self._full_path


class LogConsole(ctk.CTkFrame):
    """Большое поле лога сборки с цветными строками и отметками времени."""

    def __init__(
        self,
        master,
        title: str,
        title_font: ctk.CTkFont,
        mono_font: ctk.CTkFont,
        button_font: ctk.CTkFont,
        **kwargs,
    ) -> None:
        # Карточка-рамка для лога.
        super().__init__(
            master,
            fg_color=Colors.SURFACE,
            corner_radius=Layout.RADIUS,
            border_width=1,
            border_color=Colors.BORDER,
            **kwargs,
        )
        # Колонка растягивается по ширине.
        self.grid_columnconfigure(0, weight=1)
        # Строка с текстовым полем растягивается по высоте.
        self.grid_rowconfigure(1, weight=1)

        # --- Шапка: заголовок слева, кнопки справа ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        # Шапка занимает всю ширину карточки.
        header.grid(row=0, column=0, sticky="ew", padx=Layout.PAD_INNER, pady=(Layout.PAD_INNER, 8))
        # Заголовок растягивается и прижимает кнопки вправо.
        header.grid_columnconfigure(0, weight=1)
        # Заголовок «Ход сборки».
        ctk.CTkLabel(header, text=title, font=title_font, text_color=Colors.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        # Общие параметры маленьких «призрачных» кнопок.
        small_button = dict(
            height=28,
            width=110,
            corner_radius=8,
            font=button_font,
            fg_color="transparent",
            hover_color=Colors.SURFACE_ALT,
            border_width=1,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_MUTED,
        )
        # Кнопка «Копировать лог» — копирует весь текст в буфер обмена.
        ctk.CTkButton(header, text="Копировать", command=self.copy_to_clipboard, **small_button).grid(
            row=0, column=1, padx=(8, 0)
        )
        # Кнопка «Очистить» — стирает лог.
        ctk.CTkButton(header, text="Очистить", command=self.clear, **small_button).grid(row=0, column=2, padx=(8, 0))

        # --- Само текстовое поле ---
        self._textbox = ctk.CTkTextbox(
            self,
            font=mono_font,
            fg_color=Colors.LOG_BACKGROUND,
            text_color=Colors.TEXT,
            corner_radius=8,
            border_width=0,
            wrap="word",
            activate_scrollbars=True,
        )
        # Поле занимает всё оставшееся место.
        self._textbox.grid(row=1, column=0, sticky="nsew", padx=Layout.PAD_INNER, pady=(0, Layout.PAD_INNER))
        # Создаём цветовой «тег» для каждого уровня лога.
        for level, color in LEVEL_COLORS.items():
            # Тег с именем уровня окрашивает текст в нужный цвет.
            self._textbox.tag_config(level.value, foreground=color)
        # Отдельный тег для серых отметок времени.
        self._textbox.tag_config("timestamp", foreground=Colors.TEXT_MUTED)
        # Запрещаем пользователю печатать в лог (только чтение).
        self._textbox.configure(state="disabled")

    def append(self, text: str, level: LogLevel = LogLevel.INFO, when: Optional[datetime] = None) -> None:
        """Добавить строку в конец лога."""
        # Время строки: переданное или текущее.
        moment = (when or datetime.now()).strftime("%H:%M:%S")
        # Значок уровня.
        icon = LEVEL_ICONS.get(level, "•")
        # Перед шагами добавляем пустую строку для визуального разделения (кроме самой первой).
        prefix_newline = "\n" if level == LogLevel.STEP and not self.is_empty() else ""
        # Временно разрешаем изменение текста.
        self._textbox.configure(state="normal")
        # Пустая строка-разделитель перед шагом (если нужна).
        if prefix_newline:
            self._textbox.insert("end", prefix_newline)
        # Серая отметка времени.
        self._textbox.insert("end", f"[{moment}] ", "timestamp")
        # Цветной текст сообщения.
        self._textbox.insert("end", f"{icon} {text}\n", level.value)
        # Удаляем самые старые строки, если лог слишком разросся.
        self._trim()
        # Снова запрещаем редактирование.
        self._textbox.configure(state="disabled")
        # Автоматически прокручиваем к последней строке.
        self._textbox.see("end")

    def clear(self) -> None:
        """Полностью очистить лог."""
        # Разрешаем изменения.
        self._textbox.configure(state="normal")
        # Удаляем весь текст.
        self._textbox.delete("1.0", "end")
        # Запрещаем изменения.
        self._textbox.configure(state="disabled")

    def get_text(self) -> str:
        """Получить весь текст лога."""
        # «end-1c» — до конца, не включая последний служебный перевод строки.
        return self._textbox.get("1.0", "end-1c")

    def is_empty(self) -> bool:
        """True, если в логе пока ничего нет."""
        # Пустая строка после удаления пробелов означает пустой лог.
        return not self.get_text().strip()

    def copy_to_clipboard(self) -> None:
        """Скопировать весь лог в буфер обмена (удобно для отправки разработчику)."""
        # Очищаем буфер обмена.
        self.clipboard_clear()
        # Кладём в него текст лога.
        self.clipboard_append(self.get_text())

    def _trim(self) -> None:
        """Удалить старые строки, если их больше лимита из настроек."""
        # Номер последней строки = количество строк.
        line_count = int(self._textbox.index("end-1c").split(".")[0])
        # Сколько строк лишние.
        excess = line_count - Behaviour.MAX_LOG_LINES
        # Если лишние есть — удаляем их с начала.
        if excess > 0:
            self._textbox.delete("1.0", f"{excess + 1}.0")
