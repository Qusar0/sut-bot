import os
import tempfile
from pathlib import Path

# До импорта bot.*: временная база и фиктивный токен, чтобы тесты не трогали data/bot.db
_tmp = Path(tempfile.mkdtemp()) / "test.db"
# TEST_DATABASE_URL позволяет прогнать тесты на PostgreSQL (так делает CI)
os.environ["DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL") or f"sqlite+aiosqlite:///{_tmp.as_posix()}"
os.environ.setdefault("BOT_TOKEN", "0:test-token")
