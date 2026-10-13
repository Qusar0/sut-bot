"""Старт, выбор и смена группы (п. 10)."""

from html import escape

from aiogram import F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot.keyboards.main import consent_kb, groups_choice, main_menu
from bot.middlewares import CONSENT_TEXT
from bot.services.users import find_groups, get_group, get_or_create_user, has_actual_consent, set_user_fields

router = Router(name="start")


class GroupSelect(StatesGroup):
    waiting = State()


async def ask_group(message: Message, state: FSMContext) -> None:
    await state.set_state(GroupSelect.waiting)
    await message.answer(
        "Напишите номер вашей группы, например <code>ИСТ-2633</code>.",
        reply_markup=ReplyKeyboardRemove(),
    )


async def show_main(message: Message, text: str = "Главное меню") -> None:
    await message.answer(text, reply_markup=main_menu())


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    user = await get_or_create_user(message.from_user.id)
    if not await has_actual_consent(message.from_user.id):
        await message.answer(
            "Привет! Я показываю расписание СПбГУТ и присылаю уведомления.\n\n" + CONSENT_TEXT,
            reply_markup=consent_kb(),
        )
        return
    if not user.group_id:
        await ask_group(message, state)
        return
    await state.clear()
    await show_main(message)


@router.message(Command("change"))
async def change(message: Message, state: FSMContext) -> None:
    await ask_group(message, state)


@router.callback_query(F.data == "set:group")
async def change_cb(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await ask_group(cb.message, state)


@router.message(StateFilter(GroupSelect.waiting), F.text)
async def group_entered(message: Message, state: FSMContext) -> None:
    groups = await find_groups(message.text)
    if not groups:
        await message.answer(
            "Не нашёл такую группу. Проверьте номер и попробуйте ещё раз, например <code>ИСТ-2633</code>."
        )
        return
    if len(groups) == 1:
        await _set_group(message, state, groups[0].id)
        return
    await message.answer("Нашлось несколько групп, выберите свою:", reply_markup=groups_choice(groups))


@router.callback_query(StateFilter(GroupSelect.waiting), F.data.startswith("grp:"))
async def group_chosen(cb: CallbackQuery, state: FSMContext) -> None:
    await cb.answer()
    await cb.message.edit_reply_markup(reply_markup=None)
    await _set_group(cb.message, state, int(cb.data.split(":")[1]), tg_id=cb.from_user.id)


async def _set_group(message: Message, state: FSMContext, group_id: int, tg_id: int | None = None) -> None:
    group = await get_group(group_id)
    await set_user_fields(tg_id or message.from_user.id, group_id=group_id)
    await state.clear()
    await show_main(message, f"Готово, ваша группа — <b>{escape(group.name)}</b> ({escape(group.faculty)}).")
