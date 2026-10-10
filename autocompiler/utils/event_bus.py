"""
Потокобезопасная «шина событий» между фоновой сборкой и окном программы.

Почему это нужно: tkinter (и customtkinter) НЕ позволяет менять окно из чужих
потоков — это приводит к случайным зависаниям и вылетам. Поэтому фоновый поток
только кладёт события в очередь, а окно само забирает их по таймеру.
"""

# Отложенная обработка аннотаций — можно писать «list[str]» на Python 3.9.
from __future__ import annotations

# queue.Queue — встроенная потокобезопасная очередь.
import queue
# datetime — чтобы ставить время у каждой строки лога.
from datetime import datetime
# dataclass — короткая запись классов-«контейнеров» данных.
from dataclasses import dataclass, field
# Enum — перечисления (фиксированный набор вариантов).
from enum import Enum
# Типы для подсказок: «любое значение» и «может быть None».
from typing import Any, Optional


class EventKind(str, Enum):
    """Виды событий, которые фоновая сборка может отправить окну."""

    # Новая строка в лог.
    LOG = "log"
    # Обновление короткой строки статуса под прогресс-баром.
    STATUS = "status"
    # Обновление прогресс-бара (число 0..1 или None = «бегущая» полоска).
    PROGRESS = "progress"
    # Серьёзная ошибка — окно покажет красный диалог.
    ERROR = "error"
    # Сборка завершена (успешно или нет).
    FINISHED = "finished"


class LogLevel(str, Enum):
    """Уровень важности строки лога — от него зависит цвет текста."""

    # Заголовок крупного шага («Шаг 1: Анализ кода…») — голубой.
    STEP = "step"
    # Обычное информационное сообщение — светлый текст.
    INFO = "info"
    # Успех — зелёный.
    SUCCESS = "success"
    # Предупреждение — жёлтый.
    WARNING = "warning"
    # Ошибка — красный.
    ERROR = "error"
    # Технические подробности — приглушённый серый.
    DEBUG = "debug"


@dataclass(frozen=True)
class UiEvent:
    """Одно событие для окна: вид + произвольные данные + время создания."""

    # Вид события (см. EventKind).
    kind: EventKind
    # Данные события в виде словаря (у каждого вида — свои ключи).
    payload: dict[str, Any] = field(default_factory=dict)
    # Время создания события — для отметок времени в логе.
    created_at: datetime = field(default_factory=datetime.now)


class EventBus:
    """Удобная обёртка над очередью: понятные методы вместо «сырых» событий."""

    def __init__(self) -> None:
        # Создаём саму потокобезопасную очередь без ограничения размера.
        self._queue: "queue.Queue[UiEvent]" = queue.Queue()

    # ------------------------------------------------------------------ #
    #   Методы для ФОНОВОГО потока (отправка событий)                     #
    # ------------------------------------------------------------------ #

    def _put(self, kind: EventKind, **payload: Any) -> None:
        """Внутренний метод: упаковать данные в событие и положить в очередь."""
        # put_nowait не блокирует поток — очередь безразмерная, места хватит всегда.
        self._queue.put_nowait(UiEvent(kind=kind, payload=payload))

    def log(self, text: str, level: LogLevel = LogLevel.INFO) -> None:
        """Добавить строку в лог с нужным уровнем важности."""
        # Отправляем событие LOG с текстом и уровнем.
        self._put(EventKind.LOG, text=str(text), level=level)

    def step(self, number: int, title: str) -> None:
        """Записать в лог заголовок крупного шага и обновить статус."""
        # Формируем текст заголовка шага простым языком.
        text = f"Шаг {number}: {title}…"
        # Пишем заголовок в лог голубым цветом.
        self.log(text, LogLevel.STEP)
        # Дублируем его в строку статуса, чтобы пользователь видел текущий этап.
        self.status(text)

    def info(self, text: str) -> None:
        """Короткий вызов для обычного сообщения."""
        # Просто перенаправляем в log с уровнем INFO.
        self.log(text, LogLevel.INFO)

    def success(self, text: str) -> None:
        """Короткий вызов для сообщения об успехе."""
        # Перенаправляем в log с уровнем SUCCESS (зелёный цвет).
        self.log(text, LogLevel.SUCCESS)

    def warning(self, text: str) -> None:
        """Короткий вызов для предупреждения."""
        # Перенаправляем в log с уровнем WARNING (жёлтый цвет).
        self.log(text, LogLevel.WARNING)

    def debug(self, text: str) -> None:
        """Короткий вызов для технических подробностей."""
        # Перенаправляем в log с уровнем DEBUG (серый цвет).
        self.log(text, LogLevel.DEBUG)

    def status(self, text: str) -> None:
        """Обновить строку статуса под прогресс-баром."""
        # Отправляем событие STATUS с новым текстом.
        self._put(EventKind.STATUS, text=str(text))

    def progress(self, value: Optional[float]) -> None:
        """Обновить прогресс: число от 0 до 1 или None для «бегущей» полоски."""
        # Если передано число — зажимаем его в диапазон 0..1 на всякий случай.
        if value is not None:
            # max/min гарантируют, что значение не выйдет за границы.
            value = max(0.0, min(1.0, float(value)))
        # Отправляем событие PROGRESS.
        self._put(EventKind.PROGRESS, value=value)

    def error(self, title: str, message: str, hint: str = "", details: str = "") -> None:
        """Сообщить о серьёзной ошибке — окно покажет красный диалог."""
        # Отправляем событие ERROR со всеми частями описания ошибки.
        self._put(EventKind.ERROR, title=title, message=message, hint=hint, details=details)

    def finished(self, success: bool, output_path: Optional[str] = None, summary: str = "") -> None:
        """Сообщить о завершении сборки."""
        # output_path — путь к готовому .exe (если он есть), summary — итоговая фраза.
        self._put(EventKind.FINISHED, success=bool(success), output_path=output_path, summary=summary)

    # ------------------------------------------------------------------ #
    #   Методы для ГЛАВНОГО потока (окна) — получение событий             #
    # ------------------------------------------------------------------ #

    def drain(self, max_items: int) -> list[UiEvent]:
        """Забрать из очереди не больше max_items событий, не блокируя окно."""
        # Сюда складываем полученные события.
        events: list[UiEvent] = []
        # Забираем события, пока не наберём лимит.
        while len(events) < max_items:
            # Пытаемся взять событие без ожидания.
            try:
                # get_nowait сразу выбрасывает queue.Empty, если очередь пуста.
                events.append(self._queue.get_nowait())
            # Очередь опустела — выходим из цикла.
            except queue.Empty:
                break
        # Возвращаем пачку событий окну.
        return events
