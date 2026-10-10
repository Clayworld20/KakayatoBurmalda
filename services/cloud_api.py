# ============================================================================
#  СЕРВИС ОБЛАЧНЫХ НЕЙРОСЕТЕЙ (services/cloud_api.py)
#  --------------------------------------------------------------------------
#  Умеет проверять API-ключи Claude (Anthropic) и ChatGPT (OpenAI).
#  Проверка — это крошечный тестовый запрос: "ответь одним словом".
#  Функции возвращают пару: (True/False — всё ли хорошо, подробность для человека).
# ============================================================================

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
