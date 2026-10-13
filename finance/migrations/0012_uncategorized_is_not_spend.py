"""Uncategorized stops counting as spend; "Uncategorized Spend" is added.

The categorizer parks what it can't place in the system "Uncategorized"
category, which was expense-kind — so every unplaced deposit (paychecks with a
new description, a loan paying off a card) was netted against spending as a
refund. September 2026 showed -$11,116.60 of spend. Uncategorized becomes its
own kind, which no spend or income total includes, and spending that fits
nowhere else gets an ordinary expense category a person chooses.

Data only, besides the new choice: no table changes. Reversible.
"""

from django.db import migrations, models

UNCATEGORIZED = "uncategorized"
UNCATEGORIZED_SPEND = "uncategorized-spend"


def forwards(apps, schema_editor):
    Category = apps.get_model("finance", "Category")

    Category.objects.filter(slug=UNCATEGORIZED).update(kind="unclassified")

    if not Category.objects.filter(slug=UNCATEGORIZED_SPEND).exists():
        uncategorized = Category.objects.filter(slug=UNCATEGORIZED).first()
        Category.objects.create(
            name="Uncategorized Spend",
            slug=UNCATEGORIZED_SPEND,
            kind="expense",
            is_system=True,
            # Just ahead of Uncategorized, wherever the household has it.
            sort_order=max((uncategorized.sort_order if uncategorized else 1000) - 1, 0),
            description="Confirmed spending that fits no other category. Counts toward spend.",
        )


def backwards(apps, schema_editor):
    Category = apps.get_model("finance", "Category")
    Category.objects.filter(slug=UNCATEGORIZED).update(kind="expense")
    # Uncategorized Spend is left in place: transactions may already be in it.


class Migration(migrations.Migration):
    dependencies = [
        ("finance", "0011_alter_merchantcategorymemo_merchant_key"),
    ]

    operations = [
        migrations.AlterField(
            model_name="category",
            name="kind",
            field=models.CharField(
                choices=[
                    ("expense", "Expense"),
                    ("income", "Income"),
                    ("transfer", "Transfer"),
                    ("unclassified", "Unclassified"),
                ],
                default="expense",
                max_length=20,
            ),
        ),
        migrations.RunPython(forwards, backwards),
    ]
