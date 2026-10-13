#!/usr/bin/env python3
"""Делает из полного Xray-конфига (экспорт «Копировать JSON» из Happ) минимальный прокси-конфиг.

Берёт рабочий outbound как есть (VLESS/Reality и т. п.) и открывает локальный SOCKS5 на 0.0.0.0:1080,
чтобы бот рядом в docker-compose мог ходить через него на sut.ru. Лишние dns/routing/metrics убираются —
через этот прокси идёт только трафик к sut.ru, маршрутизация не нужна.

    python3 scripts/make_xray_proxy.py proxy.json xray/config.json
"""

import json
import sys

SOCKS_PORT = 1080


def build(src: dict) -> dict:
    outs = src.get("outbounds") or []
    proxy = next((o for o in outs if o.get("tag") == "proxy"), None)
    if proxy is None:
        proxy = next(
            (o for o in outs if o.get("protocol") in ("vless", "vmess", "trojan", "shadowsocks")),
            None,
        )
    if proxy is None:
        raise SystemExit("В конфиге не найден рабочий outbound (vless/vmess/trojan/shadowsocks)")
    proxy = {**proxy, "tag": "proxy"}
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": SOCKS_PORT,
                "protocol": "socks",
                "settings": {"auth": "noauth", "udp": True},
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
                "tag": "socks",
            }
        ],
        "outbounds": [proxy, {"protocol": "freedom", "tag": "direct"}],
    }


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        src = json.load(f)
    cfg = build(src)
    text = json.dumps(cfg, ensure_ascii=False, indent=2)
    addr = cfg["outbounds"][0].get("settings", {}).get("vnext", [{}])[0].get("address", "?")
    if len(sys.argv) >= 3:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(text + "\n")
        print(f"записан {sys.argv[2]} (сервер прокси {addr})")
    else:
        print(text)


if __name__ == "__main__":
    main()
