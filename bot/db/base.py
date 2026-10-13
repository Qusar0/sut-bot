from pathlib import Path

from sqlalchemy import event, inspect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from bot.config import settings


class Base(DeclarativeBase):
    pass


_is_sqlite = settings.database_url.startswith("sqlite")
# пул под небольшой сервер (1 ГБ): немного соединений, не упираемся в Postgres max_connections
_pool = {} if _is_sqlite else {"pool_size": settings.db_pool_size, "max_overflow": 5, "pool_recycle": 1800}
engine = create_async_engine(settings.database_url, pool_pre_ping=True, **_pool)
Session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

if _is_sqlite:

    @event.listens_for(engine.sync_engine, "connect")
    def _sqlite_pragmas(conn, _):
        cur = conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")
        cur.close()


ROOT = Path(__file__).resolve().parents[2]
INITIAL_REVISION = "0001"


def _upgrade(connection) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["connection"] = connection
    tables = set(inspect(connection).get_table_names())
    if "users" in tables and "alembic_version" not in tables:
        # база создана до появления миграций (create_all) — помечаем её начальной версией
        command.stamp(cfg, INITIAL_REVISION)
    command.upgrade(cfg, "head")


async def init_db() -> None:
    """Применяет миграции Alembic до последней версии."""
    from bot.db import models  # noqa: F401 — регистрирует модели

    async with engine.begin() as conn:
        await conn.run_sync(_upgrade)
