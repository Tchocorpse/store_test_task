from enum import Enum

from django.contrib.auth.models import User
from django.db import models
from django.db.models import AutoField, CharField, IntegerField, TextField, DecimalField


class OrderStatusEnum(Enum):
    stable = "stable"
    cancelled = "cancelled"
    completed = "completed"


class Product(models.Model):
    id = AutoField(primary_key=True)

    product_name = CharField(
        verbose_name="Наименование", max_length=255, blank=False, null=False
    )
    description = TextField(verbose_name="Описание", blank=True, null=True)

    stock = IntegerField(verbose_name="Остаток", blank=False, null=False)
    price = DecimalField(
        verbose_name="Цена", max_digits=7, decimal_places=2, blank=False, null=False
    )
    cost_price = DecimalField(
        verbose_name="Себестоимость",
        max_digits=7,
        decimal_places=2,
        blank=False,
        null=False,
    )

    created = models.DateTimeField(auto_now_add=True, blank=False, null=False)
    updated = models.DateTimeField(auto_now=True, blank=False, null=False)


class Order(models.Model):
    id = AutoField(primary_key=True)

    user = models.ForeignKey(User, on_delete=models.CASCADE)
    order_status = CharField(
        verbose_name="Статус заказа",
        max_length=10,
        choices=[(tag.name, tag.value) for tag in OrderStatusEnum],
        blank=False,
        null=False,
    )

    created = models.DateTimeField(auto_now_add=True, blank=False, null=False)
    updated = models.DateTimeField(auto_now=True, blank=False, null=False)


class ProductOrder(models.Model):
    id = AutoField(primary_key=True)

    quantity = IntegerField(verbose_name="Количество", blank=False, null=False)

    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    order = models.ForeignKey(Order, related_name="product_order", on_delete=models.CASCADE)


class SummaryReportModel(models.Model):
    id = AutoField(primary_key=True)

    name = CharField(verbose_name="Имя Отчета", max_length=255, blank=True, null=True, unique=True)
    first_date = models.DateTimeField(blank=False, null=False)
    second_date = models.DateTimeField(blank=False, null=False)

    created = models.DateTimeField(auto_now_add=True, blank=False, null=False)
    updated = models.DateTimeField(auto_now=True, blank=False, null=False)

    summary_report = models.FileField(verbose_name="CSV файл отчета", upload_to='SummaryReports/')
