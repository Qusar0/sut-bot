from zoneinfo import ZoneInfo

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

TZ = ZoneInfo("Europe/Moscow")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    bot_token: SecretStr
    encryption_key: SecretStr | None = None
    database_url: str = "sqlite+aiosqlite:///./data/bot.db"
    admin_id: int | None = None

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


settings = Settings()
