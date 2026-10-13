"""Справочник преподавателей и аудиторий поверх индекса занятий всех групп (п. 11, 16).

На sut.ru нет отдельных расписаний преподавателей и аудиторий, поэтому мы собираем их сами:
каждая загруженная неделя любой группы раскладывается в таблицу lesson_index.
"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import delete, select

from bot.db.base import Session
from bot.db.models import Group, IndexEntry, Room, Teacher
from bot.services.sut_public.models import Lesson


def normalize(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().replace("ё", "е")).strip()


def short_name(full: str) -> str:
    """«Кокорин Михаил Станиславович» → «Кокорин М.С.»"""
    parts = full.split()
    if len(parts) < 2:
        return full
    return parts[0] + " " + "".join(p[0] + "." for p in parts[1:3])


def room_label(room: str, building: str) -> str:
    if m := re.match(r"^Б22/(\d)$", building or ""):
        return f"{room}/{m.group(1)}"
    return f"{room} · {building}" if building and building not in room else room


@dataclass
class Slot:
    """Занятие, собранное из строк индекса: у преподавателя на лекции может быть несколько групп."""

    day: date
    pair: str
    start: str
    end: str
    subject: str
    kind: str
    room: str
    groups: list[str] = field(default_factory=list)
    teachers: list[str] = field(default_factory=list)


class Directory:
    def __init__(self) -> None:
        self._teachers: dict[str, Teacher] = {}  # full_name -> Teacher
        self._teachers_by_id: dict[int, Teacher] = {}
        self._rooms: dict[tuple[str, str], Room] = {}
        self._rooms_by_id: dict[int, Room] = {}
        self._lock = asyncio.Lock()
        self._loaded = False

    async def load(self) -> None:
        async with Session() as s:
            for t in (await s.execute(select(Teacher))).scalars():
                self._teachers[t.full_name] = t
                self._teachers_by_id[t.id] = t
            for r in (await s.execute(select(Room))).scalars():
                self._rooms[(r.room, r.building)] = r
                self._rooms_by_id[r.id] = r
        self._loaded = True

    # --- запись ---

    async def _teacher_id(self, s, full: str) -> int:
        if t := self._teachers.get(full):
            return t.id
        t = Teacher(full_name=full, short_name=short_name(full))
        s.add(t)
        await s.flush()
        self._teachers[full] = t
        self._teachers_by_id[t.id] = t
        return t.id

    async def _room_id(self, s, room: str, building: str) -> int | None:
        if not room:
            return None
        key = (room, building)
        if r := self._rooms.get(key):
            return r.id
        r = Room(room=room, building=building)
        s.add(r)
        await s.flush()
        self._rooms[key] = r
        self._rooms_by_id[r.id] = r
        return r.id

    async def update(self, group_id: int, monday: date, lessons: list[Lesson]) -> None:
        """Перезаписывает индекс для недели группы."""
        async with self._lock, Session() as s:
            if not self._loaded:
                await self.load()
            await s.execute(delete(IndexEntry).where(IndexEntry.group_id == group_id, IndexEntry.monday == monday))
            for l in lessons:
                room_id = await self._room_id(s, l.room, l.building)
                teacher_ids = [await self._teacher_id(s, t) for t in l.teachers] or [None]
                for tid in teacher_ids:
                    s.add(
                        IndexEntry(
                            group_id=group_id,
                            monday=monday,
                            day=l.day,
                            pair=l.pair,
                            start=l.start,
                            end=l.end,
                            subject=l.subject,
                            kind=l.kind,
                            teacher_id=tid,
                            room_id=room_id,
                        )
                    )
            await s.commit()

    async def rebuild_if_empty(self) -> int:
        """Первый запуск после обновления: строим индекс из уже сохранённых недель."""
        from bot.db.models import WeekSnapshot

        async with Session() as s:
            if await s.scalar(select(IndexEntry.id).limit(1)) is not None:
                return 0
            snaps = (await s.execute(select(WeekSnapshot))).scalars().all()
        for snap in snaps:
            await self.update(snap.group_id, snap.monday, [Lesson.from_dict(d) for d in snap.lessons])
        return len(snaps)

    # --- поиск ---

    def teacher(self, tid: int) -> Teacher | None:
        return self._teachers_by_id.get(tid)

    def room(self, rid: int) -> Room | None:
        return self._rooms_by_id.get(rid)

    def teacher_by_name(self, full: str) -> Teacher | None:
        return self._teachers.get(full)

    def room_by_key(self, room: str, building: str) -> Room | None:
        return self._rooms.get((room, building))

    def search_teachers(self, query: str, limit: int = 10) -> list[Teacher]:
        tokens = normalize(query).replace(".", " ").split()
        if not tokens:
            return []
        found = []
        for t in self._teachers.values():
            words = normalize(t.full_name).split()
            # каждое слово запроса — начало какого-то слова ФИО: «воронова м» найдёт «Воронова Мария …»
            if all(any(w.startswith(tok) for w in words) for tok in tokens):
                found.append(t)
        return sorted(found, key=lambda t: t.full_name)[:limit]

    def search_rooms(self, query: str, limit: int = 10) -> list[Room]:
        q = normalize(query).replace("ауд.", "").replace("ауд", "").strip()
        num, _, suffix = q.partition("/")
        exact, partial = [], []
        for r in self._rooms.values():
            label = normalize(room_label(r.room, r.building))
            if label == q or (normalize(r.room) == num.strip() and (not suffix or label.endswith("/" + suffix))):
                exact.append(r)
            elif q and q in label:
                partial.append(r)
        key = lambda r: room_label(r.room, r.building)  # noqa: E731
        return (sorted(exact, key=key) + sorted(partial, key=key))[:limit]

    # --- расписания ---

    async def _slots(self, where, start: date, end: date) -> list[Slot]:
        async with Session() as s:
            rows = (
                await s.execute(
                    select(IndexEntry, Group.name)
                    .join(Group, Group.id == IndexEntry.group_id)
                    .where(where, IndexEntry.day >= start, IndexEntry.day <= end)
                )
            ).all()
        slots: dict[tuple, Slot] = {}
        for e, group_name in rows:
            room = self._rooms_by_id.get(e.room_id) if e.room_id else None
            room_str = room_label(room.room, room.building) if room else ""
            key = (e.day, e.start, e.subject, e.kind, room_str)
            slot = slots.get(key)
            if slot is None:
                slot = slots[key] = Slot(e.day, e.pair, e.start, e.end, e.subject, e.kind, room_str)
            if group_name not in slot.groups:
                slot.groups.append(group_name)
            t = self._teachers_by_id.get(e.teacher_id) if e.teacher_id else None
            if t and t.short_name not in slot.teachers:
                slot.teachers.append(t.short_name)
        for slot in slots.values():
            slot.groups.sort()
        return sorted(slots.values(), key=lambda x: (x.day, x.start, x.subject))

    async def teacher_slots(self, tid: int, start: date, end: date) -> list[Slot]:
        return await self._slots(IndexEntry.teacher_id == tid, start, end)

    async def room_slots(self, rid: int, start: date, end: date) -> list[Slot]:
        return await self._slots(IndexEntry.room_id == rid, start, end)
