"""Миграции Alembic. Работают и с SQLite (локально), и с PostgreSQL (прод).

Запуск вручную: `alembic upgrade head`. Бот применяет миграции сам при старте (bot/db/base.py).
"""

import asyncio

from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from bot.config import settings
from bot.db import models  # noqa: F401 — регистрирует модели
from bot.db.base import Base

target_metadata = Base.metadata


def _run(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name == "sqlite",  # ALTER TABLE в SQLite — через пересоздание
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def _run_async() -> None:
    engine = create_async_engine(settings.database_url)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
        await conn.commit()
    await engine.dispose()


if context.is_offline_mode():
    context.configure(url=settings.database_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
elif (conn := context.config.attributes.get("connection")) is not None:
    _run(conn)  # вызов из кода бота: соединение уже открыто
else:
    asyncio.run(_run_async())
