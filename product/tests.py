import copy
import csv
import datetime
import json
import logging
import os
from collections import OrderedDict
from unittest.mock import patch

from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.test import APITestCase

from product.models import Product, Order, ProductOrder, SummaryReportModel
from product.serializers import ProductSerializer, DisplayOrdersSerializer
from product.tasks import summary_task


def generate_products_data(num):
    result = []
    for i in range(num):
        result.append(
            {
                "product_name": f"{i} product",
                "description": f"{i} product description",
                "stock": (i + 1) * 2,
                "price": i + 10,
                "cost_price": i + 1,
            }
        )
    return result


def default(o):
    if isinstance(o, (datetime.date, datetime.datetime)):
        return o.isoformat()


class PostBulkProductsTest(APITestCase):
    def setUp(self):
        self.url = "http://0.0.0.0:8000/products/bulk_create/"

    def test_missing_products_list(self):
        response = self.client.post(self.url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": "Missing or invalid products list in request json"},
        )

    def test_validation_error(self):
        payload = json.dumps(
            {"products_list": {"product_name": "the only", "stock": 23}}
        )

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": "validation error"},
        )

    def test_correct_operation(self):
        payload_raw = generate_products_data(3)
        payload = json.dumps({"products_list": payload_raw})

        response = self.client.post(self.url, payload, content_type="application/json")

        product_values = Product.objects.all()
        products_db_list = []
        for product in product_values:
            products_db_list.append(
                {
                    "product_name": product.product_name,
                    "description": product.description,
                    "stock": product.stock,
                    "price": product.price,
                    "cost_price": product.cost_price,
                }
            )

        self.assertEqual(response.status_code, 200)
        self.assertSequenceEqual(payload_raw, products_db_list)


class CreateOrderTest(APITestCase):
    def setUp(self):
        self.url = "http://0.0.0.0:8000/orders/create/"
        self.user = User.objects.create_user("admin", "admin23@admin.com", "admin23")
        self.user.save()
        self.user_id = self.user.id

        self.products_setup = ProductSerializer(
            data=generate_products_data(3), many=True
        )
        if self.products_setup.is_valid():
            self.products_setup.save()

    def test_missing_user(self):
        payload = json.dumps(
            {"order": [{"id": 4, "quantity": 49}, {"id": 2, "quantity": 4}]}
        )

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": "Missing or invalid order or user in request json"},
        )

    def test_missing_order(self):
        payload = json.dumps({"user": self.user_id})

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": "Missing or invalid order or user in request json"},
        )

    def test_no_such_user_in_db(self):
        test_id = 2
        payload = json.dumps(
            {
                "order": [{"id": 4, "quantity": 1}, {"id": 2, "quantity": 1}],
                "user": test_id,
            }
        )

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"no such User with id {test_id}"},
        )

    def test_trying_order_nonexistent_product(self):
        products = Product.objects.all()[0:2]
        test_id = 4
        payload = json.dumps(
            {
                "order": [
                    {"id": products[0].id, "quantity": products[0].stock},
                    {"id": test_id, "quantity": 4},
                ],
                "user": self.user_id,
            }
        )

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"no such Product with id {test_id}"},
        )

    def test_trying_order_nonsense_quantity(self):
        products = Product.objects.all()[0:2]
        test_quantity = products[1].stock + 1
        payload = json.dumps(
            {
                "order": [
                    {"id": products[0].id, "quantity": products[0].stock},
                    {"id": products[1].id, "quantity": test_quantity},
                ],
                "user": self.user_id,
            }
        )

        response = self.client.post(self.url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": f"Trying to order more products than in stock {products[1].stock} < {test_quantity}"
            },
        )

    def test_correct_operation(self):
        products = self.products_setup.data[0:2]
        stock_raw_list = copy.deepcopy([products[0]["stock"], products[1]["stock"]])
        test_quantity = [2, 2]

        payload = json.dumps(
            {
                "order": [
                    {"id": products[0]["id"], "quantity": test_quantity[0]},
                    {"id": products[1]["id"], "quantity": test_quantity[1]},
                ],
                "user": self.user_id,
            }
        )

        response = self.client.post(self.url, payload, content_type="application/json")
        unpacked_response = response.json()

        order = Order.objects.all()[0]
        serialized_order = DisplayOrdersSerializer(order).data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(unpacked_response["created_order"], serialized_order)

        self.assertEqual(order.order_status, "stable")
        self.assertEqual(order.user.id, self.user_id)

        test_payload_dict = {
            products[0]["id"]: test_quantity[0],
            products[1]["id"]: test_quantity[1],
        }
        for product in products:
            product_order = order.product_order.get(product__id=product["id"])
            self.assertEqual(product_order.quantity, test_payload_dict[product["id"]])

        products_new = Product.objects.filter(
            id__in=[products[0]["id"], products[1]["id"]]
        )
        stock_new_list = [
            products_new[0].stock + test_quantity[0],
            products_new[1].stock + test_quantity[1],
        ]
        self.assertSequenceEqual(stock_new_list, stock_raw_list)


class UpdateOrderTest(APITestCase):
    def setUp(self):
        self.url_pattern = "http://0.0.0.0:8000/orders/update/"
        self.user = User.objects.create_user("admin", "admin23@admin.com", "admin23")
        self.user.save()
        self.user_id = self.user.id

        self.set_up_num = 2
        self.products_setup = ProductSerializer(
            data=generate_products_data(self.set_up_num), many=True
        )
        if self.products_setup.is_valid():
            self.products_setup.save()

        self.test_quantity_old = [1 for _ in range(self.set_up_num)]
        self.test_quantity_new = [2 for _ in range(self.set_up_num)]

        self.standard_payload = {
            "order": [
                {
                    "id": self.products_setup.data[0]["id"],
                    "quantity": self.test_quantity_new[0],
                },
                {
                    "id": self.products_setup.data[1]["id"],
                    "quantity": self.test_quantity_new[1],
                },
            ],
            "user": self.user_id,
        }

    def create_order(self, status):
        order = Order(user=self.user, order_status=status)
        order.save()

        for i in range(len(self.test_quantity_old)):
            product = Product.objects.get(pk=self.products_setup.data[i]["id"])
            product_order = ProductOrder(
                quantity=self.test_quantity_old[i], product=product, order=order,
            )
            product_order.save()
        return order

    def test_trying_get_nonexistent_order(self):
        wrong_id = 10
        url = f"{self.url_pattern}{wrong_id}/"

        payload = json.dumps(self.standard_payload)

        response = self.client.put(url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": f"Missing or invalid order id {wrong_id} in request"},
        )

    def test_trying_to_update_completed_or_cancelled(self):
        def sub_function(status):
            order = self.create_order(status)
            url = f"{self.url_pattern}{order.id}/"

            payload = json.dumps(self.standard_payload)

            response = self.client.put(url, payload, content_type="application/json")

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json(),
                {"error": "Completed or cancelled orders cannot be changed"},
            )

        sub_function("completed")
        sub_function("cancelled")

    def test_missing_order(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"

        payload = {}

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": "Missing or invalid order in request json"},
        )

    def test_trying_order_nonsense_quantity(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"

        payload_raw = self.standard_payload
        payload_raw["order"][1]["quantity"] = self.products_setup.data[1]["stock"] + 1
        payload = json.dumps(payload_raw)

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": "Trying to order more products than in stock"},
        )

    def test_trying_order_nonexistent_product(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"

        payload_raw = self.standard_payload
        test_id = payload_raw["order"][1]["id"]
        payload_raw["order"][1]["id"] = test_id + 1
        payload = json.dumps(payload_raw)

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": f"Missing product with id {test_id} in request json"},
        )

    def test_correct_operation(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"

        products_old = Product.objects.values("id", "stock")
        products_old_dict = {}
        for product in products_old:
            products_old_dict.update({product["id"]: product["stock"]})

        product_orders_old = ProductOrder.objects.values("quantity", "product")
        product_orders_old_dict = {}
        for product_order in product_orders_old:
            product_orders_old_dict.update(
                {product_order["product"]: product_order["quantity"]}
            )

        payload_raw = self.standard_payload
        payload = json.dumps(payload_raw)

        response = self.client.put(url, payload, content_type="application/json")

        self.assertEqual(response.status_code, 200)
        order_updated = Order.objects.get(pk=order.id)
        serialized_order = DisplayOrdersSerializer(order_updated).data
        unpacked_response = response.json()
        self.assertEqual(unpacked_response["changed_order"], serialized_order)

        order_new = Order.objects.get(pk=order.id)
        db_product_orders = ProductOrder.objects.filter(order=order_new)

        for product_order in payload_raw["order"]:
            try:
                db_product_order = db_product_orders.get(
                    product__id=product_order["id"]
                )
            except Product.DoesNotExist as e:
                self.fail(str(e))
            self.assertEqual(product_order["quantity"], db_product_order.quantity)

            product = Product.objects.get(pk=product_order["id"])
            product_old = products_old_dict[product_order["id"]]
            self.assertEqual(
                product.stock + product_orders_old_dict[product_order["id"]],
                product_old,
            )


class CancelOrderTest(APITestCase):
    def setUp(self):
        self.url_pattern = "http://0.0.0.0:8000/orders/cancel/"
        self.user = User.objects.create_user("admin", "admin23@admin.com", "admin23")
        self.user.save()
        self.user_id = self.user.id

        self.set_up_num = 2
        self.products_setup = ProductSerializer(
            data=generate_products_data(self.set_up_num), many=True
        )
        if self.products_setup.is_valid():
            self.products_setup.save()

        self.test_quantity = [1 for _ in range(self.set_up_num)]

    def create_order(self, status):
        order = Order(user=self.user, order_status=status)
        order.save()

        for i in range(len(self.test_quantity)):
            product = Product.objects.get(pk=self.products_setup.data[i]["id"])
            product_order = ProductOrder(
                quantity=self.test_quantity[i], product=product, order=order,
            )
            product_order.save()
        return order

    def test_trying_get_nonexistent_order(self):
        wrong_id = 10
        url = f"{self.url_pattern}{wrong_id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"No such order with id {wrong_id} in request"},
        )

    def test_trying_to_cancel_completed_order(self):
        order = self.create_order("completed")
        url = f"{self.url_pattern}{order.id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": "Completed orders cannot be cancelled"},
        )

    def test_correct_operation(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"
        old_products = self.products_setup.data
        old_stock = {}
        for product in old_products:
            old_stock.update({product["id"]: product["stock"]})
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        order_cancelled = Order.objects.get(pk=order.id)
        serialized_order = DisplayOrdersSerializer(order_cancelled).data
        unpacked_response = response.json()
        self.assertEqual(unpacked_response["cancelled_order"], serialized_order)

        product_orders = ProductOrder.objects.filter(order=order)
        for unit in product_orders:
            self.assertEqual(
                unit.product.stock - unit.quantity, old_stock[unit.product.id]
            )


class CompleteOrderTest(APITestCase):
    def setUp(self):
        self.url_pattern = "http://0.0.0.0:8000/orders/complete/"
        self.user = User.objects.create_user("admin", "admin23@admin.com", "admin23")
        self.user.save()
        self.user_id = self.user.id

        self.set_up_num = 2
        self.products_setup = ProductSerializer(
            data=generate_products_data(self.set_up_num), many=True
        )
        if self.products_setup.is_valid():
            self.products_setup.save()

        self.test_quantity = [1 for _ in range(self.set_up_num)]

    def create_order(self, status):
        order = Order(user=self.user, order_status=status)
        order.save()

        for i in range(len(self.test_quantity)):
            product = Product.objects.get(pk=self.products_setup.data[i]["id"])
            product_order = ProductOrder(
                quantity=self.test_quantity[i], product=product, order=order,
            )
            product_order.save()
        return order

    def test_trying_get_nonexistent_order(self):
        wrong_id = 10
        url = f"{self.url_pattern}{wrong_id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"No such order with id {wrong_id} in request"},
        )

    def test_trying_to_cancel_completed_order(self):
        order = self.create_order("cancelled")
        url = f"{self.url_pattern}{order.id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": "Cancelled order cannot be completed"},
        )

    def test_correct_operation(self):
        order = self.create_order("stable")
        url = f"{self.url_pattern}{order.id}/"

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        order_completed = Order.objects.get(pk=order.id)
        serialized_order = DisplayOrdersSerializer(order_completed).data
        unpacked_response = response.json()
        self.assertEqual(unpacked_response["completed_order"], serialized_order)

        order_new = Order.objects.get(pk=order.id)
        self.assertEqual(order_new.order_status, "completed")


class SummaryReportViewTest(APITestCase):
    def setUp(self):
        self.url = "http://0.0.0.0:8000/report/create/"
        self.test_file_name = "test_file_etalon"

        tmp_first_date = datetime.datetime.now(tz=timezone.utc) - datetime.timedelta(days=1)
        tmp_second_date = datetime.datetime.now(tz=timezone.utc) + datetime.timedelta(days=1)

        self.first_date = tmp_first_date.isoformat()
        self.second_date = tmp_second_date.isoformat()

        self.standard_payload = {
            "first_date": self.first_date,
            "second_date": self.second_date,
            "name": self.test_file_name,
        }

    def create_summary_file(self):
        cur_path = os.getcwd()
        dir_path = os.path.join(cur_path, "SummaryReports")
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        file_path = os.path.join(dir_path, self.test_file_name)
        with open(file_path, "w") as summary_file:
            writer = csv.writer(summary_file)
            writer.writerow(["product", "revenue", "profit", "sold", "returned"])
            writer.writerow(["test p", 0, 0, 0, 0])

        return file_path

    def create_summary_model(self, file_path):
        new_summary = SummaryReportModel(
            first_date=self.first_date,
            second_date=self.second_date,
            summary_report=file_path,
            name=self.test_file_name,
        )
        new_summary.save()
        return new_summary

    def test_missing_datetime_in_request(self):
        payload = {"name": self.test_file_name}

        response = self.client.post(
            self.url, json.dumps(payload), content_type="application/json"
        )
        self.assertEqual(response.status_code, 400)

        self.assertEqual(
            response.json(), {"error": f"Missing or invalid date in request json"},
        )

    def test_trying_order_existing_summary(self):
        file_path = self.create_summary_file()
        summary = self.create_summary_model(file_path)

        response = self.client.post(
            self.url,
            json.dumps(self.standard_payload, default=default),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "summary": f"summary task named {self.test_file_name} already exists with id {summary.id}"
            },
        )

        self.addCleanup(os.remove, file_path)

    def test_correct_operation(self):

        with patch('product.tasks.summary_task.apply_async') as mock_task:
            response = self.client.post(
                self.url,
                json.dumps(self.standard_payload, default=default),
                content_type="application/json",
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(
                response.json(),
                {
                    "Summary": f"summary task named {self.test_file_name} created, please wait"
                },
            )
            mock_task.assert_called_with(args=[self.first_date, self.second_date, self.test_file_name])


class GetSummarySetUp(APITestCase):
    def setUp(self):
        self.url_pattern = "http://0.0.0.0:8000/report/"

        self.test_file_name = "test_file_etalon"
        self.file_path = self.create_summary_file()

        self.first_date = datetime.datetime.now(tz=timezone.utc)
        self.second_date = self.first_date + datetime.timedelta(days=1)

        self.summary = self.create_summary_model()

        self.addCleanup(os.remove, self.file_path)

    def create_summary_file(self):
        cur_path = os.getcwd()
        dir_path = os.path.join(cur_path, "SummaryReports")
        if not os.path.exists(dir_path):
            os.makedirs(dir_path)

        file_path = os.path.join(dir_path, self.test_file_name)
        with open(file_path, "w") as summary_file:
            writer = csv.writer(summary_file)
            writer.writerow(["product", "revenue", "profit", "sold", "returned"])
            writer.writerow(["test p", 0, 0, 0, 0])

        return file_path

    def create_summary_model(self):
        new_summary = SummaryReportModel(
            first_date=self.first_date,
            second_date=self.second_date,
            summary_report=self.file_path,
            name=self.test_file_name,
        )
        new_summary.save()
        return new_summary


class GetSummaryTest(GetSummarySetUp):
    def test_missing_summary(self):
        test_id = self.summary.id + 1
        url = f"{self.url_pattern}{test_id}/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"No such report with id {test_id}"},
        )

    def test_correct_operation(self):
        url = f"{self.url_pattern}{self.summary.id}/"

        response = self.client.get(url)

        test_string = ""
        with open(self.file_path, "r") as test_file:
            csv_reader = csv.reader(test_file, delimiter=",")
            for row in csv_reader:

                test_string = f'{test_string}{",".join(row)}\r\n'

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.content, test_string.encode("utf8"))


class GetSummaryNameTest(GetSummarySetUp):
    def test_incorrect_query_param(self):
        url = f"{self.url_pattern}name/"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {"error": f"Missing or invalid name in request querystring"},
        )

    def test_missing_summary(self):
        wrong_name = "wrong name"
        url = f"{self.url_pattern}name/?name={wrong_name}"

        response = self.client.get(url)

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(), {"error": f"No such report named {wrong_name}"},
        )

    def test_correct_operation(self):
        url = f"{self.url_pattern}name/?name={self.test_file_name}"

        response = self.client.get(url)

        test_string = ""
        with open(self.file_path, "r") as test_file:
            csv_reader = csv.reader(test_file, delimiter=",")
            for row in csv_reader:
                test_string = f'{test_string}{",".join(row)}\r\n'

        self.assertEqual(response.status_code, 200)

        self.assertEqual(response.content, test_string.encode("utf8"))


class SummuryReportTaskTest(APITestCase):
    def setUp(self):
        self.test_file_name = "test_file_etalon"

        tmp_first_date = datetime.datetime.now(tz=timezone.utc) - datetime.timedelta(days=1)
        tmp_second_date = datetime.datetime.now(tz=timezone.utc) + datetime.timedelta(days=1)

        self.first_date = tmp_first_date.isoformat()
        self.second_date = tmp_second_date.isoformat()

        self.user = User.objects.create_user("admin", "admin23@admin.com", "admin23")
        self.user.save()
        self.user_id = self.user.id

        self.set_up_num = 4
        self.products_setup = ProductSerializer(
            data=generate_products_data(self.set_up_num), many=True
        )
        if self.products_setup.is_valid():
            self.products_setup.save()

        self.test_quantity = [1 for _ in range(self.set_up_num)]
        self.stable_order = self.create_order('stable')
        self.cancelled_order = self.create_order('cancelled')
        self.completed_order = self.create_order('completed')

    def create_order(self, status):
        order = Order(user=self.user, order_status=status)
        order.save()

        for i in range(len(self.test_quantity) - 1):
            product = Product.objects.get(pk=self.products_setup.data[i]["id"])
            product_order = ProductOrder(
                quantity=self.test_quantity[i], product=product, order=order,
            )
            product_order.save()
        return order

    def test_incorrect_input_values(self):
        test_wrong_name = 1
        with self.assertRaises(ValueError):
            summary_task(self.first_date, self.second_date, test_wrong_name)

        test_wrong_date = 'wrong date'
        with self.assertRaises(ValueError):
            summary_task(test_wrong_date, self.second_date, self.test_file_name)
        with self.assertRaises(ValueError):
            summary_task(self.first_date, test_wrong_date, self.test_file_name)

    def test_correct_operation(self):
        test_summary = summary_task(self.first_date, self.second_date, self.test_file_name)

        cur_path = os.getcwd()
        file_path = os.path.join(cur_path, "SummaryReports", self.test_file_name)
        self.assertEqual(test_summary.first_date, self.first_date)
        self.assertEqual(test_summary.second_date, self.second_date)
        self.assertEqual(test_summary.name, self.test_file_name)
        self.assertEqual(test_summary.summary_report, file_path)

        etalon_path = os.path.join(os.path.dirname(__file__), 'test_file_etalon')
        with open(str(test_summary.summary_report), "r") as test_file, open(etalon_path, 'r') as etalon:
            csv_test_file_list = list(csv.reader(test_file, delimiter=","))
            csv_etalon_list = list(csv.reader(etalon, delimiter=","))
            for i in range(len(csv_etalon_list)):
                self.assertEqual(csv_etalon_list[i], csv_test_file_list[i])

        self.addCleanup(os.remove, file_path)
