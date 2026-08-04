from django.core.management.base import BaseCommand
from django.db import transaction

from finance.categories_seed import CATEGORY_TREE, SYSTEM_SLUGS
from finance.models import Category, CategoryKind


class Command(BaseCommand):
    help = (
        "Create or update the starting category tree. Safe to re-run: it "
        "matches on slug and never deletes categories you have added or "
        "transactions already reference."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--update-descriptions",
            action="store_true",
            help="Overwrite descriptions on categories that already exist.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        created, updated = self._sync(CATEGORY_TREE, options["update_descriptions"])

        if options["verbosity"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Categories: {created} created, {updated} updated, "
                    f"{Category.objects.count()} total."
                )
            )

    def _sync(self, nodes, update_descriptions, parent=None, sort_start=10):
        created = updated = 0

        for offset, node in enumerate(nodes):
            kind = node.get("kind") or (parent.kind if parent else CategoryKind.EXPENSE)

            category, was_created = Category.objects.get_or_create(
                slug=node["slug"],
                defaults={
                    "name": node["name"],
                    "parent": parent,
                    "kind": kind,
                    "description": node.get("description", ""),
                    "is_system": node.get("system", False) or node["slug"] in SYSTEM_SLUGS,
                    "sort_order": sort_start + offset * 10,
                },
            )

            if was_created:
                created += 1
            elif update_descriptions and node.get("description"):
                category.description = node["description"]
                category.save(update_fields=["description", "updated_at"])
                updated += 1

            child_created, child_updated = self._sync(
                node.get("children", []), update_descriptions, parent=category
            )
            created += child_created
            updated += child_updated

        return created, updated
