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
        invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=True,
                                                               withdrawal_to_changer=False, usdt_course__isnull=False)

        total_balance = 0
        referral_bonus = 0

        for invoice in invoices:
            amount_in_usdt = invoice.amount / invoice.usdt_course

            if invoice.req.kg_req:
                user_share = amount_in_usdt * 0.06
                referral_share = amount_in_usdt * 0.04

                if user.referred_by:
                    referral_bonus += referral_share
                total_balance += user_share + referral_bonus

            elif invoice.req.kz_req:
                user_share = amount_in_usdt * 0.075
                referral_share = amount_in_usdt * 0.06

                if user.referred_by:
                    referral_bonus += referral_share
                total_balance += user_share + referral_bonus

        total_balance = round(total_balance, 2)  # Округляем до 2 знаков после запятой


        text = (f"👤 *Пользователь*: {user.first_name}\n"
                f"💰 *Баланс*: ${total_balance}")
        await msg.answer(text)



