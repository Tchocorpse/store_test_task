import json

from django.contrib.auth.models import User
from rest_framework import serializers
from product.models import Product, Order, ProductOrder, SummaryReportModel


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = "__all__"


class UpdateProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ('stock', 'price', 'cost_price')


class ProductOrderSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProductOrder
        fields = ('id', 'quantity', 'product')
        depth = 1


class DisplayOrdersSerializer(serializers.ModelSerializer):
    product_order = ProductOrderSerializer(many=True)

    class Meta:
        model = Order
        fields = ('id', 'user', 'order_status', 'created', 'updated', 'product_order')


class SummaryReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = SummaryReportModel
        fields = "__all__"


class SummaryReportIdName(serializers.ModelSerializer):
    class Meta:
        model = SummaryReportModel
        fields = ('id', 'name')


class ProductListSerializer(serializers.ListSerializer):

    def create(self, validated_data):
        products = [Product(**item) for item in validated_data]
        return Product.objects.bulk_create(products)


class ProductBulkSerializer(serializers.ModelSerializer):

    class Meta:
        list_serializer_class = ProductListSerializer
        model = Product
        fields = "__all__"


class UserModelSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = "__all__"
