"""Документы, согласие (п. 69) и удаление данных (п. 70)."""

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

from bot.handlers.start import ask_group, show_main
from bot.keyboards.main import Btn, delete_confirm, docs_kb
from bot.legal import BY_CODE
from bot.services.users import accept_documents, delete_user_data, get_user

router = Router(name="legal")


@router.message(Command("docs"))
@router.message(F.text == Btn.DOCS)
async def docs(message: Message) -> None:
    await message.answer("Документы сервиса:", reply_markup=docs_kb())


@router.callback_query(F.data.startswith("legal:show:"))
async def show_doc(cb: CallbackQuery) -> None:
    doc = BY_CODE.get(cb.data.rsplit(":", 1)[1])
    await cb.answer()
    if doc:
        await cb.message.answer(doc.text, disable_web_page_preview=True)


@router.callback_query(F.data == "legal:accept")
async def accept(cb: CallbackQuery, state: FSMContext) -> None:
    await accept_documents(cb.from_user.id)
    await cb.answer("Спасибо!")
    await cb.message.edit_reply_markup(reply_markup=None)
    user = await get_user(cb.from_user.id)
    if user and user.group_id:
        await show_main(cb.message)
    else:
        await ask_group(cb.message, state)


@router.message(Command("delete"))
async def delete_cmd(message: Message) -> None:
    await message.answer(
        "<b>Удалить все ваши данные?</b>\n\n"
        "Будут удалены группа, настройки, согласия и всё, что бот о вас хранит. "
        "Это действие нельзя отменить. Пользоваться ботом можно будет снова через /start.",
        reply_markup=delete_confirm(),
    )


@router.callback_query(F.data == "del:yes")
async def delete_yes(cb: CallbackQuery, state: FSMContext) -> None:
    await delete_user_data(cb.from_user.id)
    await state.clear()
    await cb.answer()
    await cb.message.edit_text("Все ваши данные удалены.")
    await cb.message.answer("Чтобы начать заново — /start", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data == "del:no")
async def delete_no(cb: CallbackQuery) -> None:
    await cb.answer()
    await cb.message.edit_text("Удаление отменено.")
