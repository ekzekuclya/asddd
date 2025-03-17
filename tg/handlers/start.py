from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator
from django.db.models import F, ExpressionWrapper, FloatField, Sum
from django.db.models.functions import Coalesce

from ..models import TelegramUser, Req, Invoice, WithdrawalToShop

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
    user_balance = 0
    referral_bonus = 0
    if user.is_changer:
        invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=True,
                                                               withdrawal_to_changer=False, usdt_course__isnull=False,
                                                               req__user=user)

        for invoice in invoices:
            amount_in_usdt = invoice.amount / invoice.usdt_course

            if invoice.req.kg_req:
                if user.referred_by:
                    user_share = amount_in_usdt * 0.04
                    referral_share = amount_in_usdt * 0.02
                else:
                    user_share = amount_in_usdt * 0.06
                    referral_share = 0

            elif invoice.req.kz_req:
                if user.referred_by:
                    user_share = amount_in_usdt * 0.05
                    referral_share = amount_in_usdt * 0.025
                else:
                    user_share = amount_in_usdt * 0.075
                    referral_share = 0

            user_balance += user_share

        ref_users = await sync_to_async(TelegramUser.objects.filter)(referred_by=user)
        for ref_user in ref_users:
            invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=True,
                                                                   withdrawal_to_changer=False,
                                                                   usdt_course__isnull=False,
                                                                   req__user=ref_user)

            for invoice in invoices:
                amount_in_usdt = invoice.amount / invoice.usdt_course

                if invoice.req.kg_req:
                    if ref_user.referred_by == user:
                        user_share = amount_in_usdt * 0.04
                        referral_share = amount_in_usdt * 0.02

                elif invoice.req.kz_req:
                    if ref_user.referred_by == user:
                        referral_share = amount_in_usdt * 0.02
                referral_bonus += referral_share

        total_balance = round(user_balance, 2) + round(referral_bonus, 2)

        text = (f"👤 *Пользователь*: `{user.first_name}`\n"
                    f"💰 *Баланс*: $`{total_balance}`")

        reqs = await sync_to_async(Req.objects.filter)(active=True, user=user)
        builder = InlineKeyboardBuilder()
        for req in reqs:
            total_amount = await sync_to_async(
                lambda: Invoice.objects.filter(
                    accepted=True, withdrawal=False, req=req
                ).aggregate(
                    total=Coalesce(Sum('amount'), 0)
                )['total']
            )()
            if total_amount > 0:
                invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=False, req=req)
                withdrawal_to_main = await sync_to_async(WithdrawalToShop.objects.create)()
                await sync_to_async(withdrawal_to_main.invoices.add)(*invoices)
                builder.add(InlineKeyboardButton(text=f"{req.req_name} ({total_amount})",
                                                 callback_data=f"order_to_withdrawal_{withdrawal_to_main.id}_{total_amount}"))
        builder.adjust(2)
        await msg.answer(text, parse_mode="Markdown", reply_markup=builder.as_markup())



