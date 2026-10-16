"""Локальный запуск Bonch Free: бот дома + обратный ssh-туннель на VPS-витрину (Хельсинки).

Бот крутится дома (sut.ru по домашнему РФ-IP, Telegram через VPN) и отдаёт /app на
localhost:8080. Отдельный поток-супервизор держит обратный туннель на VPS:
    ssh -R 8080:localhost:8080 <vps>
VPS'ный Caddy (46.38.156.87.sslip.io, Let's Encrypt) проксирует публичный HTTPS в этот
туннель → к домашнему боту. Адрес стабильный, поэтому PUBLIC_URL фиксированный и кнопку
Mini App бот ставит сам один раз. Туннель упал → супервизор переподнимает.

Перезапуск самого бота делает run-bot.bat.
"""

import os
import subprocess
import sys
import threading
import time

ROOT = os.path.dirname(os.path.abspath(__file__))
PY = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
PUBLIC_URL = "https://46.38.156.87.sslip.io"
VPS = "sut-bot"  # алиас из ~/.ssh/config: deploy@46.38.156.87 по ключу
SSH = [
    "ssh", "-N",
    "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=15",
    "-o", "ServerAliveCountMax=3", "-o", "ExitOnForwardFailure=yes",
    "-R", "8080:localhost:8080", VPS,
]


def tunnel_supervisor(stop: threading.Event) -> None:
    log = os.path.join(ROOT, "data", "tunnel.log")
    os.makedirs(os.path.dirname(log), exist_ok=True)
    while not stop.is_set():
        with open(log, "w", encoding="utf-8", errors="replace") as f:
            proc = subprocess.Popen(SSH, stdout=f, stderr=subprocess.STDOUT)
        while proc.poll() is None and not stop.is_set():
            time.sleep(2)
        try:
            proc.terminate()
        except Exception:  # noqa: BLE001
            pass
        if not stop.is_set():
            time.sleep(3)  # переподнять туннель


def main() -> int:
    stop = threading.Event()
    threading.Thread(target=tunnel_supervisor, args=(stop,), daemon=True).start()
    env = dict(os.environ, PUBLIC_URL=PUBLIC_URL, USE_WEBHOOK="false")
    try:
        return subprocess.run([PY, "-X", "utf8", "-m", "bot"], cwd=ROOT, env=env).returncode
    finally:
        stop.set()


if __name__ == "__main__":
    sys.exit(main())
