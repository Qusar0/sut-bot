"""Работа с личными кабинетами студентов: привязка (п. 33), разделы (п. 37–50), синхронизация (п. 34).

Пароль студента хранится только зашифрованным (crypto.encrypt), в логи не пишется, стирается в /delete.
"""

import asyncio
import hashlib
import json
import logging
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime

from sqlalchemy import delete

from bot.config import TZ
from bot.db.base import Session
from bot.db.models import LkAccount, LkSnapshot
from bot.services.lk import parser as P
from bot.services.lk.client import LkAuthError, LkError, LkSession
from bot.services.lk.crypto import decrypt, encrypt

log = logging.getLogger(__name__)

# раздел -> (modul, key, доп. параметры POST)
SECTIONS: dict[str, tuple[str, str, dict[str, str]]] = {
    "messages": ("project/cabinet/forms/message.php", "840", {}),
    "files": ("project/cabinet/forms/files_group_pr.php", "842", {}),
    "diary": ("project/cabinet/forms/jurnal_dnevnik.php", "6119", {}),
    "record_book": ("project/cabinet/forms/zachetka.php", "812", {}),
    "debts": ("project/cabinet/forms/dolg.php", "802", {}),
    "attestation": ("project/cabinet/forms/vedomost_attest_stud.php", "1923", {}),
    "plan": ("project/cabinet/forms/uch_grafik.php", "805", {}),
    "orders": ("project/cabinet/forms/prikazs.php", "809", {}),
    "rating": ("project/cabinet/forms/raiting.php", "808", {"spec": "1", "training_form": "1", "period": "1"}),
    "scholarships": ("project/cabinet/forms/stipendii.php", "1683", {}),
    "certificates": ("project/cabinet/forms/doc_zakaz.php", "801", {}),
    "profile": ("project/cabinet/forms/profil.php", "1678", {}),
    "studsovet": ("project/cabinet/forms/studsovet.php", "814", {}),
}

PARSERS = {
    "messages": P.parse_messages,
    "files": P.parse_group_files,
    "diary": P.parse_diary,
    "record_book": P.parse_record_book,
    "debts": P.parse_debts,
    "attestation": P.parse_text_section,
    "plan": P.parse_study_plan,
    "orders": P.parse_orders,
    "rating": P.parse_rating,
    "scholarships": P.parse_scholarships,
    "certificates": P.parse_text_section,
    "profile": P.parse_profile,
    "studsovet": P.parse_text_section,
}

# Что опрашивать часто (каждый цикл синхронизации), а что — редко
HOT = ("messages", "files", "diary")
COLD = ("record_book", "debts", "orders", "scholarships", "rating")

CACHE_TTL = 180  # секунд: повторное открытие раздела в боте не ходит в ЛК заново


class NotLinked(LkError):
    """Кабинет не подключён."""


def _jsonable(obj):
    if is_dataclass(obj):
        return {k: _jsonable(v) for k, v in asdict(obj).items()}
    if isinstance(obj, list | tuple):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    return obj


def digest_of(data) -> str:
    return hashlib.sha256(json.dumps(_jsonable(data), ensure_ascii=False, sort_keys=True).encode()).hexdigest()


async def _fetch(sess: LkSession, name: str):
    modul, key, params = SECTIONS[name]
    return PARSERS[name](await sess.form(modul, key, **params))


class LkService:
    def __init__(self) -> None:
        self._sessions: dict[int, LkSession] = {}  # tg_id -> живая сессия ЛК
        self._cache: dict[tuple[int, str], tuple[float, object]] = {}
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, tg_id: int) -> asyncio.Lock:
        return self._locks.setdefault(tg_id, asyncio.Lock())

    async def _drop(self, tg_id: int) -> None:
        sess = self._sessions.pop(tg_id, None)
        if sess is not None:
            await sess.close()
        for k in [k for k in self._cache if k[0] == tg_id]:
            self._cache.pop(k, None)

    # --- привязка ---

    async def link(self, tg_id: int, login: str, password: str) -> P.Profile:
        """Проверяет вход и сохраняет учётку. Бросает LkAuthError / LkBlockedError / LkUnavailable."""
        sess = LkSession(login, password)
        try:
            await sess.login()
            profile = await _fetch(sess, "profile")
        except Exception:
            await sess.close()
            raise
        async with Session() as s:
            acc = await s.get(LkAccount, tg_id)
            if acc is None:
                acc = LkAccount(tg_id=tg_id)
                s.add(acc)
            acc.login = login
            acc.password_enc = encrypt(password)
            acc.fio = profile.fio
            acc.group_name = profile.group
            acc.course = profile.fields.get("Курс", "")
            acc.status = "ok"
            acc.last_error = ""
            acc.last_sync_at = datetime.now(TZ)
            await s.commit()
        await self._drop(tg_id)
        self._sessions[tg_id] = sess
        return profile

    async def account(self, tg_id: int) -> LkAccount | None:
        async with Session() as s:
            return await s.get(LkAccount, tg_id)

    async def is_linked(self, tg_id: int) -> bool:
        return await self.account(tg_id) is not None

    async def unlink(self, tg_id: int) -> None:
        """Отключить кабинет по желанию пользователя: закрыть сессию и стереть учётку и снимки."""
        await self._drop(tg_id)
        async with Session() as s:
            await s.execute(delete(LkSnapshot).where(LkSnapshot.tg_id == tg_id))
            await s.execute(delete(LkAccount).where(LkAccount.tg_id == tg_id))
            await s.commit()

    # --- сессии и чтение разделов ---

    async def _session(self, tg_id: int) -> LkSession:
        sess = self._sessions.get(tg_id)
        if sess is not None:
            return sess
        acc = await self.account(tg_id)
        if acc is None:
            raise NotLinked("кабинет не подключён")
        sess = LkSession(acc.login, decrypt(acc.password_enc))
        self._sessions[tg_id] = sess
        return sess

    async def _mark(self, tg_id: int, status: str, error: str) -> None:
        async with Session() as s:
            acc = await s.get(LkAccount, tg_id)
            if acc is not None:
                acc.status, acc.last_error = status, error
                await s.commit()

    async def section(self, tg_id: int, name: str):
        """Читает раздел ЛК (с коротким кэшем). При неверном пароле помечает учётку и пробрасывает ошибку."""
        key = (tg_id, name)
        hit = self._cache.get(key)
        if hit and time.monotonic() - hit[0] < CACHE_TTL:
            return hit[1]
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            try:
                data = await _fetch(sess, name)
            except LkAuthError:
                await self._mark(tg_id, "auth_failed", "пароль не подошёл — переподключите кабинет")
                await self._drop(tg_id)
                raise
            except LkError as e:
                await self._mark(tg_id, "error", str(e)[:200])
                raise
        self._cache[key] = (time.monotonic(), data)
        return data
