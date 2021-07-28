import copy
import json
import logging
from collections import OrderedDict

from django.contrib.auth.models import User
from rest_framework.test import APITestCase

from product.models import Product, Order, ProductOrder
from product.serializers import ProductSerializer, DisplayOrdersSerializer


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
        stock_raw_list = copy.deepcopy([products[0]['stock'], products[1]['stock']])
        test_quantity = [2, 2]

        payload = json.dumps(
            {
                "order": [
                    {"id": products[0]['id'], "quantity": test_quantity[0]},
                    {"id": products[1]['id'], "quantity": test_quantity[1]},
                ],
                "user": self.user_id,
            }
        )

        response = self.client.post(self.url, payload, content_type="application/json")
        unpacked_response = response.json()

        order = Order.objects.get(pk=1)
        serialized_order = DisplayOrdersSerializer(order).data

        self.assertEqual(response.status_code, 200)
        self.assertEqual(unpacked_response["created_order"], serialized_order)

        self.assertEqual(order.order_status, "stable")
        self.assertEqual(order.user.id, self.user_id)

        test_payload_dict = {
            products[0]['id']: test_quantity[0],
            products[1]['id']: test_quantity[1],
        }
        for product in products:
            product_order = order.product_order.get(product__id=product['id'])
            self.assertEqual(product_order.quantity, test_payload_dict[product['id']])

        products_new = Product.objects.filter(id__range=(0, 2))
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
                    {"id": self.products_setup.data[0]['id'], "quantity": self.test_quantity_new[0]},
                    {"id": self.products_setup.data[1]['id'], "quantity": self.test_quantity_new[1]},
                ],
                "user": self.user_id,
            }

    def create_order(self, status):
        order = Order(
            user=self.user,
            order_status=status
        )
        order.save()

        for i in range(len(self.test_quantity_old)):
            product = Product.objects.get(pk=self.products_setup.data[i]['id'])
            product_order = ProductOrder(
                quantity=self.test_quantity_old[i],
                product=product,
                order=order,
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
            {
                "error": f"Missing or invalid order id {wrong_id} in request"
            },
        )

    def test_trying_to_update_completed_or_cancelled(self):
        def sub_function(status):
            order = self.create_order(status)
            url = f'{self.url_pattern}{order.id}/'

            payload = json.dumps(self.standard_payload)

            response = self.client.put(url, payload, content_type="application/json")

            self.assertEqual(response.status_code, 400)
            self.assertEqual(
                response.json(),
                {
                    "error": 'Completed or cancelled orders cannot be changed'
                },
            )

        sub_function('completed')
        sub_function('cancelled')

    def test_missing_order(self):
        order = self.create_order('stable')
        url = f'{self.url_pattern}{order.id}/'

        payload = {}

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": "Missing or invalid order in request json"
            },
        )

    def test_trying_order_nonsense_quantity(self):
        order = self.create_order('stable')
        url = f'{self.url_pattern}{order.id}/'

        payload_raw = self.standard_payload
        payload_raw['order'][1]['quantity'] = self.products_setup.data[1]['stock'] + 1
        payload = json.dumps(payload_raw)

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": "Trying to order more products than in stock"
            },
        )

    def test_trying_order_nonexistent_product(self):
        order = self.create_order('stable')
        url = f'{self.url_pattern}{order.id}/'

        payload_raw = self.standard_payload
        test_id = payload_raw['order'][1]['id']
        payload_raw['order'][1]['id'] = test_id + 1
        payload = json.dumps(payload_raw)

        response = self.client.put(url, payload, content_type="application/json")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {
                "error": f"Missing product with id {test_id} in request json"
            },
        )

    def test_correct_operation(self):
        order = self.create_order('stable')
        url = f'{self.url_pattern}{order.id}/'

        products_old = Product.objects.values('id', 'stock')
        products_old_dict = {}
        for product in products_old:
            products_old_dict.update({
                product['id']: product['stock']
            })

        product_orders_old = ProductOrder.objects.values('quantity', 'product')
        product_orders_old_dict = {}
        for product_order in product_orders_old:
            product_orders_old_dict.update({
                product_order['product']: product_order['quantity']
            })

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

        for product_order in payload_raw['order']:
            try:
                db_product_order = db_product_orders.get(product__id=product_order['id'])
            except Product.DoesNotExist as e:
                self.fail(str(e))
            self.assertEqual(product_order['quantity'], db_product_order.quantity)

            product = Product.objects.get(pk=product_order['id'])
            product_old = products_old_dict[product_order['id']]
            self.assertEqual(product.stock + product_orders_old_dict[product_order['id']], product_old)
