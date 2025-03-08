from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator
from django.db.models import F, ExpressionWrapper, FloatField, Sum
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
    if user.is_changer:
        balance = await sync_to_async(lambda: Invoice.objects.filter(accepted=True, withdrawal=True,
                                                                     withdrawal_to_changer=False, usdt_course__isnull=False)
                                      .annotate(amount_in_usdt=ExpressionWrapper(F('amount') * F('usdt_course'),
                                                                                 output_field=FloatField()))
                                      .aggregate(total_in_usdt=Coalesce(Sum('amount_in_usdt'),
                                                                        0))['total_in_usdt'])()

        text = (f"👤 *Пользователь*: {user.first_name}\n"
                f"💰 *Баланс*: ${round(balance, 2)}")
        await msg.answer(text)
        


