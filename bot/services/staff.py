"""Справочник профилей преподавателей (п. 14): обход кафедр и ленивая загрузка профиля."""

import logging
from datetime import datetime, timedelta

from sqlalchemy import func, select

from bot.config import TZ
from bot.db.base import Session
from bot.db.models import StaffProfile
from bot.services.directory import normalize
from bot.services.sut_public import staff as S
from bot.services.sut_public.client import SutPublicClient

log = logging.getLogger(__name__)

PROFILE_TTL = timedelta(days=7)


class StaffService:
    def __init__(self, client: SutPublicClient):
        self.client = client

    async def count(self) -> int:
        async with Session() as s:
            return await s.scalar(select(func.count()).select_from(StaffProfile)) or 0

    async def refresh_lists(self) -> int:
        """Обходит факультеты и кафедры, обновляет список преподавателей со ссылками на профили."""
        now = datetime.now(TZ)
        cards: dict[str, S.StaffCard] = {}
        faculties = S.parse_faculty_links(await self.client.get_url(S.SITE + S.FACULTIES_PATH))
        for fac in faculties:
            try:
                deps = S.parse_department_links(await self.client.get_url(S.SITE + fac), fac)
            except Exception:
                log.warning("факультет %s недоступен", fac)
                continue
            for dep in deps:
                try:
                    html = await self.client.get_url(S.SITE + dep + "/prepodavatelskiy-sostav")
                except Exception:
                    continue  # у части разделов нет страницы состава — это нормально
                for c in S.parse_staff_list(html):
                    cards.setdefault(normalize(c.full_name), c)
        async with Session() as s:
            for key, c in cards.items():
                row = await s.get(StaffProfile, key)
                if row is None:
                    s.add(StaffProfile(key=key, full_name=c.full_name, position=c.position, url=c.url, listed_at=now))
                else:
                    row.position, row.url, row.listed_at = c.position, c.url, now
            await s.commit()
        log.info("профили преподавателей: %d", len(cards))
        return len(cards)

    async def profile(self, full_name: str) -> S.Profile | None:
        key = normalize(full_name)
        async with Session() as s:
            row = await s.get(StaffProfile, key)
            if row is None:
                return None
            fresh = row.fetched_at and datetime.now(TZ) - row.fetched_at.astimezone(TZ) < PROFILE_TTL
            if row.data and fresh:
                return S.Profile(**row.data)
            try:
                html = await self.client.get_url(row.url, background=False)
                prof = S.parse_profile(html, row.url)
            except Exception:
                log.warning("профиль %s недоступен", row.url)
                return S.Profile(**row.data) if row.data else S.Profile(row.full_name, row.position, url=row.url)
            row.data, row.fetched_at = prof.to_dict(), datetime.now(TZ)
            await s.commit()
            return prof
