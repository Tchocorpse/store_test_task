import collections
import csv
import logging
import os

from product.models import Product, ProductOrder, SummaryReportModel
from store_test_task.celery import app


@app.task(bind=True)
def summary_task(self, first_date, second_date, name):
    products = Product.objects.all()
    product_dict = {}
    for product in products:
        product_orders = (
            ProductOrder.objects.filter(product=product.id)
            .filter(order__updated__gte=first_date)
            .filter(order__updated__lte=second_date)
        )

        returned = 0
        cancelled_product_orders = product_orders.filter(order__order_status="cancelled")
        for cancelled_product in cancelled_product_orders:
            returned += cancelled_product.quantity

        revenue = 0
        profit = 0
        sold = 0
        completed_product_orders = product_orders.filter(order__order_status="completed")
        for completed_product in completed_product_orders:
            sold += completed_product.quantity
            revenue += completed_product.product.price
            profit += completed_product.product.price - completed_product.product.cost_price

        ord_dict = collections.OrderedDict({
                    "revenue": str(revenue),
                    "profit": str(profit),
                    "sold": sold,
                    "returned": returned,
                })
        product_dict.update(
            {
                product.product_name: ord_dict
            }
        )

    cur_path = os.getcwd()
    dir_path = os.path.join(cur_path, 'SummaryReports')
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)

    file_path = os.path.join(dir_path, name)
    with open(file_path, "w") as summary_file:
        writer = csv.writer(summary_file)

        writer.writerow(["product", "revenue", "profit", "sold", "returned"])
        for s_product in product_dict:
            writer.writerow(
                [
                    s_product,
                    product_dict[s_product]["revenue"],
                    product_dict[s_product]["profit"],
                    product_dict[s_product]["sold"],
                    product_dict[s_product]['returned'],
                ]
            )

        new_summary = SummaryReportModel(first_date=first_date, second_date=second_date, summary_report=file_path, name=name)
        new_summary.save()

    return new_summary
