from django.db import models


class TelegramUser(models.Model):
    user_id = models.IntegerField(unique=True)
    first_name = models.CharField(max_length=255)
    last_name = models.CharField(max_length=255, blank=True, null=True)
    username = models.CharField(max_length=255, blank=True, null=True)
    is_admin = models.BooleanField(default=False)
    is_changer = models.BooleanField(default=False)
    is_super_admin = models.BooleanField(default=False)
    referred_by = models.ForeignKey("Self", on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.username if self.username else f'{self.first_name} {self.last_name}'


class Shop(models.Model):
    name = models.CharField(max_length=255, null=True, blank=True)
    usdt_req = models.CharField(max_length=2555, null=True, blank=True)
    chat_id = models.CharField(max_length=2555)

    def __str__(self):
        return self.name


class ShopReq(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    req = models.ForeignKey("Req", on_delete=models.CASCADE)
    active = models.BooleanField(default=True)


class Invoice(models.Model):
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE)
    amount = models.PositiveIntegerField(null=True, blank=True)
    accepted = models.BooleanField(default=False)
    date = models.DateTimeField(auto_now_add=True)
    withdrawal = models.BooleanField(default=False)
    withdrawal_to_shop = models.BooleanField(default=False)
    withdrawal_to_changer = models.BooleanField(default=False)
    status_message_id = models.CharField(max_length=2555, null=True, blank=True)
    check_message_id = models.CharField(max_length=2555, null=True, blank=True)
    req = models.ForeignKey("Req", on_delete=models.SET_NULL, null=True, blank=True)
    usdt_course = models.FloatField(null=True, blank=True)


class Req(models.Model):
    bank = models.CharField(max_length=255)
    active = models.BooleanField(default=False)
    req_name = models.CharField(max_length=255)
    user = models.ForeignKey(TelegramUser, on_delete=models.CASCADE)
    req = models.CharField(max_length=255)
    kg_req = models.BooleanField(default=False)
    kz_req = models.BooleanField(default=False)
    ref_by = models.ForeignKey(TelegramUser, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.req_name


class WithdrawalToShop(models.Model):
    invoices = models.ManyToManyField(Invoice)


class Course(models.Model):
    kgs_course = models.FloatField(null=True, blank=True)
    kzt_course = models.FloatField(null=True, blank=True)



