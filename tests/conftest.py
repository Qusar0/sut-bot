import os
import tempfile
from pathlib import Path

# До импорта bot.*: временная база и фиктивный токен, чтобы тесты не трогали data/bot.db
_tmp = Path(tempfile.mkdtemp()) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_tmp.as_posix()}"
os.environ.setdefault("BOT_TOKEN", "0:test-token")
