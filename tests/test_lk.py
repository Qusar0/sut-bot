"""Тесты ЛК на синтетической обезличенной разметке (реальные данные в репозиторий не кладём)."""

from datetime import date

import pytest

from bot.services.lk import parser as P
from bot.services.lk import service as S
from bot.services.lk.crypto import decrypt, encrypt

PROFILE_HTML = """
<table class='profil'><tr><td><img></td></tr>
<tr><th>ФИО:</th><td>Тестов Тест Тестович</td></tr>
<tr><th>Группа:</th><td>ТЕСТ-0000</td></tr>
<tr><th>Курс:</th><td>1</td></tr>
<tr><th>Дата рождения:</th><td>01.01.2000</td></tr></table>
"""

MESSAGES_HTML = """
<table id='mytable'><tr id='tr_111'><td>13-10-2026 <small>10:00:00</small></td>
<td>Тема раз</td><td><a href='/f/a.pdf'>a.pdf</a></td><td>Преподов П.П. - (сотрудник)</td></tr>
<tr id='tr_222'><td>12-10-2026 <small>09:00:00</small></td><td>Тема два</td><td></td><td>Иванова И.И.</td></tr></table>
"""

DIARY_HTML = """
<table class='smalltab'><tr><th>№нед.</th><th>Дата</th><th>Матанализ</th><th>Физика</th></tr>
<tr date1='2026-09-02'><td>1</td><td>Ср 02.09.26</td><td rasp='1' onclick='gettema(this)'>5</td><td></td></tr>
<tr date1='2026-09-09'><td>2</td><td>Ср 09.09.26</td><td></td><td rasp='2' onclick='gettema(this)'>Н</td></tr></table>
"""

SCHEDULE_HTML = """
<table class='simple-little-table'><tr><td colspan=6><b>Понедельник</b></td></tr>
<tr><td><small>1 (9:00-10:35)</small></td><td><b>Матанализ</b><small>занятие началось 09:02</small></td>
<td></td><td>303; Б22/2</td><td>Иванова И.И.</td><td><span id='knop10'>Закончено</span></td></tr>
<tr><td><small>2 (10:45-12:20)</small></td><td><b>Физика</b></td><td></td><td>110; Б22/1</td>
<td>Петров П.П.</td><td><span id='knop20'><a onclick='update_zan(20)'>Отметиться</a></span></td></tr></table>
"""


def test_crypto_roundtrip():
    token = encrypt("секрет123")
    assert token != "секрет123"
    assert decrypt(token) == "секрет123"


def test_parse_profile():
    p = P.parse_profile(PROFILE_HTML)
    assert p.fio == "Тестов Тест Тестович"
    assert p.group == "ТЕСТ-0000"
    assert p.fields.get("Курс") == "1"
    assert "Дата рождения" not in p.fields  # дату рождения не храним


def test_parse_messages():
    msgs = P.parse_messages(MESSAGES_HTML)
    assert [m.id for m in msgs] == [111, 222]
    assert msgs[0].subject == "Тема раз" and msgs[0].sender == "Преподов П.П."
    assert msgs[0].files == [("a.pdf", "https://lk.sut.ru/cabinet/f/a.pdf")]


def test_parse_diary():
    marks = P.parse_diary(DIARY_HTML)
    assert P.Mark(date(2026, 9, 2), "Матанализ", "5") in marks
    assert P.Mark(date(2026, 9, 9), "Физика", "Н") in marks


def test_parse_lk_schedule():
    lessons = P.parse_lk_schedule(SCHEDULE_HTML)
    assert len(lessons) == 2
    assert lessons[0].rasp == "10" and lessons[0].started
    assert lessons[1].rasp == "20" and lessons[1].button_ready and not lessons[1].started


def test_parse_mark_result():
    assert P.parse_mark_result('{"data": "<b>Отмечено</b>"}') == "Отмечено"


def test_new_items():
    assert S._new_items("messages", [{"id": 1}], [{"id": 1}, {"id": 2}]) == [{"id": 2}]
    old = [{"day": "2026-09-02", "subject": "Матанализ", "value": "4"}]
    new = old + [{"day": "2026-09-09", "subject": "Физика", "value": "5"}]
    assert S._new_items("diary", old, new) == [new[1]]
    assert S._new_items("debts", [], []) == []


class FakeSession:
    """Подменяет LkSession: не ходит в сеть, отдаёт заготовленные разделы."""

    def __init__(self, login, password, **kw):
        self.login_name = login
        self._password = password
        self.closed = False

    async def login(self):
        if self._password != "right":
            from bot.services.lk.client import LkAuthError

            raise LkAuthError("неверный пароль")
        return "<html>ok</html>"

    async def form(self, modul, key, **params):
        if "profil" in modul:
            return PROFILE_HTML
        if "message" in modul:
            return MESSAGES_HTML
        return DIARY_HTML

    async def post(self, modul, data):
        return SCHEDULE_HTML

    async def close(self):
        self.closed = True


@pytest.fixture
def _fake_session(monkeypatch):
    monkeypatch.setattr(S, "LkSession", FakeSession)


async def test_link_and_sections(_fake_session):
    from bot.db.base import init_db
    from bot.services.users import get_or_create_user

    await init_db()
    await get_or_create_user(5001)
    svc = S.LkService()

    from bot.services.lk.client import LkAuthError

    with pytest.raises(LkAuthError):
        await svc.link(5001, "login@sut.ru", "wrong")

    profile = await svc.link(5001, "login@sut.ru", "right")
    assert profile.fio == "Тестов Тест Тестович"

    acc = await svc.account(5001)
    assert acc is not None and acc.group_name == "ТЕСТ-0000"
    assert acc.password_enc != "right" and decrypt(acc.password_enc) == "right"  # пароль зашифрован

    msgs = await svc.section(5001, "messages")
    assert [m.id for m in msgs] == [111, 222]

    assert 5001 in await svc.linked_ids()
    await svc.unlink(5001)
    assert await svc.account(5001) is None


async def test_sync_detects_new(_fake_session):
    from bot.db.base import init_db
    from bot.services.users import get_or_create_user

    await init_db()
    await get_or_create_user(5002)
    svc = S.LkService()
    await svc.link(5002, "l@sut.ru", "right")

    first = await svc.sync(5002, ("diary",))
    assert first == {}  # первый снимок — без уведомлений
    second = await svc.sync(5002, ("diary",))
    assert second == {}  # данные те же — нового нет
