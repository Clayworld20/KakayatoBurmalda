# ============================================================================
#  СЕРВИС ОБЛАЧНЫХ НЕЙРОСЕТЕЙ (services/cloud_api.py)
#  --------------------------------------------------------------------------
#  Умеет проверять API-ключи Claude (Anthropic) и ChatGPT (OpenAI).
#  Проверка — это крошечный тестовый запрос: "ответь одним словом".
#  Функции возвращают пару: (True/False — всё ли хорошо, подробность для человека).
# ============================================================================

import base64    # кодирование картинок в текстовый формат base64 (так их "едят" API)
import requests   # библиотека для запросов в интернет

# Адреса, куда мы стучимся с ключами
ANTHROPIC_ADDRESS = "https://api.anthropic.com/v1/messages"     # сервер Claude
OPENAI_ADDRESS = "https://api.openai.com/v1/chat/completions"   # сервер OpenAI


def test_anthropic_key(api_key):
    """Проверяет ключ Anthropic (Claude). Возвращает (успех, подробность)."""
    # Особые заголовки, которые требует сервер Anthropic
    headers = {
        "x-api-key": api_key.strip(),          # сам ключ (без случайных пробелов)
        "anthropic-version": "2023-06-01",     # версия API, обязательный заголовок
        "content-type": "application/json",    # мы отправляем данные в формате JSON
    }
    # Крошечное письмо нейросети: ответь максимум 5 словами — это почти бесплатно
    body = {
        "model": "claude-3-5-haiku-latest",    # самая дешёвая и быстрая модель Claude
        "max_tokens": 5,                       # ограничиваем длину ответа
        "messages": [{"role": "user", "content": "Привет"}],  # само письмо
    }
    try:
        answer = requests.post(ANTHROPIC_ADDRESS, headers=headers, json=body, timeout=20)
    except Exception:
        return False, "не удалось выйти в интернет"     # сети нет или сервер недоступен
    if answer.status_code == 200:                       # код 200 = "всё хорошо"
        return True, "ключ принят сервером"
    if answer.status_code in (401, 403):                # коды "доступ запрещён"
        return False, "сервер не принял ключ"
    return False, f"сервер ответил кодом {answer.status_code}"  # любая другая ситуация


def test_openai_key(api_key):
    """Проверяет ключ OpenAI (ChatGPT). Возвращает (успех, подробность)."""
    headers = {
        "Authorization": "Bearer " + api_key.strip(),  # OpenAI ждёт ключ в таком формате
        "content-type": "application/json",            # данные в формате JSON
    }
    body = {
        "model": "gpt-4o-mini",                # самая дешёвая и быстрая модель OpenAI
        "max_tokens": 5,                       # ограничиваем длину ответа
        "messages": [{"role": "user", "content": "Привет"}],  # тестовое письмо
    }
    try:
        answer = requests.post(OPENAI_ADDRESS, headers=headers, json=body, timeout=20)
    except Exception:
        return False, "не удалось выйти в интернет"     # сети нет или сервер недоступен
    if answer.status_code == 200:                       # код 200 = "всё хорошо"
        return True, "ключ принят сервером"
    if answer.status_code in (401, 403):                # коды "доступ запрещён"
        return False, "сервер не принял ключ"
    return False, f"сервер ответил кодом {answer.status_code}"  # любая другая ситуация

# ============================================================================
#  ПОЛНЫЕ ЗАПРОСЫ К НЕЙРОСЕТЯМ (используются роботом из Шага 4)
#  ----------------------------------------------------------------------------

def ask_claude(api_key, prompt, image_path=None):
    """Задаёт Claude вопрос и возвращает (успех, полный текст ответа).

    prompt     — текст задания для нейросети
    image_path — путь к картинке-скриншоту (необязательно); если передать,
                 Claude сможет "посмотреть" на экран компьютера.
    """
    headers = {
        "x-api-key": api_key.strip(),          # ключ пользователя
        "anthropic-version": "2023-06-01",     # обязательная версия API
        "content-type": "application/json",    # данные в формате JSON
    }
    # "Письмо" может состоять из нескольких частей: картинка + текст
    content = []
    if image_path:                             # если есть скриншот — прикрепляем
        try:
            with open(image_path, "rb") as image_file:      # открываем картинку
                encoded = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception:
            return False, "не смог открыть файл скриншота"
        content.append({                       # часть-картинка в формате Anthropic
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": encoded},
        })
    content.append({"type": "text", "text": prompt})   # часть-текст с заданием

    body = {
        "model": "claude-3-5-sonnet-latest",   # умная модель, понимает картинки
        "max_tokens": 1000,                    # запас на развёрнутый ответ
        "messages": [{"role": "user", "content": content}],  # само письмо
    }
    try:
        answer = requests.post(ANTHROPIC_ADDRESS, headers=headers, json=body, timeout=60)
    except Exception:
        return False, "не удалось выйти в интернет"
    if answer.status_code != 200:              # сервер недоволен (ключ, сеть и т.д.)
        return False, f"сервер ответил кодом {answer.status_code}"
    try:
        data = answer.json()                   # разбираем ответ сервера
        # Ответ приходит списком частей — ищем первую текстовую часть
        for part in data.get("content", []):
            if part.get("type") == "text":
                return True, part.get("text", "")
        return False, "в ответе нет текста"
    except Exception:
        return False, "не смог разобрать ответ сервера"


def ask_openai(api_key, prompt, image_path=None):
    """Задаёт ChatGPT (OpenAI) вопрос и возвращает (успех, полный текст ответа)."""
    headers = {
        "Authorization": "Bearer " + api_key.strip(),  # ключ в специальном заголовке
        "content-type": "application/json",
    }
    # Части письма: текст всегда, картинка — если есть
    content = [{"type": "text", "text": prompt}]
    if image_path:
        try:
            with open(image_path, "rb") as image_file:      # открываем скриншот
                encoded = base64.b64encode(image_file.read()).decode("utf-8")
        except Exception:
            return False, "не смог открыть файл скриншота"
        content.append({                       # часть-картинка в формате OpenAI
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + encoded},
        })
    body = {
        "model": "gpt-4o-mini",                # быстрая модель, понимает картинки
        "max_tokens": 1000,                    # запас на развёрнутый ответ
        "messages": [{"role": "user", "content": content}],
    }
    try:
        answer = requests.post(OPENAI_ADDRESS, headers=headers, json=body, timeout=60)
    except Exception:
        return False, "не удалось выйти в интернет"
    if answer.status_code != 200:
        return False, f"сервер ответил кодом {answer.status_code}"
    try:
        data = answer.json()
        text = data["choices"][0]["message"]["content"]   # текст ответа модели
        return True, text
    except Exception:
        return False, "не смог разобрать ответ сервера"
