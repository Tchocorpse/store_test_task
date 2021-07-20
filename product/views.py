import logging

from django.contrib.auth.models import User
from django.http import JsonResponse
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import generics, status
from rest_framework.decorators import api_view, action
from rest_framework.views import APIView

from product.models import Product, Order, ProductOrder, SummaryReportModel
from product.serializers import (
    ProductSerializer,
    UpdateProductSerializer,
    DisplayOrdersSerializer,
    SummaryReportSerializer,
)
from product.tasks import summary_task


class GetProducts(generics.ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class PostProducts(generics.CreateAPIView):
    serializer_class = ProductSerializer


class UpdateProducts(generics.UpdateAPIView):
    queryset = Product.objects.all()
    lookup_field = "pk"
    serializer_class = UpdateProductSerializer


class DisplayOrders(generics.ListAPIView):
    queryset = Order.objects.all()
    serializer_class = DisplayOrdersSerializer


order_request_schema = openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "order": openapi.Schema(
                    type=openapi.TYPE_OBJECT,
                    description="list of json",
                    properties={
                        "id": openapi.Schema(
                            type=openapi.TYPE_NUMBER, description="product id"
                        ),
                        "quantity": openapi.Schema(
                            type=openapi.TYPE_NUMBER,
                            description="quantity of product order",
                        ),
                    },
                ),
                "user": openapi.Schema(
                    type=openapi.TYPE_NUMBER, description="id of user making order"
                ),
            },
        )


class CreateOrder(APIView):
    @swagger_auto_schema(
        method="post",
        request_body=order_request_schema,
        responses={
            status.HTTP_200_OK: DisplayOrdersSerializer,
        },
    )
    @api_view(["POST"])
    def post(self, request):
        try:
            received_order = request.data["order"]
            received_user = request.data["user"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid order or user in request json"},
                status=400,
            )

        try:
            user = User.objects.get(pk=received_user)
        except User.DoesNotExist:
            return JsonResponse(
                {"error": f"no such User with id {received_user}"}, status=400
            )

        products_list = []
        product_order_list = []
        order = Order(user=user, order_status="stable")
        for unit in received_order:
            product = self.retrieve_product(unit["id"])
            products_list.append(product)

            p_quantity = unit["quantity"]
            if p_quantity > product.stock:
                return JsonResponse(
                    {"error": "Trying to order more products than in stock"}, status=400
                )

            product.stock = product.stock - p_quantity
            product_order = ProductOrder(
                quantity=p_quantity, product=product, order=order
            )
            product_order_list.append(product_order)

        order.save()
        self.save_models(products_list)
        self.save_models(product_order_list)

        serialized_data = DisplayOrdersSerializer(order).data
        return JsonResponse({"created_order": serialized_data}, status=200)

    def retrieve_product(self, p_id):
        try:
            product = Product.objects.get(pk=p_id)
        except Product.DoesNotExist:
            return JsonResponse(
                {"error": f"no such Product with id {p_id}"}, status=400
            )
        return product

    def save_models(self, model_list):
        for model in model_list:
            model.save()


class UpdateOrder(APIView):
    @swagger_auto_schema(
        method="put",
        request_body=order_request_schema,
        responses={
            status.HTTP_200_OK: DisplayOrdersSerializer,
        },
    )
    @action(detail=False, methods=['PUT'])
    def put(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return JsonResponse(
                {"error": f"Missing or invalid order id {pk} in request"}, status=400
            )

        if (order.order_status == "completed") or (order.order_status == "completed"):
            return JsonResponse(
                {"error": f"Completed or cancelled orders cannot be changed"},
                status=400,
            )

        try:
            new_order_products = request.data["order"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid order in request json"}, status=400
            )

        new_order_dict = self.reorder_by_id(new_order_products)
        product_order_qs = ProductOrder.objects.filter(order=pk)

        products_list = []
        product_order_list = []
        for product_order in product_order_qs:
            product = product_order.product
            try:
                new_quantity = new_order_dict[product.id]
            except KeyError:
                return JsonResponse(
                    {"error": f"Missing product with id {product.id} in request json"},
                    status=400,
                )
            if new_quantity > product.stock:
                return JsonResponse(
                    {"error": "Trying to order more products than in stock"}, status=400
                )

            product.stock = product.stock + product_order.quantity - new_quantity
            product_order.quantity = new_quantity

            products_list.append(product)
            product_order_list.append(product_order)

        order.save()
        self.save_models(products_list)
        self.save_models(product_order_list)

        serialized_data = DisplayOrdersSerializer(order).data
        return JsonResponse({"changed_order": serialized_data}, status=200)

    def reorder_by_id(self, reordering_list):
        reordered_dict = {}
        for unit in reordering_list:
            reordered_dict.update({unit['id']: unit['quantity']})
        return reordered_dict

    def save_models(self, model_list):
        for model in model_list:
            model.save()


class CancelOrder(APIView):
    def get(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return JsonResponse(
                {"error": f"Missing or invalid order id {pk} in request"}, status=400
            )

        if order.order_status == "completed":
            return JsonResponse(
                {"error": f"Completed orders cannot be cancelled"}, status=400
            )

        product_order_list = ProductOrder.objects.filter(order=pk)
        for product_order in product_order_list:
            product = product_order.product
            product.stock = product.stock + product_order.quantity
            product.save()
        order.order_status = "cancelled"
        order.save()

        serialized_data = DisplayOrdersSerializer(order).data
        return JsonResponse({"cancelled_order": serialized_data}, status=200)


class CompleteOrder(APIView):
    def get(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return JsonResponse(
                {"error": f"Missing or invalid order id {pk} in request"}, status=400
            )

        if order.order_status == "cancelled":
            return JsonResponse(
                {"error": f"Cancelled order cannot be completed"}, status=400
            )

        order.order_status = "completed"
        order.save()

        serialized_data = DisplayOrdersSerializer(order).data
        return JsonResponse({"completed_order": serialized_data}, status=200)


class SummaryReport(APIView):
    @swagger_auto_schema(
        method="post",
        request_body=openapi.Schema(
            type=openapi.TYPE_OBJECT,
            properties={
                "first_date": openapi.Schema(
                    type=openapi.TYPE_STRING, description="starting datetime"
                ),
                "second_date": openapi.Schema(
                    type=openapi.TYPE_STRING, description="ending datetime"
                ),
            },
        ),
        responses={
            status.HTTP_200_OK: openapi.Schema(
                type=openapi.TYPE_OBJECT,
                properties={
                    "summary": openapi.Schema(
                        type=openapi.TYPE_STRING, description="message about summary"
                    ),
                },
            ),
        },
    )
    @api_view(["POST"])
    def post(self, request):
        try:
            first_date = request.data["first_date"]
            second_date = request.data["second_date"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid date in request json"}, status=400
            )

        summary_task.apply_async(args=[first_date, second_date])

        return JsonResponse(
            {"Summary": "summary task created, please wait"}, status=200
        )


class GetSummary(generics.RetrieveAPIView):
    queryset = SummaryReportModel.objects.all()
    serializer_class = SummaryReportSerializer
