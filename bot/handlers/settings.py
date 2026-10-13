from html import escape

from aiogram import F, Router
from aiogram.types import CallbackQuery, Message

from bot.keyboards.main import Btn, settings_kb
from bot.services.users import get_group, get_user, set_user_fields

router = Router(name="settings")

TOGGLES = {"notify_tomorrow", "notify_week", "notify_changes", "morning_digest", "quiet_hours"}
REMIND_STEPS = [0, 5, 10, 15, 30]  # по кругу: выкл → 5 → 10 → 15 → 30 → выкл


async def _text(user) -> str:
    group = await get_group(user.group_id) if user.group_id else None
    return f"<b>⚙️ Настройки</b>\n\nГруппа: <b>{escape(group.name) if group else '—'}</b>\n\nУведомления:"


@router.message(F.text == Btn.SETTINGS)
async def settings_msg(message: Message) -> None:
    user = await get_user(message.from_user.id)
    await message.answer(await _text(user), reply_markup=settings_kb(user))


@router.callback_query(F.data.startswith("set:") & (F.data != "set:group"))
async def toggle(cb: CallbackQuery) -> None:
    field = cb.data.split(":", 1)[1]
    user = await get_user(cb.from_user.id)
    if field == "remind_minutes":
        cur = user.remind_minutes if user.remind_minutes in REMIND_STEPS else 0
        nxt = REMIND_STEPS[(REMIND_STEPS.index(cur) + 1) % len(REMIND_STEPS)]
        user = await set_user_fields(cb.from_user.id, remind_minutes=nxt)
    elif field in TOGGLES:
        user = await set_user_fields(cb.from_user.id, **{field: not getattr(user, field)})
    else:
        await cb.answer()
        return
    await cb.answer("Сохранено")
    await cb.message.edit_text(await _text(user), reply_markup=settings_kb(user))
