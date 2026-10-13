"""Личный кабинет lk.sut.ru (п. 33, 37–50): привязка, просмотр разделов, отметка на паре."""

import logging
from html import escape

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from bot.keyboards.main import Btn, lk_back, lk_cabinet, lk_link_offer, lk_unlink_confirm
from bot.render import lk as R
from bot.services.lk.client import LkAuthError, LkBlockedError, LkUnavailable
from bot.services.lk.service import LkService, NotLinked

router = Router(name="lk")
log = logging.getLogger(__name__)

UNAVAILABLE = "Личный кабинет сейчас недоступен, попробуйте позже."

RENDERERS = {
    "messages": R.render_messages,
    "files": R.render_files,
    "diary": R.render_diary,
    "record_book": R.render_record_book,
    "orders": R.render_orders,
    "scholarships": R.render_scholarships,
    "rating": R.render_rating,
    "plan": R.render_plan,
    "debts": R.render_debts,
}


class LkLink(StatesGroup):
    login = State()
    password = State()


async def _render_section(name: str, data) -> str:
    if name == "profile":
        return R.render_text("👤 Профиль в ЛК", "\n".join(f"{k}: {v}" for k, v in data.fields.items()))
    if name == "attestation":
        return R.render_text("📊 Аттестация", data)
    return RENDERERS[name](data)


# --- вход в раздел ---


async def _show_cabinet(message: Message, lk: LkService) -> None:
    acc = await lk.account(message.from_user.id)
    if acc is None:
        await message.answer(
            "<b>🏛 Личный кабинет</b>\n\n"
            "Подключите личный кабинет lk.sut.ru — и прямо в боте будут оценки, сообщения преподавателей, "
            "файлы группы, долги, стипендия и отметка на паре.\n\n"
            "Логин и пароль хранятся в зашифрованном виде, их можно удалить в любой момент.",
            reply_markup=lk_link_offer(),
        )
        return
    status = ""
    if acc.status == "auth_failed":
        status = "\n\n⚠️ Пароль не подошёл при последней проверке — переподключите кабинет."
    sync = f"\n<i>обновлено: {acc.last_sync_at:%d.%m %H:%M}</i>" if acc.last_sync_at else ""
    await message.answer(
        f"<b>🏛 Личный кабинет</b>\n{escape(acc.fio)} · {escape(acc.group_name)}{sync}{status}",
        reply_markup=lk_cabinet(),
    )


@router.message(Command("lk"))
@router.message(F.text == Btn.LK)
async def lk_menu(message: Message, lk: LkService) -> None:
    await _show_cabinet(message, lk)


@router.callback_query(F.data == "lk:menu")
async def lk_menu_cb(cb: CallbackQuery, lk: LkService) -> None:
    await cb.answer()
    await _show_cabinet(cb.message, lk)


# --- привязка ---


@router.callback_query(F.data == "lk:link")
async def link_start(cb: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LkLink.login)
    await cb.answer()
    await cb.message.answer("Введите <b>логин</b> от личного кабинета lk.sut.ru (обычно это ваш студенческий e-mail).")


@router.message(StateFilter(LkLink.login), F.text)
async def link_login(message: Message, state: FSMContext) -> None:
    await state.update_data(login=message.text.strip())
    await state.set_state(LkLink.password)
    await message.answer(
        "Теперь введите <b>пароль</b>.\n\n"
        "🔒 Я сразу удалю ваше сообщение с паролем, а сам пароль сохраню в зашифрованном виде."
    )


@router.message(StateFilter(LkLink.password), F.text)
async def link_password(message: Message, state: FSMContext, lk: LkService) -> None:
    password = message.text
    try:  # сразу убираем пароль из чата
        await message.delete()
    except TelegramBadRequest:
        pass
    data = await state.get_data()
    await state.clear()
    login = data.get("login", "")
    wait = await message.answer("Проверяю вход…")
    try:
        profile = await lk.link(message.from_user.id, login, password)
    except LkAuthError:
        await wait.edit_text("❌ Неверный логин или пароль. Попробуйте снова — «🏛 Личный кабинет».")
        return
    except LkBlockedError:
        await wait.edit_text("❌ Вход в ЛК заблокирован. Войдите один раз на сайте lk.sut.ru и повторите.")
        return
    except LkUnavailable:
        await wait.edit_text(UNAVAILABLE)
        return
    except Exception:
        log.exception("привязка ЛК")
        await wait.edit_text(UNAVAILABLE)
        return
    await wait.edit_text(f"✅ Кабинет подключён: <b>{escape(profile.fio)}</b>")
    await _show_cabinet(message, lk)


# --- разделы ---


@router.callback_query(F.data.startswith("lk:sec:"))
async def section(cb: CallbackQuery, lk: LkService) -> None:
    name = cb.data.split(":")[2]
    await cb.answer("Загружаю…")
    try:
        data = await lk.section(cb.from_user.id, name)
    except NotLinked:
        await cb.message.answer("Кабинет не подключён.")
        return
    except LkAuthError:
        await cb.message.answer("⚠️ Пароль не подошёл — переподключите кабинет через «🏛 Личный кабинет».")
        return
    except Exception:
        log.exception("раздел ЛК %s", name)
        await cb.message.answer(UNAVAILABLE)
        return
    await cb.message.answer(await _render_section(name, data), reply_markup=lk_back(), disable_web_page_preview=True)


# --- отметка на паре ---


@router.callback_query(F.data == "lk:att")
async def attendance(cb: CallbackQuery, lk: LkService) -> None:
    await cb.answer("Загружаю расписание…")
    try:
        lessons = await lk.lk_schedule(cb.from_user.id)
    except NotLinked:
        await cb.message.answer("Кабинет не подключён.")
        return
    except Exception:
        log.exception("расписание ЛК")
        await cb.message.answer(UNAVAILABLE)
        return
    if not lessons:
        await cb.message.answer("Сегодня пар нет.", reply_markup=lk_back())
        return
    rows = []
    for l in lessons:
        if l.started:
            label = f"✅ {l.time} {l.subject[:24]}"
            data = "lk:noop"
        elif l.button_ready:
            label = f"✍️ Отметиться: {l.time} {l.subject[:20]}"
            data = f"lk:mark:{l.rasp}"
        else:
            label = f"⏳ {l.time} {l.subject[:24]}"
            data = f"lk:upd:{l.rasp}"
        rows.append([InlineKeyboardButton(text=label[:60], callback_data=data)])
    rows.append([InlineKeyboardButton(text="⬅️ В кабинет", callback_data="lk:menu")])
    await cb.message.answer(
        "<b>✅ Отметка на паре</b>\n<i>Кнопка появляется за 10 минут до начала. "
        "Отметка — действие в ЛК от вашего имени.</i>",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )


@router.callback_query(F.data == "lk:noop")
async def att_noop(cb: CallbackQuery) -> None:
    await cb.answer("Уже отмечено")


@router.callback_query(F.data.startswith("lk:upd:"))
async def att_update(cb: CallbackQuery, lk: LkService) -> None:
    rasp = cb.data.split(":")[2]
    try:
        result = await lk.refresh_button(cb.from_user.id, rasp)
    except Exception:
        await cb.answer(UNAVAILABLE, show_alert=True)
        return
    await cb.answer(result[:190] or "Кнопка пока недоступна", show_alert=True)


@router.callback_query(F.data.startswith("lk:mark:"))
async def att_mark(cb: CallbackQuery, lk: LkService) -> None:
    rasp = cb.data.split(":")[2]
    await cb.answer("Отмечаю…")
    try:
        result = await lk.mark_attendance(cb.from_user.id, rasp)
    except Exception:
        log.exception("отметка ЛК")
        await cb.message.answer(UNAVAILABLE)
        return
    await cb.message.answer(f"✅ {escape(result or 'Готово')}", reply_markup=lk_back())


# --- отключение ---


@router.callback_query(F.data == "lk:unlink")
async def unlink_ask(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.answer(
        "Отключить личный кабинет? Логин, пароль и сохранённые данные ЛК будут удалены.",
        reply_markup=lk_unlink_confirm(),
    )


@router.callback_query(F.data == "lk:unlink:yes")
async def unlink_yes(cb: CallbackQuery, lk: LkService) -> None:
    await lk.unlink(cb.from_user.id)
    await cb.answer("Кабинет отключён")
    try:
        await cb.message.edit_text("🔌 Личный кабинет отключён, данные удалены.")
    except TelegramBadRequest:
        pass
