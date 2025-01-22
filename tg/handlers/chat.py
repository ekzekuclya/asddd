from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery
from django.db.models.functions import Coalesce
from django.db.models import Case, When, Value, IntegerField, Sum
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
        new_shop, created = await sync_to_async(Shop.objects.get_or_create)(chat_id=msg.chat.id, name=msg.chat.title)
        await msg.answer(f"Ваш идентификационный номер {new_shop.id}\n"
                         f"Бот готов к работе!")


@router.message(Command("b"))
async def balance(msg: Message):
    if await IsShopChatID()(msg):
        shop = await sync_to_async(Shop.objects.get)(chat_id=msg.chat.id)
        total_amount = await sync_to_async(
            lambda: Invoice.objects.filter(
                shop=shop, accepted=True, withdrawal_to_shop=False
            ).aggregate(
                total=Coalesce(Sum('amount'), 0)
            )['total']
        )()
        builder = InlineKeyboardBuilder()
        builder.add(InlineKeyboardButton(text="Запросить вывод", callback_data=f"withdraw_balance_{shop.id}"))
        await msg.answer(f"Ваш баланс {total_amount}", reply_markup=builder.as_markup())


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
        builder.add(InlineKeyboardButton(text="✅ Принято", callback_data=f"invoice_{new_invoice.id}"))
        await bot.send_message(chat_id=shop_req.req.user.user_id, reply_to_message_id=checking.message_id, text="На подтверждение", reply_markup=builder.as_markup())


@router.callback_query(F.data.startswith("withdraw_balance_"))
async def withdraw_balance(call: CallbackQuery, bot: Bot):
    shop = await sync_to_async(Shop.objects.get)(chat_id=call.message.chat.id)
    total_amount = await sync_to_async(
        lambda: Invoice.objects.filter(
            shop=shop, accepted=True, withdrawal_to_shop=False
        ).aggregate(
            total=Coalesce(Sum('amount'), 0)
        )['total']
    )()
    users = await sync_to_async(TelegramUser.objects.filter)(is_admin=True)
    await call.message.answer(f"Запрошен вывод {total_amount} ₸")
    text = f"{shop.id}"
    invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, shop=shop, withdrawal_to_shop=False)
    invoices = invoices.order_by('req')
    req_text = ""
    bank_text = ""
    for i in invoices:
        if i.req.req != req_text or i.req.bank != bank_text:
            req_text = i.req.req
            bank_text = i.req.bank
            text += f"\n{i.req.bank}\n{i.req.req}\n\n"
        text += f"({i.date.strftime('%d.%m.%Y %H:%M')}) {i.amount}₸\n"
    builder = InlineKeyboardBuilder()
    withdrawal_to_shop = await sync_to_async(WithdrawalToShop.objects.create)()
    for i in invoices:
        await sync_to_async(withdrawal_to_shop.invoices.add)(i)

    builder.add(InlineKeyboardButton(
        text="Вывод готов",
        callback_data=f"withdrawal_to_shop_{withdrawal_to_shop.id}"
    ))
    for i in users:
        await bot.send_message(chat_id=i.user_id, text=text, reply_markup=builder.as_markup())

