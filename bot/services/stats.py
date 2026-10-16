"""Персистентная дневная статистика автоотметки (переживает перезапуск, хранит историю)."""

from datetime import date, datetime, timedelta

from sqlalchemy import select

from bot.config import TZ
from bot.db.base import Session
from bot.db.models import StatDaily

_FIELDS = ("scans", "available", "marked", "failed", "lk_down")


async def bump_attendance(day: date, **deltas: int) -> None:
    """Прибавляет счётчики за день (одним апдейтом за прогон задачи)."""
    async with Session() as s:
        row = await s.get(StatDaily, day)
        if row is None:
            row = StatDaily(day=day)
            s.add(row)
        for f in _FIELDS:
            if deltas.get(f):
                setattr(row, f, (getattr(row, f) or 0) + deltas[f])
        if deltas.get("scans"):
            row.last_scan = datetime.now(TZ)
        await s.commit()


def _as_dict(row: StatDaily | None, day: date) -> dict:
    if row is None:
        return {"day": day.isoformat(), **{f: 0 for f in _FIELDS}, "last_scan": None}
    return {
        "day": row.day.isoformat(),
        **{f: getattr(row, f) for f in _FIELDS},
        "last_scan": row.last_scan.timestamp() if row.last_scan else None,
    }


async def attendance_stats(day: date, history_days: int = 7) -> dict:
    """Статистика за сегодня + история за последние N дней (для мониторинга)."""
    async with Session() as s:
        today_row = await s.get(StatDaily, day)
        rows = (
            (
                await s.execute(
                    select(StatDaily)
                    .where(StatDaily.day <= day, StatDaily.day >= day - timedelta(days=history_days - 1))
                    .order_by(StatDaily.day.desc())
                )
            )
            .scalars()
            .all()
        )
    return {"today": _as_dict(today_row, day), "history": [_as_dict(r, r.day) for r in rows]}
