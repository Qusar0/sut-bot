"""Тесты авторизации Mini App и сериализаторов API."""

import time

import pytest

from bot.webapp.auth import InitDataError, sign_init_data, validate_init_data

TOKEN = "123456:TESTTOKEN"


def test_valid_init_data():
    init = sign_init_data({"user": '{"id":42,"first_name":"Тест"}', "auth_date": str(int(time.time()))}, TOKEN)
    user = validate_init_data(init, TOKEN, now=time.time())
    assert user["id"] == 42


def test_tampered_rejected():
    init = sign_init_data({"user": '{"id":42}', "auth_date": str(int(time.time()))}, TOKEN)
    # портим последний символ подписи
    last = "0" if init[-1] != "0" else "1"
    with pytest.raises(InitDataError):
        validate_init_data(init[:-1] + last, TOKEN, now=time.time())


def test_wrong_token_rejected():
    init = sign_init_data({"user": '{"id":42}', "auth_date": str(int(time.time()))}, TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(init, "другой:токен", now=time.time())


def test_expired_rejected():
    init = sign_init_data({"user": '{"id":42}', "auth_date": "1000000000"}, TOKEN)
    with pytest.raises(InitDataError):
        validate_init_data(init, TOKEN, now=time.time())


def test_no_hash_rejected():
    with pytest.raises(InitDataError):
        validate_init_data("user=%7B%7D&auth_date=1", TOKEN)


def test_serializers():
    from datetime import date
    from pathlib import Path

    from bot.services.sut_public.parser import parse_week
    from bot.webapp.api import _lesson

    week = parse_week(
        (Path(__file__).parent / "fixtures" / "group_week.html").read_text(encoding="utf-8"), 56882, date(2026, 10, 13)
    )
    d = _lesson(week.lessons[0])
    assert d["kind_key"] in ("lecture", "practice", "lab")
    assert d["subject"] and d["start"] and "room" in d
