# core/admin.py
from django.contrib import admin
from .models import Project, Tag, Post


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


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "status",
        "published_at",
        "created_at",
    )

    list_filter = (
        "published_at",
        "tags",
    )

    search_fields = (
        "title",
        "summary",
        "content",
    )

    prepopulated_fields = {"slug": ("title",)}

    date_hierarchy = "published_at"
    ordering = ("-published_at", "-created_at")

    filter_horizontal = ("tags",)

    readonly_fields = (
        "created_at",
        "updated_at",
        "content_html",
    )

    actions = (
        "publish_selected",
        "unpublish_selected",
    )

    fieldsets = (
        (None, {
            "fields": (
                "title",
                "slug",
                "summary",
                "tags",
            )
        }),
        ("Content", {
            "fields": (
                "content",
                "content_html",
            )
        }),
        ("Publishing", {
            "fields": (
                "published_at",
            )
        }),
        ("Metadata", {
            "fields": (
                "created_at",
                "updated_at",
            )
        }),
    )

    @admin.display(description="Status")
    def status(self, obj):
        return "Published" if obj.published_at else "Draft"

    @admin.action(description="Publish selected posts")
    def publish_selected(self, request, queryset):
        for post in queryset:
            post.publish()

    @admin.action(description="Unpublish selected posts")
    def unpublish_selected(self, request, queryset):
        for post in queryset:
            post.unpublish()
