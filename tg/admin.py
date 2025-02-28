from django.contrib import admin
from .models import TelegramUser, Shop, ShopReq, Invoice, Req


@admin.register(TelegramUser)
class TelegramUserAdmin(admin.ModelAdmin):
    list_display = ['id', 'username' if 'username' else 'None']


@admin.register(Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ['id', 'name']


@admin.register(ShopReq)
class ShopReqAdmin(admin.ModelAdmin):
    list_display = ['id', 'active', 'shop', 'req']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['id']


@admin.register(Req)
class ReqAdmin(admin.ModelAdmin):
    list_display = ['id', 'req_name', 'active', 'kg_req', 'kz_req']