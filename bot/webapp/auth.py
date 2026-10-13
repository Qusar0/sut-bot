"""Проверка подписи Telegram Mini App (initData). https://core.telegram.org/bots/webapps#validating-data"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qsl

MAX_AGE = 24 * 3600  # initData старше суток не принимаем


class InitDataError(Exception):
    pass


def validate_init_data(init_data: str, bot_token: str, now: float | None = None) -> dict:
    """Возвращает данные пользователя Telegram ({'id': …, 'first_name': …}) или бросает InitDataError."""
    pairs = dict(parse_qsl(init_data, keep_blank_values=True, strict_parsing=False))
    received = pairs.pop("hash", None)
    if not received:
        raise InitDataError("нет подписи")
    check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received):
        raise InitDataError("подпись не совпала")
    auth_date = int(pairs.get("auth_date", "0"))
    if (now or time.time()) - auth_date > MAX_AGE:
        raise InitDataError("данные устарели")
    try:
        user = json.loads(pairs.get("user", "{}"))
    except json.JSONDecodeError as e:
        raise InitDataError("испорчены данные пользователя") from e
    if "id" not in user:
        raise InitDataError("нет пользователя")
    return user


def sign_init_data(fields: dict[str, str], bot_token: str) -> str:
    """Для тестов: собирает initData с правильной подписью."""
    from urllib.parse import urlencode

    check = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    return urlencode({**fields, "hash": hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()})
