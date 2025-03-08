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
                                                               withdrawal_to_changer=False, usdt_course__isnull=False,
                                                               req__user=user)

        total_balance = 0  # Общий баланс пользователя
        referral_bonus = 0  # Реферальный бонус для пригласившего пользователя

        for invoice in invoices:
            # Преобразуем сумму инвойса в доллары
            amount_in_usdt = invoice.amount / invoice.usdt_course

            # Рассчитываем долю пользователя
            if invoice.req.kg_req:  # Если тип запроса kg_req
                if user.referred_by:  # Если пользователь пришел по рефералу
                    user_share = amount_in_usdt * 0.04  # 4% для пришедшего
                    referral_share = amount_in_usdt * 0.02  # 2% для того, кто пригласил
                else:  # Если пользователь не пришел по рефералу
                    user_share = amount_in_usdt * 0.06  # 6% для обычного пользователя
                    referral_share = 0  # Реферального бонуса нет

            elif invoice.req.kz_req:  # Если тип запроса kz_req
                if user.referred_by:  # Если пользователь пришел по рефералу
                    user_share = amount_in_usdt * 0.06  # 6% для пришедшего
                    referral_share = amount_in_usdt * 0.02  # 2% для того, кто пригласил
                else:  # Если пользователь не пришел по рефералу
                    user_share = amount_in_usdt * 0.075  # 7.5% для обычного пользователя
                    referral_share = 0  # Реферального бонуса нет

            total_balance += user_share  # Добавляем долю пользователя
            if user.referred_by:
                total_balance += referral_share  # Добавляем бонус для пригласившего

        total_balance = round(total_balance, 2)  # Округляем до 2 знаков после запятой

        # Формируем сообщение для ответа
        text = (f"👤 *Пользователь*: `{user.first_name}`\n"
                f"💰 *Баланс*: $`{total_balance}`")
        await msg.answer(text, parse_mode="Markdown")



