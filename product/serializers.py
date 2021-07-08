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
