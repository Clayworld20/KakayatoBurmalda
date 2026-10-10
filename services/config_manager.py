# ============================================================================
#  СЕРВИС ХРАНЕНИЯ НАСТРОЕК (services/config_manager.py)
#  --------------------------------------------------------------------------
#  Сохраняет и читает файл config.json, который лежит рядом с программой.
#  Туда записываются API-ключи пользователя, чтобы не вводить их каждый раз.
#  Файл добавлен в .gitignore — ключи не попадут в интернет случайно.
# ============================================================================

import json     # модуль для работы с файлами формата JSON (простой " блокнот данных")
import os       # модуль для работы с файлами и папками
import threading  # замок, чтобы два потока не записывали файл одновременно

# Путь к файлу настроек: папка НАД папкой services (то есть корень программы)
CONFIG_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),  # корень программы
    "config.json",                                                # имя файла настроек
)

# Замок: если два потока захотят писать файл одновременно — они встанут в очередь
file_lock = threading.Lock()


def load_config():
    """Читает файл настроек и возвращает словарь. Если файла нет — пустой словарь."""
    with file_lock:                            # занимаем замок на время чтения
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:  # открываем файл
                return json.load(file)         # превращаем текст JSON в словарь Python
        except Exception:
            return {}                          # файла нет или он испорчен — начинаем с чистого листа


def save_config(config):
    """Записывает словарь настроек в файл. Возвращает True (получилось) или False (нет)."""
    with file_lock:                            # занимаем замок на время записи
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:  # открываем файл на запись
                # ensure_ascii=False — чтобы русский текст остался читаемым
                json.dump(config, file, ensure_ascii=False, indent=2)
            return True                        # запись прошла успешно
        except Exception:
            return False                       # например, диск защищён от записи


def save_api_key(provider, key):
    """Сохраняет один ключ. provider — это "anthropic" или "openai"."""
    config = load_config()                     # сначала читаем текущие настройки
    if "api_keys" not in config:               # если раздела для ключей ещё нет...
        config["api_keys"] = {}                # ...создаём пустой раздел
    config["api_keys"][provider] = key.strip() # убираем лишние пробелы и сохраняем ключ
    return save_config(config)                 # записываем всё в файл


def get_api_key(provider):
    """Возвращает сохранённый ключ. Если ключа нет — пустую строку."""
    config = load_config()                     # читаем настройки
    return config.get("api_keys", {}).get(provider, "")  # достаём нужный ключ
