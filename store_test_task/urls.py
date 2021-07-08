from django.contrib import admin
from django.urls import path

from product.views import (
    GetProducts,
    PostProducts,
    UpdateProducts,
    CreateOrder,
    DisplayOrders,
    CancelOrder,
    CompleteOrder,
    SummaryReport,
    GetSummary,
)


urlpatterns = [
    path("admin/", admin.site.urls),
    path("products/", GetProducts.as_view()),
    path("products/create/", PostProducts.as_view()),
    path("products/update/<int:pk>", UpdateProducts.as_view()),
    path("orders/create/", CreateOrder.as_view()),
    path("orders/cancel/<int:pk>", CancelOrder.as_view()),
    path("orders/complete/<int:pk>", CompleteOrder.as_view()),
    path("orders/", DisplayOrders.as_view()),
    path("report/create/", SummaryReport.as_view()),
    path("report/<int:pk>", GetSummary.as_view()),
]
