import datetime
import logging
from wsgiref.util import FileWrapper

from django.contrib.auth.models import User
from django.http import JsonResponse, HttpResponse
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
    SummaryReportIdName,
    ProductBulkSerializer,
    UserModelSerializer,
)
from product.tasks import summary_task


# Products section #


bulk_products_schema = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    properties={
        "products_list": openapi.Schema(
            type=openapi.TYPE_OBJECT,
            description="list of products",
            properties={
                "product_name": openapi.Schema(
                    type=openapi.TYPE_STRING, description="product name"
                ),
                "description": openapi.Schema(
                    type=openapi.TYPE_NUMBER, description="product description",
                ),
                "stock": openapi.Schema(
                    type=openapi.TYPE_NUMBER,
                    description="quantity of product in stock",
                ),
                "price": openapi.Schema(
                    type=openapi.TYPE_NUMBER, description="price of the product",
                ),
                "cost_price": openapi.Schema(
                    type=openapi.TYPE_NUMBER, description="cost price of the product",
                ),
            },
        ),
    },
)


class GetProducts(generics.ListAPIView):
    queryset = Product.objects.all()
    serializer_class = ProductSerializer


class PostProduct(generics.CreateAPIView):
    serializer_class = ProductSerializer


class UpdateProduct(generics.UpdateAPIView):
    queryset = Product.objects.all()
    lookup_field = "pk"
    serializer_class = UpdateProductSerializer


class PostBulkProducts(APIView):
    @swagger_auto_schema(
        method="post",
        request_body=bulk_products_schema,
        responses={status.HTTP_200_OK: ProductBulkSerializer,},
    )
    @action(detail=False, methods=["POST"])
    def post(self, request):
        try:
            products_list = request.data["products_list"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid products list in request json"},
                status=400,
            )

        serialized_products = ProductBulkSerializer(data=products_list, many=True)
        if serialized_products.is_valid():
            serialized_products.save()

            return JsonResponse(
                {"completed_order": serialized_products.data}, status=200
            )
        else:
            return JsonResponse({"error": f"validation error"}, status=400)


# Orders section #


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
                    type=openapi.TYPE_NUMBER, description="quantity of product order",
                ),
            },
        ),
        "user": openapi.Schema(
            type=openapi.TYPE_NUMBER, description="id of user making order"
        ),
    },
)


class DisplayOrders(generics.ListAPIView):
    queryset = Order.objects.all()
    serializer_class = DisplayOrdersSerializer


class CreateOrder(APIView):
    @swagger_auto_schema(
        method="post",
        request_body=order_request_schema,
        responses={status.HTTP_200_OK: DisplayOrdersSerializer,},
    )
    @action(detail=False, methods=["POST"])
    def post(self, request):
        try:
            received_order = request.data["order"]
            received_user_id = request.data["user"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid order or user in request json"},
                status=400,
            )

        try:
            user = User.objects.get(pk=received_user_id)
        except User.DoesNotExist:
            return JsonResponse(
                {"error": f"no such User with id {received_user_id}"}, status=400
            )

        products_list = []
        product_order_list = []
        order = Order(user=user, order_status="stable")
        for unit in received_order:
            try:
                product = Product.objects.get(pk=unit["id"])
            except Product.DoesNotExist:
                return JsonResponse(
                    {"error": f"no such Product with id {unit['id']}"}, status=400
                )
            products_list.append(product)

            p_quantity = unit["quantity"]
            if p_quantity > product.stock:
                return JsonResponse(
                    {
                        "error": f"Trying to order more products than in stock {product.stock} < {p_quantity}"
                    },
                    status=400,
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

    def save_models(self, model_list):
        for model in model_list:
            model.save()


class UpdateOrder(APIView):
    @swagger_auto_schema(
        method="put",
        request_body=order_request_schema,
        responses={status.HTTP_200_OK: DisplayOrdersSerializer,},
    )
    @action(detail=False, methods=["PUT"])
    def put(self, request, pk):
        try:
            order = Order.objects.get(pk=pk)
        except Order.DoesNotExist:
            return JsonResponse(
                {"error": f"Missing or invalid order id {pk} in request"}, status=400
            )

        if (order.order_status == "completed") or (order.order_status == "cancelled"):
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
        product_order_qs = ProductOrder.objects.select_related("product").filter(
            order=pk
        )

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
            reordered_dict.update({unit["id"]: unit["quantity"]})
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
                {"error": f"No such order with id {pk} in request"}, status=400
            )

        if order.order_status == "completed":
            return JsonResponse(
                {"error": f"Completed orders cannot be cancelled"}, status=400
            )

        product_order_list = ProductOrder.objects.select_related("product").filter(
            order=pk
        )
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
                {"error": f"No such order with id {pk} in request"}, status=400
            )

        if order.order_status == "cancelled":
            return JsonResponse(
                {"error": f"Cancelled order cannot be completed"}, status=400
            )

        order.order_status = "completed"
        order.save()

        serialized_data = DisplayOrdersSerializer(order).data
        return JsonResponse({"completed_order": serialized_data}, status=200)


class GetOrder(generics.RetrieveAPIView):
    queryset = Order.objects.all()
    serializer_class = DisplayOrdersSerializer


class GetUsers(generics.ListAPIView):
    queryset = User.objects.all()
    serializer_class = UserModelSerializer


# Summary reports section #


summary_report_request_schema = openapi.Schema(
    type=openapi.TYPE_OBJECT,
    required=["first_date", "second_date"],
    properties={
        "first_date": openapi.Schema(
            type=openapi.TYPE_STRING, description="starting datetime"
        ),
        "second_date": openapi.Schema(
            type=openapi.TYPE_STRING, description="ending datetime"
        ),
        "name": openapi.Schema(
            type=openapi.TYPE_STRING,
            description="Optional name of the report. Should be unique.",
            maximum=100,
        ),
    },
)


class SummaryReport(APIView):
    @swagger_auto_schema(
        method="post",
        request_body=summary_report_request_schema,
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
    @action(detail=False, methods=["POST"])
    def post(self, request):
        try:
            first_date = request.data["first_date"]
            second_date = request.data["second_date"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid date in request json"}, status=400
            )

        try:
            name = request.data["name"]
        except KeyError:
            name = self.generate_name()

        try:
            summary = SummaryReportModel.objects.get(name=name)
        except SummaryReportModel.DoesNotExist:
            summary_task.apply_async(args=[first_date, second_date, name])
            return JsonResponse(
                {"Summary": f"summary task named {name} created, please wait"},
                status=200,
            )

        return JsonResponse(
            {
                "summary": f"summary task named {name} already exists with id {summary.id}"
            },
            status=200,
        )

    def generate_name(self):
        return f"summary_report_requested_{datetime.datetime.now()}"


class GetSummary(APIView):
    @swagger_auto_schema(
        method="get",
        responses={
            status.HTTP_200_OK: openapi.Schema(
                type=openapi.TYPE_FILE, description="CSV report file",
            ),
        },
    )
    @action(detail=False, methods=["GET"])
    def get(self, request, pk):
        try:
            summary_report = SummaryReportModel.objects.get(pk=pk)
        except SummaryReportModel.DoesNotExist:
            return JsonResponse({"error": f"No such report with id {pk}"}, status=400)

        with open(summary_report.summary_report.path, "rb") as report_file:
            return HttpResponse(
                FileWrapper(report_file), content_type="application/csv"
            )


class GetSummaryName(APIView):
    @swagger_auto_schema(
        method="get",
        manual_parameters=[
            openapi.Parameter(
                in_="query",
                name="name",
                type="string",
                description="unique name of requested summary report",
            )
        ],
        responses={
            status.HTTP_200_OK: openapi.Schema(
                type=openapi.TYPE_FILE, description="CSV report file",
            ),
        },
    )
    @action(detail=False, methods=["GET"])
    def get(self, request):
        try:
            name = request.GET["name"]
        except KeyError:
            return JsonResponse(
                {"error": f"Missing or invalid name in request querystring"}, status=400
            )

        try:
            summary_report = SummaryReportModel.objects.get(name=name)
        except SummaryReportModel.DoesNotExist:
            return JsonResponse({"error": f"No such report named {name}"}, status=400)

        with open(summary_report.summary_report.path, "rb") as report_file:
            return HttpResponse(
                FileWrapper(report_file), content_type="application/csv"
            )


class GetSummaryList(generics.ListAPIView):
    queryset = SummaryReportModel.objects.all()
    serializer_class = SummaryReportIdName
