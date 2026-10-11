# ============================================================================
#  СЕРВИС ПРОВЕРКИ СЕТИ (services/netcheck.py)
#  --------------------------------------------------------------------------
#  Отвечает на два простых вопроса:
#    1) Есть ли интернет?          -> is_internet_available()
#    2) Запущена ли Ollama?        -> is_ollama_available()
#  Функции НИКОГДА не вызывают ошибок — только возвращают True (да) или False (нет).
# ============================================================================

try:
    import requests                       # библиотека для запросов в интернет
except ImportError:
    requests = None                       # если библиотеки нет — считаем, что сети нет

# Адреса, по которым мы проверяем подключение
GOOGLE_URL = "https://www.google.com"     # зарубежный сайт для проверки интернета
YANDEX_URL = "https://www.yandex.ru"      # запасной сайт (если Google недоступен)
OLLAMA_URL = "http://localhost:11434"     # адрес локальной нейросети Ollama


def is_internet_available():
    """Возвращает True, если интернет работает, и False, если нет."""
    if requests is None:                  # библиотеки requests нет в программе
        return False
    # Пробуем два сайта по очереди: если хоть один открылся — интернет есть
    for url in (GOOGLE_URL, YANDEX_URL):
        try:
            requests.get(url, timeout=5)  # открываем сайт, ждём ответ максимум 5 секунд
            return True                   # получилось — интернет есть
        except Exception:
            continue                      # не получилось — пробуем следующий сайт
    return False                          # ни один сайт не открылся — интернета нет


def is_ollama_available():
    """Возвращает True, если локальная нейросеть Ollama запущена на компьютере."""
    if requests is None:                  # библиотеки requests нет в программе
        return False
    try:
        requests.get(OLLAMA_URL, timeout=2)  # стучимся к Ollama, ждём максимум 2 секунды
        return True                         # ответила — значит запущена
    except Exception:
        return False                        # не ответила — не установлена или выключена
