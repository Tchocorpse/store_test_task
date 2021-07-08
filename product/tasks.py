import collections
import json
import logging

from product.models import Product, ProductOrder, SummaryReportModel
from store_test_task.celery import app


@app.task(bind=True)
def summary_task(self, first_date, second_date):

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

    product_string = json.dumps(product_dict)
    new_summary = SummaryReportModel(first_date=first_date, second_date=second_date, summary_report=product_string)
    new_summary.save()

    logging.warning(new_summary)
