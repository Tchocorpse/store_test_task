from django.contrib import admin
from django.urls import path

from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

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


schema_view = get_schema_view(
   openapi.Info(
      title="API references",
      default_version='v1',
   ),
   public=True,
   permission_classes=[permissions.AllowAny],
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

    #drf-yasg part
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
]
