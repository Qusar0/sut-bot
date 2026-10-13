"""Служебные команды администратора."""

import time

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import func, select

from bot import metrics
from bot.config import settings
from bot.db.base import Session
from bot.db.models import User

router = Router(name="admin")


@router.message(Command("stats"))
async def stats(message: Message) -> None:
    if settings.admin_id is None or message.from_user.id != settings.admin_id:
        return  # для остальных команды не существует

    async with Session() as s:
        users = await s.scalar(select(func.count()).select_from(User))
        with_group = await s.scalar(select(func.count()).select_from(User).where(User.group_id.is_not(None)))

    uptime = int(time.time() - metrics.started_at)
    lines = [
        "<b>📊 Статистика</b>",
        f"Аптайм: {uptime // 3600} ч {uptime % 3600 // 60} мин",
        f"Пользователей: {users} (с группой: {with_group})",
        "",
        "<b>Время, мс</b> <i>(вызовов · p50 · p95 · max)</i>",
    ]
    for name, total, p50, p95, mx in metrics.snapshot():
        lines.append(f"<code>{name}</code>\n    {total} · {p50:.0f} · {p95:.0f} · {mx:.0f}")
    if metrics.counters:
        lines += ["", "<b>Счётчики</b>"]
        lines += [f"<code>{k}</code>: {v}" for k, v in sorted(metrics.counters.items())]
        hits = sum(metrics.counters[k] for k in ("кэш: память", "кэш: БД", "кэш: склеенный запрос"))
        total = hits + metrics.counters["кэш: промах"]
        if total:
            lines.append(f"Попаданий в кэш: {hits / total:.0%}")
    await message.answer("\n".join(lines))
