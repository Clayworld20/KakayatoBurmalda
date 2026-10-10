"""
Главное окно Авто-Компилятора.

Устройство окна (сверху вниз):
    1. Шапка — название и подзаголовок.
    2. Карточка «Главный файл программы» — большая кнопка выбора .py и поле пути.
    3. Карточка «Настройки сборки» — два переключателя и выбор иконки.
    4. Большая кнопка «Собрать .exe» + прогресс-бар + строка статуса.
    5. Большое поле лога «Ход сборки».
    6. Зелёная кнопка «Открыть папку с готовым файлом» (появляется после успеха).

Правило безопасности потоков: окно меняется ТОЛЬКО из главного потока.
Фоновая сборка общается с окном через EventBus, который окно опрашивает по таймеру.
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# threading — запуск сборки в фоне, чтобы окно не «зависало».
import threading
# Path — работа с путями.
from pathlib import Path
# Стандартные диалоги tkinter: выбор файла и вопрос «да/нет».
from tkinter import filedialog, messagebox
# Типы для подсказок.
from typing import Optional

# Библиотека современного интерфейса.
import customtkinter as ctk

# Название и версия приложения.
from autocompiler import APP_NAME, APP_VERSION
# Все настройки внешнего вида.
from autocompiler.config import Behaviour, Colors, Fonts, Layout, Texts
# Конвейер сборки и его настройки.
from autocompiler.core.pipeline import BuildPipeline, BuildSettings
# Красное окно ошибки.
from autocompiler.gui.dialogs import ErrorDialog
# Виджеты-«кирпичики».
from autocompiler.gui.widgets import LogConsole, PathField, SectionCard
# Перевод ошибок на понятный язык.
from autocompiler.utils.errors import describe_exception
# Шина событий и её типы.
from autocompiler.utils.event_bus import EventBus, EventKind, LogLevel, UiEvent
# Открытие проводника.
from autocompiler.utils.system import reveal_in_explorer


class MainWindow(ctk.CTk):
    """Главное окно приложения."""

    def __init__(self) -> None:
        # Включаем тёмную тему customtkinter ДО создания окна.
        ctk.set_appearance_mode("dark")
        # Базовая цветовая схема (наши цвета всё равно задаются явно).
        ctk.set_default_color_theme("dark-blue")
        # Создаём само окно Tk.
        super().__init__()

        # --- Состояние окна ---
        # Шина событий между фоновой сборкой и окном.
        self.bus = EventBus()
        # Путь к выбранному главному файлу (None — ещё не выбран).
        self._script_path: Optional[Path] = None
        # Путь к выбранной иконке (None — стандартная).
        self._icon_path: Optional[Path] = None
        # Путь к готовому .exe после успешной сборки.
        self._result_path: Optional[Path] = None
        # Фоновый поток сборки (None — сборка не идёт).
        self._worker: Optional[threading.Thread] = None
        # Флаг «идёт сборка».
        self._busy = False
        # Последняя папка, открытая в проводнике (чтобы не листать каждый раз заново).
        self._last_dir: Optional[str] = None
        # Защита от «лавины» окон ошибок, если ошибка возникает в цикле.
        self._showing_error = False

        # Переменная переключателя «Скрыть консоль» (по умолчанию выключено).
        self.hide_console_var = ctk.BooleanVar(value=False)
        # Переменная переключателя «Один файл» (по умолчанию включено — удобнее новичкам).
        self.one_file_var = ctk.BooleanVar(value=True)

        # --- Сборка интерфейса ---
        self._configure_window()
        # Создаём шрифты (их можно создать только после запуска Tk).
        self._create_fonts()
        # Создаём все элементы окна.
        self._build_header()
        # Карточка выбора файла.
        self._build_file_section()
        # Карточка настроек.
        self._build_options_section()
        # Кнопка сборки и прогресс.
        self._build_action_section()
        # Поле лога.
        self._build_log_section()
        # Кнопка «Открыть папку» (изначально скрыта).
        self._build_result_section()

        # --- Защита от сбоев ---
        self._install_exception_hooks()

        # Приветственное сообщение в логе.
        self.log_console.append(f"{APP_NAME} {APP_VERSION} готов к работе.", LogLevel.SUCCESS)
        # Подсказка о первом действии.
        self.log_console.append("Нажмите «Выбрать главный файл программы (.py)», чтобы начать.", LogLevel.INFO)
        # Обновляем доступность кнопок.
        self._refresh_controls()
        # Запускаем периодический опрос событий из фонового потока.
        self.after(Behaviour.POLL_INTERVAL_MS, self._poll_events)

    # ================================================================== #
    #   ПОСТРОЕНИЕ ИНТЕРФЕЙСА                                             #
    # ================================================================== #

    def _configure_window(self) -> None:
        """Базовые параметры окна."""
        # Заголовок окна.
        self.title(f"{APP_NAME} — сборка Python в .exe")
        # Стартовый размер.
        self.geometry(Layout.WINDOW_SIZE)
        # Минимальный размер.
        self.minsize(Layout.MIN_WIDTH, Layout.MIN_HEIGHT)
        # Глубокий тёмный фон.
        self.configure(fg_color=Colors.BACKGROUND)
        # Единственная колонка растягивается по ширине.
        self.grid_columnconfigure(0, weight=1)
        # Строка с логом (номер 4) забирает всё свободное место по высоте.
        self.grid_rowconfigure(4, weight=1)
        # Перехватываем закрытие окна крестиком (чтобы спросить, если идёт сборка).
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _create_fonts(self) -> None:
        """Создать все шрифты окна."""
        # Крупный заголовок приложения.
        self.font_title = ctk.CTkFont(family=Fonts.UI_FAMILY, size=26, weight="bold")
        # Подзаголовок.
        self.font_subtitle = ctk.CTkFont(family=Fonts.UI_FAMILY, size=14)
        # Заголовки карточек.
        self.font_section = ctk.CTkFont(family=Fonts.UI_FAMILY, size=16, weight="bold")
        # Обычный текст.
        self.font_body = ctk.CTkFont(family=Fonts.UI_FAMILY, size=13)
        # Мелкие подсказки.
        self.font_hint = ctk.CTkFont(family=Fonts.UI_FAMILY, size=12)
        # Текст обычных кнопок.
        self.font_button = ctk.CTkFont(family=Fonts.UI_FAMILY, size=13, weight="bold")
        # Текст больших кнопок.
        self.font_big_button = ctk.CTkFont(family=Fonts.UI_FAMILY, size=16, weight="bold")
        # Моноширинный шрифт лога.
        self.font_mono = ctk.CTkFont(family=Fonts.MONO_FAMILY, size=13)

    def _build_header(self) -> None:
        """Шапка с названием программы."""
        # Прозрачный контейнер шапки.
        header = ctk.CTkFrame(self, fg_color="transparent")
        # Размещаем сверху с внешними отступами.
        header.grid(row=0, column=0, sticky="ew", padx=Layout.PAD_OUTER, pady=(Layout.PAD_OUTER, 10))
        # Колонка растягивается.
        header.grid_columnconfigure(0, weight=1)
        # Название программы (акцентный значок + текст).
        ctk.CTkLabel(header, text=f"⚙  {APP_NAME}", font=self.font_title, text_color=Colors.TEXT, anchor="w").grid(
            row=0, column=0, sticky="w"
        )
        # Номер версии справа.
        ctk.CTkLabel(header, text=f"v{APP_VERSION}", font=self.font_hint, text_color=Colors.TEXT_MUTED).grid(
            row=0, column=1, sticky="e"
        )
        # Подзаголовок с описанием.
        ctk.CTkLabel(header, text=Texts.SUBTITLE, font=self.font_subtitle, text_color=Colors.TEXT_MUTED, anchor="w").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )

    def _build_file_section(self) -> None:
        """Карточка выбора главного .py-файла."""
        # Создаём карточку с заголовком.
        card = SectionCard(self, Texts.SECTION_FILE, self.font_section)
        # Размещаем карточку.
        card.grid(row=1, column=0, sticky="ew", padx=Layout.PAD_OUTER, pady=(0, 12))
        # Большая акцентная кнопка выбора файла.
        self.pick_script_button = ctk.CTkButton(
            card.body,
            text=f"📂  {Texts.PICK_SCRIPT}" if _emoji_supported(self) else Texts.PICK_SCRIPT,
            command=self._on_pick_script,
            height=Layout.BIG_BUTTON_HEIGHT,
            corner_radius=Layout.RADIUS,
            font=self.font_big_button,
            fg_color=Colors.ACCENT,
            hover_color=Colors.ACCENT_HOVER,
            text_color="#ffffff",
        )
        # Кнопка во всю ширину карточки.
        self.pick_script_button.grid(row=0, column=0, sticky="ew")
        # Поле с выбранным путём.
        self.script_field = PathField(card.body, Texts.NO_SCRIPT, self.font_body)
        # Размещаем под кнопкой.
        self.script_field.grid(row=1, column=0, sticky="ew", pady=(10, 0))

    def _build_options_section(self) -> None:
        """Карточка настроек: переключатели и иконка."""
        # Создаём карточку.
        card = SectionCard(self, Texts.SECTION_OPTIONS, self.font_section)
        # Размещаем.
        card.grid(row=2, column=0, sticky="ew", padx=Layout.PAD_OUTER, pady=(0, 12))
        # Две колонки одинаковой ширины: слева переключатели, справа иконка.
        card.body.grid_columnconfigure((0, 1), weight=1, uniform="options")

        # --- Левая колонка: переключатели ---
        switches = ctk.CTkFrame(card.body, fg_color="transparent")
        # Левая колонка.
        switches.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        # Переключатель «Скрыть консоль» с подсказкой.
        self.hide_console_switch = self._make_switch(switches, 0, Texts.HIDE_CONSOLE, Texts.HIDE_CONSOLE_HINT, self.hide_console_var)
        # Переключатель «Один файл» с подсказкой.
        self.one_file_switch = self._make_switch(switches, 2, Texts.ONE_FILE, Texts.ONE_FILE_HINT, self.one_file_var)

        # --- Правая колонка: иконка ---
        icon_box = ctk.CTkFrame(card.body, fg_color="transparent")
        # Правая колонка.
        icon_box.grid(row=0, column=1, sticky="nsew", padx=(12, 0))
        # Колонка с кнопкой выбора растягивается.
        icon_box.grid_columnconfigure(0, weight=1)
        # Кнопка «Выбрать иконку (.ico)».
        self.pick_icon_button = ctk.CTkButton(
            icon_box,
            text=Texts.PICK_ICON,
            command=self._on_pick_icon,
            height=Layout.BUTTON_HEIGHT,
            corner_radius=8,
            font=self.font_button,
            fg_color=Colors.SURFACE_ALT,
            hover_color=Colors.BORDER,
            border_width=1,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT,
        )
        # Размещаем кнопку.
        self.pick_icon_button.grid(row=0, column=0, sticky="ew")
        # Маленькая кнопка «✖» — сбросить иконку.
        self.clear_icon_button = ctk.CTkButton(
            icon_box,
            text="✖",
            width=Layout.BUTTON_HEIGHT,
            command=self._on_clear_icon,
            height=Layout.BUTTON_HEIGHT,
            corner_radius=8,
            font=self.font_button,
            fg_color=Colors.SURFACE_ALT,
            hover_color=Colors.DANGER_DARK,
            border_width=1,
            border_color=Colors.BORDER,
            text_color=Colors.TEXT_MUTED,
        )
        # Размещаем справа от кнопки выбора.
        self.clear_icon_button.grid(row=0, column=1, padx=(8, 0))
        # Поле с путём к иконке.
        self.icon_field = PathField(icon_box, Texts.NO_ICON, self.font_hint)
        # Под кнопками, на всю ширину.
        self.icon_field.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))

    def _make_switch(self, master, row: int, text: str, hint: str, variable: ctk.BooleanVar) -> ctk.CTkSwitch:
        """Создать переключатель с серой подсказкой под ним."""
        # Сам переключатель.
        switch = ctk.CTkSwitch(
            master,
            text=text,
            variable=variable,
            onvalue=True,
            offvalue=False,
            font=self.font_body,
            text_color=Colors.TEXT,
            progress_color=Colors.ACCENT,
            button_color="#ffffff",
            button_hover_color="#dcdcdc",
            fg_color=Colors.BORDER,
            command=self._on_option_changed,
        )
        # Размещаем переключатель.
        switch.grid(row=row, column=0, sticky="w", pady=(0 if row == 0 else 10, 0))
        # Подсказка под переключателем (с отступом под текст переключателя).
        ctk.CTkLabel(master, text=hint, font=self.font_hint, text_color=Colors.TEXT_MUTED, anchor="w").grid(
            row=row + 1, column=0, sticky="w", padx=(50, 0)
        )
        # Возвращаем переключатель, чтобы его можно было блокировать во время сборки.
        return switch

    def _build_action_section(self) -> None:
        """Большая кнопка сборки, прогресс-бар и строка статуса."""
        # Прозрачный контейнер.
        box = ctk.CTkFrame(self, fg_color="transparent")
        # Размещаем под настройками.
        box.grid(row=3, column=0, sticky="ew", padx=Layout.PAD_OUTER, pady=(0, 12))
        # Колонка растягивается.
        box.grid_columnconfigure(0, weight=1)
        # Главная кнопка «Собрать .exe».
        self.build_button = ctk.CTkButton(
            box,
            text=Texts.BUILD,
            command=self._on_build,
            height=Layout.BIG_BUTTON_HEIGHT,
            corner_radius=Layout.RADIUS,
            font=self.font_big_button,
            fg_color=Colors.ACCENT,
            hover_color=Colors.ACCENT_HOVER,
            text_color="#ffffff",
            text_color_disabled=Colors.TEXT_MUTED,
        )
        # Кнопка во всю ширину.
        self.build_button.grid(row=0, column=0, sticky="ew")
        # Прогресс-бар.
        self.progress_bar = ctk.CTkProgressBar(
            box, height=8, corner_radius=4, progress_color=Colors.ACCENT, fg_color=Colors.SURFACE_ALT, mode="determinate"
        )
        # Изначально пустой.
        self.progress_bar.set(0)
        # Под кнопкой.
        self.progress_bar.grid(row=1, column=0, sticky="ew", pady=(12, 6))
        # Строка статуса.
        self.status_label = ctk.CTkLabel(
            box, text=Texts.STATUS_IDLE, font=self.font_body, text_color=Colors.TEXT_MUTED, anchor="w"
        )
        # Под прогресс-баром.
        self.status_label.grid(row=2, column=0, sticky="ew")

    def _build_log_section(self) -> None:
        """Большое поле лога сборки."""
        # Создаём консоль лога.
        self.log_console = LogConsole(
            self,
            title=Texts.SECTION_LOG,
            title_font=self.font_section,
            mono_font=self.font_mono,
            button_font=self.font_hint,
        )
        # Растягиваем во все стороны (строка 4 имеет weight=1).
        self.log_console.grid(row=4, column=0, sticky="nsew", padx=Layout.PAD_OUTER, pady=(0, 12))

    def _build_result_section(self) -> None:
        """Зелёная кнопка «Открыть папку с готовым файлом»."""
        # Большая зелёная кнопка.
        self.result_button = ctk.CTkButton(
            self,
            text=f"✔  {Texts.OPEN_RESULT}",
            command=self._on_open_result,
            height=Layout.BIG_BUTTON_HEIGHT,
            corner_radius=Layout.RADIUS,
            font=self.font_big_button,
            fg_color=Colors.SUCCESS,
            hover_color=Colors.SUCCESS_HOVER,
            text_color="#ffffff",
        )
        # Размещаем внизу окна.
        self.result_button.grid(row=5, column=0, sticky="ew", padx=Layout.PAD_OUTER, pady=(0, Layout.PAD_OUTER))
        # Сразу прячем — кнопка появится только после успешной сборки.
        self.result_button.grid_remove()

    # ================================================================== #
    #   ОБРАБОТЧИКИ ДЕЙСТВИЙ ПОЛЬЗОВАТЕЛЯ                                  #
    # ================================================================== #

    def _on_pick_script(self) -> None:
        """Кнопка «Выбрать главный файл программы (.py)»."""
        # Открываем стандартный проводник Windows.
        filename = filedialog.askopenfilename(
            parent=self,
            title="Выберите главный файл вашей программы",
            initialdir=self._last_dir,
            filetypes=[("Python-скрипты", "*.py *.pyw"), ("Все файлы", "*.*")],
        )
        # Пользователь нажал «Отмена» — ничего не делаем.
        if not filename:
            return
        # Превращаем строку в Path.
        path = Path(filename)
        # Мягкая проверка расширения прямо при выборе.
        if path.suffix.lower() not in (".py", ".pyw"):
            # Показываем понятную ошибку и не меняем текущий выбор.
            self.show_error(
                "Неподходящий тип файла",
                f"Файл «{path.name}» не похож на Python-скрипт.",
                "Выберите файл с расширением .py или .pyw — это главный файл вашей программы.",
            )
            # Прерываем обработку.
            return
        # Сохраняем выбор.
        self._script_path = path
        # Запоминаем папку для следующего открытия проводника.
        self._last_dir = str(path.parent)
        # Показываем путь в поле.
        self.script_field.set_path(str(path))
        # Прячем кнопку результата от прошлой сборки.
        self._hide_result()
        # Сбрасываем прогресс-бар и возвращаем ему акцентный цвет (после ошибки он красный).
        self.progress_bar.configure(progress_color=Colors.ACCENT)
        # Обнуляем заполнение полоски.
        self.progress_bar.set(0)
        # Сообщаем в лог.
        self.log_console.append(f"Выбран файл: {path}", LogLevel.INFO)
        # Обновляем статус.
        self._set_status(Texts.STATUS_READY, Colors.TEXT)
        # Разблокируем кнопку сборки.
        self._refresh_controls()

    def _on_pick_icon(self) -> None:
        """Кнопка «Выбрать иконку (.ico)»."""
        # Открываем проводник с фильтром .ico.
        filename = filedialog.askopenfilename(
            parent=self,
            title="Выберите иконку для программы",
            initialdir=self._last_dir,
            filetypes=[("Иконки Windows", "*.ico"), ("Все файлы", "*.*")],
        )
        # Отмена — ничего не делаем.
        if not filename:
            return
        # Превращаем в Path.
        path = Path(filename)
        # Проверяем расширение.
        if path.suffix.lower() != ".ico":
            # Понятная ошибка.
            self.show_error(
                "Нужна иконка в формате .ico",
                f"Файл «{path.name}» не является иконкой Windows.",
                "Сконвертируйте картинку (.png/.jpg) в .ico любым онлайн-конвертером и выберите её снова.",
            )
            # Прерываем.
            return
        # Сохраняем выбор.
        self._icon_path = path
        # Показываем путь.
        self.icon_field.set_path(str(path))
        # Пишем в лог.
        self.log_console.append(f"Выбрана иконка: {path.name}", LogLevel.INFO)
        # Обновляем состояние кнопок (появится крестик сброса).
        self._refresh_controls()

    def _on_clear_icon(self) -> None:
        """Кнопка «✖» — вернуть стандартную иконку."""
        # Сбрасываем выбор.
        self._icon_path = None
        # Очищаем поле.
        self.icon_field.set_path(None)
        # Пишем в лог.
        self.log_console.append("Иконка сброшена — будет использована стандартная.", LogLevel.INFO)
        # Обновляем кнопки.
        self._refresh_controls()

    def _on_option_changed(self) -> None:
        """Пользователь переключил одну из галочек."""
        # Описание режима консоли простым языком.
        console = "консоль будет скрыта" if self.hide_console_var.get() else "консоль будет видна"
        # Описание режима упаковки.
        mode = "один файл" if self.one_file_var.get() else "папка с файлами"
        # Короткая запись в лог.
        self.log_console.append(f"Настройки: {mode}, {console}.", LogLevel.DEBUG)

    def _on_build(self) -> None:
        """Кнопка «Собрать .exe» — запуск сборки в фоновом потоке."""
        # Защита от двойного нажатия.
        if self._busy:
            return
        # Файл не выбран — подсказываем.
        if self._script_path is None:
            self.show_error("Файл не выбран", "Сначала выберите главный файл программы.", "Нажмите большую фиолетовую кнопку вверху окна.")
            return
        # Собираем настройки из элементов окна.
        settings = BuildSettings(
            script_path=self._script_path,
            icon_path=self._icon_path,
            hide_console=bool(self.hide_console_var.get()),
            one_file=bool(self.one_file_var.get()),
        )
        # Прячем результат прошлой сборки.
        self._hide_result()
        # Переводим окно в режим «идёт сборка».
        self._set_busy(True)
        # Разделитель в логе для новой сборки.
        self.log_console.append("═" * 20 + "  Новая сборка  " + "═" * 20, LogLevel.DEBUG)
        # Создаём конвейер сборки.
        pipeline = BuildPipeline(settings, self.bus)
        # Фоновый поток-«демон» (не мешает закрыть программу).
        self._worker = threading.Thread(target=pipeline.run, name="BuildWorker", daemon=True)
        # Запускаем.
        self._worker.start()

    def _on_open_result(self) -> None:
        """Кнопка «Открыть папку с готовым файлом»."""
        # Защитимся от ситуации, когда результата нет.
        if self._result_path is None:
            return
        # Открытие проводника может не удаться (файл удалили антивирусом и т.п.).
        try:
            # Открываем проводник с выделенным .exe.
            reveal_in_explorer(self._result_path)
        # Любую ошибку показываем понятным красным окном.
        except Exception as exc:  # noqa: BLE001
            # Переводим ошибку на понятный язык.
            err = describe_exception(exc, "Открытие папки")
            # Показываем.
            self.show_error(err.title, err.message, err.hint, err.details)

    def _on_close(self) -> None:
        """Закрытие окна крестиком."""
        # Если идёт сборка — спрашиваем подтверждение.
        if self._busy and not messagebox.askyesno(
            "Сборка ещё идёт", "Сборка ещё не завершена. Точно закрыть программу?", parent=self
        ):
            # Пользователь передумал.
            return
        # Закрываем окно и завершаем программу.
        self.destroy()

    # ================================================================== #
    #   ОБРАБОТКА СОБЫТИЙ ИЗ ФОНОВОГО ПОТОКА                               #
    # ================================================================== #

    def _poll_events(self) -> None:
        """Каждые ~60 мс забираем события из шины и применяем их к окну."""
        # Обработка обёрнута в try, чтобы одна «кривая» запись не остановила опрос навсегда.
        try:
            # Забираем пачку событий.
            for event in self.bus.drain(Behaviour.MAX_EVENTS_PER_TICK):
                # Обрабатываем каждое.
                self._handle_event(event)
        # Ошибка обработки — пишем в лог, но опрос продолжаем.
        except Exception as exc:  # noqa: BLE001
            # Красная строка в логе (без всплывающего окна, чтобы не спамить).
            self.log_console.append(f"Внутренняя ошибка интерфейса: {exc}", LogLevel.ERROR)
        # В любом случае планируем следующий опрос.
        finally:
            # Окно могли закрыть — тогда after выбросит ошибку, игнорируем её.
            try:
                # Следующий «тик» опроса.
                self.after(Behaviour.POLL_INTERVAL_MS, self._poll_events)
            # Окно уже уничтожено.
            except Exception:  # noqa: BLE001
                pass

    def _handle_event(self, event: UiEvent) -> None:
        """Применить одно событие к окну."""
        # Данные события.
        data = event.payload
        # Новая строка лога.
        if event.kind == EventKind.LOG:
            self.log_console.append(data.get("text", ""), data.get("level", LogLevel.INFO), event.created_at)
        # Обновление статуса.
        elif event.kind == EventKind.STATUS:
            self._set_status(data.get("text", ""), Colors.TEXT)
        # Обновление прогресса.
        elif event.kind == EventKind.PROGRESS:
            self._set_progress(data.get("value"))
        # Серьёзная ошибка — красное окно.
        elif event.kind == EventKind.ERROR:
            self.show_error(data.get("title", "Ошибка"), data.get("message", ""), data.get("hint", ""), data.get("details", ""))
        # Завершение сборки.
        elif event.kind == EventKind.FINISHED:
            self._on_build_finished(bool(data.get("success")), data.get("output_path"), data.get("summary", ""))

    def _on_build_finished(self, success: bool, output_path: Optional[str], summary: str) -> None:
        """Сборка закончилась — возвращаем окно в обычный режим."""
        # Снимаем режим «идёт сборка».
        self._set_busy(False)
        # Поток больше не нужен.
        self._worker = None
        # Успех.
        if success:
            # Прогресс-бар до конца.
            self._set_progress(1.0)
            # Зелёный статус.
            self._set_status(summary or "Готово!", Colors.SUCCESS)
            # Если есть готовый файл — показываем зелёную кнопку.
            if output_path:
                self._show_result(Path(output_path))
        # Неудача.
        else:
            # Прогресс-бар красным, чтобы было видно, что что-то пошло не так.
            self.progress_bar.configure(progress_color=Colors.DANGER)
            # Красный статус.
            self._set_status(summary or "Сборка не удалась.", Colors.DANGER)

    # ================================================================== #
    #   ВСПОМОГАТЕЛЬНЫЕ МЕТОДЫ СОСТОЯНИЯ ОКНА                              #
    # ================================================================== #

    def _set_busy(self, busy: bool) -> None:
        """Включить/выключить режим «идёт сборка»."""
        # Запоминаем флаг.
        self._busy = busy
        # Текст главной кнопки.
        self.build_button.configure(text=Texts.BUILDING if busy else Texts.BUILD)
        # Возвращаем акцентный цвет прогресс-бару (мог стать красным после ошибки).
        self.progress_bar.configure(progress_color=Colors.ACCENT)
        # При старте сборки сбрасываем прогресс в ноль.
        if busy:
            self._set_progress(0.0)
        # Блокируем/разблокируем элементы.
        self._refresh_controls()

    def _refresh_controls(self) -> None:
        """Включить или выключить кнопки в зависимости от состояния."""
        # Во время сборки — всё заблокировано; иначе — активно.
        idle_state = "disabled" if self._busy else "normal"
        # Кнопка выбора файла.
        self.pick_script_button.configure(state=idle_state)
        # Кнопка выбора иконки.
        self.pick_icon_button.configure(state=idle_state)
        # Крестик сброса иконки активен, только если иконка выбрана и сборка не идёт.
        self.clear_icon_button.configure(state="normal" if (self._icon_path and not self._busy) else "disabled")
        # Переключатели.
        self.hide_console_switch.configure(state=idle_state)
        # Второй переключатель.
        self.one_file_switch.configure(state=idle_state)
        # Кнопка сборки активна, только если файл выбран и сборка не идёт.
        can_build = self._script_path is not None and not self._busy
        # Применяем состояние и цвет (серый, когда недоступна).
        self.build_button.configure(
            state="normal" if can_build else "disabled",
            fg_color=Colors.ACCENT if can_build or self._busy else Colors.DISABLED,
        )

    def _set_status(self, text: str, color: str = Colors.TEXT_MUTED) -> None:
        """Обновить строку статуса."""
        # Меняем текст и цвет.
        self.status_label.configure(text=text, text_color=color)

    def _set_progress(self, value: Optional[float]) -> None:
        """Обновить прогресс-бар (None — «бегущая» полоска неопределённой длительности)."""
        # Неопределённый прогресс — включаем анимацию.
        if value is None:
            # Режим «бегущая полоска».
            self.progress_bar.configure(mode="indeterminate")
            # Запуск анимации.
            self.progress_bar.start()
        # Конкретное значение.
        else:
            # Останавливаем анимацию (если была).
            self.progress_bar.stop()
            # Обычный режим.
            self.progress_bar.configure(mode="determinate")
            # Устанавливаем значение.
            self.progress_bar.set(value)

    def _show_result(self, path: Path) -> None:
        """Показать зелёную кнопку «Открыть папку»."""
        # Запоминаем путь к .exe.
        self._result_path = path
        # Возвращаем кнопку на её место в сетке.
        self.result_button.grid()

    def _hide_result(self) -> None:
        """Спрятать зелёную кнопку."""
        # Забываем путь.
        self._result_path = None
        # Убираем кнопку с экрана.
        self.result_button.grid_remove()

    # ================================================================== #
    #   ЗАЩИТА ОТ СБОЕВ                                                    #
    # ================================================================== #

    def show_error(self, title: str, message: str, hint: str = "", details: str = "") -> None:
        """Показать красное окно ошибки. Никогда не роняет программу."""
        # Если окно ошибки уже открыто — не плодим новые, только пишем в лог.
        if self._showing_error:
            self.log_console.append(f"{title}: {message}", LogLevel.ERROR)
            return
        # Поднимаем флаг «окно ошибки открыто».
        self._showing_error = True
        # Пытаемся показать красивое окно.
        try:
            # Создаём диалог.
            dialog = ErrorDialog(self, title, message, hint, details)
            # Когда диалог закроется — снимем флаг.
            dialog.bind("<Destroy>", lambda e: self._on_error_dialog_closed(e, dialog))
        # Если даже красивое окно не создалось — используем простейшее системное.
        except Exception:  # noqa: BLE001
            # Снимаем флаг.
            self._showing_error = False
            # Стандартное окно Windows с ошибкой.
            messagebox.showerror(title, f"{message}\n\n{hint}".strip(), parent=self)

    def _on_error_dialog_closed(self, event, dialog: ErrorDialog) -> None:
        """Снять флаг, когда окно ошибки закрыто."""
        # Событие <Destroy> приходит и от дочерних виджетов — реагируем только на само окно.
        if event.widget is dialog:
            self._showing_error = False

    def _install_exception_hooks(self) -> None:
        """Перехватывать любые необработанные ошибки и показывать их в красном окне."""
        # Ошибки внутри обработчиков кнопок tkinter.
        self.report_callback_exception = self._on_tk_exception
        # Ошибки в фоновых потоках (Python 3.8+): отправляем их через шину событий.
        threading.excepthook = self._on_thread_exception

    def _on_tk_exception(self, exc_type, exc_value, exc_tb) -> None:
        """Необработанная ошибка в обработчике кнопки/события окна."""
        # Привязываем traceback к объекту исключения.
        exc_value = exc_value.with_traceback(exc_tb) if exc_value is not None else exc_type()
        # Переводим на понятный язык.
        err = describe_exception(exc_value, "Работа интерфейса")
        # Пишем в лог.
        self.log_console.append(f"{err.title}: {err.message}", LogLevel.ERROR)
        # Показываем красное окно.
        self.show_error(err.title, err.message, err.hint, err.details)

    def _on_thread_exception(self, args: threading.ExceptHookArgs) -> None:
        """Необработанная ошибка в фоновом потоке."""
        # Переводим на понятный язык (args.exc_value может быть None в редких случаях).
        err = describe_exception(args.exc_value or args.exc_type(), f"Фоновая задача «{args.thread.name if args.thread else '?'}»")
        # Красная строка в лог — тоже через шину (окно нельзя трогать из чужого потока!).
        self.bus.log(f"{err.title}: {err.message}", LogLevel.ERROR)
        # Красное окно — через шину.
        self.bus.error(err.title, err.message, err.hint, err.details)
        # Если упал поток сборки — сообщаем о завершении, чтобы разблокировать кнопки.
        if args.thread is not None and args.thread.name == "BuildWorker":
            self.bus.finished(False, None, "Сборка остановлена из-за ошибки.")


def _emoji_supported(widget) -> bool:
    """Можно ли безопасно показывать цветные эмодзи (Tk 8.6.10+ корректно их рисует)."""
    # Проверка версии Tcl/Tk может не удаться в экзотических сборках Python.
    try:
        # Спрашиваем полную версию Tk у уже запущенного интерпретатора окна, например «8.6.13».
        patchlevel = str(widget.tk.call("info", "patchlevel"))
        # Превращаем «8.6.13» в кортеж чисел (8, 6, 13).
        version = tuple(int(part) for part in patchlevel.split(".")[:3])
        # Эмодзи за пределами базового набора Unicode надёжно работают с Tk 8.6.10.
        return version >= (8, 6, 10)
    # Не удалось определить — перестраховываемся и не используем эмодзи.
    except Exception:  # noqa: BLE001
        return False
