import json
import logging

from django.contrib import admin

from product.models import Product, Order, ProductOrder, SummaryReportModel

admin.site.register(Product)
admin.site.register(Order)
admin.site.register(ProductOrder)


@admin.action(description="Download csv summary")
def download_csv(self, request, queryset):
    import csv

    for qs in queryset:
        name = f"{qs.id} summary_report.csv"
        f = open(name, "w")

        writer = csv.writer(f)
        summary_dict = json.loads(qs.summary_report)

        writer.writerow(["product", "revenue", "profit", "sold", "returned"])
        for product in summary_dict:
            writer.writerow(
                [
                    product,
                    summary_dict[product]["revenue"],
                    summary_dict[product]["profit"],
                    summary_dict[product]["sold"],
                    summary_dict[product]['returned'],
                ]
            )


class SummaryAdmin(admin.ModelAdmin):
    model = SummaryReportModel
    readonly_fields = ("id", "first_date", "second_date")
    list_display = ("id", "description", "first_date", "second_date")
    exclude = ("summary_report",)
    actions = [download_csv]


admin.site.register(SummaryReportModel, SummaryAdmin)
