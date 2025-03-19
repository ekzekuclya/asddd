from collections import deque
from django.db.models import Sum
from models import Invoice, Req

def distribute_amount(amount_to_distribute):
    # Получаем все активные реквизиты
    active_reqs = Req.objects.filter(active=True)

    # Сортируем реквизиты по балансам и лимитам
    reqs_with_balance = []
    for req in active_reqs:
        # Рассчитываем текущий баланс для каждого реквизита
        total_balance = Invoice.objects.filter(req=req, withdrawal=False).aggregate(total=Sum('amount'))['total'] or 0
        daily_balance = Invoice.objects.filter(req=req, accepted=True, withdrawal=False).aggregate(total=Sum('amount'))[
                            'total'] or 0

        # Добавляем реквизит в список с его балансом
        reqs_with_balance.append({
            'req': req,
            'total_balance': total_balance,
            'daily_balance': daily_balance
        })

    # Сортируем реквизиты: сначала с нулевым балансом, затем по наименьшему балансу
    reqs_with_balance.sort(key=lambda x: (x['total_balance'], x['daily_balance']))

    # Переменные для отслеживания суммы, распределяемой между реквизитами
    remaining_amount = amount_to_distribute
    distributed = {}

    for req_info in reqs_with_balance:
        req = req_info['req']
        total_balance = req_info['total_balance']
        daily_balance = req_info['daily_balance']

        # Проверяем максимальный баланс и лимит в день для этого реквизита
        max_balance = 20000  # Максимальный баланс
        max_daily_limit = req.max_limit_per_day  # Лимит в день для конкретного реквизита

        # Проверяем, сколько еще можно добавить на этот реквизит, не нарушив лимиты
        available_balance_space = max_balance - total_balance
        available_daily_space = max_daily_limit - daily_balance

        # Определяем, сколько можно добавить на этот реквизит
        amount_to_add = min(remaining_amount, available_balance_space, available_daily_space)

        if amount_to_add > 0:
            # Заполняем реквизит и обновляем остаток
            distributed[req] = amount_to_add
            remaining_amount -= amount_to_add

            # Если реквизит заполнился (баланс достиг максимума), то больше его не заполняем
            if total_balance + amount_to_add >= max_balance or daily_balance + amount_to_add >= max_daily_limit:
                continue  # Если баланс или лимит в день достигнут, пропускаем его в следующий раз

        # Если остаток суммы еще остался, продолжаем двигаться по реквизитам

    return distributed


# Пример использования
amount = 5230
amount = 1345
result = distribute_amount(amount)