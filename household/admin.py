"""Admin registrations — a safety net for surgery, not the primary interface."""

from django.contrib import admin

from .models import Chore, Occurrence


class OccurrenceInline(admin.TabularInline):
    model = Occurrence
    extra = 0
    fields = ["due_on", "deadline", "status", "completed_by", "completed_at", "note"]
    ordering = ["-id"]


@admin.register(Chore)
class ChoreAdmin(admin.ModelAdmin):
    list_display = ["title", "owner", "assignee", "frequency", "anchor", "is_active"]
    list_filter = ["frequency", "anchor", "is_active", "owner"]
    search_fields = ["title", "notes"]
    inlines = [OccurrenceInline]


@admin.register(Occurrence)
class OccurrenceAdmin(admin.ModelAdmin):
    list_display = ["chore", "due_on", "deadline", "status", "completed_by", "completed_at"]
    list_filter = ["status"]
    date_hierarchy = "due_on"
