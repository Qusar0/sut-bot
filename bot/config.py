from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TZ = ZoneInfo("Europe/Moscow")


class Settings(BaseSettings):
    # env_ignore_empty: пустые значения в .env (например WEBAPP_DEV_USER=) трактуем как «не задано»,
    # иначе pydantic падает на попытке привести "" к int/None-полю.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore", env_ignore_empty=True)

    bot_token: SecretStr
    encryption_key: SecretStr | None = None
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    admin_id: int | None = None

    # Размер пула соединений к PostgreSQL. На сервере с 1 ГБ RAM держим небольшим (к нему ещё +max_overflow=5).
    db_pool_size: int = 5

    # Сколько минут считать кэш недели свежим при просмотре
    schedule_cache_minutes: int = 30
    # Пауза между запросами к sut.ru при фоновом обходе, секунды
    crawl_delay: float = 1.0
    # Пауза между запросами к sut.ru, вызванными действиями пользователей, секунды
    interactive_delay: float = 0.2

    # Веб-сервер для подписки на календарь (п. 32). Без PUBLIC_URL доступна только выгрузка файла.
    public_url: str | None = None  # например https://bot.example.ru
    web_host: str = "0.0.0.0"
    web_port: int = 8080

    # Состояния диалогов (выбор группы, поиск) в Redis переживают перезапуск. Без REDIS_URL — в памяти.
    redis_url: str | None = None
    # Вебхук вместо polling (нужен PUBLIC_URL с HTTPS). Секрет проверяется в заголовке каждого запроса.
    use_webhook: bool = False
    webhook_secret: SecretStr | None = None

    # Mini App: при локальной разработке (с 127.0.0.1) запросы без подписи Telegram считаются от этого tg_id.
    webapp_dev_user: int | None = None

    # Прокси для запросов к sut.ru/lk.sut.ru, если прямой IP сервера заблокирован вузом.
    # Например socks5h://proxy:1080 (sing-box рядом в docker-compose). Пусто — ходим напрямую.
    sut_proxy: str | None = None


settings = Settings()
