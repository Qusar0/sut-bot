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

from bot.config import TZ, settings
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
        sess = LkSession(login, password, proxy=settings.sut_proxy)
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

    async def close(self) -> None:
        for sess in list(self._sessions.values()):
            await sess.close()
        self._sessions.clear()

    async def linked_ids(self) -> list[int]:
        from sqlalchemy import select

        async with Session() as s:
            return [r[0] for r in await s.execute(select(LkAccount.tg_id).where(LkAccount.status != "auth_failed"))]

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
        sess = LkSession(acc.login, decrypt(acc.password_enc), proxy=settings.sut_proxy)
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

    # --- синхронизация (п. 34) и поиск нового для уведомлений (п. 52–56, 58) ---

    async def sync(self, tg_id: int, sections: tuple[str, ...]) -> dict[str, list]:
        """Опрашивает разделы, обновляет снимки и возвращает {раздел: [новые элементы]}.

        Первый снимок раздела не порождает уведомлений (просто запоминаем состояние).
        """
        news: dict[str, list] = {}
        async with self._lock(tg_id):
            try:
                sess = await self._session(tg_id)
            except NotLinked:
                return news
            async with Session() as s:
                for name in sections:
                    try:
                        data = await _fetch(sess, name)
                    except LkAuthError:
                        await self._mark(tg_id, "auth_failed", "пароль не подошёл — переподключите кабинет")
                        await self._drop(tg_id)
                        return news
                    except LkError:
                        continue
                    jsonable = _jsonable(data)
                    dg = digest_of(data)
                    snap = await s.get(LkSnapshot, (tg_id, name))
                    if snap is None:
                        s.add(
                            LkSnapshot(tg_id=tg_id, section=name, data=jsonable, digest=dg, fetched_at=datetime.now(TZ))
                        )
                    elif snap.digest != dg:
                        fresh = _new_items(name, snap.data, jsonable)
                        if fresh:
                            news[name] = fresh
                        snap.data, snap.digest, snap.fetched_at = jsonable, dg, datetime.now(TZ)
                acc = await s.get(LkAccount, tg_id)
                if acc is not None:
                    acc.last_sync_at = datetime.now(TZ)
                    if acc.status != "ok":
                        acc.status, acc.last_error = "ok", ""
                await s.commit()
            # раздел мог обновиться — сбрасываем короткий кэш
            for name in sections:
                self._cache.pop((tg_id, name), None)
        return news

    # --- отметка на паре (п. 35–36) ---
    # Делает действие в ЛК от имени студента. Только по явной команде или включённой автоотметке.

    async def lk_schedule(self, tg_id: int):
        """Расписание из ЛК на сегодня с состоянием кнопки отметки."""
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            html = await sess.post("project/cabinet/forms/raspisanie.php", {"key": "6118"})
        return P.parse_lk_schedule(html)

    async def refresh_button(self, tg_id: int, rasp: str) -> str:
        """Обновляет состояние кнопки отметки (open=3)."""
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            raw = await sess.post("project/cabinet/forms/raspisanie.php", {"open": "3", "rasp": rasp})
        return P.parse_mark_result(raw)

    # --- переписка с преподавателем (п. 37) ---

    async def message_thread(self, tg_id: int, mid: int) -> dict:
        """Текст сообщения и история переписки. prosmotr отмечает сообщение прочитанным."""
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            body_raw = await sess.post("project/cabinet/forms/sendto2.php", {"id": str(mid), "prosmotr": ""})
            hist_raw = await sess.post("project/cabinet/forms/sendto2.php", {"id": str(mid), "history_show": ""})
        return P.parse_message_thread(body_raw, hist_raw)

    async def send_reply(self, tg_id: int, mid: int, text: str) -> bool:
        """Отправляет ответ преподавателю (действие в ЛК от имени студента, по явной команде)."""
        text = text.strip()
        if not text:
            return False
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            await sess.post(
                "project/cabinet/forms/message.php",
                {"item": str(mid), "idinfo": "0", "mes_otvet": text, "saveotv": ""},
            )
        from bot import metrics

        metrics.inc("ЛК: ответ преподавателю")
        self._cache.pop((tg_id, "messages"), None)
        return True

    async def set_auto(self, tg_id: int, on: bool) -> None:
        async with Session() as s:
            acc = await s.get(LkAccount, tg_id)
            if acc is not None:
                acc.auto_attendance = on
                await s.commit()

    async def auto_ids(self) -> list[int]:
        from sqlalchemy import select

        async with Session() as s:
            q = select(LkAccount.tg_id).where(LkAccount.auto_attendance.is_(True), LkAccount.status != "auth_failed")
            return [r[0] for r in await s.execute(q)]

    async def auto_mark(self, tg_id: int) -> list[str]:
        """Автоотметка (п. 36): отмечает все пары, у которых кнопка готова и занятие ещё не начато.

        Возвращает названия отмеченных пар. Делается от имени студента по его согласию.
        """
        try:
            lessons = await self.lk_schedule(tg_id)
        except LkError:
            return []
        marked = []
        for l in lessons:
            if l.button_ready and not l.started:
                try:
                    await self.mark_attendance(tg_id, l.rasp)
                    marked.append(l.subject)
                except LkError:
                    continue
        return marked

    async def mark_attendance(self, tg_id: int, rasp: str, week: str = "") -> str:
        """Нажимает «Начать занятие» (open=1) от имени студента. Возвращает текст результата."""
        async with self._lock(tg_id):
            sess = await self._session(tg_id)
            raw = await sess.post("project/cabinet/forms/raspisanie.php", {"open": "1", "rasp": rasp, "week": week})
        from bot import metrics

        metrics.inc("ЛК: отметка")
        return P.parse_mark_result(raw)


def _new_items(section: str, old, new) -> list:
    """Что появилось в разделе по сравнению с прошлым снимком."""
    if not isinstance(new, list):
        return [new] if new != old else []  # текст/объект целиком изменился
    if section in ("messages", "files"):
        old_ids = {x.get("id") for x in old} if isinstance(old, list) else set()
        return [x for x in new if x.get("id") not in old_ids]
    if section == "diary":
        old_set = {(x.get("day"), x.get("subject"), x.get("value")) for x in old} if isinstance(old, list) else set()
        return [x for x in new if (x.get("day"), x.get("subject"), x.get("value")) not in old_set]
    old_rows = old if isinstance(old, list) else []
    return [x for x in new if x not in old_rows]
