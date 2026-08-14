from django.contrib import admin

from .models import Merchant, RiskSignal, WebPresenceReview


class RiskSignalInline(admin.TabularInline):
    model = RiskSignal
    extra = 0


@admin.register(WebPresenceReview)
class WebPresenceReviewAdmin(admin.ModelAdmin):
    list_display = ["id", "merchant", "status", "recommendation", "created_at"]
    list_filter = ["status", "recommendation", "is_monitoring_check"]
    inlines = [RiskSignalInline]


@admin.register(Merchant)
class MerchantAdmin(admin.ModelAdmin):
    list_display = ["business_name", "website_url", "monitoring_enabled", "created_at"]
    list_filter = ["monitoring_enabled"]
