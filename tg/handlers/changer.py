import asyncio

from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery
from aiogram.types.reaction_type_emoji import ReactionTypeEmoji
from django.db.models import Q
from aiogram.fsm.context import FSMContext
from django.db.models.functions import Coalesce

from .utils import totaler
from ..models import TelegramUser, Shop, Invoice, Req, ShopReq, WithdrawalToShop
from django.db.models import Sum
from aiogram.methods import SetMessageReaction
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from asgiref.sync import sync_to_async
from django.utils import timezone
from datetime import timedelta
router = Router()


class CheckState(StatesGroup):
    awaiting_amount = State()
    awaiting_photo = State()


@router.callback_query(F.data.startswith("invoice"))
async def invoice_changer(call: CallbackQuery):
    data = call.data.split("_")
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=call.from_user.id)
    invoice = await sync_to_async(Invoice.objects.get)(id=data[1])
    reqs = await sync_to_async(Req.objects.filter)(user=user, active=True)
    builder = InlineKeyboardBuilder()
    for i in reqs:
        builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"accept_{invoice.id}_{i.id}"))
    builder.adjust(2)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.message(Command("reqs"))
async def my_reqs(msg: Message):
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=msg.from_user.id)
    if user.is_changer:
        reqs = await sync_to_async(Req.objects.filter)(user=user)
        builder = InlineKeyboardBuilder()
        for req in reqs:
            builder.add(InlineKeyboardButton(text=f"{req.req_name}", callback_data=f"user_show_req_{req.id}"))


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
    if amount > 0:
        await bot.set_message_reaction(chat_id=invoice.shop.chat_id, reaction=[reaction],
                                       message_id=invoice.check_message_id)
    if amount == 0:
        reaction = ReactionTypeEmoji(emoji="👎")
        await bot.set_message_reaction(chat_id=invoice.shop.chat_id, reaction=[reaction],
                                       message_id=invoice.check_message_id)
    await bot.set_message_reaction(chat_id=msg.chat.id, reaction=[reaction],
                                   message_id=msg.message_id)
    await bot.edit_message_text(chat_id=invoice.shop.chat_id, text=f"+{amount}", message_id=invoice.status_message_id)
    shop = await sync_to_async(Shop.objects.get)(id=invoice.shop.id)
    now = timezone.now()
    total_amount = await sync_to_async(
        lambda: Invoice.objects.filter(
            shop=shop, accepted=True, withdrawal=False, req=invoice.req
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    if invoice.req.kz_req:
        if total_amount >= 130000:
            await msg.answer(f"На вашем банке {invoice.req.req_name} имеется {total_amount} тенге. \n"
                             f"Нужно вывести!")
    if invoice.req.kg_req:
        if total_amount >= 18000:
            await msg.answer(f"На вашем банке {invoice.req.req_name} имеется {total_amount} сом. \n"
                             f"Нужно вывести!\nВыберите реквизиты, если хотите сменить для:\nId {shop.id}-{shop.name}")
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
    try:
        await bot.unpin_all_chat_messages(chat_id=shop.chat_id)
    except Exception as e:
        print(e)
    new_req_msg = await bot.send_message(chat_id=shop.chat_id, text=f"Актуальные реквзиты:\n\n{req.bank}\n{req.req}")
    await new_req_msg.pin()
    await call.message.answer(f"SHOP:\nID {new_shop_req.shop.id} - {new_shop_req.shop.name}\n{new_shop_req.req.req_name}\n 🟢 Изменен")


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
    text = "Баланс магазинов\n\n"
    if user.is_admin:
        shops_req = await sync_to_async(ShopReq.objects.filter)(active=True)
        builder = InlineKeyboardBuilder()
        for shop_req in shops_req:
            kgs, kzt = await totaler(shop_req.shop)
            if kgs > 0 or kzt > 0:
                text += (f"🏪 `{shop_req.shop.name}` 🏪\n"
                         f"💰 *Баланс*: `{kgs}` *KGS*, `{kzt}` *T*\n")
                text += f"💶 *Реквизиты*: `{shop_req.req.req_name}`\n\n"
                builder.add(
                    InlineKeyboardButton(text=f"ID {shop_req.shop.id} - {shop_req.shop.name}", callback_data=f"show_shop_{shop_req.shop.id}"))
        builder.adjust(2)
        await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("stats"))
async def show_stats(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_admin:
        text = "Отчет за сегодня:\n\n"
        reqs = await sync_to_async(Req.objects.filter)(active=True)
        today = timezone.now().date()
        empty_req = []
        for i in reqs:
            today_invoices = await sync_to_async(Invoice.objects.filter)(date__date=today, req=i)
            today_total_amount = today_invoices.aggregate(Sum('amount'))['amount__sum']
            if today_total_amount:
                text += f"{i.req_name} - {today_total_amount} {'kgs' if i.kg_req else 'T'}\n"
            else:
                empty_req.append(i.req_name)
        if empty_req:
            text += "\nПустые реквизиты:\n"
            for i in empty_req:
                text += f"\n {i}"
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Статистика по магазинам", callback_data="mag_stats"))
        await msg.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data == "mag_stats")
async def show_shop_stats(call: CallbackQuery):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=call.from_user.id)
    if user.is_admin:
        today = timezone.now().date()
        shops = await sync_to_async(ShopReq.objects.filter)(active=True)
        text = f"STATISTICS\n"
        for shopR in shops:
            kg_req_invoices = await sync_to_async(Invoice.objects.filter)(date__date=today, shop=shopR.shop, req__kg_req=True)
            kg_req_turnover = kg_req_invoices.aggregate(Sum('amount'))['amount__sum'] or 0
            kz_req_invoices = await sync_to_async(Invoice.objects.filter)(date__date=today, shop=shopR.shop, req__kg_req=False)
            kz_req_turnover = kz_req_invoices.aggregate(Sum('amount'))['amount__sum'] or 0
            all_kg_req_invoices = await sync_to_async(Invoice.objects.filter)(shop=shopR.shop, req__kg_req=True)
            all_kg_req_turnover = all_kg_req_invoices.aggregate(Sum('amount'))['amount__sum'] or 0
            all_kz_req_invoices = await sync_to_async(Invoice.objects.filter)(shop=shopR.shop, req__kg_req=False)
            all_kz_req_turnover = all_kz_req_invoices.aggregate(Sum('amount'))['amount__sum'] or 0
            total_days = (timezone.now().date() - all_kg_req_invoices.first().date.date()).days if all_kg_req_invoices.exists() else 1

            avg_kg_req_turnover_per_day = all_kg_req_turnover / total_days if total_days > 0 else 0
            avg_kz_req_turnover_per_day = all_kz_req_turnover / total_days if total_days > 0 else 0

            text += f"\n{shopR.shop.name} - Оборот за сегодня:\n"
            text += f"kg_req: {kg_req_turnover} {'kgs' if kg_req_turnover else 'T'}\n"
            text += f"kz_req: {kz_req_turnover} {'kgs' if kz_req_turnover else 'T'}\n"
            text += f"Общий оборот (kg_req): {all_kg_req_turnover} {'kgs' if all_kg_req_turnover else 'T'}\n"
            text += f"Общий оборот (kz_req): {all_kz_req_turnover} {'kgs' if all_kz_req_turnover else 'T'}\n"
            text += f"Средний оборот в день (kg_req): {avg_kg_req_turnover_per_day:.2f} {'kgs' if avg_kg_req_turnover_per_day else 'T'}\n"
            text += f"Средний оборот в день (kz_req): {avg_kz_req_turnover_per_day:.2f} {'kgs' if avg_kz_req_turnover_per_day else 'T'}\n"
        await call.message.answer(text)
            # await asyncio.sleep(1)


@router.message(Command("admin"))
async def admin_panel(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_admin:
        shop_req = await sync_to_async(ShopReq.objects.filter)(active=True)
        builder = InlineKeyboardBuilder()
        for i in shop_req:
            builder.add(InlineKeyboardButton(text=f"ID {i.shop.id} - {i.shop.name}", callback_data=f"show_shop_{i.shop.id}"))
        builder.adjust(1)
        await msg.answer("shops", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("show_shop_"))
async def show_shop(call: CallbackQuery):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[2])
    shop_req = await sync_to_async(ShopReq.objects.filter)(shop=shop, active=True)
    if shop_req:
        shop_req = shop_req.first()
        reqs = await sync_to_async(Req.objects.filter)(active=True)
        builder = InlineKeyboardBuilder()
        for i in reqs:
            builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"tsdafs"))
            builder.add(InlineKeyboardButton(text=f"{'🟢' if i == shop_req.req else '🔴'}", callback_data=f"change_{i.id}_{shop.id}"))
        builder.adjust(2)
        await call.message.answer(f"SHOP ID {shop.id}-{shop.name}", reply_markup=builder.as_markup())







