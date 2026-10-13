import re

from sqlalchemy import delete, select

from bot.db.base import Session
from bot.db.models import AuditLog, Consent, Group, User
from bot.legal import DOCUMENTS

# Кэш «пользователь принял актуальные редакции» — чтобы не ходить в БД на каждое сообщение
_consent_ok: set[int] = set()


async def get_or_create_user(tg_id: int) -> User:
    async with Session() as s:
        user = await s.get(User, tg_id)
        if user is None:
            user = User(tg_id=tg_id)
            s.add(user)
            await s.commit()
        elif user.blocked:
            user.blocked = False
            await s.commit()
        return user


async def get_user(tg_id: int) -> User | None:
    async with Session() as s:
        return await s.get(User, tg_id)


async def has_actual_consent(tg_id: int) -> bool:
    if tg_id in _consent_ok:
        return True
    async with Session() as s:
        rows = await s.execute(select(Consent.doc, Consent.version).where(Consent.tg_id == tg_id))
        accepted = {(d, v) for d, v in rows}
    ok = all((d.code, d.version) in accepted for d in DOCUMENTS)
    if ok:
        _consent_ok.add(tg_id)
    return ok


async def accept_documents(tg_id: int) -> None:
    await get_or_create_user(tg_id)
    async with Session() as s:
        for d in DOCUMENTS:
            s.add(Consent(tg_id=tg_id, doc=d.code, version=d.version))
        await s.commit()
    _consent_ok.add(tg_id)


async def delete_user_data(tg_id: int) -> None:
    """Полное удаление данных пользователя (п. 70). Новые таблицы с данными пользователя добавлять сюда."""
    async with Session() as s:
        await s.execute(delete(Consent).where(Consent.tg_id == tg_id))
        await s.execute(delete(User).where(User.tg_id == tg_id))
        s.add(AuditLog(event="user_deleted", tg_id=tg_id))
        await s.commit()
    _consent_ok.discard(tg_id)


async def set_user_fields(tg_id: int, **fields) -> User:
    async with Session() as s:
        user = await s.get(User, tg_id)
        for k, v in fields.items():
            setattr(user, k, v)
        await s.commit()
        return user


# --- группы ---

_LAT_TO_CYR = str.maketrans("ABCEHKMOPTXY", "АВСЕНКМОРТХУ")


def normalize_group(name: str) -> str:
    n = re.sub(r"[\s_]+", "", name.upper()).replace("—", "-").replace("–", "-")
    return n.translate(_LAT_TO_CYR)


_groups_cache: list[Group] | None = None


async def _all_groups() -> list[Group]:
    global _groups_cache
    if _groups_cache is None:
        async with Session() as s:
            _groups_cache = list((await s.execute(select(Group))).scalars().all())
    return _groups_cache


async def find_groups(query: str, limit: int = 10) -> list[Group]:
    q = normalize_group(query)
    groups = await _all_groups()
    exact = [g for g in groups if normalize_group(g.name) == q]
    if exact:
        return exact
    q_nodash = q.replace("-", "")
    found = [g for g in groups if q_nodash in normalize_group(g.name).replace("-", "")]
    return sorted(found, key=lambda g: g.name)[:limit]


async def get_group(group_id: int) -> Group | None:
    return next((g for g in await _all_groups() if g.id == group_id), None)


async def save_groups(groups) -> None:
    global _groups_cache
    async with Session() as s:
        for g in groups:
            await s.merge(Group(id=g.id, name=g.name, faculty=g.faculty))
        await s.commit()
    _groups_cache = None


async def groups_count() -> int:
    return len(await _all_groups())


async def all_group_ids() -> list[int]:
    return [g.id for g in await _all_groups()]
