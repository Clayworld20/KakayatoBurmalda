"""
Конвейер сборки — выполняет этапы по очереди в ФОНОВОМ потоке.

Каждый этап обёрнут в собственный try-except (метод _run_stage), поэтому
любая ошибка превращается в понятное сообщение и красное окно, а программа
продолжает работать.

Сейчас (первый шаг разработки) полностью работает этап «Анализ кода»:
проверка файла, чтение с правильной кодировкой, проверка синтаксиса, проверка иконки.
Этапы «Загрузка библиотек» и «Упаковка в .exe» подключатся на следующих шагах
(модули core/scanner.py, core/environment.py, core/builder.py).
"""

# Отложенная обработка аннотаций типов.
from __future__ import annotations

# tokenize.open умеет правильно определять кодировку .py-файла (BOM, «# coding: …»).
import tokenize
# time — для замера длительности сборки.
import time
# dataclass — короткая запись класса настроек.
from dataclasses import dataclass
# Path — работа с путями.
from pathlib import Path
# Типы для подсказок.
from typing import Callable, Optional, TypeVar

# Шина событий для общения с окном.
from autocompiler.utils.event_bus import EventBus, LogLevel
# Понятные ошибки и переводчик исключений.
from autocompiler.utils.errors import CompilerError, describe_exception, format_traceback

# Обобщённый тип результата этапа (каждый этап может вернуть что угодно).
T = TypeVar("T")

# Допустимые расширения главного файла программы.
SCRIPT_EXTENSIONS = {".py", ".pyw"}
# «Магические» первые 4 байта настоящего .ico-файла.
ICO_MAGIC = b"\x00\x00\x01\x00"


@dataclass(frozen=True)
class BuildSettings:
    """Все настройки, выбранные пользователем в окне, — одним объектом."""

    # Путь к главному .py-файлу программы.
    script_path: Path
    # Путь к иконке .ico (или None — стандартная иконка).
    icon_path: Optional[Path] = None
    # Скрыть консоль (флаг PyInstaller --noconsole).
    hide_console: bool = False
    # Собрать в один файл (флаг PyInstaller --onefile).
    one_file: bool = True


@dataclass
class AnalysisResult:
    """Результат этапа анализа — понадобится следующим этапам."""

    # Полный текст исходного кода.
    source: str
    # Кодировка, в которой был сохранён файл.
    encoding: str
    # Количество строк кода.
    line_count: int


class BuildPipeline:
    """Последовательно выполняет этапы сборки и сообщает о ходе работы в EventBus."""

    # Общее число этапов — нужно для расчёта прогресс-бара.
    TOTAL_STAGES = 3

    def __init__(self, settings: BuildSettings, bus: EventBus) -> None:
        # Сохраняем настройки сборки.
        self.settings = settings
        # Сохраняем шину событий.
        self.bus = bus

    # ------------------------------------------------------------------ #
    #   Точка входа фонового потока                                       #
    # ------------------------------------------------------------------ #

    def run(self) -> None:
        """Запустить все этапы. Этот метод НИКОГДА не выбрасывает исключения наружу."""
        # Запоминаем время старта, чтобы показать длительность сборки.
        started = time.perf_counter()
        # Внешний try-except — последняя линия обороны от любых сбоев.
        try:
            # Сбрасываем прогресс-бар в ноль.
            self.bus.progress(0.0)
            # Этап 1: анализ кода (полностью рабочий уже сейчас).
            analysis = self._run_stage(1, "Анализ кода", self._stage_analyze)
            # Этап 2: загрузка библиотек (будет реализован на следующем шаге).
            self._run_stage(2, "Загрузка библиотек", lambda: self._stage_prepare_environment(analysis))
            # Этап 3: упаковка в .exe (будет реализован на следующем шаге).
            exe_path = self._run_stage(3, "Упаковка в .exe", lambda: self._stage_build(analysis))
            # Считаем, сколько секунд заняла работа.
            elapsed = time.perf_counter() - started
            # Если .exe создан — сообщаем об успехе с путём к файлу.
            if exe_path is not None:
                # Зелёная строка в лог.
                self.bus.success(f"Готово! Сборка заняла {elapsed:.1f} сек. Файл: {exe_path}")
                # Сигнал окну: показать кнопку «Открыть папку».
                self.bus.finished(True, str(exe_path), "Программа успешно собрана!")
            # Пока упаковка не подключена — честно сообщаем, что выполнен только анализ.
            else:
                # Итоговая строка в лог.
                self.bus.success(f"Анализ завершён за {elapsed:.1f} сек. Код готов к упаковке.")
                # Сигнал окну: работа закончена без готового .exe.
                self.bus.finished(True, None, "Анализ завершён. Упаковка в .exe появится на следующем этапе разработки.")
        # Понятная ошибка одного из этапов — показываем её пользователю.
        except CompilerError as exc:
            # Красная строка в лог.
            self.bus.log(f"Ошибка: {exc.title}. {exc.message}", level=LogLevel.ERROR)
            # Красное окно с описанием.
            self.bus.error(exc.title, exc.message, exc.hint, exc.details)
            # Сообщаем окну, что сборка завершилась неудачно.
            self.bus.finished(False, None, "Сборка остановлена из-за ошибки.")
        # Совсем непредвиденная ситуация (например, ошибка внутри самой шины).
        except BaseException as exc:  # noqa: BLE001 — ловим вообще всё, чтобы поток не «умер» молча
            # Переводим ошибку на понятный язык.
            err = describe_exception(exc, "Сборка")
            # Отправляем красное окно.
            self.bus.error(err.title, err.message, err.hint, err.details or format_traceback(exc))
            # Сообщаем о завершении.
            self.bus.finished(False, None, "Сборка остановлена из-за ошибки.")

    # ------------------------------------------------------------------ #
    #   Защитная обёртка для каждого этапа                                #
    # ------------------------------------------------------------------ #

    def _run_stage(self, number: int, title: str, func: Callable[[], T]) -> T:
        """Выполнить один этап с отдельной защитой от сбоев и обновлением прогресса."""
        # Пишем в лог «Шаг N: …» и обновляем статус.
        self.bus.step(number, title)
        # Индивидуальный try-except для этапа.
        try:
            # Выполняем сам этап.
            result = func()
        # Уже понятная ошибка — пробрасываем дальше без изменений.
        except CompilerError:
            raise
        # Любая другая ошибка — переводим на понятный язык с указанием этапа.
        except Exception as exc:  # noqa: BLE001
            # «from exc» сохраняет исходную причину для отладки.
            raise describe_exception(exc, title) from exc
        # Этап прошёл — двигаем прогресс-бар.
        self.bus.progress(number / self.TOTAL_STAGES)
        # Возвращаем результат этапа.
        return result

    # ------------------------------------------------------------------ #
    #   Этап 1 — анализ кода                                              #
    # ------------------------------------------------------------------ #

    def _stage_analyze(self) -> AnalysisResult:
        """Проверить главный файл и иконку, прочитать код и проверить синтаксис."""
        # Короткое имя для удобства.
        script = self.settings.script_path
        # Сообщаем, какой файл анализируем.
        self.bus.info(f"Проверяю файл: {script.name}")

        # Файл должен существовать.
        if not script.is_file():
            raise CompilerError(
                title="Файл не найден",
                message=f"Главный файл программы не найден:\n{script}",
                hint="Выберите файл заново кнопкой «Выбрать главный файл программы».",
            )
        # Расширение должно быть .py или .pyw.
        if script.suffix.lower() not in SCRIPT_EXTENSIONS:
            raise CompilerError(
                title="Неподходящий тип файла",
                message=f"Файл «{script.name}» не похож на Python-скрипт.",
                hint="Выберите файл с расширением .py или .pyw.",
            )

        # Читаем исходный код с автоматическим определением кодировки.
        source, encoding = _read_source(script)
        # Считаем количество строк (splitlines не учитывает завершающий перевод строки).
        line_count = len(source.splitlines())
        # Сообщаем о результатах чтения.
        self.bus.info(f"Файл прочитан. Строк кода: {line_count}, кодировка: {encoding}.")

        # Пустой файл собирать бессмысленно — предупреждаем, но не останавливаемся.
        if not source.strip():
            self.bus.warning("Файл пустой — готовая программа ничего не будет делать.")

        # Проверяем синтаксис: compile() найдёт опечатки, не запуская код.
        self.bus.info("Проверяю код на ошибки…")
        # SyntaxError отсюда будет переведён в понятное сообщение в _run_stage.
        compile(source, str(script), "exec", dont_inherit=True)
        # Синтаксис в порядке.
        self.bus.success("Ошибок в коде не найдено.")

        # Если указана иконка — проверяем её.
        if self.settings.icon_path is not None:
            # Проверка формата иконки.
            _validate_icon(self.settings.icon_path)
            # Иконка подходит.
            self.bus.success(f"Иконка подходит: {self.settings.icon_path.name}")
        # Иконка не выбрана — будет стандартная.
        else:
            self.bus.info("Иконка не выбрана — будет использована стандартная.")

        # Перечисляем выбранные режимы сборки простым языком.
        console_text = "без чёрного окна консоли" if self.settings.hide_console else "с окном консоли"
        # Режим «один файл» или «папка».
        mode_text = "один .exe-файл" if self.settings.one_file else "папка с программой"
        # Пишем итог настроек в лог.
        self.bus.info(f"Режим сборки: {mode_text}, {console_text}.")

        # Возвращаем результат для следующих этапов.
        return AnalysisResult(source=source, encoding=encoding, line_count=line_count)

    # ------------------------------------------------------------------ #
    #   Этапы 2 и 3 — заглушки до следующего шага разработки               #
    # ------------------------------------------------------------------ #

    def _stage_prepare_environment(self, analysis: AnalysisResult) -> None:
        """Сканер импортов + установка библиотек (подключится на шаге 2)."""
        # Честно предупреждаем, что этап ещё не реализован.
        self.bus.warning("Поиск и загрузка библиотек будут подключены на следующем шаге разработки.")

    def _stage_build(self, analysis: AnalysisResult) -> Optional[Path]:
        """Запуск PyInstaller (подключится на шаге 3). Вернёт путь к готовому .exe."""
        # Честно предупреждаем, что этап ещё не реализован.
        self.bus.warning("Упаковка в .exe будет подключена на следующем шаге разработки.")
        # Пока .exe не создаётся — возвращаем None.
        return None


# ---------------------------------------------------------------------- #
#   Вспомогательные функции модуля                                        #
# ---------------------------------------------------------------------- #

def _read_source(path: Path) -> tuple[str, str]:
    """Прочитать .py-файл, правильно определив кодировку. Вернуть (текст, кодировка)."""
    # Сначала пробуем стандартный способ Python (учитывает BOM и «# -*- coding -*-»).
    try:
        # tokenize.open возвращает текстовый файл с уже определённой кодировкой.
        with tokenize.open(str(path)) as handle:
            # Читаем весь текст и запоминаем кодировку.
            return handle.read(), handle.encoding
    # Кодировка не UTF-8 и не указана в файле — пробуем популярную в России cp1251.
    except (SyntaxError, UnicodeDecodeError) as exc:
        # Запоминаем исходную ошибку, чтобы приложить её к понятному сообщению.
        original_error = exc
        # Читаем «сырые» байты файла.
        raw = path.read_bytes()
        # Перебираем запасные кодировки.
        for encoding in ("cp1251", "cp866"):
            # Пробуем декодировать.
            try:
                # Успех — возвращаем текст (заменяя \r\n на \n, как это делает Python).
                return raw.decode(encoding).replace("\r\n", "\n"), encoding
            # Не подошла — пробуем следующую.
            except UnicodeDecodeError:
                continue
        # Ни одна кодировка не подошла — понятная ошибка.
        raise CompilerError(
            title="Не удалось прочитать текст файла",
            message=f"Файл «{path.name}» сохранён в неизвестной кодировке.",
            hint="Откройте файл в редакторе (например, Блокноте) и сохраните его в кодировке UTF-8.",
        ) from original_error


def _validate_icon(icon: Path) -> None:
    """Убедиться, что иконка существует и является настоящим .ico-файлом."""
    # Файл иконки должен существовать.
    if not icon.is_file():
        raise CompilerError(
            title="Иконка не найдена",
            message=f"Файл иконки не найден:\n{icon}",
            hint="Выберите иконку заново или уберите её, чтобы использовать стандартную.",
        )
    # Читаем первые 4 байта файла.
    with icon.open("rb") as handle:
        # Этого достаточно, чтобы распознать формат .ico.
        header = handle.read(4)
    # Если это не .ico (например, переименованный .png) — Windows не покажет иконку.
    if header != ICO_MAGIC:
        raise CompilerError(
            title="Неподходящий файл иконки",
            message=f"Файл «{icon.name}» не является настоящей иконкой .ico.",
            hint="Похоже, это картинка с переименованным расширением. Сконвертируйте её в .ico любым онлайн-конвертером.",
        )
