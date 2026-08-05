"""The category tree."""

from django import forms
from django.utils.text import slugify

from ..models import Category
from .base import StyledFormMixin


class CategoryForm(StyledFormMixin, forms.ModelForm):
    """Create or rename a category. The slug is set once, at creation, and
    never changes after — several system categories (Uncategorized, Internal
    Transfer, Credit Card Payment) are looked up by slug in code, and a
    handful of other slugs are what CategoryRule/MerchantCategoryMemo
    matching keys off of, so renaming a category must not disturb it."""

    class Meta:
        model = Category
        fields = ["name", "parent", "kind", "sort_order", "description"]
        widgets = {
            "name": forms.TextInput(attrs={"placeholder": "Groceries"}),
            "description": forms.TextInput(),
        }
        help_texts = {
            "parent": "Leave unset for a top-level category. Nesting goes at most three levels deep.",
            "kind": "A subcategory must share its parent's kind.",
            "sort_order": "Lower sorts first among siblings.",
            "description": "Steers the classifier — say what belongs here and what doesn't.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["parent"].queryset = Category.objects.filter(is_active=True)
        self.fields["parent"].required = False
        self.fields["parent"].empty_label = "No parent (top-level)"
        self.fields["description"].required = False

    def clean_parent(self):
        parent = self.cleaned_data.get("parent")

        if parent and self.instance.pk:
            # Without this guard, picking one of a category's own descendants
            # as its new parent creates a cycle — full_path/depth walk parent
            # links and would loop forever.
            node = parent
            while node is not None:
                if node.pk == self.instance.pk:
                    raise forms.ValidationError(
                        "A category can't be nested under one of its own subcategories."
                    )
                node = node.parent

        return parent

    def save(self, commit=True):
        category = super().save(commit=False)

        if not category.slug:
            category.slug = self._unique_slug(category.name)

        if commit:
            category.save()

        return category

    def _unique_slug(self, name):
        base = slugify(name)[:90] or "category"
        slug = base
        suffix = 1

        while Category.objects.filter(slug=slug).exclude(pk=self.instance.pk).exists():
            suffix += 1
            slug = f"{base}-{suffix}"

        return slug
