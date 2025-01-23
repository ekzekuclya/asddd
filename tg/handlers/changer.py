from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery
from aiogram.types.reaction_type_emoji import ReactionTypeEmoji
from django.db.models import Q
from aiogram.fsm.context import FSMContext
from django.db.models.functions import Coalesce
from ..models import TelegramUser, Shop, Invoice, Req, ShopReq, WithdrawalToShop
from django.db.models import Sum
from aiogram.methods import SetMessageReaction
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from asgiref.sync import sync_to_async
router = Router()


class CheckState(StatesGroup):
    awaiting_amount = State()
    awaiting_photo = State()


@router.callback_query(F.data.startswith("invoice"))
async def invoice_changer(call: CallbackQuery):
    data = call.data.split("_")
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=call.from_user.id)
    invoice = await sync_to_async(Invoice.objects.get)(id=data[1])
    reqs = await sync_to_async(Req.objects.filter)(user=user)
    builder = InlineKeyboardBuilder()
    for i in reqs:
        builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"accept_{invoice.id}_{i.id}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("accept"))
async def accept_invoice(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    invoice = await sync_to_async(Invoice.objects.get)(id=data[1])
    req = await sync_to_async(Req.objects.get)(id=data[2])
    invoice.req = req
    invoice.save()
    await state.set_state(CheckState.awaiting_amount)
    await state.update_data(invoice_id=invoice.id)
    await call.message.answer("Введите сумму прихода:")


@router.message(CheckState.awaiting_amount)
async def accept_amount(msg: Message, state: FSMContext, bot: Bot):
    amount = int(msg.text)
    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
    invoice.amount = amount
    invoice.accepted = True
    invoice.save()
    reaction = ReactionTypeEmoji(emoji="👍")
    await bot.set_message_reaction(chat_id=invoice.shop.chat_id, reaction=[reaction],
                                   message_id=invoice.check_message_id)
    await bot.set_message_reaction(chat_id=msg.chat.id, reaction=[reaction],
                                   message_id=msg.message_id)
    await bot.edit_message_text(chat_id=invoice.shop.chat_id, text=f"+{amount}", message_id=invoice.status_message_id)
    shop = await sync_to_async(Shop.objects.get)(id=invoice.shop.id)
    total_amount = await sync_to_async(
        lambda: Invoice.objects.filter(
            shop=shop, accepted=True, withdrawal=False, req=invoice.req
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    if total_amount >= 90000:
        user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
        builder = InlineKeyboardBuilder()
        reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
        for i in reqs:
            builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"change_{i.id}_{shop.id}"))
        builder.adjust(1)
        await msg.answer(f"На вашем банке {invoice.req.req_name} имеется {total_amount} тенге. \n"
                         f"Нужно вывести!\nВыберите реквизиты, если хотите сменить для:\nId {shop.id}-{shop.name}",
                         reply_markup=builder.as_markup())
    await state.clear()


@router.callback_query(F.data.startswith("change_"))
async def change_req(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[1])
    shop = await sync_to_async(Shop.objects.get)(id=data[2])
    shop_req = await sync_to_async(ShopReq.objects.get)(shop=shop, active=True)
    shop_req.active = False
    shop_req.save()
    new_shop_req = await sync_to_async(ShopReq.objects.create)(shop=shop, req=req, active=True)
    await bot.unpin_all_chat_messages(chat_id=shop.chat_id)
    new_req_msg = await bot.send_message(chat_id=shop.chat_id, text=f"Актуальные реквзиты:\n\n{req.bank}\n{req.req}")
    await new_req_msg.pin()


@router.callback_query(F.data.startswith("changer_withdraw_"))
async def withdraw_to_admin(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[2])
    invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdraw=False, req=req)
    req_text = ""
    bank_text = ""
    text = ""
    for i in invoices:
        i.withdraw = True
        i.save()
        if i.req.req != req_text or i.req.bank != bank_text:
            req_text = i.req.req
            bank_text = i.req.bank
            text += f"\n{i.req.bank}\n{i.req.req}\n\n"
        text += f"({i.date.strftime('%d.%m.%Y %H:%M')}) {i.amount}₸\n"
    await call.message.answer(text)
    await call.message.answer("АДРЕС ДЛЯ ПЕРЕВОДА ВЕР20\n\n`0xe6f7c4d12c348b8d71963e10b947327278d39a61`", parse_mode="Markdown")


@router.callback_query(F.data.startswith("withdrawal_to_shop_"))
async def handle_withdrawal_to_shop(callback_query: CallbackQuery):
    data = callback_query.data.split("_")
    with_id = data[3]
    withdrawal_to_shop = await sync_to_async(WithdrawalToShop.objects.get)(id=with_id)
    invoices = withdrawal_to_shop.invoices.all()
    for i in invoices:
        i.withdrawal = True
        i.withdrawal_to_shop = True
        i.save()
    await callback_query.answer("Вывод успешно завершен.")


@router.message(Command("balance"))
async def show_balance(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_changer:
        reqs = await sync_to_async(Req.objects.filter)(user=user)
        if reqs:
            text = ""
            for req in reqs:
                total_amount = await sync_to_async(
                    lambda: Invoice.objects.filter(req=req, withdrawal=False).aggregate(total_amount=Sum('amount'))
                )()
                text += f"{req.req_name} {total_amount} Т\n"
            await msg.answer(text)


@router.message(Command("admin"))
async def admin_panel(msg: Message):
    shop_req = await sync_to_async(ShopReq.objects.filter)(active=True)
    builder = InlineKeyboardBuilder()
    for i in shop_req:
        builder.add(InlineKeyboardButton(text=f"ID {i.shop.id} - {i.shop.name}", callback_data=f"show_shop_{shop_req.shop.id}"))
    builder.adjust(1)
    await msg.answer("shops", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("show_shop_"))
async def show_shop(call: CallbackQuery):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[2])
    shop_req = await sync_to_async(ShopReq.objects.filter)(shop=shop, active=True)
    reqs = await sync_to_async(Req.objects.filter)(active=True)
    builder = InlineKeyboardBuilder()
    for i in reqs:
        ...


