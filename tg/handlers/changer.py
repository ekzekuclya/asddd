import asyncio

from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.fsm.state import StatesGroup, State
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery, KeyboardButton, ReplyKeyboardRemove
from aiogram.types.reaction_type_emoji import ReactionTypeEmoji
from django.db.models import Q
from aiogram.fsm.context import FSMContext
from django.db.models.functions import Coalesce

from .utils import totaler, balancer
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
async def invoice_changer(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    await state.clear()
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=call.from_user.id)
    invoice = await sync_to_async(Invoice.objects.get)(id=data[1])
    reqs = await sync_to_async(Req.objects.filter)(user=user, active=True)
    builder = InlineKeyboardBuilder()
    for i in reqs:
        builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"accept_{invoice.id}_{data[2]}_{data[3]}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"backing_{data[2]}_{data[3]}_{data[1]}"))
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
    # req = await sync_to_async(Req.objects.get)(id=data[2])
    # invoice.req = req
    # invoice.save()
    await state.set_state(CheckState.awaiting_amount)
    await state.update_data(invoice_id=invoice.id)
    await state.update_data(req_id=data[2])
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="❌ Отмена", callback_data=f"backing_{data[2]}_{data[3]}_{data[1]}"))
    await call.message.edit_text("Введите сумму прихода:", reply_markup=builder.as_markup())


@router.message(CheckState.awaiting_amount)
async def accept_amount(msg: Message, state: FSMContext, bot: Bot):
    amount = int(msg.text)
    data = await state.get_data()
    invoice_id = data.get("invoice_id")
    req_id = data.get("req_id")
    invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
    req = await sync_to_async(Req.objects.get)(id=req_id)
    invoice.req = req
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
    total_amount = await sync_to_async(
        lambda: Invoice.objects.filter(
            accepted=True, withdrawal=False, req=invoice.req, status__isnull=True
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()

    print("TOTAL AMOUNT", total_amount, "REQ", invoice.req.req_name)
    if invoice.req.kz_req:
        if total_amount >= 130000:
            builder = InlineKeyboardBuilder()
            invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=False, req=invoice.req,
                                                                   status__isnull=True)
            withdrawal_to_main = await sync_to_async(WithdrawalToShop.objects.create)()
            await sync_to_async(withdrawal_to_main.invoices.add)(*invoices)
            builder.add(InlineKeyboardButton(text="Вывести", callback_data=f"order_to_withdrawal_{withdrawal_to_main.id}_{total_amount}"))
            await msg.answer(f"На вашем банке {invoice.req.req_name} имеется {total_amount} тенге. \n"
                             f"Нужно вывести!", reply_markup=builder.as_markup())
    if invoice.req.kg_req:
        if total_amount >= 18000:
            builder = InlineKeyboardBuilder()
            invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=False,
                                                                   req=invoice.req, status__isnull=True)
            withdrawal_to_main = await sync_to_async(WithdrawalToShop.objects.create)()
            await sync_to_async(withdrawal_to_main.invoices.add)(*invoices)
            builder.add(
                InlineKeyboardButton(text="Вывести", callback_data=f"order_to_withdrawal_{withdrawal_to_main.id}_{total_amount}"))
            await msg.answer(f"На вашем банке {invoice.req.req_name} имеется {total_amount} сом. \n"
                             f"Нужно вывести!", reply_markup=builder.as_markup())
    await state.clear()


class WithdrawalState(StatesGroup):
    awaiting_photo = State()
    awaiting_accepting = State()


@router.callback_query(F.data.startswith("order_to_withdrawal_"))
async def order_to_withdrawal(call: CallbackQuery, state: FSMContext):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=call.from_user.id)
    if user.is_changer:
        keyboard = ReplyKeyboardMarkup(keyboard=[[KeyboardButton(text="Финиш")]],
                                       resize_keyboard=True)
        await call.message.answer("0xa92dddb34728a9630685c4dc3426d6787e257527\nBEP20")
        await call.message.answer("`Отправьте 2 чека!\nПервый чек курс покупки, второй чек отправки:", reply_markup=keyboard)

        data = call.data.split("_")
        withdrawal_id = data[3]
        amount = data[4]
        await state.update_data(wid=withdrawal_id, total=amount)
        await state.set_state(WithdrawalState.awaiting_photo)


@router.message(WithdrawalState.awaiting_photo)
async def awaiting_withdrawal_photo(msg: Message, state: FSMContext, bot: Bot):
    if msg.photo:
        super_admin = await sync_to_async(TelegramUser.objects.filter)(is_super_admin=True)
        data = await state.get_data()
        wid = data.get("wid")
        total_amount = data.get("total")
        super_admin = super_admin.first()
        withdrawal = await sync_to_async(WithdrawalToShop.objects.get)(id=wid)
        order_msg = await msg.forward(chat_id=super_admin.user_id)
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Принять", callback_data=f"withdrawal_accept_{wid}"))
        builder.add(InlineKeyboardButton(text="Отказ", callback_data=f"dont_accept_{wid}"))
        invoices = withdrawal.invoices.all()
        for i in invoices:
            i.status = "check"
            i.save()
        await bot.send_message(chat_id=super_admin.user_id, text=f"Проверка: {wid}\nСумма: {total_amount}",
                               reply_to_message_id=order_msg.message_id, reply_markup=builder.as_markup())
    if msg.text == "Финиш":
        await state.clear()
        await msg.answer("Чек был отправлен, скоро обновится баланс", reply_markup=ReplyKeyboardRemove())


@router.callback_query(F.data.startswith("withdrawal_accept_"))
async def accept_withdrawal(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    withdrawal_id = data[2]
    await state.set_state(WithdrawalState.awaiting_accepting)
    await state.update_data(wid=withdrawal_id)
    await call.message.answer("Введите пришедшую сумму в $")


@router.callback_query(F.data.startswith("dont_accept_"))
async def do_not_accepting(call: CallbackQuery):
    data = call.data.split("_")
    wid = data[2]
    withdraw = await sync_to_async(WithdrawalToShop.objects.get)(id=wid)
    invoices = withdraw.invoices.all()
    for i in invoices:
        i.status = None
        i.save()
    await call.answer("Сброшено")


@router.message(WithdrawalState.awaiting_accepting)
async def awaiting_accepting(msg: Message, state: FSMContext):
    data = await state.get_data()
    withdrawal_id = data.get("wid")
    withdrawals = await sync_to_async(WithdrawalToShop.objects.get)(id=withdrawal_id)
    try:
        all_sum = float(msg.text)
        invoices = withdrawals.invoices.all()
        total_amount = sum(invoice.amount for invoice in invoices)
        if total_amount > 0:
            usdt_course = total_amount / all_sum
            for invoice in invoices:
                invoice.usdt_course = usdt_course
                invoice.withdrawal = True
                invoice.save()
        await state.clear()
        await msg.answer("Принято!")
    except Exception as e:
        print(e)


@router.callback_query(F.data.startswith("change_"))
async def change_req(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[1])
    shop = await sync_to_async(Shop.objects.get)(id=data[2])
    shop_req = await sync_to_async(ShopReq.objects.get)(shop=shop, active=True)
    if shop_req:
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
        total_kgs = 0
        total_kzt = 0
        for shop_req in shops_req:
            kgs, kzt = await totaler(shop_req.shop)
            total_kgs += kgs
            total_kzt += kzt
            if kgs > 0 or kzt > 0:
                text += (f"🏪 `{shop_req.shop.name}` 🏪\n"
                         f"💰 *Баланс*: `{kgs}` *KGS*, `{kzt}` *T*\n")
                text += f"💶 *Реквизиты*: `{shop_req.req.req_name}`\n\n"
                builder.add(
                    InlineKeyboardButton(text=f"ID {shop_req.shop.id} - {shop_req.shop.name}", callback_data=f"show_shop_{shop_req.shop.id}"))
        builder.adjust(2)
        text += (f"Общий баланс KGS: {total_kgs}\n"
                 f"Общий баланс KZT: {total_kzt}")
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
        changers = await sync_to_async(TelegramUser.objects.filter)(is_changer=True)
        for changer in changers:
            builder.add(InlineKeyboardButton(text=f"{changer.username if changer.username else changer.first_name}",
                                             callback_data=f"changerreq_{changer.user_id}_{shop_req.id}"))

        builder.adjust(1)
        await call.message.answer(f"SHOP ID {shop.id}-{shop.name}", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("changerreq_"))
async def changer_req(call: CallbackQuery):
    data = call.data.split("_")
    changer = await sync_to_async(TelegramUser.objects.get)(user_id=data[1])
    shop_req = await sync_to_async(ShopReq.objects.get)(id=data[2])
    reqs = await sync_to_async(Req.objects.filter)(active=True, user=changer)
    builder = InlineKeyboardBuilder()
    for i in reqs:
        builder.add(InlineKeyboardButton(text=f"{i.req_name}", callback_data=f"tsdafs"))
        builder.add(
            InlineKeyboardButton(text=f"{'🟢' if i == shop_req.req else '🔴'}", callback_data=f"change_{i.id}_{shop_req.shop.id}"))
    builder.adjust(2)
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"shower_shop_{shop_req.shop.id}"))
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("shower_shop_"))
async def shower_shop(call: CallbackQuery):
    data = call.data.split("_")
    shop = await sync_to_async(Shop.objects.get)(id=data[2])
    shop_req = await sync_to_async(ShopReq.objects.filter)(shop=shop, active=True)
    if shop_req:
        shop_req = shop_req.first()
        reqs = await sync_to_async(Req.objects.filter)(active=True)
        builder = InlineKeyboardBuilder()
        changers = await sync_to_async(TelegramUser.objects.filter)(is_changer=True)
        for changer in changers:
            builder.add(InlineKeyboardButton(text=f"{changer.username if changer.username else changer.first_name}",
                                             callback_data=f"changerreq_{changer.user_id}_{shop_req.id}"))

        builder.adjust(1)
        await call.message.edit_text(f"SHOP ID {shop.id}-{shop.name}", reply_markup=builder.as_markup())


@router.message(Command("zp"))
async def zp(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_super_admin:
        changers = await sync_to_async(TelegramUser.objects.filter)(is_changer=True)
        text = "BALANCES\n\n"
        callback_text = "zp"
        total = 0
        for user in changers:
            balance, wid = await balancer(user)
            text += f"{user.username if user.username else user.first_name} - ${balance}\n"
            callback_text += f"_{wid}"
            total += balance
        text += f"\nTOTAL: {round(total, 2)}$"
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Зп выдан", callback_data=callback_text))
        await msg.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("zp"))
async def accepting_zp(call: CallbackQuery):
    data = call.data.split("_")[1:]
    for withdrawal_id in data:
        try:
            withdrawal = await sync_to_async(WithdrawalToShop.objects.get)(id=withdrawal_id)
            for invoice in withdrawal.invoices.all():
                invoice.withdrawal_to_changer = True
                await sync_to_async(invoice.save)()
            await call.message.answer(f"Зарплата выдана для инвойсов из запроса {withdrawal_id}.")
        except WithdrawalToShop.DoesNotExist:
            await call.message.answer(f"Не найден запрос с ID {withdrawal_id}.")
        except Exception as e:
            await call.message.answer(f"Произошла ошибка при обработке запроса {withdrawal_id}: {e}")


@router.message(Command("bc"))
async def changer_balance(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_admin:
        changers = await sync_to_async(TelegramUser.objects.filter)(is_changer=True)
        text = ""
        total_balance_kgs = 0
        total_balance_kzt = 0
        builder = InlineKeyboardBuilder()
        for changer in changers:
            text += f"👤 {changer.username if changer.username else changer.first_name}\n"
            reqs = await sync_to_async(Req.objects.filter)(user=changer, active=True)
            for req in reqs:
                total_amount = await sync_to_async(
                    lambda: Invoice.objects.filter(
                        accepted=True, withdrawal=False, req=req
                    ).aggregate(
                        total=Coalesce(Sum('amount'), 0)
                    )['total']
                )()
                if total_amount > 0:
                    text += f"💳 {req.req_name} {total_amount} {'KGS' if req.kg_req else 'KZT'}\n"
                    if req.kg_req:
                        total_balance_kgs += total_amount
                    if req.kz_req:
                        total_balance_kzt += total_amount
                    builder.add(InlineKeyboardButton(text=f"Запрос {req.req_name}", callback_data=f"zapros_vivod_{req.id}"))
            text += "\n"
        total_balance_usdt_kgs = total_balance_kgs / 90
        total_balance_usdt_kzt = total_balance_kzt / 511
        text += f"\n{total_balance_kgs} KGS - {total_balance_usdt_kgs}$\n"
        text += f"{total_balance_kzt} KZT - {total_balance_usdt_kzt}"

        builder.adjust(1)
        await msg.answer(text, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("zapros_vivod_"))
async def zapros_vivod(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    req = await sync_to_async(Req.objects.get)(id=data[2])
    total_amount = await sync_to_async(
        lambda: Invoice.objects.filter(
            accepted=True, withdrawal=False, req=req
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    builder = InlineKeyboardBuilder()
    if total_amount > 0:
        invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=False, req=req)
        withdrawal_to_main = await sync_to_async(WithdrawalToShop.objects.create)()
        await sync_to_async(withdrawal_to_main.invoices.add)(*invoices)
        builder.add(InlineKeyboardButton(text=f"{req.req_name} ({total_amount})",
                                         callback_data=f"order_to_withdrawal_{withdrawal_to_main.id}_{total_amount}"))
    text = (f"‼️ СРОЧНЫЙ ЗАПРОС НА ВЫВОД!\n"
            f"Сумма: {total_amount}\n"
            f"Реквизиты: {req.req_name}")
    await bot.send_message(chat_id=req.user.user_id, reply_markup=builder.as_markup(), text=text)
    await call.message.answer(f"Срочное сообщение о запросе на вывод отправлено пользователю {req.user.username if req.user.username else req.user.first_name}")


@router.message(Command("ost"))
async def ostatki(msg: Message):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=msg.from_user.id)
    if user.is_super_admin:
        invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal_to_shop=False,
                                                               req__isnull=False)
        if invoices:
            invoices = invoices.order_by('req')
            text = ""
            req_text = ""
            bank_text = ""
            kg_count = 0
            kz_count = 0
            total_kg_sum = 0
            total_kz_sum = 0
            for i in invoices:
                print(i)
                text += f"➖➖➖ 🏬 {i.shop.name} 🏬 ➖➖➖\n"
                if i.req.req != req_text or i.req.bank != bank_text:
                    req_text = i.req.req
                    bank_text = i.req.bank
                    text += f"\n🎟 `{i.req.bank}`\n💳 `{i.req.req}`\n`{i.req.user.username if i.req.user.username else i.req.user.first_name}`\n"
                text += f"🔹 `({i.date.strftime('%d.%m.%Y %H:%M')})` `{i.amount}` {'*₸*' if i.req.kz_req else '*KGS*'} {'✅' if i.withdrawal else '🚫'}\n\n"
                if i.req.kg_req:
                    kg_count += 1
                    total_kg_sum += i.amount
                if i.req.kz_req:
                    kz_count += 1
                    total_kz_sum += i.amount
            if total_kg_sum > 0:
                text += f"\n💷 *Общая сумма KGS*: `{total_kg_sum}` *KGS* \n          `({kg_count} инвойсов)`"
            if total_kz_sum > 0:
                text += f"\n💴 *Общая сумма KZT*: `{total_kz_sum}` *₸* \n          `({kz_count} инвойсов)`"
            max_message_length = 4096
            text_parts = [text[i:i + max_message_length] for i in range(0, len(text), max_message_length)]
            for part in text_parts:
                await msg.answer(part, parse_mode="Markdown")
        else:
            print("NO INVOICES")





