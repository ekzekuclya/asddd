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
