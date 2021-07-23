import collections
import csv
import logging
import os

from django.db.models import Sum, F

from product.models import Product, ProductOrder, SummaryReportModel
from store_test_task.celery import app


@app.task(bind=True)
def summary_task(self, first_date, second_date, name):
    products = Product.objects.all()
    product_dict = {}

    product_orders_raw = ProductOrder.objects.select_related("product", "order").filter(
        order__updated__range=(first_date, second_date)
    )

    for product in products:
        product_orders = product_orders_raw.filter(product=product.id)

        returned = (
            product_orders.filter(order__order_status="cancelled")
            .aggregate(returned=Sum("quantity"))
        )

        summary_data_dict = product_orders.filter(
            order__order_status="completed"
        ).aggregate(
            sold=Sum("quantity"),
            revenue=Sum("product__price"),
            profit=Sum(F("product__price") - F("product__cost_price")),
        )

        summary_data_dict.update(returned)

        for field in summary_data_dict:
            if not summary_data_dict[field]:
                summary_data_dict[field] = 0

        ord_dict = collections.OrderedDict(
            {
                "revenue": summary_data_dict["revenue"],
                "profit": summary_data_dict["profit"],
                "sold": summary_data_dict["sold"],
                "returned": summary_data_dict["returned"],
            }
        )
        product_dict.update({product.product_name: ord_dict})

    cur_path = os.getcwd()
    dir_path = os.path.join(cur_path, "SummaryReports")
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
                    product_dict[s_product]["returned"],
                ]
            )

        new_summary = SummaryReportModel(
            first_date=first_date,
            second_date=second_date,
            summary_report=file_path,
            name=name,
        )
        new_summary.save()

    return new_summary
