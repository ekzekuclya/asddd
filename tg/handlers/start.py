from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator
from django.db.models import Q
from django.db.models import Case, When, Value, IntegerField, Sum
from django.db.models.functions import Coalesce

from ..models import TelegramUser, Req, Invoice

from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from asgiref.sync import sync_to_async
router = Router()


@router.message(Command("start"))
async def start_command(msg: Message):
    user, created = await sync_to_async(TelegramUser.objects.get_or_create)(user_id=msg.from_user.id)
    user.username = msg.from_user.username
    user.last_name = msg.from_user.last_name
    user.first_name = msg.from_user.first_name
    user.save()
    await msg.answer("Бот-приемник платежей, для связи пишите @JB_change")
    if user.is_changer:
        builder = InlineKeyboardBuilder()
        req = await sync_to_async(Req.objects.filter)(user=user)
        for i in req:
            total_amount = await sync_to_async(
                lambda: Invoice.objects.filter(accepted=True, withdrawal=False, req=i
                ).aggregate(
                    total=Coalesce(Sum('amount'), 0)
                )['total']
            )()
            builder.add(InlineKeyboardButton(text=f"Вывод из {i.req_name} ({total_amount})", callback_data=f"changer_withdraw_{i.id}"))
        builder.adjust(1)
        await msg.answer("Выберите действие", reply_markup=builder.as_markup())

