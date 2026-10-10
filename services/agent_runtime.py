# ============================================================================
#  СЕРВИС "РОБОТ" (services/agent_runtime.py)
#  --------------------------------------------------------------------------
#  Это "двигатель" агента-помощника. Он умеет:
#    1) выбрать "мозг": Claude -> OpenAI -> локальная модель из Ollama;
#    2) делать скриншоты экрана (pyautogui) и показывать их мозгу;
#    3) выполнять решения мозга: клики мышкой, набор текста, нажатия клавиш;
#    4) рассказывать о каждом шаге простым русским языком (функция on_log);
#    5) мгновенно останавливаться по глобальной клавише Esc — даже если
#       окно программы свернуто (библиотека keyboard).
#
#  Режимы работы робота (их показываем во вкладке "Робот"):
#    MODE_REPORT  — "Напиши отчет": мозг пишет текст, робот сохраняет файл.
#    MODE_CLEANUP — "Чистка рабочего стола": робот смотрит на экран и действует.
#    MODE_CONTROL — "Полное управление экраном": робот выполняет любое задание.
# ============================================================================

# --- ПОДКЛЮЧЕНИЕ БИБЛИОТЕК -----------------------------------------------------

import json        # разбор ответов мозга в формате JSON
import os          # работа с файлами и папками (сохранение отчёта)
import tempfile    # создание временных файлов для скриншотов
import threading   # отдельный поток, чтобы робот не замораживал окно
import time        # паузы между действиями робота

# Библиотека keyboard ловит клавиши ВО ВСЕЙ системе (даже когда окно свернуто).
# Подключаем мягко: если её вдруг нет — робот всё равно работает, просто без Esc.
try:
    import keyboard
except ImportError:
    keyboard = None                       # стоп-кран Esc будет недоступен

from services import config_manager    # чтение сохранённых API-ключей
from services import netcheck          # проверка: запущена ли Ollama
from services import cloud_api         # вопросы к Claude / OpenAI
from services import ollama_client     # вопросы к локальной модели + список моделей

# Технические имена режимов (во вкладке "Робот" их ждут русские названия)
MODE_REPORT = "report"                 # режим "Напиши отчет"
MODE_CLEANUP = "cleanup"               # режим "Чистка рабочего стола"
MODE_CONTROL = "control"               # режим "Полное управление экраном"

# Защита от зацикливания: максимум действий за один запуск робота
MAX_STEPS = 8

# Глобальная клавиша аварийной остановки (захотите другую — поменяйте здесь,
# например "ctrl+alt+s"). Работает во всех программах, пока робот запущен.
HOTKEY = "esc"
EMERGENCY_MESSAGE = "⏹ Аварийная остановка клавишей Esc!"

# Задание для режима "Чистка рабочего стола" (безопасное и понятное)
CLEANUP_GOAL = (
    "Приведи в порядок рабочий стол: создай новую папку «Разобрать позже» "
    "(правый клик по пустому месту -> Создать -> Папку) и переложи туда "
    "несколько самых беспорядочных файлов."
)


def get_desktop_folder():
    """Возвращает путь к папке рабочего стола пользователя."""
    return os.path.join(os.path.expanduser("~"), "Desktop")  # стандартное место в Windows


def parse_decision(raw_text):
    """Достаёт из ответа мозга команду-решение (JSON). Возвращает словарь или None.

    Мозг должен ответить примерно так:
      {"thought": "мысль по-русски", "action": "click", "x": 100, "y": 200, "text": ""}
    Некоторые модели заворачивают JSON в лишний текст или в ```...``` — мы терпеливы.
    """
    start = raw_text.find("{")             # ищем начало JSON в ответе
    end = raw_text.rfind("}")              # ищем конец JSON в ответе
    if start == -1 or end == -1 or end <= start:
        return None                        # скобок нет — ответ не про действия
    try:
        data = json.loads(raw_text[start:end + 1])   # разбираем найденный JSON
    except Exception:
        return None                        # текст внутри скобок — не JSON
    decision = {
        "thought": str(data.get("thought", "") or ""),            # мысль простыми словами
        "action": str(data.get("action", "") or "").strip().lower(),  # что сделать
        "x": data.get("x"),                # координата X (для кликов)
        "y": data.get("y"),                # координата Y (для кликов)
        "text": str(data.get("text", "") or ""),                  # текст/клавиша
    }
    # Разрешаем роботу только эти пять действий — всё остальное считаем ошибкой
    known_actions = {"click", "doubleclick", "type", "press", "done"}
    if decision["action"] not in known_actions:
        return None                        # неизвестное действие — не рискуем
    return decision


class AgentRuntime:
    """Двигатель робота: думает мозгом, смотрит экран, двигает мышь, пишет лог."""

    def __init__(self, on_log, on_finished):
        # on_log(тип_сообщения, текст) — функция, выводящая строку в окно трансляции
        self.on_log = on_log
        # on_finished() — функция, которую зовём, когда робот закончил работу
        self.on_finished = on_finished
        self.stop_event = threading.Event()   # "стоп-кран": робот проверяет его на каждом шаге
        self.thread = None                    # поток, в котором робот работает
        self.mode = None                      # выбранный режим работы
        self.task = ""                        # задание пользователя своими словами
        self.hotkey_handle = None             # обработчик клавиши Esc (чтобы снять его потом)
        self.emergency = False                # флаг: остановка была аварийной (Esc)?

    # ------------------------------------------------------------- УПРАВЛЕНИЕ

    def is_running(self):
        """Возвращает True, если робот сейчас работает."""
        return self.thread is not None and self.thread.is_alive()

    def start(self, mode, task):
        """Включает робота в выбранном режиме. Возвращает True, если получилось."""
        if self.is_running():                 # робот уже работает
            return False                      # второй запуск не нужен
        self.stop_event.clear()               # сбрасываем "стоп-кран"
        self.emergency = False                # прошлая остановка нас больше не волнует
        self.mode = mode                      # запоминаем режим
        self.task = task.strip()              # и задание (без лишних пробелов)
        self.install_hotkey()                 # включаем глобальный стоп-кран Esc
        self.thread = threading.Thread(       # робот живёт в отдельном потоке
            target=self.run,
            daemon=True,                      # закроется вместе с программой
        )
        self.thread.start()                   # поехали!
        return True

    def stop(self):
        """Просит робота остановиться (мягко, после текущего действия)."""
        self.stop_event.set()                 # поднимаем флажок "стоп"

    def log(self, kind, text):
        """Безопасно отправляет строку в окно трансляции."""
        try:
            self.on_log(kind, text)           # пробуем передать сообщение в окно
        except Exception:
            pass                              # окно закрыто — молча пропускаем

    # ------------------------------------------------------------- СТОП-КРАН ESC

    def install_hotkey(self):
        """Включает глобальную клавишу Esc на всё время работы робота."""
        self.hotkey_handle = None             # пока обработчик не установлен
        if keyboard is None:                  # библиотеки нет — работаем без хоткея
            self.log("info", "Клавиша Esc недоступна: для остановки жмите кнопку «Остановить».")
            return
        try:
            # add_hotkey ловит клавишу ВО ВСЕЙ системе, а не только в нашем окне,
            # поэтому сработает даже из игры или из свернутой программы
            self.hotkey_handle = keyboard.add_hotkey(HOTKEY, self.on_emergency_hotkey)
        except Exception:
            self.hotkey_handle = None         # например, не хватило прав — живём без хоткея
            self.log("info", "Клавиша Esc недоступна: для остановки жмите кнопку «Остановить».")

    def on_emergency_hotkey(self):
        """Вызывается при нажатии Esc в ЛЮБОЙ программе. Должен быть очень быстрым."""
        if self.stop_event.is_set():          # робот уже останавливается
            return
        self.emergency = True                 # помечаем: остановка аварийная
        self.stop_event.set()                 # дергаем "стоп-кран" — цикл увидит его мгновенно
        self.log("error", EMERGENCY_MESSAGE)  # сразу пишем в трансляцию, не дожидаясь цикла

    def uninstall_hotkey(self):
        """Убирает перехват Esc, чтобы клавиша снова работала как обычно."""
        if keyboard is not None and self.hotkey_handle is not None:
            try:
                keyboard.remove_hotkey(self.hotkey_handle)   # снимаем перехват
            except Exception:
                pass                          # уже снят — не страшно
        self.hotkey_handle = None

    def check_stop(self):
        """Проверяет, просили ли робота остановиться. True = стоп (лог уже написан)."""
        if not self.stop_event.is_set():      # никто не просил остановку
            return False
        if not self.emergency:                # обычная остановка кнопкой...
            self.log("info", "Останавливаюсь по вашей команде.")  # ...объясняем в логе
        # при аварийной (Esc) сообщение уже написал обработчик клавиши
        return True

    # ------------------------------------------------------------- ГЛАВНЫЙ ЦИКЛ

    def run(self):
        """Тело робота: выбирает мозг и выполняет задание выбранного режима."""
        try:
            brain = self.pick_brain()         # шаг 1: найти, чем думать
            if brain is None:                 # мозга нет — работать нечем
                self.log("error", "Робот не смог найти мозг. Проверьте вкладку «Мозг».")
                return
            self.log("info", f"Мой мозг: {brain['label']}")
            if keyboard is not None:          # подсказка про аварийный стоп
                self.log("info", "Подсказка: клавиша Esc — мгновенный стоп, даже если окно свернуто.")

            if self.mode == MODE_REPORT:      # режим "Напиши отчет"
                self.do_report(brain)
            else:                             # режимы с экраном (чистка/управление)
                self.do_screen_mission(brain)
        except Exception as error:            # любая непредвиденная ситуация
            self.log("error", f"Непредвиденная ошибка: {error}")
        finally:
            self.uninstall_hotkey()           # снимаем перехват Esc в любом случае
            # Как бы ни закончилось — сообщаем окну, что робот выключается
            try:
                self.on_finished()
            except Exception:
                pass

    # ------------------------------------------------------------- ВЫБОР МОЗГА

    def pick_brain(self):
        """Выбирает самый умный доступный мозг. Возвращает описание или None.

        Порядок приоритета: Claude (умеет всё) -> OpenAI -> локальная Ollama (бесплатно).
        """
        # 1) Пробуем сохранённый ключ Claude
        anthropic_key = config_manager.get_api_key("anthropic")
        if anthropic_key:
            return {"kind": "claude", "key": anthropic_key, "label": "Claude (облачный)"}

        # 2) Пробуем сохранённый ключ OpenAI
        openai_key = config_manager.get_api_key("openai")
        if openai_key:
            return {"kind": "openai", "key": openai_key, "label": "OpenAI, ChatGPT (облачный)"}

        # 3) Пробуем локальную Ollama
        if netcheck.is_ollama_available():
            models = ollama_client.list_installed_models()   # какие модели скачаны?
            if models:
                # Берём первую скачанную модель (новее скачали — та и в начале)
                return {"kind": "local", "model": models[0],
                        "label": f"Ollama: {models[0]} (локальный)"}
            self.log("error", "Ollama запущена, но ни одна модель ещё не скачана.")
            self.log("info", "Скачайте модель во вкладке «Мозг» — это бесплатно.")
            return None

        # Не нашлось ничего: объясняем пользователю, что делать
        self.log("error", "Не найдено ни одного мозга.")
        self.log("info", "Запустите Ollama или добавьте ключ Claude/OpenAI во вкладке «Мозг».")
        return None

    def ask_brain(self, brain, prompt, image_path=None):
        """Задаёт мозгу вопрос. Возвращает текст ответа или None (если не вышло)."""
        if brain["kind"] == "claude":         # спрашиваем Claude
            success, text = cloud_api.ask_claude(brain["key"], prompt, image_path)
        elif brain["kind"] == "openai":       # спрашиваем ChatGPT
            success, text = cloud_api.ask_openai(brain["key"], prompt, image_path)
        else:                                 # спрашиваем локальную модель
            success, text = ollama_client.chat(brain["model"], prompt, image_path)
        if not success:                       # мозг не ответил
            self.log("error", f"Мозг не ответил: {text}")
            return None
        return text.strip()                   # ответ без лишних пробелов по краям

    # ------------------------------------------------------------- РЕЖИМ "ОТЧЁТ"

    def do_report(self, brain):
        """Режим "Напиши отчет": мозг пишет текст, робот сохраняет его в файл."""
        if not self.task:                     # тему отчёта не написали
            self.log("error", "Напишите тему отчёта в поле «Задание» и включите меня снова.")
            return

        self.log("thought", f"Пользователь просит написать отчёт: «{self.task}». Думаю...")
        prompt = (
            "Напиши короткий деловой отчёт на русском языке на тему: "
            f"«{self.task}». Структура: заголовок, 2-3 абзаца, выводы. "
            "Пиши простым и понятным языком."
        )
        text = self.ask_brain(brain, prompt)  # мозг пишет текст отчёта
        if text is None:                      # не ответил — выходим (ошибка уже в логе)
            return
        if self.check_stop():                 # пока мозг писал, нажали остановку?
            return

        self.log("success", "Отчёт готов!\n" + text)   # показываем отчёт целиком
        self.log("action", "Сохраняю отчёт на рабочий стол...")

        try:
            # Путь к файлу: Рабочий стол/Отчет_от_робота.txt
            report_path = os.path.join(get_desktop_folder(), "Отчет_от_робота.txt")
            with open(report_path, "w", encoding="utf-8") as file:  # создаём файл
                file.write(text)              # записываем текст отчёта
            self.log("success", f"Готово! Файл отчёта лежит на рабочем столе: {report_path}")
        except Exception:
            # Папка может быть недоступна — тогда просто оставляем текст в логе
            self.log("error", "Не смог сохранить файл, но отчёт остался в окне выше.")

    # --------------------------------------------------- РЕЖИМЫ СО СКРИНШОТАМИ

    def take_screenshot(self):
        """Делает снимок экрана. Возвращает (путь_к_файлу, размер_картинки)."""
        import pyautogui                      # подключаем управление экраном
        image = pyautogui.screenshot()        # снимок экрана (картинка из pillow)
        descriptor, path = tempfile.mkstemp(suffix=".png")  # временный файл
        os.close(descriptor)                  # закрываем файл, чтобы не мешать
        image.save(path)                      # сохраняем снимок на диск
        return path, image.size               # размер: (ширина, высота) в пикселях

    def build_screen_prompt(self, goal, step, image_width, image_height):
        """Собирает задание для мозга — базовую разметку Computer Use."""
        return (
            f"Ты — робот-помощник, управляющий компьютером (Computer Use). Шаг {step}.\n"
            f"Цель: {goal}\n"
            f"Перед тобой скриншот экрана {image_width}x{image_height} пикселей. "
            "Точка (0, 0) — левый верхний угол. Координаты считай в пикселях скриншота.\n"
            "Ответь СТРОГО одним JSON-объектом без пояснений:\n"
            '{"thought": "что ты понял и решил сделать, по-русски", '
            '"action": "click|doubleclick|type|press|done", '
            '"x": число, "y": число, "text": "текст для type или клавиша для press"}\n'
            "Если цель уже достигнута — выбери action \"done\". Будь осторожен: "
            "не удаляй файлы и не делай необратимых действий."
        )

    def do_screen_mission(self, brain):
        """Режимы с экраном: цикл "скриншот -> мысль -> действие" до победы."""
        import pyautogui                      # подключаем управление экраном

        if brain["kind"] == "local":
            # Честно предупреждаем: не все локальные модели умеют смотреть на экран
            self.log("info", "Подсказка: локальные текстовые модели не всегда умеют "
                             "видеть экран. Лучше всего с этим справляются Claude и ChatGPT.")

        # Определяем цель: для чистки стола она своя, иначе — задание пользователя
        if self.mode == MODE_CLEANUP:
            goal = CLEANUP_GOAL
        else:
            goal = self.task
            if not goal:                      # задание не написали
                self.log("error", "Опишите задание в поле «Задание» и включите меня снова.")
                return

        self.log("thought", f"Цель понятна: {goal}")

        # Настоящий размер экрана в пикселях (нужен для пересчёта координат)
        screen_width, screen_height = pyautogui.size()

        for step in range(1, MAX_STEPS + 1):              # не больше MAX_STEPS шагов
            if self.check_stop():                         # нажали Esc или кнопку "Стоп"?
                return

            self.log("action", f"Делаю скриншот экрана (шаг {step} из {MAX_STEPS})...")
            try:
                image_path, (image_width, image_height) = self.take_screenshot()
            except Exception:
                self.log("error", "Не смог сделать скриншот экрана.")
                return

            # Спрашиваем мозг, что делать дальше (с показом скриншота)
            prompt = self.build_screen_prompt(goal, step, image_width, image_height)
            reply = self.ask_brain(brain, prompt, image_path)
            if reply is None:                             # мозг не ответил
                return                                    # ошибка уже в логе
            if self.check_stop():                         # пока мозг думал, нажали стоп?
                return

            decision = parse_decision(reply)              # разбираем решение мозга
            if decision is None:
                self.log("error", "Не смог понять ответ мозга, останавливаюсь.")
                return

            self.log("thought", decision["thought"] or "Думаю, что делать дальше...")

            if decision["action"] == "done":              # мозг считает задачу решённой
                self.log("success", "Готово! " + (decision["text"] or "Задание выполнено."))
                return

            if self.check_stop():                         # проверяем "стоп" перед действием
                return

            if not self.perform_action(decision, screen_width, screen_height, image_width, image_height):
                return                                    # действие не удалось — стоп

            # Секунда тишины между шагами. Хитрость: wait просыпается МГНОВЕННО,
            # если во время паузы нажали Esc или кнопку остановки
            if self.stop_event.wait(1):
                self.check_stop()                         # написать сообщение об остановке
                return

        # Сюда попадаем, если шаги закончились, а "done" так и не пришёл
        self.log("info", f"Достиг лимита в {MAX_STEPS} шагов и остановился, чтобы ничего не сломать.")

    def perform_action(self, decision, screen_width, screen_height, image_width, image_height):
        """Выполняет одно действие мышью или клавиатурой. False = робот должен стоп."""
        import pyautogui                      # управление мышкой и клавиатурой

        action = decision["action"]

        if action in ("click", "doubleclick"):
            # Пересчёт координат: мозг видел картинку, а экран может быть другого размера
            try:
                real_x = int(decision["x"] * screen_width / image_width)   # X для настоящего экрана
                real_y = int(decision["y"] * screen_height / image_height) # Y для настоящего экрана
            except Exception:
                self.log("error", "Мозг прислал неверные координаты, останавливаюсь.")
                return False
            if action == "click":
                self.log("action", f"Двигаю мышку к точке ({real_x}, {real_y}) и кликаю...")
            else:
                self.log("action", f"Двойной клик в точке ({real_x}, {real_y})...")
            try:
                if action == "click":
                    pyautogui.click(real_x, real_y)               # одиночный клик
                else:
                    pyautogui.doubleClick(real_x, real_y)         # двойной клик
            except pyautogui.FailSafeException:
                # Защита pyautogui: мышь у угла экрана — аварийный стоп
                self.log("error", "Аварийная остановка: курсор в углу экрана.")
                return False
            except Exception as error:
                self.log("error", f"Не смог кликнуть: {error}")
                return False
            return True

        if action == "type":
            self.log("action", f"Печатаю текст: «{decision['text'][:40]}»...")
            try:
                pyautogui.write(decision["text"], interval=0.03)  # печатаем по буквам
            except Exception:
                # pyautogui не умеет печатать русский — честно говорим об этом
                self.log("error", "Не смог напечатать этот текст (кириллицу мышь не печатает).")
            return True

        if action == "press":
            self.log("action", f"Нажимаю клавишу {decision['text']}...")
            try:
                pyautogui.press(decision["text"])                 # нажимаем клавишу
            except pyautogui.FailSafeException:
                self.log("error", "Аварийная остановка: курсор в углу экрана.")
                return False
            except Exception as error:
                self.log("error", f"Не смог нажать клавишу: {error}")
            return True

        return True                            # неизвестное действие — просто идём дальше
