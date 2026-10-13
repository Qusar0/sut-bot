"""JSON API для Mini App. Данные те же, что в боте; каждый запрос подписан Telegram (initData).

Только чтение расписания и справочников плюс изменение собственных настроек.
"""

import logging
from datetime import date, datetime, timedelta
from pathlib import Path

from aiohttp import web

from bot import metrics
from bot.config import TZ, settings
from bot.render.directory import KINDS, subject_list, subject_stats
from bot.render.text import WEEKDAYS, day_title, kind_short, room_short, week_label
from bot.services.directory import Directory, Slot, room_label
from bot.services.schedule import ScheduleService, monday_of, today
from bot.services.staff import StaffService
from bot.services.sut_public.models import Lesson
from bot.services.users import (
    find_groups,
    get_group,
    get_or_create_user,
    get_user,
    has_actual_consent,
    set_user_fields,
)
from bot.webapp.auth import InitDataError, validate_init_data

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"

KIND_KEY = {"Лекция": "lecture", "Практика": "practice", "Лабораторная": "lab"}
SETTINGS_FIELDS = (
    "notify_tomorrow",
    "notify_week",
    "notify_changes",
    "morning_digest",
    "quiet_hours",
    "remind_minutes",
)


def _lesson(l: Lesson) -> dict:
    kind = kind_short(l.kind)
    return {
        "pair": l.pair,
        "start": l.start,
        "end": l.end,
        "subject": l.subject,
        "kind": kind,
        "kind_key": KIND_KEY.get(kind, "other"),
        "room": room_short(l),
        "teachers": l.teachers_short,
    }


def _slot(s: Slot) -> dict:
    kind = kind_short(s.kind)
    return {
        "pair": s.pair,
        "start": s.start,
        "end": s.end,
        "subject": s.subject,
        "kind": kind,
        "kind_key": KIND_KEY.get(kind, "other"),
        "room": s.room,
        "groups": s.groups,
        "teachers": "; ".join(s.teachers),
    }


def _parse_date(value: str | None, default: date) -> date:
    try:
        return date.fromisoformat(value) if value else default
    except ValueError as e:
        raise web.HTTPBadRequest(text="bad date") from e


@web.middleware
async def auth_middleware(request: web.Request, handler):
    """Пускает в /api/ только запросы с корректной подписью Telegram (или с localhost в dev-режиме)."""
    if not request.path.startswith("/api/"):
        return await handler(request)
    raw = request.headers.get("X-Telegram-Init-Data", "")
    tg_user = None
    if raw:
        try:
            tg_user = validate_init_data(raw, settings.bot_token.get_secret_value())
        except InitDataError:
            raise web.HTTPUnauthorized(text="bad init data") from None
    elif settings.webapp_dev_user and request.remote in ("127.0.0.1", "::1"):
        tg_user = {"id": settings.webapp_dev_user}
    if tg_user is None:
        raise web.HTTPUnauthorized(text="open from Telegram")
    request["tg_id"] = int(tg_user["id"])
    with metrics.timer("приложение: " + (request.path.split("/")[2] or "root")):
        return await handler(request)


async def _need_group(request: web.Request):
    user = await get_user(request["tg_id"])
    if not user or not user.group_id:
        raise web.HTTPConflict(text="no group")
    return user, await get_group(user.group_id)


async def _guard_consent(request: web.Request) -> None:
    if not await has_actual_consent(request["tg_id"]):
        raise web.HTTPForbidden(text="consent required")


def build_webapp(
    app: web.Application, schedule: ScheduleService, directory: Directory, staff: StaffService, lk=None
) -> None:
    app.middlewares.append(auth_middleware)
    r = app.router

    async def index(_: web.Request) -> web.FileResponse:
        return web.FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-cache"})

    async def me(request: web.Request) -> web.Response:
        tg = request["tg_id"]
        user = await get_or_create_user(tg)
        group = await get_group(user.group_id) if user.group_id else None
        return web.json_response(
            {
                "consent": await has_actual_consent(tg),
                "group": {"id": group.id, "name": group.name, "faculty": group.faculty} if group else None,
                "settings": {f: getattr(user, f) for f in SETTINGS_FIELDS},
                "today": today().isoformat(),
            }
        )

    async def set_settings(request: web.Request) -> web.Response:
        body = await request.json()
        fields = {}
        for f in SETTINGS_FIELDS:
            if f in body:
                fields[f] = int(body[f]) if f == "remind_minutes" else bool(body[f])
        if fields:
            await set_user_fields(request["tg_id"], **fields)
        return web.json_response({"ok": True})

    async def set_group(request: web.Request) -> web.Response:
        body = await request.json()
        gid = int(body.get("group_id", 0))
        if await get_group(gid) is None:
            raise web.HTTPBadRequest(text="unknown group")
        await set_user_fields(request["tg_id"], group_id=gid)
        return web.json_response({"ok": True})

    async def groups(request: web.Request) -> web.Response:
        found = await find_groups(request.query.get("q", ""), limit=20)
        return web.json_response({"groups": [{"id": g.id, "name": g.name, "faculty": g.faculty} for g in found]})

    async def day(request: web.Request) -> web.Response:
        from bot.render.image import counter_key, lesson_counters

        await _guard_consent(request)
        _, group = await _need_group(request)
        d = _parse_date(request.query.get("date"), today())
        week = await schedule.week(group.id, d)
        try:
            counters = lesson_counters([x for w in await schedule.semester(group.id) for x in w.lessons])
        except Exception:
            counters = {}

        def day_kinds(day):
            return sorted({KIND_KEY.get(kind_short(x.kind), "other") for x in week.by_day(day)})

        lessons = []
        for l in week.by_day(d):
            item = _lesson(l)
            cnt = counters.get(counter_key(l))
            if cnt:
                item["num"], item["of"] = cnt
            lessons.append(item)
        return web.json_response(
            {
                "date": d.isoformat(),
                "title": day_title(d),
                "week_label": week_label(week),
                "monday": week.monday.isoformat(),
                "strip": [
                    {
                        "date": (week.monday + timedelta(days=i)).isoformat(),
                        "weekday": WEEKDAYS[i][:2],
                        "day": (week.monday + timedelta(days=i)).day,
                        "kinds": day_kinds(week.monday + timedelta(days=i)),
                        "active": (week.monday + timedelta(days=i)) == d,
                    }
                    for i in range(6)
                ],
                "lessons": lessons,
            }
        )

    async def week_view(request: web.Request) -> web.Response:
        await _guard_consent(request)
        _, group = await _need_group(request)
        m = monday_of(_parse_date(request.query.get("date"), today()))
        week = await schedule.week(group.id, m)
        return web.json_response(
            {
                "monday": m.isoformat(),
                "prev": (m - timedelta(days=7)).isoformat(),
                "next": (m + timedelta(days=7)).isoformat(),
                "week_label": week_label(week),
                "days": [
                    {
                        "date": (m + timedelta(days=i)).isoformat(),
                        "title": f"{WEEKDAYS[i]}, {(m + timedelta(days=i)).day}",
                        "lessons": [_lesson(l) for l in week.by_day(m + timedelta(days=i))],
                    }
                    for i in range(6)
                ],
            }
        )

    async def subjects(request: web.Request) -> web.Response:
        await _guard_consent(request)
        _, group = await _need_group(request)
        weeks = await schedule.semester(group.id)
        out = []
        for name in subject_list(weeks):
            st = subject_stats(weeks, name)
            out.append({"name": name, "passed": st.passed, "total": len(st.lessons)})
        return web.json_response({"subjects": out})

    async def subject(request: web.Request) -> web.Response:
        await _guard_consent(request)
        _, group = await _need_group(request)
        weeks = await schedule.semester(group.id)
        name = request.query.get("name", "")
        st = subject_stats(weeks, name)
        now = datetime.now(TZ)
        numbers = {w.monday: w.number for w in weeks}
        return web.json_response(
            {
                "name": name,
                "teachers": st.teachers,
                "passed": st.passed,
                "total": len(st.lessons),
                "by_kind": [
                    {"kind": k, "kind_key": KIND_KEY[k], "passed": st.by_kind[k][0], "total": st.by_kind[k][1]}
                    for k in KINDS
                    if k in st.by_kind
                ],
                "lessons": [
                    {
                        **_lesson(l),
                        "date": l.day.isoformat(),
                        "week": numbers.get(monday_of(l.day)),
                        "done": l.day < now.date() or (l.day == now.date() and l.end <= now.strftime("%H:%M")),
                    }
                    for l in st.lessons
                ],
            }
        )

    async def search(request: web.Request) -> web.Response:
        await _guard_consent(request)
        q = request.query.get("q", "").strip()
        if len(q) < 2:
            return web.json_response({"teachers": [], "rooms": []})
        teachers = [{"id": t.id, "name": t.full_name} for t in directory.search_teachers(q, limit=8)]
        rooms = []
        if any(ch.isdigit() for ch in q) or not teachers:
            rooms = [{"id": x.id, "name": room_label(x.room, x.building)} for x in directory.search_rooms(q, limit=8)]
        return web.json_response({"teachers": teachers, "rooms": rooms})

    async def my_teachers(request: web.Request) -> web.Response:
        """Преподаватели группы за семестр — показываются в поиске по умолчанию."""
        await _guard_consent(request)
        _, group = await _need_group(request)
        weeks = await schedule.semester(group.id)
        subjects: dict[str, set[str]] = {}
        for w in weeks:
            for l in w.lessons:
                for t in l.teachers:
                    subjects.setdefault(t, set()).add(l.subject.split(" (")[0])
        out = []
        for full in sorted(subjects):
            t = directory.teacher_by_name(full)
            if t is not None:
                out.append({"id": t.id, "name": t.full_name, "subjects": ", ".join(sorted(subjects[full]))})
        return web.json_response({"teachers": out})

    async def my_rooms(request: web.Request) -> web.Response:
        """Аудитории группы за семестр, по частоте занятий."""
        from collections import Counter

        await _guard_consent(request)
        _, group = await _need_group(request)
        weeks = await schedule.semester(group.id)
        usage = Counter((l.room, l.building) for w in weeks for l in w.lessons if l.room)
        out = []
        for (room, building), n in usage.most_common(40):
            r_obj = directory.room_by_key(room, building)
            if r_obj is not None:
                out.append({"id": r_obj.id, "name": room_label(room, building), "count": n})
        return web.json_response({"rooms": out})

    async def entity(request: web.Request) -> web.Response:
        await _guard_consent(request)
        kind, eid = request.match_info["kind"], int(request.match_info["id"])
        m = monday_of(_parse_date(request.query.get("date"), today()))
        if kind == "teacher":
            t = directory.teacher(eid)
            if t is None:
                raise web.HTTPNotFound()
            title, slots = t.full_name, await directory.teacher_slots(eid, m, m + timedelta(days=5))
        else:
            room = directory.room(eid)
            if room is None:
                raise web.HTTPNotFound()
            title = "Аудитория " + room_label(room.room, room.building)
            slots = await directory.room_slots(eid, m, m + timedelta(days=5))
        cur = monday_of(today())
        return web.json_response(
            {
                "title": title,
                "monday": m.isoformat(),
                "prev": (m - timedelta(days=7)).isoformat(),
                "next": (m + timedelta(days=7)).isoformat(),
                "partial": m not in (cur, cur + timedelta(days=7)),
                "days": [
                    {
                        "title": f"{WEEKDAYS[i]}, {(m + timedelta(days=i)).day}",
                        "slots": [_slot(s) for s in slots if s.day == m + timedelta(days=i)],
                    }
                    for i in range(6)
                ],
            }
        )

    async def teacher_profile(request: web.Request) -> web.Response:
        await _guard_consent(request)
        t = directory.teacher(int(request.match_info["id"]))
        if t is None:
            raise web.HTTPNotFound()
        prof = await staff.profile(t.full_name)
        if prof is None:
            return web.json_response({"found": False, "name": t.full_name})
        return web.json_response(
            {
                "found": True,
                "name": prof.full_name,
                "position": prof.position,
                "contacts": prof.contacts,
                "interests": prof.interests,
                "education": prof.education,
                "photo": prof.photo,
                "url": prof.url,
            }
        )

    # --- личный кабинет (п. 33, 37–50) ---

    if lk is not None:
        from bot.render import lk as LKR

        SECTION_RENDER = {
            "diary": LKR.render_diary,
            "messages": LKR.render_messages,
            "files": LKR.render_files,
            "record_book": LKR.render_record_book,
            "debts": LKR.render_debts,
            "rating": LKR.render_rating,
            "scholarships": LKR.render_scholarships,
            "orders": LKR.render_orders,
            "plan": LKR.render_plan,
        }

        async def lk_status(request: web.Request) -> web.Response:
            acc = await lk.account(request["tg_id"])
            if acc is None:
                return web.json_response({"linked": False})
            return web.json_response(
                {
                    "linked": True,
                    "fio": acc.fio,
                    "group": acc.group_name,
                    "status": acc.status,
                    "auto_attendance": acc.auto_attendance,
                    "last_sync": acc.last_sync_at.isoformat() if acc.last_sync_at else None,
                    "sections": list(SECTION_RENDER.keys()),
                }
            )

        async def lk_link(request: web.Request) -> web.Response:
            await _guard_consent(request)
            body = await request.json()
            login = (body.get("login") or "").strip()
            password = body.get("password") or ""
            if not login or not password:
                raise web.HTTPBadRequest(text="empty")
            from bot.services.lk.client import LkAuthError, LkBlockedError, LkUnavailable

            try:
                profile = await lk.link(request["tg_id"], login, password)
            except LkAuthError:
                return web.json_response({"ok": False, "error": "Неверный логин или пароль."})
            except LkBlockedError:
                return web.json_response({"ok": False, "error": "Вход в ЛК заблокирован, войдите на сайте."})
            except LkUnavailable:
                return web.json_response({"ok": False, "error": "ЛК недоступен, попробуйте позже."})
            return web.json_response({"ok": True, "fio": profile.fio})

        async def lk_unlink(request: web.Request) -> web.Response:
            await lk.unlink(request["tg_id"])
            return web.json_response({"ok": True})

        async def lk_section(request: web.Request) -> web.Response:
            name = request.query.get("name", "")
            if name not in SECTION_RENDER:
                raise web.HTTPNotFound()
            from bot.services.lk.service import NotLinked

            try:
                data = await lk.section(request["tg_id"], name)
            except NotLinked:
                raise web.HTTPConflict(text="not linked") from None
            except Exception:
                raise web.HTTPServiceUnavailable() from None
            html = SECTION_RENDER[name](data).replace("\n", "<br>")
            return web.json_response({"name": name, "html": html})

        async def lk_diary(request: web.Request) -> web.Response:
            """Дневник, сгруппированный по предметам: для каждого — оценки и пропуски по датам."""
            from bot.services.lk.service import NotLinked

            try:
                marks = await lk.section(request["tg_id"], "diary")
            except NotLinked:
                raise web.HTTPConflict(text="not linked") from None
            except Exception:
                raise web.HTTPServiceUnavailable() from None
            by_subject: dict[str, list] = {}
            for m in marks:
                by_subject.setdefault(m.subject, []).append({"date": m.day.isoformat(), "value": m.value})
            out = []
            for name, entries in sorted(by_subject.items()):
                entries.sort(key=lambda e: e["date"], reverse=True)
                grades = [e["value"] for e in entries if any(ch.isdigit() for ch in e["value"])]
                absences = sum("н" in e["value"].lower() for e in entries)
                out.append({"name": name, "entries": entries, "grades": grades, "absences": absences})
            return web.json_response({"subjects": out})

        async def lk_attendance(request: web.Request) -> web.Response:
            from bot.services.lk.service import NotLinked

            try:
                lessons = await lk.lk_schedule(request["tg_id"])
            except NotLinked:
                raise web.HTTPConflict(text="not linked") from None
            except Exception:
                raise web.HTTPServiceUnavailable() from None
            return web.json_response(
                {
                    "lessons": [
                        {
                            "rasp": l.rasp,
                            "time": l.time,
                            "subject": l.subject,
                            "room": l.room,
                            "started": l.started,
                            "ready": l.button_ready,
                        }
                        for l in lessons
                    ]
                }
            )

        async def lk_mark(request: web.Request) -> web.Response:
            body = await request.json()
            rasp = str(body.get("rasp", ""))
            if not rasp:
                raise web.HTTPBadRequest(text="no rasp")
            try:
                result = await lk.mark_attendance(request["tg_id"], rasp)
            except Exception:
                raise web.HTTPServiceUnavailable() from None
            return web.json_response({"ok": True, "result": result})

        async def lk_auto(request: web.Request) -> web.Response:
            body = await request.json()
            await lk.set_auto(request["tg_id"], bool(body.get("on")))
            return web.json_response({"ok": True})

        r.add_get("/api/lk/status", lk_status)
        r.add_post("/api/lk/link", lk_link)
        r.add_post("/api/lk/unlink", lk_unlink)
        r.add_get("/api/lk/section", lk_section)
        r.add_get("/api/lk/diary", lk_diary)
        r.add_get("/api/lk/attendance", lk_attendance)
        r.add_post("/api/lk/mark", lk_mark)
        r.add_post("/api/lk/auto", lk_auto)

    r.add_get("/", index)
    r.add_get("/app", index)
    r.add_get("/api/me", me)
    r.add_post("/api/settings", set_settings)
    r.add_post("/api/group", set_group)
    r.add_get("/api/groups", groups)
    r.add_get("/api/day", day)
    r.add_get("/api/week", week_view)
    r.add_get("/api/subjects", subjects)
    r.add_get("/api/subject", subject)
    r.add_get("/api/search", search)
    r.add_get("/api/my-teachers", my_teachers)
    r.add_get("/api/my-rooms", my_rooms)
    r.add_get("/api/entity/{kind}/{id}", entity)
    r.add_get("/api/teacher/{id}/profile", teacher_profile)
    if STATIC.exists():
        r.add_static("/static/", STATIC, name="static")
