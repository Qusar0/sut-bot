#!/usr/bin/env python3
"""Конвертирует ссылку VLESS (vless://...) в конфиг sing-box с локальным SOCKS5.

Нужно, чтобы ходить на sut.ru через разрешённую сеть, если прямой IP сервера заблокирован вузом.
Поддерживает VLESS поверх TCP/WS/gRPC с TLS или Reality (как в Happ: VLESS / TCP / REALITY).

    python scripts/vless_to_singbox.py 'vless://UUID@host:443?security=reality&...#name' singbox/config.json

Ссылку лучше передавать из файла, чтобы не светить секрет в истории команд:
    python scripts/vless_to_singbox.py "$(cat proxy.txt)" singbox/config.json
"""

import json
import sys
from urllib.parse import parse_qs, urlparse

SOCKS_PORT = 1080


def convert(link: str) -> dict:
    link = link.strip()
    if not link.startswith("vless://"):
        raise SystemExit("Ожидалась ссылка vless://… (экспорт одного сервера из Happ)")
    u = urlparse(link)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    if not u.username or not u.hostname or not u.port:
        raise SystemExit("В ссылке нет uuid/хоста/порта — проверьте, что скопирована целиком")

    out: dict = {
        "type": "vless",
        "tag": "proxy-out",
        "server": u.hostname,
        "server_port": u.port,
        "uuid": u.username,
        "network": "tcp",
    }
    if q.get("flow"):
        out["flow"] = q["flow"]

    security = q.get("security", "none")
    if security in ("reality", "tls", "xtls"):
        tls: dict = {
            "enabled": True,
            "server_name": q.get("sni") or q.get("peer") or u.hostname,
            "utls": {"enabled": True, "fingerprint": q.get("fp") or "chrome"},
        }
        if q.get("alpn"):
            tls["alpn"] = q["alpn"].split(",")
        if security == "reality":
            tls["reality"] = {
                "enabled": True,
                "public_key": q.get("pbk", ""),
                "short_id": q.get("sid", ""),
            }
            if not tls["reality"]["public_key"]:
                raise SystemExit("Reality-ссылка без публичного ключа (pbk)")
        out["tls"] = tls

    net = q.get("type", "tcp")
    if net == "ws":
        out["transport"] = {
            "type": "ws",
            "path": q.get("path", "/"),
            "headers": {"Host": q["host"]} if q.get("host") else {},
        }
        out["network"] = "tcp"
    elif net == "grpc":
        out["transport"] = {"type": "grpc", "service_name": q.get("serviceName", "")}

    return {
        "log": {"level": "warn"},
        "inbounds": [{"type": "socks", "tag": "socks-in", "listen": "0.0.0.0", "listen_port": SOCKS_PORT}],
        "outbounds": [out, {"type": "direct", "tag": "direct"}],
        "route": {"final": "proxy-out"},
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    cfg = convert(sys.argv[1])
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"записан {sys.argv[2]} (сервер {cfg['outbounds'][0]['server']}:{cfg['outbounds'][0]['server_port']})")
    else:
        print(text)


if __name__ == "__main__":
    main()
