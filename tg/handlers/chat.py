import asyncio

from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery
from django.db.models.functions import Coalesce
from django.db.models import Case, When, Value, IntegerField, Sum
from aiogram.fsm.context import FSMContext
from .utils import inv_checker
from ..models import TelegramUser, Shop, Invoice, Req, ShopReq, WithdrawalToShop
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from asgiref.sync import sync_to_async
router = Router()


class IsShopChatID(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_chat_id = str(message.chat.id)
        try:
            shop = await sync_to_async(Shop.objects.get)(chat_id=user_chat_id)
            return True
        except Exception as e:
            print(e)
            return False





class IsShopCheck(BaseFilter):
    async def __call__(self, message: Message) -> bool:
        user_chat_id = str(message.chat.id)
        try:
            shop = await sync_to_async(Shop.objects.get)(chat_id=user_chat_id)
            if message.photo or message.document:
                return True
        except Exception as e:
            print(e)
            return False

@sync_to_async
def get_total_amount(shop):
    return Invoice.objects.filter(shop=shop, accepted=True, withdrawal_to_shop=False).aggregate(Sum('amount'))['amount__sum']


@router.message(Command("reg"))
async def shop_register(msg: Message):
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=msg.from_user.id)
    if user.is_changer:
        new_shop, created = await sync_to_async(Shop.objects.get_or_create)(chat_id=msg.chat.id)
        new_shop.name = msg.chat.title
        new_shop.save()
        await msg.answer(f"Ваш идентификационный номер {new_shop.id}\n"
                         f"Бот готов к работе!")


@router.message(Command("b"))
async def balance(msg: Message):
    if await IsShopChatID()(msg):
        shop = await sync_to_async(Shop.objects.get)(chat_id=msg.chat.id)
        total_amount_kgs = await sync_to_async(
            lambda: Invoice.objects.filter(
                shop=shop, accepted=True, withdrawal_to_shop=False, req__kg_req=True
            ).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
        )()

        total_amount_kzt = await sync_to_async(
            lambda: Invoice.objects.filter(
                shop=shop, accepted=True, withdrawal_to_shop=False, req__kz_req=True
            ).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
        )()
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Запросить вывод", callback_data=f"withdraw_balance_{shop.id}"))
        text = "💰 *Ваш баланс*:\n"
        if total_amount_kzt:
            text += f"💴 `{total_amount_kzt}` *T*\n"
        if total_amount_kgs:
            text += f"💷 `{total_amount_kgs}` *KGS*\n"
        await msg.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.message(Command("r"))
async def get_req(msg: Message, bot: Bot):
    if await IsShopChatID()(msg):
        try:
            await bot.unpin_all_chat_messages(chat_id=msg.chat.id)
        except Exception as e:
            print(e)
        shop = await sync_to_async(Shop.objects.get)(chat_id=msg.chat.id)
        shop_req = await sync_to_async(ShopReq.objects.filter)(shop=shop, active=True)
        if shop_req:
            shop_req = shop_req.first()
            req_msg = await msg.answer(f"Актуальные реквизиты:\n\n{shop_req.req.bank}\n{shop_req.req.req}")
            await req_msg.pin()
        else:
            reqs = await sync_to_async(Req.objects.filter)(active=True)
            min_req = None
            min_invoice_count = float('inf')
            for req_item in reqs:
                invoice_count = await sync_to_async(
                    lambda: Invoice.objects.filter(req=req_item).count())()
                if invoice_count < min_invoice_count:
                    min_invoice_count = invoice_count
                    min_req = req_item
            if min_req:
                await sync_to_async(ShopReq.objects.create)(shop=shop, req=min_req)
                req_msg = await msg.answer(f"Актуальные реквизиты:\n\n{min_req.bank}\n{min_req.req}")
                await req_msg.pin()
            else:
                await msg.answer("Все реквизиты заняты и не доступны для назначения.")


@router.message(Command("unpin"))
async def unpin_last_message(msg: Message, bot):
    await bot.unpin_all_chat_messages(chat_id=msg.chat.id)
    await msg.answer("Последнее закрепленное сообщение откреплено.")


@router.message(IsShopCheck())
async def check(msg: Message, bot: Bot):
    if msg.photo or msg.document:
        shop = await sync_to_async(Shop.objects.get)(chat_id=msg.chat.id)
        shop_req = await sync_to_async(ShopReq.objects.filter)(shop=shop, active=True)
        if shop_req:
            shop_req = shop_req.first()
        status_message = await msg.reply("♻️ _Платеж находится на проверке_", parse_mode="Markdown")
        new_invoice = await sync_to_async(Invoice.objects.create)(shop=shop, status_message_id=status_message.message_id,
                                                                  check_message_id=msg.message_id)
        checking = await msg.forward(chat_id=shop_req.req.user.user_id)
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="✅ Принято",
                                         callback_data=f"invoice_{new_invoice.id}_{msg.chat.id}_{msg.message_id}"))
        builder.add(InlineKeyboardButton(text="❌ Нет",
                                         callback_data=f"repost_{msg.chat.id}_{msg.message_id}_{new_invoice.id}"))
        builder.adjust(1)

        check_op_msg = await bot.send_message(chat_id=shop_req.req.user.user_id, reply_to_message_id=checking.message_id,
                               text=f"На подтверждение", reply_markup=builder.as_markup())
        asyncio.create_task(inv_checker(new_invoice.id, bot, shop_req.req.user.user_id, check_op_msg.message_id))
        new_invoice.save()


@router.callback_query(F.data.startswith("repost_"))
async def repost(call: CallbackQuery, bot: Bot):
    user = await sync_to_async(TelegramUser.objects.get)(user_id=call.from_user.id)
    changers = await sync_to_async(TelegramUser.objects.filter)(is_changer=True)
    data = call.data.split("_")
    builder = InlineKeyboardBuilder()
    if user.is_admin:
        for changer in changers:
            if changer != user:
                builder.add(InlineKeyboardButton(text=f"🔂 {changer.username if changer.username else changer.first_name}",
                                                 callback_data=f"sending_{data[1]}_{data[2]}_{data[3]}_{changer.user_id}"))

    elif user.is_changer:
        admin = await sync_to_async(TelegramUser.objects.filter)(is_admin=True)
        admin = admin.first()
        builder.add(InlineKeyboardButton(text="Подтвердить",
                                         callback_data=f"sending_{data[1]}_{data[2]}_{data[3]}_{admin.user_id}"))
    builder.row(InlineKeyboardButton(text="Назад", callback_data=f"backing_{data[1]}_{data[2]}_{data[3]}"))
    builder.adjust(1)
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("backing_"))
async def backing(call: CallbackQuery, state: FSMContext):
    data = call.data.split("_")
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Принято", callback_data=f"invoice_{data[3]}_{data[1]}_{data[2]}"))
    builder.add(InlineKeyboardButton(text="❌ Нет", callback_data=f"repost_{data[1]}_{data[2]}_{data[3]}"))
    builder.adjust(1)
    await state.clear()
    await call.message.edit_reply_markup(reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("sending_"))
async def sending_to_another_op(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    to_user = data[4]
    to_user_tg = await sync_to_async(TelegramUser.objects.get)(user_id=to_user)
    from_chat_id = data[1]
    message_id = data[2]
    invoice_id = data[3]
    try:
        checking = await bot.forward_message(chat_id=to_user, from_chat_id=from_chat_id, message_id=int(message_id))
    except Exception as e:
        invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
        invoice.status = "deleted"
        invoice.save()
        print(e)
        return
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="✅ Принято", callback_data=f"invoice_{invoice_id}_{from_chat_id}_{message_id}"))
    builder.add(InlineKeyboardButton(text="❌ Нет",
                                     callback_data=f"repost_{from_chat_id}_{message_id}_{invoice_id}"))
    builder.adjust(1)
    check_op_msg = await bot.send_message(chat_id=to_user, reply_to_message_id=checking.message_id,
                           text=f"На подтверждение", reply_markup=builder.as_markup())
    asyncio.create_task(inv_checker(invoice_id, bot, to_user, check_op_msg.message_id))
    await call.message.answer(f"Инвойс отправлен пользователю {to_user_tg.username if to_user_tg.username else to_user_tg.first_name}")


@router.callback_query(F.data.startswith("withdraw_balance_"))
async def withdraw_balance(call: CallbackQuery, bot: Bot):
    shop = await sync_to_async(Shop.objects.get)(chat_id=call.message.chat.id)
    total_amount_kgs = await sync_to_async(
        lambda: Invoice.objects.filter(
            shop=shop, accepted=True, withdrawal_to_shop=False, req__kg_req=True
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    total_amount_kzt = await sync_to_async(
        lambda: Invoice.objects.filter(
            shop=shop, accepted=True, withdrawal_to_shop=False, req__kz_req=True
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    users = await sync_to_async(TelegramUser.objects.filter)(is_super_admin=True)
    await call.message.answer(f"Запрошен вывод:\n"
                              f"💷 {total_amount_kzt}₸ "
                              f"\n 💴 {total_amount_kgs}KGS\n"
                              f"Обработка может занять некоторое время")

    text = f" 🏬 `{shop.name}` 🏬 \n"
    invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, shop=shop, withdrawal_to_shop=False)
    invoices = invoices.order_by('req')
    req_text = ""
    bank_text = ""
    kg_count = 0
    kz_count = 0
    total_kg_sum = 0
    total_kz_sum = 0
    for i in invoices:
        if i.req.req != req_text or i.req.bank != bank_text:
            req_text = i.req.req
            bank_text = i.req.bank
            text += f"\n🎟 `{i.req.bank}`\n💳 `{i.req.req}`\n`{i.req.user.username if i.req.user.username else i.req.user.first_name}`\n"
        text += f"🔹 `({i.date.strftime('%d.%m.%Y %H:%M')})` `{i.amount}` {'*₸*' if i.req.kz_req else '*KGS*'} {'✅' if i.withdrawal else '🚫'}\n"
        if i.req.kg_req:
            kg_count += 1
            total_kg_sum += i.amount
        if i.req.kz_req:
            kz_count += 1
            total_kz_sum += i.amount
    if total_kg_sum > 0:
        usdt_ssum = total_kg_sum / 90
        text += (f"\n💷 *Общая сумма KGS*: `{total_kg_sum}` *KGS* \n          `({kg_count} инвойсов)`\n\n"
                 f"`{total_kg_sum}` / `90` = *{round(usdt_ssum, 2)}*\n"
                 f"`{round(usdt_ssum, 2)}` - `12%` = *{round(usdt_ssum / 100 * 88, 2)}*\n\n")
    if total_kz_sum > 0:
        usdt_tsum = total_kg_sum / 515
        text += (f"\n💴 *Общая сумма KZT*: `{total_kz_sum}` *₸* \n          `({kz_count} инвойсов)`\n\n"
                 f"`{total_kz_sum}` / `511` = *{round(usdt_tsum, 2)}*\n"
                 f"`{round(usdt_tsum, 2)}` - `15%` = *{round(usdt_tsum / 100 * 85, 2)}*")
    if total_kz_sum > 0 and total_kg_sum > 0:
        text += (f"\n{round(usdt_ssum / 100 * 88, 2)} + {round(usdt_tsum / 100 * 85, 2)} = "
                 f"{round(usdt_ssum / 100 * 88, 2) + round(usdt_tsum / 100 * 85, 2)}")
    builder = InlineKeyboardBuilder()
    withdrawal_to_shop = await sync_to_async(WithdrawalToShop.objects.create)()
    for i in invoices:
        await sync_to_async(withdrawal_to_shop.invoices.add)(i)

    builder.add(InlineKeyboardButton(text="Вывод готов",callback_data=f"withdrawal_to_shop_{withdrawal_to_shop.id}"))
    builder.add(InlineKeyboardButton(text="Чек", callback_data=f"kvitto_{withdrawal_to_shop.id}"))
    builder.add(InlineKeyboardButton(text="Обновить", callback_data=f"obnov_{withdrawal_to_shop.id}"))
    max_message_length = 4096
    text_parts = [text[i:i + max_message_length] for i in range(0, len(text), max_message_length)]
    for i in users:
        for part in text_parts:
            try:
                await bot.send_message(chat_id=i.user_id, text=part, reply_markup=builder.as_markup(),
                                       parse_mode="Markdown")
            except Exception as e:
                print(e)
                await bot.send_message(chat_id=i.user_id, text=part, reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("kvitto_"))
async def kvitto_send(call: CallbackQuery):
    data = call.data.split("_")
    withdraw_invs = await sync_to_async(WithdrawalToShop.objects.get)(id=data[1])
    invoices = withdraw_invs.invoices.all()
    invoices_shop = invoices.first()
    text = f" 🏬 `{invoices_shop.shop.name}` 🏬 \n"
    kg_count = 0
    kz_count = 0
    total_kg_sum = 0
    total_kz_sum = 0
    for i in invoices:
        text += f"🔹 `({i.date.strftime('%d.%m.%Y %H:%M')})` `{i.amount}` {'*₸*' if i.req.kz_req else '*KGS*'} {'✅' if i.withdrawal else '🚫'}\n"
        if i.req.kg_req:
            kg_count += 1
            total_kg_sum += i.amount
        if i.req.kz_req:
            kz_count += 1
            total_kz_sum += i.amount
    if total_kg_sum > 0:
        usdt_ssum = total_kg_sum / 90
        text += (f"\n💷 *Общая сумма KGS*: `{total_kg_sum}` *KGS* \n          `({kg_count} инвойсов)`\n\n"
                 f"`{total_kg_sum}` / `90` = *{round(usdt_ssum, 2)}*\n"
                 f"`{round(usdt_ssum, 2)}` - `12%` = *{round(usdt_ssum / 100 * 88, 2)}*\n\n")
    if total_kz_sum > 0:
        usdt_tsum = total_kg_sum / 515
        text += (f"\n💴 *Общая сумма KZT*: `{total_kz_sum}` *₸* \n          `({kz_count} инвойсов)`\n\n"
                 f"`{total_kz_sum}` / `511` = *{round(usdt_tsum, 2)}*\n"
                 f"`{round(usdt_tsum, 2)}` - `15%` = *{round(usdt_tsum / 100 * 85, 2)}*")
    if total_kz_sum > 0 and total_kg_sum > 0:
        text += (f"\n{round(usdt_ssum / 100 * 88, 2)} + {round(usdt_tsum / 100 * 85, 2)} = "
                 f"{round(usdt_ssum / 100 * 88, 2) + round(usdt_tsum / 100 * 85, 2)}")
    builder = InlineKeyboardBuilder()
    builder.add(InlineKeyboardButton(text="Вывод готов", callback_data=f"withdrawal_to_shop_{withdraw_invs.id}"))
    builder.add(InlineKeyboardButton(text="Обновить", callback_data=f"obnov_{withdraw_invs.id}"))
    max_message_length = 4096
    text_parts = [text[i:i + max_message_length] for i in range(0, len(text), max_message_length)]
    if len(text) > 4096:
        for part in text_parts:
            await call.message.answer(text=part, reply_markup=builder.as_markup(), parse_mode="Markdown")
        return
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")


@router.callback_query(F.data.startswith("obnov_"))
async def obnov(call: CallbackQuery, bot: Bot):
    data = call.data.split("_")
    with_id = data[1]
    withdrawal_to_shop = await sync_to_async(WithdrawalToShop.objects.get)(id=with_id)
    invoices = withdrawal_to_shop.invoices.all()
    first_invoice = invoices.first()
    users = await sync_to_async(TelegramUser.objects.filter)(is_super_admin=True)
    text = f"➖➖➖ 🏬 {first_invoice.shop.name} 🏬 ➖➖➖\n"
    invoices = invoices.order_by('req')
    req_text = ""
    bank_text = ""
    kg_count = 0
    kz_count = 0
    total_kg_sum = 0
    total_kz_sum = 0
    for i in invoices:
        if i.req.req != req_text or i.req.bank != bank_text:
            req_text = i.req.req
            bank_text = i.req.bank
            text += f"\n🎟 `{i.req.bank}`\n💳 `{i.req.req}`\n`{i.req.user.username if i.req.user.username else i.req.user.first_name}`\n"
        text += f"🔹 `({i.date.strftime('%d.%m.%Y %H:%M')})` `{i.amount}` {'*₸*' if i.req.kz_req else '*KGS*'} {'✅' if i.withdrawal else '🚫'}\n"
        if i.req.kg_req:
            kg_count += 1
            total_kg_sum += i.amount
        if i.req.kz_req:
            kz_count += 1
            total_kz_sum += i.amount
    if total_kg_sum > 0:
        usdt_ssum = total_kg_sum / 90
        text += (f"\n💷 *Общая сумма KGS*: `{total_kg_sum}` *KGS* \n          `({kg_count} инвойсов)`\n\n"
                 f"`{total_kg_sum}` / `90` = *{round(usdt_ssum, 2)}*\n"
                 f"`{round(usdt_ssum, 2)}` - `12%` = *{round(usdt_ssum / 100 * 88, 2)}*\n\n")
    if total_kz_sum > 0:
        usdt_tsum = total_kg_sum / 515
        text += (f"\n💴 *Общая сумма KZT*: `{total_kz_sum}` *₸* \n          `({kz_count} инвойсов)`\n\n"
                 f"`{total_kz_sum}` / `511` = *{round(usdt_tsum, 2)}*\n"
                 f"`{round(usdt_tsum, 2)}` - `15%` = *{round(usdt_tsum / 100 * 85, 2)}*")
    if total_kz_sum > 0 and total_kg_sum > 0:
        text += (f"\n{round(usdt_ssum / 100 * 88, 2)} + {round(usdt_tsum / 100 * 85, 2)} = "
                 f"{round(usdt_ssum / 100 * 88, 2) + round(usdt_tsum / 100 * 85, 2)}")
    builder = InlineKeyboardBuilder()
    withdrawal_to_shop = await sync_to_async(WithdrawalToShop.objects.create)()
    for i in invoices:
        await sync_to_async(withdrawal_to_shop.invoices.add)(i)

    builder.add(InlineKeyboardButton(text="Вывод готов",callback_data=f"withdrawal_to_shop_{withdrawal_to_shop.id}"))
    builder.add(InlineKeyboardButton(text="Обновить", callback_data=f"obnov_{withdrawal_to_shop.id}"))
    builder.add(InlineKeyboardButton(text="Чек", callback_data=f"kvitto_{withdrawal_to_shop.id}"))
    builder.adjust(1)
    max_message_length = 4096
    text_parts = [text[i:i + max_message_length] for i in range(0, len(text), max_message_length)]
    if len(text) > 4096:
        for i in users:
            for part in text_parts:
                await bot.send_message(chat_id=i.user_id, text=part, reply_markup=builder.as_markup(),
                                       parse_mode="Markdown")
    await call.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
