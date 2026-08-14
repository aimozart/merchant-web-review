from django.contrib import admin

from .models import OpsFlag, Ticket


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = ["title", "status", "priority", "category", "source", "created_at"]
    list_filter = ["status", "priority", "category", "source"]


@admin.register(OpsFlag)
class OpsFlagAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "note"]
