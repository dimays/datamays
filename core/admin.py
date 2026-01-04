# core/admin.py
from django.contrib import admin
from .models import Project


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    """
    Admin configuration optimized for:
    - Writing narrative project case studies
    - Quickly managing visibility and priority
    - Scanning project health at a glance
    """

    # --- List view ---
    list_display = (
        "title",
        "is_public",
        "is_featured",
        "priority",
        "created_at",
        "updated_at",
    )
    list_filter = (
        "is_public",
        "is_featured",
    )
    search_fields = (
        "title",
        "short_description",
        "motivation",
        "challenges",
        "lessons_learned",
    )
    ordering = ("priority", "-created_at")
    list_editable = (
        "is_public",
        "is_featured",
        "priority",
    )

    # --- Detail view ---
    prepopulated_fields = {"slug": ("title",)}

    fieldsets = (
        (
            "Core Information",
            {
                "fields": (
                    "title",
                    "slug",
                    "short_description",
                )
            },
        ),
        (
            "Project Narrative",
            {
                "description": (
                    "Tell the story of the project."
                    "Focus on motivation, tradeoffs, and lessons learned."
                ),
                "fields": (
                    "motivation",
                    "expected_outcome",
                    "challenges",
                    "lessons_learned",
                ),
            },
        ),
        (
            "Technical Details",
            {
                "fields": (
                    "tech_stack",
                    "repo_url",
                    "live_url",
                    "blog_post_url",
                )
            },
        ),
        (
            "Visibility & Ordering",
            {
                "fields": (
                    "is_public",
                    "is_featured",
                    "priority",
                    "status",
                )
            },
        ),
        (
            "Timestamps",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    readonly_fields = (
        "created_at",
        "updated_at",
    )
