import asyncio

from aiogram import Router, Bot, F
from aiogram.filters import Command, CommandObject, BaseFilter
from aiogram.types import Message, InlineKeyboardButton, ReplyKeyboardMarkup, ChatMemberOwner, ChatMemberAdministrator, \
    CallbackQuery
from django.db.models.functions import Coalesce
from django.db.models import Case, When, Value, IntegerField, Sum
from ..models import TelegramUser, Shop, Invoice, Req, ShopReq, WithdrawalToShop
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from asgiref.sync import sync_to_async


async def totaler(shop):
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

    return total_amount_kgs, total_amount_kzt


async def balancer(user):
    withdrawal_m2m = await sync_to_async(WithdrawalToShop.objects.create)()
    invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=True,
                                                           withdrawal_to_changer=False, usdt_course__isnull=False,
                                                           req__user=user)

    await sync_to_async(withdrawal_m2m.invoices.add)(*invoices)
    total_balance = 0
    referral_bonus = 0
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

        total_balance += user_share

    ref_users = await sync_to_async(TelegramUser.objects.filter)(referred_by=user)
    for ref_user in ref_users:
        invoices = await sync_to_async(Invoice.objects.filter)(accepted=True, withdrawal=True,
                                                               withdrawal_to_changer=False,
                                                               usdt_course__isnull=False,
                                                               req__user=ref_user)
        referral_bonus = 0
        for invoice in invoices:
            amount_in_usdt = invoice.amount / invoice.usdt_course

            if invoice.req.kg_req:
                if ref_user.referred_by == user:
                    user_share = amount_in_usdt * 0.04
                    referral_share = amount_in_usdt * 0.02

            elif invoice.req.kz_req:
                if ref_user.referred_by == user:
                    referral_share = amount_in_usdt * 0.02
            total_balance += referral_share
            await sync_to_async(withdrawal_m2m.invoices.add)(*invoices)
    return total_balance, withdrawal_m2m.id


async def inv_checker(invoice_id, bot, user_id, check_mes_id):
    minutes = 0
    while True:
        invoice = await sync_to_async(Invoice.objects.get)(id=invoice_id)
        if minutes % 20 == 0 and minutes != 0:
            text = f"‼️‼️ Просрочен на {minutes} минут"
            await bot.send_message(chat_id=user_id, text=text, reply_to_message_id=check_mes_id)
        if invoice.req and invoice.amount:
            text = f"+{invoice.amount}"
            builder = InlineKeyboardBuilder()
            builder.add(InlineKeyboardButton(text=f"{invoice.req.req_name}", callback_data="gfdgdfh"))
            await bot.edit_message_text(text=text, chat_id=user_id, message_id=check_mes_id,
                                        reply_markup=builder.as_markup())
            break
        await asyncio.sleep(60)
        minutes += 1
