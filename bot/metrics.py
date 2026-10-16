"""Простые замеры в памяти процесса: длительности операций и счётчики. Смотреть — командой /stats."""

import time
from collections import Counter, defaultdict, deque
from contextlib import contextmanager

_WINDOW = 1000  # сколько последних замеров храним на каждую метрику

started_at = time.time()
durations: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=_WINDOW))
totals: Counter[str] = Counter()
counters: Counter[str] = Counter()
events: dict[str, float] = {}  # имя -> время последнего события (unix), для «последний скан N мин назад»


def observe(name: str, seconds: float) -> None:
    durations[name].append(seconds)
    totals[name] += 1


def inc(name: str, n: int = 1) -> None:
    counters[name] += n


def mark(name: str) -> None:
    """Отметить момент последнего события (используется в мониторинге)."""
    events[name] = time.time()


@contextmanager
def timer(name: str):
    t0 = time.perf_counter()
    try:
        yield
    finally:
        observe(name, time.perf_counter() - t0)


def _pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return values[min(len(values) - 1, int(round(p * (len(values) - 1))))]


def snapshot() -> list[tuple[str, int, float, float, float]]:
    """(имя, всего вызовов, p50 мс, p95 мс, max мс) по последним замерам."""
    rows = []
    for name in sorted(durations):
        v = list(durations[name])
        rows.append((name, totals[name], _pct(v, 0.5) * 1000, _pct(v, 0.95) * 1000, max(v) * 1000))
    return rows
