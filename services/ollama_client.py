# ============================================================================
#  СЕРВИС ОБЩЕНИЯ С OLLAMA (services/ollama_client.py)
#  --------------------------------------------------------------------------
#  Здесь живёт команда "скачать модель": программа отправляет запрос локальной
#  Ollama (http://localhost:11434/api/pull) и читает прогресс построчно.
# ============================================================================

import base64     # кодирование скриншотов в base64 (так картинки передаются модели)
import json        # Ollama отвечает строчками в формате JSON — этот модуль их разбирает
import requests    # библиотека для общения с программой Ollama

# Адреса программы Ollama на компьютере пользователя
OLLAMA_ADDRESS = "http://localhost:11434"       # адрес, где живёт Ollama
PULL_ADDRESS = OLLAMA_ADDRESS + "/api/pull"     # адрес команды "скачать модель"


def pull_model(model_name, on_progress):
    """Скачивает модель через Ollama, сообщая прогресс в функцию on_progress.

    model_name  — техническое имя модели, например "llama3.2:1b"
    on_progress — функция, которую мы дёргаем: on_progress(проценты, текст)
                  (проценты — число от 0 до 100 или None, если их пока не видно)
    Если что-то пошло не так — бросаем ошибку, её мягко поймает вкладка "Мозг".
    """
    # Отправляем запрос на скачивание. stream=True значит "читай ответ по строчкам,
    # не дожидаясь конца" — благодаря этому мы видим прогресс в реальном времени.
    response = requests.post(
        PULL_ADDRESS,
        # Отправляем имя модели в двух полях сразу: старые версии Ollama ждут "name",
        # новые — "model". Лишнее поле они просто проигнорируют.
        json={"name": model_name, "model": model_name},
        stream=True,             # читать ответ потоком, строчка за строчкой
        timeout=(15, 600),       # 15 сек на соединение, до 10 минут на ожидание данных
    )
    response.raise_for_status()  # если сервер ответил ошибкой — бросаем исключение

    # Читаем ответ построчно: каждая строчка — маленький отчёт о прогрессе
    for line in response.iter_lines():
        if not line:                     # пустые строки пропускаем
            continue
        try:
            data = json.loads(line)      # превращаем строчку JSON в словарь Python
        except Exception:
            continue                     # строчка не разобралась — не беда, идём дальше
        if "error" in data:              # Ollama сообщила об ошибке
            raise RuntimeError(data["error"])  # передаём её наверх

        total = data.get("total") or 0       # общий размер модели в байтах
        done = data.get("completed") or 0    # сколько байтов уже скачано
        status = data.get("status") or ""    # текстовый статус от Ollama

        if total and done:                   # числа есть — считаем проценты
            percent = int(done * 100 / total)  # формула процентов скачивания
            on_progress(percent, f"Скачивание... {percent}%")
        elif "verifying" in status:          # файлы скачаны, Ollama их проверяет
            on_progress(None, "Проверяю файлы, почти готово...")
        elif "writing manifest" in status:   # финальная запись в список моделей
            on_progress(None, "Завершаю установку...")
        else:                                # прочие промежуточные статусы
            on_progress(None, status or "Подготовка к скачиванию...")

    # Поток ответа закончился — модель полностью скачана и установлена
    on_progress(100, "Готово! Модель установлена ✓")

# ============================================================================
#  ЧТЕНИЕ СПИСКА МОДЕЛЕЙ И ЧАТ (используется роботом из Шага 4)
#  ----------------------------------------------------------------------------

def list_installed_models():
    """Спрашивает у Ollama список уже скачанных моделей. Возвращает их имена.

    Если Ollama не запущена — вернёт пустой список (без ошибок и падений).
    """
    try:
        answer = requests.get(OLLAMA_ADDRESS + "/api/tags", timeout=3)  # список моделей
        data = answer.json()                       # разбираем JSON-ответ
        # В ответе приходит список словарей — достаём из каждого поле "name"
        return [model.get("name", "") for model in data.get("models", [])]
    except Exception:
        return []                                  # Ollama не отвечает — моделей нет


def chat(model_name, prompt, image_path=None):
    """Задаёт вопрос локальной модели и возвращает (успех, текст ответа).

    model_name — имя модели, например "llama3.2:1b"
    prompt     — текст задания
    image_path — путь к скриншоту (необязательно; работает только у моделей,
                 которые умеют видеть картинки)
    """
    message = {"role": "user", "content": prompt}  # письмо модели
    if image_path:                                 # если есть скриншот — прикрепляем
        try:
            with open(image_path, "rb") as image_file:
                encoded = base64.b64encode(image_file.read()).decode("utf-8")
            message["images"] = [encoded]          # Ollama ждёт base64-текст картинки
        except Exception:
            pass                                   # без картинки, но всё равно ответит
    try:
        answer = requests.post(
            OLLAMA_ADDRESS + "/api/chat",          # адрес чата Ollama
            json={"model": model_name, "messages": [message], "stream": False},
            timeout=120,                           # локальная модель думает долго — ждём 2 минуты
        )
    except Exception:
        return False, "Ollama не отвечает"
    if answer.status_code != 200:
        return False, f"Ollama ответила ошибкой {answer.status_code}"
    try:
        data = answer.json()                       # разбираем ответ
        text = data["message"]["content"]          # достаём текст сообщения
        return True, text
    except Exception:
        return False, "не смог разобрать ответ Ollama"
